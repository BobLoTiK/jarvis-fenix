"""Первый запуск — знакомство через LLM-диалог.

Никаких сценариев. LLM ведёт диалог ненавязчиво.
Observer работает параллельно и сохраняет факты.
"""

import logging

from jarvis import persona

log = logging.getLogger("jarvis.first_run")


def is_first_run() -> bool:
    return not persona.is_onboarded()


def greeting() -> str:
    return (
        "Привет! Я Феникс, локальный голосовой помощник. "
        "Не хочешь немного поболтать? Расскажи — чем занимаешься, что нового?"
    )

def mark_done() -> None:
    persona.mark_onboarded()
    log.info("First run: знакомство завершено")