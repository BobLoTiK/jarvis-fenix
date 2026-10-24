"""Управление голосами TTS — работает через tts_engines.

Голоса НЕ хардкодятся здесь. Список берётся из активного движка
(jarvis.tts_engines.factory._try_create).

ВАЖНО: движок берётся из кэша factory (см. _ENGINE_CACHE там) —
поэтому повторные вызовы не грузят Silero/Piper заново.
"""

import logging
import re

from jarvis import config_manager
from jarvis.tts_engines.factory import _try_create, normalize_backend


log = logging.getLogger("jarvis.voices")


# Подсказки для каждой модели (для озвучки)
_BACKEND_HINT = {
    "piper":  "Piper: ruslan, dmitri, irina, denis",
    "silero": "Silero: aidar, baya, kseniya, xenia, eugene",
    "sapi":   "SAPI: зависит от системы",
}


# Кэш голосов по backend. Движки НЕ создаём каждый раз — это долго
# (Silero каждый раз грузит модель, Piper тянет HF).
_VOICES_CACHE: dict[str, dict] = {}

# Алиасы русских имён → канонические ключи.
# Для Piper и Silero они совпадают с ключами движка.
_VOICE_ALIASES = {
    # Piper
    "руслан": "ruslan", "руслана": "ruslan",
    "дмитрий": "dmitri", "дмитрия": "dmitri",
    "дима": "dmitri", "диму": "dmitri",
    "ирина": "irina", "ирину": "irina", "ире": "irina",
    "ира": "irina", "иру": "irina",
    "денис": "denis", "дениса": "denis",
    # Silero
    "айдар": "aidar", "айдара": "aidar",
    "бая": "baya", "баю": "baya",
    "ксения": "kseniya", "ксению": "kseniya",
    "евгений": "eugene", "евгения": "eugene",
    # SAPI (системные голоса Windows, ключи с заглавной)
    "павел": "pavel", "павла": "pavel",
}


def _hint_for(backend: str) -> str:
    """Человеческая подсказка по голосам для backend.

    Для auto — собираем подсказки всех движков.
    """
    hint = _BACKEND_HINT.get(backend)
    if hint:
        return hint
    return " | ".join(f"{k}: {v}" for k, v in _BACKEND_HINT.items())


# Fallback-голоса, если движок не загрузился (CI без piper/torch).
# Нужно для тестов, чтобы переключение голоса работало даже без движка.
_FALLBACK_VOICES = {
    "piper": {
        "ruslan": "Руслан — мужской",
        "dmitri": "Дмитрий — мужской",
        "irina":  "Ирина — женский",
        "denis":  "Денис — мужской",
    },
    "silero": {
        "aidar":   "Айдар",
        "baya":    "Бая",
        "kseniya": "Ксения",
        "xenia":   "Ксения (v5)",
        "eugene":  "Евгений",
    },
    "sapi": {"auto": "Авто"},
}


def _voices_for_backend(backend: str) -> dict:
    """Голоса движка. Кэшируется, чтобы не грузить движок на каждый вызов.

    Если движок не загрузился (нет piper/torch, CI), возвращаем
    fallback-словарь из _FALLBACK_VOICES — чтобы переключение голоса
    в тестах работало без реального синтеза.
    """
    backend = normalize_backend(backend)
    if backend in _VOICES_CACHE:
        return _VOICES_CACHE[backend]

    result: dict = {}

    if backend == "auto":
        for name in ("silero", "piper", "sapi"):
            eng = _try_create(name, "", "medium", 1.15)
            if eng is not None and eng.voices:
                result = dict(eng.voices)
                break
        # fallback если ничего не загрузилось
        if not result:
            result = dict(_FALLBACK_VOICES["piper"])
    else:
        eng = _try_create(backend, "", "medium", 1.15)
        if eng is not None:
            result = dict(eng.voices)
        # fallback если движок недоступен
        if not result:
            result = dict(_FALLBACK_VOICES.get(backend, {}))

    _VOICES_CACHE[backend] = result
    return result


def _normalize_voice(name: str) -> str:
    """Русское имя → канонический ключ. Без изменений, если не в алиасах."""
    return _VOICE_ALIASES.get(name.lower(), name.lower())


def _match_voice(key: str, voices: dict) -> str | None:
    """Ищет ключ голоса в словаре движка без учёта регистра.

    Ключи движков неоднородны: piper/silero — строчные («irina»),
    sapi — с заглавной («Pavel»). Возвращает ключ ровно таким,
    как он записан в движке, либо None, если голоса нет.
    """
    if key in voices:
        return key
    low = key.lower()
    for name in voices:
        if name.lower() == low:
            return name
    return None


def current_voice(config=None) -> str:
    if config is not None:
        return config.get("tts_voice", "ruslan")
    return config_manager.load().get("tts_voice", "ruslan")


def current_backend(config=None) -> str:
    if config is not None:
        return normalize_backend(config.get("tts_backend", "auto"))
    return normalize_backend(config_manager.load().get("tts_backend", "auto"))


def switch(voice: str, config=None) -> str:
    """Сменить голос текущего backend."""
    backend = current_backend(config)
    voices = _voices_for_backend(backend)

    if not voices:
        return f"Движок {backend} недоступен, голоса неизвестны."

    # Алиасы: «ирину» → «irina», «руслан» → «ruslan»
    key = _normalize_voice(voice)

    # Регистронезависимый матчинг: у sapi ключи с заглавной
    # («Pavel», «Irina»), а алиасы приводят имя к нижнему регистру.
    matched = _match_voice(key, voices)
    if matched is None:
        return (f"Голос '{voice}' не знаю. Доступные: "
                f"{', '.join(voices)}. Подсказка: {_hint_for(backend)}")

    key = matched
    if config is not None:
        config.set("tts_voice", key)
    else:
        config_manager.update("tts_voice", key)
    log.info("Голос переключён на %s (backend=%s)", key, backend)
    return f"Голос переключён на {key.capitalize()}."


def handle_voice_command(cmd: str, config=None) -> str | None:
    backend = current_backend(config)
    voices = _voices_for_backend(backend)

    if re.search(r"(какой|текущий|что\s+за)\s+голос", cmd) \
            or cmd in {"какой голос", "текущий голос"}:
        cur = current_voice(config)
        return f"Сейчас голос: {cur.capitalize()} (движок {backend})."

    if re.search(r"(список|какие|покажи|доступные)\s+голос", cmd) \
            or cmd in {"список голосов", "какие голоса", "покажи голоса"}:
        if not voices:
            return f"Движок {backend} недоступен."
        return (f"Голоса ({backend}): {', '.join(voices)}. "
                f"Подсказка: {_hint_for(backend)}")

    m = re.search(
        r"(?:смени|поменяй|переключи|включи|поставь)\s+голос\s+(?:на\s+)?(\S+)",
        cmd,
    )
    if m:
        return switch(m.group(1).strip().rstrip(".,!?").lower(), config)

    m = re.match(r"^голос\s+(\S+)$", cmd)
    if m:
        return switch(m.group(1).strip().rstrip(".,!?").lower(), config)

    return None


def reset_cache() -> None:
    """Сбросить кэш голосов (при смене backend)."""
    _VOICES_CACHE.clear()


# Список бэкендов — для GUI/CLI
def available_backends() -> list[str]:
    from jarvis.tts import available_backends as _ab
    return _ab()