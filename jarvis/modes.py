"""Режимы работы Феникса: commands, llm, combo."""

import logging
import re

from jarvis import config_manager

log = logging.getLogger("jarvis.modes")

NAMES = {
    "commands": "только команды",
    "llm": "только ИИ",
    "combo": "комбинированный",
}


def get_mode(config) -> str:
    m = config.get("mode", "combo")
    return m if m in NAMES else "combo"


def set_mode(mode: str, config=None) -> str:
    if mode not in NAMES:
        return f"Неизвестный режим: {mode}."
    if config is not None:
        config.set("mode", mode)
    else:
        config_manager.update("mode", mode)
    log.info("Режим переключён на %s", mode)
    return f"Режим: {NAMES[mode]}."


def handle_mode_command(cmd: str, current_mode: str, config=None) -> tuple[str | None, str]:
    if re.search(r"режим\s+(команд|команды|только\s+команд)", cmd) \
            or cmd in {"только команды", "без ии"}:
        return set_mode("commands", config), "commands"

    if re.search(r"режим\s+(ии|искусственн\w*|нейросет\w*|нейронк\w*)", cmd) \
            or cmd in {"только ии", "режим ии", "режим нейросети", "только нейросеть"}:
        return set_mode("llm", config), "llm"

    if re.search(r"(комбинированн|обычн|стандартн|смешанн)\w*\s+режим", cmd) \
            or re.search(r"режим\s+(комбо|обычн|стандартн|смешанн|комбинированн)", cmd) \
            or cmd in {"обычный режим", "комбо", "режим комбо"}:
        return set_mode("combo", config), "combo"

    if re.search(r"(какой|текущий|что\s+за)\s+режим", cmd) \
            or cmd in {"какой режим", "текущий режим"}:
        return f"Сейчас режим: {NAMES.get(current_mode, current_mode)}.", current_mode

    return None, current_mode