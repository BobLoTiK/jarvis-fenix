"""Простые правила для погоды и курса — без LLM.

Если фраза явно про «курс доллара» или «какая погода», не гоняем
через brain.parse, а сразу отвечаем. Быстрее и надёжнее.
"""

import re
import time

from jarvis import profile, weather


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

        m = re.search(r"\bв\s+([а-яёa-z\-]+(?:\s+[а-яёa-z\-]+)?)", cmd)
        city = m.group(1).strip() if m else ""

        if not city:
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