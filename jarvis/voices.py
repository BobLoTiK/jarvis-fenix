"""Управление голосами Piper: ruslan, dmitri, irina, denis.

Голосом: «смени голос на ирину», «голос дмитрий», «какой голос», «список голосов».
Сохраняется в config.json → tts_voice.
Запись — через config_manager (единый FileLock, атомарная замена).
"""

import logging
import re

from jarvis import config_manager

log = logging.getLogger("jarvis.voices")

PIPER_VOICES = {
    "ruslan": "Руслан — мужской, спокойный",
    "dmitri": "Дмитрий — мужской, ниже и медленнее",
    "irina":  "Ирина — женский",
    "denis":  "Денис — мужской, дикторский",
}

ALIASES = {
    "руслан": "ruslan", "руслана": "ruslan",
    "дмитрий": "dmitri", "дмитрия": "dmitri",
    "дима": "dmitri", "диму": "dmitri",
    "ирина": "irina", "ирину": "irina",
    "ира": "irina", "иру": "irina",
    "денис": "denis", "дениса": "denis",
}


def current_voice() -> str:
    cfg = config_manager.load()
    return cfg.get("tts_voice", "ruslan")


def switch(voice: str) -> str:
    if voice not in PIPER_VOICES:
        return f"Голос '{voice}' не знаю. Доступны: {', '.join(PIPER_VOICES)}."
    if not config_manager.update("tts_voice", voice):
        log.error("Не удалось сохранить голос")
        return f"Не удалось переключить голос на {voice}."
    log.info("Голос переключён на %s", voice)
    return f"Голос переключён на {voice.capitalize()}."


def handle_voice_command(cmd: str) -> str | None:
    if re.search(r"(какой|текущий|что\s+за)\s+голос", cmd) \
            or cmd in {"какой голос", "текущий голос"}:
        return f"Сейчас голос: {current_voice().capitalize()}."

    if re.search(r"(список|какие|покажи|доступные)\s+голос", cmd) \
            or cmd in {"список голосов", "какие голоса", "покажи голоса"}:
        return f"Доступные голоса: {', '.join(PIPER_VOICES.keys())}."

    m = re.search(r"(?:смени|поменяй|переключи|включи|поставь)\s+голос\s+(?:на\s+)?(\S+)", cmd)
    if m:
        name = m.group(1).strip().rstrip(".,!?").lower()
        key = ALIASES.get(name, name)
        if key in PIPER_VOICES:
            return switch(key)
        return f"Голос '{name}' не знаю. Доступны: {', '.join(PIPER_VOICES)}."

    m = re.match(r"^голос\s+(\S+)$", cmd)
    if m:
        name = m.group(1).strip().rstrip(".,!?").lower()
        key = ALIASES.get(name, name)
        if key in PIPER_VOICES:
            return switch(key)
        return f"Голос '{name}' не знаю."

    return None