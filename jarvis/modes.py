"""Режимы работы Феникса: commands, llm, combo.

- commands — работают только правила, LLM выключена.
- llm      — все фразы идут в LLM, правила пропускаются (кроме скриншота).
- combo    — правила → LLM (по умолчанию).

Запись в config.json — атомарная (через .tmp + replace), с мьютексом.
Защита от гонки, когда несколько модулей пишут одновременно.
"""

import json
import logging
import re
import threading
from pathlib import Path

log = logging.getLogger("jarvis.modes")

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"
_write_lock = threading.Lock()

NAMES = {
    "commands": "только команды",
    "llm": "только ИИ",
    "combo": "комбинированный",
}


def _atomic_write(path: Path, data: dict) -> None:
    """Пишет JSON атомарно: сначала .tmp, потом replace. С мьютексом."""
    with _write_lock:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)


def _read_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        log.exception("Не удалось прочитать config.json")
        return {}


def get_mode(config: dict) -> str:
    m = config.get("mode", "combo")
    return m if m in NAMES else "combo"


def set_mode(mode: str) -> str:
    """Сохраняет режим в config.json атомарно."""
    if mode not in NAMES:
        return f"Неизвестный режим: {mode}."
    try:
        data = _read_config()
        data["mode"] = mode
        _atomic_write(CONFIG_PATH, data)
        log.info("Режим переключён на %s", mode)
    except Exception:
        log.exception("Не удалось сохранить режим")
    return f"Режим: {NAMES[mode]}."


def handle_mode_command(cmd: str, current_mode: str) -> tuple[str | None, str]:
    """Возвращает (ответ_или_None, новый_режим)."""
    if re.search(r"режим\s+(команд|команды|только\s+команд)", cmd) \
            or cmd in {"только команды", "без ии"}:
        return set_mode("commands"), "commands"

    if re.search(r"режим\s+(ии|искусственн\w*|нейросет\w*|нейронк\w*)", cmd) \
            or cmd in {"только ии", "режим ии", "режим нейросети", "только нейросеть"}:
        return set_mode("llm"), "llm"

    if re.search(r"(комбинированн|обычн|стандартн|смешанн)\w*\s+режим", cmd) \
            or re.search(r"режим\s+(комбо|обычн|стандартн|смешанн|комбинированн)", cmd) \
            or cmd in {"обычный режим", "комбо", "режим комбо"}:
        return set_mode("combo"), "combo"

    if re.search(r"(какой|текущий|что\s+за)\s+режим", cmd) \
            or cmd in {"какой режим", "текущий режим"}:
        return f"Сейчас режим: {NAMES.get(current_mode, current_mode)}.", current_mode

    return None, current_mode