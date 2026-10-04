"""Погода и курс валют.

Источники:
    - open-meteo.com (погода, без ключа)
    - cbr-xml-daily.ru (курс ЦБ РФ, без ключа)

Кэш: 10 минут на город / на курс.
"""

import json
import logging
import time
import urllib.parse
import urllib.request
from typing import Optional

log = logging.getLogger("jarvis.weather")

# Кэш: {(тип, ключ): (timestamp, data)}
_CACHE: dict = {}
_CACHE_TTL = 600  # 10 минут


def _cached(key: tuple, fetcher):
    now = time.time()
    if key in _CACHE:
        ts, data = _CACHE[key]
        if now - ts < _CACHE_TTL:
            return data
    data = fetcher()
    if data is not None:
        _CACHE[key] = (now, data)
    return data


def _http_get_json(url: str, timeout: float = 8.0):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Phoenix/0.2.2"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        log.exception("HTTP GET не удался: %s", url)
        return None


# --- геокодинг --------------------------------------------------------------

def geocode(city: str) -> Optional[dict]:
    """Возвращает {'name': ..., 'lat': ..., 'lon': ...} или None."""
    key = ("geo", city.lower().strip())
    return _cached(key, lambda: _geocode_uncached(city))


def _geocode_uncached(city: str) -> Optional[dict]:
    q = urllib.parse.quote(city.strip())
    url = f"https://geocoding-api.open-meteo.com/v1/search?name={q}&count=1&language=ru&format=json"
    data = _http_get_json(url)
    if not data:
        return None
    results = data.get("results")
    if not results:
        return None
    r = results[0]
    return {
        "name": r.get("name") or city,
        "lat": r.get("latitude"),
        "lon": r.get("longitude"),
    }


# --- погода -----------------------------------------------------------------

_WEATHER_CODES = {
    0: "ясно",
    1: "преимущественно ясно", 2: "переменная облачность", 3: "пасмурно",
    45: "туман", 48: "изморозь",
    51: "лёгкая морось", 53: "морось", 55: "сильная морось",
    61: "небольшой дождь", 63: "дождь", 65: "сильный дождь",
    71: "небольшой снег", 73: "снег", 75: "сильный снег",
    77: "снежная крупа",
    80: "небольшие ливни", 81: "ливни", 82: "сильные ливни",
    85: "снегопад", 86: "сильный снегопад",
    95: "гроза", 96: "гроза с градом", 99: "сильная гроза с градом",
}


def get_weather(city: str, day: str = "today") -> Optional[dict]:
    """Возвращает погоду для города.
    
    day: 'today' | 'tomorrow'
    """
    key = ("weather", city.lower().strip(), day)
    return _cached(key, lambda: _get_weather_uncached(city, day))


def _get_weather_uncached(city: str, day: str) -> Optional[dict]:
    geo = geocode(city)
    if not geo:
        return None
    lat, lon = geo["lat"], geo["lon"]
    params = (
        f"latitude={lat}&longitude={lon}"
        "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m"
        "&daily=temperature_2m_max,temperature_2m_min,weather_code,precipitation_sum"
        "&timezone=auto&forecast_days=2"
    )
    url = f"https://api.open-meteo.com/v1/forecast?{params}"
    data = _http_get_json(url)
    if not data:
        return None

    try:
        if day == "tomorrow":
            return {
                "city": geo["name"],
                "day": "завтра",
                "temp_min": round(data["daily"]["temperature_2m_min"][1]),
                "temp_max": round(data["daily"]["temperature_2m_max"][1]),
                "code": data["daily"]["weather_code"][1],
                "precip": data["daily"]["precipitation_sum"][1] or 0,
            }
        cur = data["current"]
        daily = data["daily"]
        return {
            "city": geo["name"],
            "day": "сегодня",
            "temp": round(cur["temperature_2m"]),
            "feels": round(cur["apparent_temperature"]),
            "code": cur["weather_code"],
            "wind": round(cur["wind_speed_10m"]),
            "humidity": cur["relative_humidity_2m"],
            "temp_min": round(daily["temperature_2m_min"][0]),
            "temp_max": round(daily["temperature_2m_max"][0]),
            "precip": daily["precipitation_sum"][0] or 0,
        }
    except (KeyError, IndexError, TypeError):
        log.exception("Не удалось разобрать ответ погоды")
        return None


def describe_weather(w: dict) -> str:
    """Формирует человеческую фразу для озвучки."""
    if not w:
        return "Не удалось узнать погоду."
    code = w.get("code", -1)
    desc = _WEATHER_CODES.get(code, "неизвестно")
    if w.get("day") == "завтра":
        return (
            f"Погода в {w['city']} на завтра: {desc}, "
            f"от {w['temp_min']} до {w['temp_max']} градусов, "
            f"осадки {round(w['precip'], 1)} мм."
        )
    return (
        f"Погода в {w['city']} сейчас: {desc}, "
        f"{w['temp']} градусов, ощущается как {w['feels']}. "
        f"Ветер {w['wind']} метров в секунду, влажность {w['humidity']} процентов. "
        f"Днём от {w['temp_min']} до {w['temp_max']} градусов."
    )


# --- курс валют -------------------------------------------------------------

def get_currency_rates() -> Optional[dict]:
    """Возвращает {'USD': ..., 'EUR': ..., 'date': ...} (рублей за единицу)."""
    key = ("currency", "cbr")
    return _cached(key, _get_currency_uncached)


def _get_currency_uncached() -> Optional[dict]:
    url = "https://www.cbr-xml-daily.ru/daily_json.js"
    data = _http_get_json(url)
    if not data:
        return None
    try:
        val = data["Valute"]
        return {
            "date": data.get("Date", "")[:10],
            "USD": val["USD"]["Value"],
            "EUR": val["EUR"]["Value"],
            "CNY": val.get("CNY", {}).get("Value"),
        }
    except (KeyError, TypeError):
        log.exception("Не удалось разобрать ответ ЦБ")
        return None


def describe_currency(rates: dict) -> str:
    if not rates:
        return "Не удалось узнать курс валют."
    parts = [f"Доллар — {rates['USD']:.2f} рубля", f"евро — {rates['EUR']:.2f} рубля"]
    if rates.get("CNY"):
        parts.append(f"юань — {rates['CNY']:.2f} рубля")
    return "Курс ЦБ на сегодня: " + ", ".join(parts) + "."