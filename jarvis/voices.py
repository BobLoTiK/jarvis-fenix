"""Управление голосами Piper: ruslan, dmitri, irina, denis.

Голосом: «смени голос на ирину», «голос дмитрий», «какой голос», «список голосов».
Сохраняется в config.json → tts_voice.
"""

import json
import logging
import re
from pathlib import Path

log = logging.getLogger("jarvis.voices")

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"

# доступные Piper-голоса
PIPER_VOICES = {
    "ruslan": "Руслан — мужской, спокойный",
    "dmitri": "Дмитрий — мужской, ниже и медленнее",
    "irina":  "Ирина — женский",
    "denis":  "Денис — мужской, дикторский",
}

# псевдонимы (что пользователь может сказать) → ключ
ALIASES = {
    "руслан": "ruslan",
    "руслана": "ruslan",
    "дмитрий": "dmitri",
    "дмитрия": "dmitri",
    "дима": "dmitri",
    "диму": "dmitri",
    "ирина": "irina",
    "ирину": "irina",
    "ира": "irina",
    "иру": "irina",
    "денис": "denis",
    "дениса": "denis",
}


def _read_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        log.exception("Не удалось прочитать config.json")
        return {}


def _write_config(data: dict) -> None:
    try:
        CONFIG_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        log.exception("Не удалось записать config.json")


def current_voice() -> str:
    """Текущий голос из config.json."""
    cfg = _read_config()
    return cfg.get("tts_voice", "ruslan")


def switch(voice: str) -> str:
    """Переключает голос. voice — ключ из PIPER_VOICES."""
    if voice not in PIPER_VOICES:
        return f"Голос '{voice}' не знаю. Доступны: {', '.join(PIPER_VOICES)}."
    cfg = _read_config()
    cfg["tts_voice"] = voice
    _write_config(cfg)
    log.info("Голос переключён на %s", voice)
    # человекочитаемое название
    title = voice.capitalize()
    return f"Голос переключён на {title}."


def handle_voice_command(cmd: str) -> str | None:
    """Разбирает команды про голос. Возвращает ответ или None."""
    # какой голос
    if re.search(r"(какой|текущий|что\s+за)\s+голос", cmd) \
            or cmd in {"какой голос", "текущий голос"}:
        v = current_voice()
        title = v.capitalize()
        return f"Сейчас голос: {title}."

    # список голосов
    if re.search(r"(список|какие|покажи|доступные)\s+голос", cmd) \
            or cmd in {"список голосов", "какие голоса", "покажи голоса"}:
        names = ", ".join(PIPER_VOICES.keys())
        return f"Доступные голоса: {names}."

    # «смени голос на X» / «поменяй голос X» / «включи голос X»
    m = re.search(r"(?:смени|поменяй|переключи|включи|поставь)\s+голос\s+(?:на\s+)?(\S+)", cmd)
    if m:
        name = m.group(1).strip().rstrip(".,!?").lower()
        key = ALIASES.get(name, name)
        if key in PIPER_VOICES:
            return switch(key)
        return f"Голос '{name}' не знаю. Доступны: {', '.join(PIPER_VOICES)}."

    # короткая форма «голос X»
    m = re.match(r"^голос\s+(\S+)$", cmd)
    if m:
        name = m.group(1).strip().rstrip(".,!?").lower()
        key = ALIASES.get(name, name)
        if key in PIPER_VOICES:
            return switch(key)
        return f"Голос '{name}' не знаю."

    return None