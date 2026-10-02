"""Режимы работы Феникса: commands, llm, combo.

- commands — работают только правила, LLM выключена.
- llm      — все фразы идут в LLM, правила пропускаются (кроме скриншота).
- combo    — правила → LLM (по умолчанию).
"""

import json
import logging
import re
from pathlib import Path

log = logging.getLogger("jarvis.modes")

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"

NAMES = {
    "commands": "только команды",
    "llm": "только ИИ",
    "combo": "комбинированный",
}


def get_mode(config: dict) -> str:
    m = config.get("mode", "combo")
    return m if m in NAMES else "combo"


def set_mode(mode: str) -> str:
    """Сохраняет режим в config.json и возвращает человекочитаемое название."""
    if mode not in NAMES:
        return f"Неизвестный режим: {mode}."
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            data["mode"] = mode
            CONFIG_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log.info("Режим переключён на %s и сохранён в config.json", mode)
    except Exception:
        log.exception("Не удалось сохранить режим")
    return f"Режим: {NAMES[mode]}."


def handle_mode_command(cmd: str, current_mode: str) -> tuple[str | None, str]:
    """Возвращает (ответ_или_None, новый_режим).

    Если фраза не про режим — вернёт (None, current_mode).
    Если про режим — (ответ, новый_режим).
    """
    # только команды
    if re.search(r"режим\s+(команд|команды|только\s+команд)", cmd) \
            or cmd in {"только команды", "без ии", "без ии"}:
        return set_mode("commands"), "commands"

    # только ИИ
    if re.search(r"режим\s+(ии|искусственн\w*|нейросет\w*|нейронк\w*)", cmd) \
            or cmd in {"только ии", "режим ии", "режим нейросети", "только нейросеть"}:
        return set_mode("llm"), "llm"

    # комбинированный
    if re.search(r"(комбинированн|обычн|стандартн|смешанн)\w*\s+режим", cmd) \
            or re.search(r"режим\s+(комбо|обычн|стандартн|смешанн|комбинированн)", cmd) \
            or cmd in {"обычный режим", "комбо", "режим комбо"}:
        return set_mode("combo"), "combo"

    # какой режим
    if re.search(r"(какой|текущий|что\s+за)\s+режим", cmd) \
            or cmd in {"какой режим", "текущий режим"}:
        return f"Сейчас режим: {NAMES.get(current_mode, current_mode)}.", current_mode

    return None, current_mode