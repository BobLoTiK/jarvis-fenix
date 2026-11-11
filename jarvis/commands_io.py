"""Импорт и экспорт пользовательских команд: только данные, без исполнения.

Формат: JSON-объект `{"format": "fenix-commands", "version": 1, "commands": [...]}`.
Экспорт — снимок `custom_commands` из конфига. Импорт — проверка размера,
схемы и каждой записи через `command_builder.validate_entry`, затем один атомарный
`config.set("custom_commands", ...)`. Никакого pickle, eval и запуска шагов:
файл — это данные, а не программа.

Конфликты не решаются молча: план импорта показывает, что добавится, что
обновится и что отклонено (с причиной), а применяется только явным вызовом.
"""

import json
import logging
from datetime import datetime, timezone

from jarvis import command_builder, packs
from jarvis.text_utils import normalize

log = logging.getLogger("jarvis.commands_io")

FORMAT = "fenix-commands"
VERSION = 1
MAX_BYTES = 256 * 1024
MAX_ENTRIES = 200


def export_payload(config, *, now=None) -> dict:
    """Снимок пользовательских команд для файла."""
    commands = command_builder.entries(config)
    stamp = (now or datetime.now(timezone.utc)).astimezone().isoformat(timespec="seconds")
    return {
        "format": FORMAT,
        "version": VERSION,
        "exported_at": stamp,
        "commands": commands,
    }


def dumps(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _load(text) -> list:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Файл пустой.")
    size = len(text.encode("utf-8"))
    if size > MAX_BYTES:
        raise ValueError(f"Файл слишком большой: {size} байт (максимум {MAX_BYTES}).")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"Это не JSON: {error.msg} в строке {error.lineno}.") from None
    if not isinstance(data, dict):
        raise ValueError("Ожидался JSON-объект с полем commands.")
    if data.get("format") != FORMAT:
        raise ValueError("Это не файл команд Феникса: поле format не совпало.")
    if data.get("version") != VERSION:
        raise ValueError(
            f"Версия файла {data.get('version')!r} не поддерживается (нужна {VERSION})."
        )
    commands = data.get("commands")
    if not isinstance(commands, list):
        raise ValueError("Поле commands должно быть списком.")
    if len(commands) > MAX_ENTRIES:
        raise ValueError(f"Слишком много команд: {len(commands)} (максимум {MAX_ENTRIES}).")
    return commands


def _phrase_owner_map(entries):
    owners = {}
    for entry in entries:
        if not entry.get("enabled", True):
            continue
        for phrase in entry.get("phrases", []):
            if isinstance(phrase, str):
                owners.setdefault(normalize(phrase), entry.get("id"))
    return owners


def plan_import(config, text) -> dict:
    """Разбирает файл и строит план: add / update / conflicts / errors.

    Ничего не пишет в конфиг. `conflicts` — записи, которые нельзя применить
    без ручного решения (чужая фраза, старая версия, дубль внутри файла).
    """
    raw_commands = _load(text)
    wake_words = config.get("wake_words", [])
    current = command_builder.entries(config)

    try:
        active_packs = packs.load_active(config)
    except Exception:
        log.exception("Пакеты не прочитались, конфликты с ними не проверялись")
        active_packs = []

    owners = _phrase_owner_map(current + list(active_packs))
    current_ids = {entry.get("id"): entry for entry in current}
    seen_ids = set()
    plan = {"add": [], "update": [], "conflicts": [], "errors": []}

    for index, raw in enumerate(raw_commands):
        name = str(raw.get("name", "")) if isinstance(raw, dict) else ""
        try:
            entry = command_builder.validate_entry(raw, wake_words)
        except ValueError as error:
            plan["errors"].append({"index": index, "name": name, "error": str(error)})
            continue

        entry_id = entry["id"]
        if entry_id in seen_ids:
            plan["conflicts"].append(
                {"index": index, "name": entry["name"],
                 "reason": "Такой ID уже есть в файле."}
            )
            continue
        seen_ids.add(entry_id)

        existing = current_ids.get(entry_id)
        if existing is not None and existing.get("builder_version") != 1:
            plan["conflicts"].append(
                {"index": index, "name": entry["name"],
                 "reason": "Старую команду нельзя перезаписывать конструктором."}
            )
            continue

        clash = None
        for phrase in entry["phrases"]:
            owner = owners.get(normalize(phrase))
            if owner and owner != entry_id:
                clash = phrase
                break
        if clash and entry.get("enabled", True):
            plan["conflicts"].append(
                {"index": index, "name": entry["name"],
                 "reason": f"Фраза «{clash}» уже занята другой командой или паком."}
            )
            continue

        if entry.get("enabled", True):
            for phrase in entry["phrases"]:
                owners.setdefault(normalize(phrase), entry_id)
        if existing is not None:
            plan["update"].append(entry)
        else:
            plan["add"].append(entry)

    return plan


def apply_plan(config, plan) -> dict:
    """Применяет план одним `config.set`. Возвращает счётчики."""
    current = command_builder.entries(config)
    updates = {entry["id"]: entry for entry in plan.get("update", [])}
    merged = []
    for entry in current:
        merged.append(updates.pop(entry.get("id"), entry))
    merged.extend(plan.get("add", []))
    merged.extend(updates.values())
    if not config.set("custom_commands", merged):
        raise OSError("Не удалось сохранить config.json. Изменения не применены.")
    return {
        "added": len(plan.get("add", [])),
        "updated": len(plan.get("update", [])),
        "conflicts": len(plan.get("conflicts", [])),
        "errors": len(plan.get("errors", [])),
        "total": len(merged),
    }


def describe_plan(plan) -> str:
    """Одна фраза для человека: что произойдёт при импорте."""
    added = len(plan.get("add", []))
    updated = len(plan.get("update", []))
    conflicts = len(plan.get("conflicts", []))
    errors = len(plan.get("errors", []))
    if not (added or updated):
        tail = []
        if conflicts:
            tail.append(f"конфликтов: {conflicts}")
        if errors:
            tail.append(f"ошибок: {errors}")
        reason = ", ".join(tail) if tail else "нечего импортировать"
        return f"Импорт ничего не добавит ({reason})."
    parts = [f"добавить: {added}", f"обновить: {updated}"]
    if conflicts:
        parts.append(f"конфликтов: {conflicts}")
    if errors:
        parts.append(f"ошибок: {errors}")
    return "Импорт: " + ", ".join(parts) + "."
