"""Режимы работы Феникса: commands, llm, combo.

- commands — работают только правила, LLM выключена.
- llm      — все фразы идут в LLM, правила пропускаются (кроме скриншота).
- combo    — правила → LLM (по умолчанию).

Запись в config.json — через config_manager (единый FileLock, атомарная замена).
"""

import logging
import re

from jarvis import config_manager

log = logging.getLogger("jarvis.modes")

NAMES = {
    "commands": "только команды",
    "llm": "только ИИ",
    "combo": "комбинированный",
}


def get_mode(config: dict) -> str:
    m = config.get("mode", "combo")
    return m if m in NAMES else "combo"


def set_mode(mode: str) -> str:
    """Сохраняет режим в config.json атомарно через config_manager."""
    if mode not in NAMES:
        return f"Неизвестный режим: {mode}."
    if config_manager.update("mode", mode):
        log.info("Режим переключён на %s", mode)
    else:
        log.error("Не удалось сохранить режим")
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