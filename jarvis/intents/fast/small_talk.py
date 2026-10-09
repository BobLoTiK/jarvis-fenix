"""Мелкий разговор: время, дата, «кто ты», праздники.

Всё остальное (привет, как дела) — уходит в LLM.
Если LLM недоступна, этот модуль даёт минимальные ответы,
чтобы test_intents.py проходил без Ollama.
"""

import datetime

from jarvis import APP_NAME, __version__


MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]

WEEKDAYS = [
    "понедельник", "вторник", "среда", "четверг",
    "пятница", "суббота", "воскресенье",
]


def small_talk(handler, cmd: str) -> str | None:
    """Только точные команды. Диалог — через LLM."""

    # Праздничные триггеры — до всего остального.
    from jarvis import celebrations
    if celebrations.match_celebration(cmd):
        if handler.jarvis is not None:
            celebrations.start_celebration(handler.jarvis, handler.gui)
            return "\u200b"  # zero-width, чтобы handle не шёл в LLM
        return "Поздравляю! С днём рождения!"

    now = datetime.datetime.now()

    if any(p in cmd for p in ("который час", "сколько времени")):
        return f"Сейчас {now.hour} {_hours(now.hour)} {now.minute} {_minutes(now.minute)}."

    if any(p in cmd for p in ("какое число", "какая дата", "какое сегодня число")):
        return (f"Сегодня {now.day} {MONTHS[now.month - 1]} {now.year} года, "
                f"{WEEKDAYS[now.weekday()]}.")

    if "день недели" in cmd or cmd == "какой сегодня день":
        return f"Сегодня {WEEKDAYS[now.weekday()]}."

    # «Кто ты» — оставляем здесь, чтобы работало без LLM (test_intents).
    if any(p in cmd for p in ("кто ты", "ты кто", "представься", "как тебя зовут")):
        return f"Я {APP_NAME}, локальный голосовой ассистент, версия {__version__}."

    return None


def _hours(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "час"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "часа"
    return "часов"


def _minutes(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "минута"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "минуты"
    return "минут"