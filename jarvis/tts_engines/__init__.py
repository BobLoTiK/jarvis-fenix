"""TTS-движки Феникса — абстракция над Piper, Silero, WinRT, SAPI.

Публичный API:
    BaseEngine   — абстрактный класс
    get_engine   — фабрика по имени бэкенда
    list_engines — список доступных движков
"""

from jarvis.tts_engines.base import BaseEngine
from jarvis.tts_engines.factory import get_engine, list_engines

__all__ = ["BaseEngine", "get_engine", "list_engines"]