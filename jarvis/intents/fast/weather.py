"""Простые правила для погоды и курса — без LLM.

Если фраза явно про «курс доллара» или «какая погода», не гоняем
через brain.parse, а сразу отвечаем. Быстрее и надёжнее.

ВАЖНО про падежи:
    «погода в нижнем новгороде» — «нижнем новгороде» в предложном падеже.
    open-meteo такие формы не понимает.
    Стратегия (гибрид):
        1. Пробуем weather.normalize_city() — словарь топ-городов.
        2. Если не помогло — get_weather() не найдёт → return None.
        3. LLMStage подхватит и нормализует через промпт.
"""

import logging
import re
import time

from jarvis import profile, weather

log = logging.getLogger("jarvis.intents")


def weather_currency_fast(handler, cmd: str) -> str | None:
    # === Курс ===
    if re.search(r"\bкурс\b|\bвалют", cmd):
        code_map = {
            "доллар": "USD", "доллара": "USD", "бакс": "USD", "бакса": "USD",
            "евро": "EUR",
            "юан": "CNY", "юаня": "CNY",
            "фунт": "GBP", "фунта": "GBP",
            "йен": "JPY", "йены": "JPY",
            "лир": "TRY", "лиры": "TRY",
            "тенге": "KZT",
            "белорусск": "BYN", "бел рубл": "BYN",
            "гривн": "UAH",
        }
        code = ""
        for word, iso in code_map.items():
            if word in cmd:
                code = iso
                break
        r = weather.get_currency_rates()
        return weather.describe_currency(r, code=code)

    # === Погода ===
    if re.search(r"\bпогод|\bпрогноз", cmd):
        day = "tomorrow" if "завтра" in cmd else "today"

        # Явно названный город? («в москве», «в нижнем новгороде»)
        # Захватываем максимум 2 слова, но отсекаем предлоги/мусор:
        # «в питере на завтра» → «питере» (не «питере на»).
        m = re.search(r"\bв\s+([а-яёa-z\-]+(?:\s+[а-яёa-z\-]+)?)", cmd)
        explicit_city = m.group(1).strip() if m else ""

        # Отсекаем служебные слова, если затесались.
        if explicit_city:
            explicit_city = _strip_city_noise(explicit_city)

        if explicit_city:
            # Гибрид, шаг 1: пробуем нормализовать падеж словарём.
            normalized = weather.normalize_city(explicit_city)
            w = weather.get_weather(normalized, day=day)

            if not w:
                # Гибрид, шаг 2: пусть LLM нормализует. Возвращаем None,
                # LLMStage подхватит фразу и вызовет get_weather с
                # правильным target.
                log.debug(
                    "weather_fast: город %r не найден, отдаю LLM",
                    explicit_city,
                )
                return None

            return weather.describe_weather(w)

        # Город не назван — берём default_city из профиля.
        city = profile.get("default_city")
        if not city:
            handler._pending_question = {
                "type": "city_for_weather",
                "day": day,
                "expires_at": time.time() + 30,
            }
            return "В каком городе узнать погоду?"

        w = weather.get_weather(city, day=day)
        if not w:
            return None
        return weather.describe_weather(w)

    return None

# Служебные слова, которые regex может захватить вместе с городом.
_CITY_NOISE = (
    " на", " завтра", " сегодня", " сейчас", " пожалуйста",
    " погода", " прогноз",
)


def _strip_city_noise(raw: str) -> str:
    """Убирает служебные слова, случайно захваченные regex.

    «питере на»        → «питере»
    «москве сегодня»   → «москве»
    «казань пожалуйста» → «казань»
    """
    text = " " + raw.lower()
    for noise in _CITY_NOISE:
        idx = text.find(noise)
        if idx > 0:
            text = text[:idx]
    return text.strip()