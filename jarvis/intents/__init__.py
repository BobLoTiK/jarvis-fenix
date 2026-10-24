"""Разбор команд Феникса — пакет.

Публичный API:
    IntentHandler  — вызывается из main.py
    normalize      — реэкспорт (для совместимости)
"""
from jarvis.intents.handler import IntentHandler
from jarvis.text_utils import normalize

__all__ = ["IntentHandler", "normalize"]