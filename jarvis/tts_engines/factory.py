"""Фабрика TTS-движков.

По имени бэкенда ("piper", "silero", "auto") возвращает готовый engine.
"""

import importlib
import importlib.util
import logging

log = logging.getLogger("jarvis.tts")

# Модуль и класс каждого движка — для «заглушки» без создания движка.
_ENGINE_IMPORTS = {
    "silero": ("jarvis.tts_engines.silero", "SileroEngine"),
    "piper":  ("jarvis.tts_engines.piper", "PiperEngine"),
    "sapi":   ("jarvis.tts_engines.sapi", "SAPIEngine"),
}

# Пакет, без которого движок не работает (проверка дешёвая, без импорта).
_ENGINE_REQUIRES = {
    "silero": "torch",
    "piper":  "piper",
    "sapi":   "pyttsx3",
}


class _EngineProbe:
    """Заглушка движка — только для служебных вызовов (voice="").

    Настоящий движок создавать дорого: Silero грузит torch + модель
    (~150 МБ), Piper тянет модель с HF Hub (~3 с сетевого round-trip
    на КАЖДЫЙ вызов). Раньше это платилось за открытие вкладки
    «Главная»: GUI просит список голосов, а получал полноценную загрузку.
    Голоса — статические атрибуты классов, поэтому хватает импорта модуля.

    Синтез через заглушку невозможен (и не нужен): Speaker всегда
    передаёт конкретный голос из config.
    """

    def __init__(self, name: str, cls) -> None:
        self.name = name
        self.voices = dict(getattr(cls, "voices", {}) or {})
        self.default_quality = getattr(cls, "default_quality", "medium")
        self.default_rate = getattr(cls, "default_rate", 1.15)

    def is_available(self) -> bool:
        return bool(self.voices)

    def __repr__(self) -> str:
        return f"<_EngineProbe {self.name} voices={len(self.voices)}>"


# Кэш заглушек: (name) → _EngineProbe | None.
_PROBE_CACHE: dict[str, object] = {}


def _dependency_present(module_name: str) -> bool:
    """Есть ли пакет, нужный движку (без реального импорта)."""
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def _probe_engine(name: str):
    """Заглушка движка по имени. None — модуля/зависимости нет."""
    if name not in _ENGINE_IMPORTS:
        return None
    if name in _PROBE_CACHE:
        return _PROBE_CACHE[name]

    probe = None
    entry = _ENGINE_IMPORTS.get(name)
    if entry is not None:
        module_name, class_name = entry
        requires = _ENGINE_REQUIRES.get(name)
        if requires is None or _dependency_present(requires):
            try:
                module = importlib.import_module(module_name)
                probe = _EngineProbe(name, getattr(module, class_name))
            except Exception as e:
                log.debug("TTS: движок %s не импортируется (%s)", name, e)

    _PROBE_CACHE[name] = probe
    return probe


def normalize_backend(backend):
    """Retired stored WinRT selection falls back without loading the old engine."""
    if backend == "winrt":
        log.warning("TTS: WinRT speech removed; using auto (Silero -> Piper -> SAPI)")
        return "auto"
    return backend


def get_engine(backend: str, voice: str, quality: str = "medium",
               rate: float = 1.15):
    """Возвращает engine по имени.

    backend: "auto" | "piper" | "silero" | "sapi"
    При "auto" — первый доступный из списка приоритета.

    ВАЖНО: voice="" — служебный вызов (список голосов / список движков),
    движок при этом НЕ создаётся, см. _probe_engine.
    """
    backend = normalize_backend(backend)
    if backend == "auto":
        for name in ("silero", "piper", "sapi"):
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
    при проверке доступных движков (voice=""). В этом же случае
    возвращаем дешёвую заглушку — движок не создаём.
    """
    if name not in _ENGINE_IMPORTS:
        return None  # retired names cannot be revived through either cache
    if voice == "":
        return _probe_engine(name)

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
    for name in ("silero", "piper", "sapi"):
        if _try_create(name, "", "medium", 1.15) is not None:
            available.append(name)
    return available