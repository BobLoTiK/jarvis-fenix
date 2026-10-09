"""Ожидание уточнения (pending_question).

Сейчас единственный тип — `city_for_weather`:
Феникс спросил город, ждём ответа.
"""

import logging
import time

from jarvis import profile, weather
from jarvis.intents.stages.base import Stage

log = logging.getLogger("jarvis.intents")


_NOT_A_CITY = (
    "открой", "закрой", "найди", "включи", "выключи",
    "как дела", "кто ты", "спасибо", "привет", "пока",
    "который час", "какое число", "сделай скриншот",
    "загугли", "поищи", "напечатай",
)


class PendingStage(Stage):
    name = "pending"

    def handle(self, ctx):
        h = ctx.handler
        if not h._pending_question:
            return None
        if time.time() >= h._pending_question.get("expires_at", 0):
            h._pending_question = None
            return None
        return self._handle(ctx)

    def _handle(self, ctx) -> str:
        h = ctx.handler
        pending = h._pending_question
        h._pending_question = None

        if pending.get("type") == "city_for_weather":
            city = ctx.cmd.strip()
            words = city.split()

            if not city or len(city) > 60 or len(words) > 3:
                return "Не расслышал город. Повторите, пожалуйста."

            if any(w in city for w in _NOT_A_CITY):
                log.info("pending_question: %r не похоже на город — обрабатываю как команду", city)
                result = h._handle_single(ctx.cmd)
                return result if isinstance(result, str) else "Не понял команду."

            profile.set("default_city", city)
            log.info("Запомнил город по умолчанию: %s", city)

            day = pending.get("day", "today")
            w = weather.get_weather(city, day=day)
            if w:
                return f"Запомнил. {weather.describe_weather(w)}"
            return f"Запомнил город «{city}», но погоду узнать не удалось."

        return "Не понял уточнение."