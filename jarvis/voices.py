"""Управление голосами Piper: ruslan, dmitri, irina, denis.

Голосом: «смени голос на ирину», «голос дмитрий», «какой голос», «список голосов».
Сохраняется в config.json → tts_voice. Запись атомарная, с мьютексом.
"""

import json
import logging
import re
import threading
from pathlib import Path

log = logging.getLogger("jarvis.voices")

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"
_write_lock = threading.Lock()

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


def _atomic_write(path: Path, data: dict) -> None:
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


def current_voice() -> str:
    cfg = _read_config()
    return cfg.get("tts_voice", "ruslan")


def switch(voice: str) -> str:
    if voice not in PIPER_VOICES:
        return f"Голос '{voice}' не знаю. Доступны: {', '.join(PIPER_VOICES)}."
    try:
        cfg = _read_config()
        cfg["tts_voice"] = voice
        _atomic_write(CONFIG_PATH, cfg)
        log.info("Голос переключён на %s", voice)
    except Exception:
        log.exception("Не удалось сохранить голос")
        return f"Не удалось переключить голос на {voice}."
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