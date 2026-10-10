"""Фабрика TTS-движков.

По имени бэкенда ("piper", "silero", "auto") возвращает готовый engine.
"""

import logging

log = logging.getLogger("jarvis.tts")


def get_engine(backend: str, voice: str, quality: str = "medium",
               rate: float = 1.15):
    """Возвращает engine по имени.

    backend: "auto" | "piper" | "silero" | "winrt" | "sapi"
    При "auto" — первый доступный из списка приоритета.
    """
    if backend == "auto":
        for name in ("silero", "piper", "winrt", "sapi"):
            engine = _try_create(name, voice, quality, rate)
            if engine is not None:
                log.info("TTS auto: выбран движок %s", name)
                return engine
        log.error("TTS auto: ни один движок не доступен")
        return None

    return _try_create(backend, voice, quality, rate)


# Кэш созданных движков: (name, voice) → engine.
# Не создаём каждый раз — Silero грузит модель, Piper тянет HF.
_ENGINE_CACHE: dict[tuple[str, str], object] = {}


def _try_create(name: str, voice: str, quality: str, rate: float):
    """Создаёт движок или возвращает из кэша.

    ВАЖНО: не логируем warning про пустой голос, чтобы не спамить
    при проверке доступных движков (voice="").
    """
    key = (name, voice or "")
    if key in _ENGINE_CACHE:
        return _ENGINE_CACHE[key]

    engine = None
    try:
        if name == "silero":
            from jarvis.tts_engines.silero import SileroEngine
            engine = SileroEngine(voice or "aidar", quality, rate)
        elif name == "piper":
            from jarvis.tts_engines.piper import PiperEngine
            engine = PiperEngine(voice or "ruslan", quality, rate)
        elif name == "winrt":
            from jarvis.tts_engines.winrt import WinRTEngine
            engine = WinRTEngine(voice or "Pavel", quality, rate)
        elif name == "sapi":
            from jarvis.tts_engines.sapi import SAPIEngine
            engine = SAPIEngine(voice or "auto", quality, rate)
    except ImportError as e:
        log.debug("TTS: движок %s не установлен (%s)", name, e)
    except Exception:
        log.exception("TTS: движок %s упал при инициализации", name)

    if engine is not None:
        _ENGINE_CACHE[key] = engine
    return engine


def list_engines() -> list[str]:
    """Список доступных движков (по факту импорта)."""
    available = []
    for name in ("silero", "piper", "winrt", "sapi"):
        if _try_create(name, "", "medium", 1.15) is not None:
            available.append(name)
    return available