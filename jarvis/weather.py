"""Погода и курс валют.

Источники:
    - open-meteo.com (погода, без ключа)
    - cbr-xml-daily.ru (курс ЦБ РФ, без ключа)

Кэш: 10 минут на город / на курс.

ВАЖНО: нормализация города и валюты (падежи, синонимы, ISO-коды) — задача LLM.
Этот модуль ожидает уже нормализованные данные.
"""

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from typing import Optional

from jarvis import __version__

log = logging.getLogger("jarvis.weather")

# Кэш: {(тип, ключ): (timestamp, data)}
_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()

# TTL по умолчанию, если Config недоступен.
_DEFAULT_TTL = 600  # 10 минут

# Ссылка на Config — устанавливается через set_config() из main.py.
_config = None


def set_config(config) -> None:
    """Регистрирует Config — оттуда читаем weather_cache_ttl_sec.

    Вызывается один раз при старте Феникса.
    """
    global _config
    _config = config
    log.info("weather: Config подключён, TTL = %d сек",
             _current_ttl())


def _current_ttl() -> int:
    """Актуальный TTL кэша в секундах.

    Читает weather_cache_ttl_sec из Config на КАЖДЫЙ вызов —
    чтобы смена значения на лету работала.
    """
    if _config is None:
        return _DEFAULT_TTL
    try:
        v = _config.get("weather_cache_ttl_sec", _DEFAULT_TTL)
        v = int(v)
        return v if v > 0 else _DEFAULT_TTL
    except (TypeError, ValueError):
        return _DEFAULT_TTL


def _cached(key: tuple, fetcher):
    now = time.time()
    ttl = _current_ttl()

    with _CACHE_LOCK:
        if key in _CACHE:
            ts, data = _CACHE[key]
            if now - ts < ttl:
                return data

    # fetcher() вызываем ВНЕ лока — иначе блокируем HTTP на весь кэш
    data = fetcher()

    if data is not None:
        with _CACHE_LOCK:
            _CACHE[key] = (time.time(), data)
    return data


def _http_get_json(url: str, timeout: float = 8.0):
    # User-Agent — из версии проекта, чтобы не отставать от __version__.
    ua = f"Phoenix/{__version__}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": ua})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        log.exception("HTTP GET не удался: %s", url)
        return None


# --- геокодинг --------------------------------------------------------------

def geocode(city: str) -> Optional[dict]:
    """Возвращает {'name': ..., 'country': ..., 'lat': ..., 'lon': ...} или None.

    Ожидает название города в именительном падеже (нормализует LLM).
    """
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
        "country": r.get("country") or "",
        "admin1": r.get("admin1") or "",
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
                "country": geo.get("country", ""),
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
            "country": geo.get("country", ""),
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
    """Формирует человеческую фразу для озвучки.

    Падежи: «Сейчас в городе Казань» / «Завтра в городе Казань» —
    именительный падеж уместен, никаких склонений не нужно.
    """
    if not w:
        return "Не удалось узнать погоду."
    code = w.get("code", -1)
    desc = _WEATHER_CODES.get(code, "неизвестно")

    country = (w.get("country") or "").strip()
    city = w.get("city", "")
    city_full = f"{city}, {country}" if country else city

    if w.get("day") == "завтра":
        return (
            f"Прогноз на завтра — {city_full}: {desc}, "
            f"от {w['temp_min']} до {w['temp_max']} градусов, "
            f"осадки {round(w['precip'], 1)} мм."
        )
    return (
        f"Сейчас в городе {city_full}: {desc}, "
        f"{w['temp']} градусов, ощущается как {w['feels']}. "
        f"Ветер {w['wind']} метров в секунду, влажность {w['humidity']} процентов. "
        f"Днём от {w['temp_min']} до {w['temp_max']} градусов."
    )


# --- курс валют -------------------------------------------------------------

def get_currency_rates() -> Optional[dict]:
    """Возвращает все валюты ЦБ:
        {
            "date": "2026-10-04",
            "valutes": {
                "USD": {"name": "Доллар США", "value": 83.48, "nominal": 1},
                "EUR": {...},
                "BYN": {...},
                ...
            }
        }
    """
    key = ("currency", "cbr")
    return _cached(key, _get_currency_uncached)


def _get_currency_uncached() -> Optional[dict]:
    url = "https://www.cbr-xml-daily.ru/daily_json.js"
    data = _http_get_json(url)
    if not data:
        return None
    try:
        valutes = {}
        for code, v in data["Valute"].items():
            valutes[code] = {
                "name": v.get("Name") or code,
                "value": v.get("Value"),
                "nominal": v.get("Nominal", 1),
            }
        return {
            "date": data.get("Date", "")[:10],
            "valutes": valutes,
        }
    except (KeyError, TypeError):
        log.exception("Не удалось разобрать ответ ЦБ")
        return None


# Приоритет для вывода «общего курса»
_DEFAULT_CURRENCIES = ["USD", "EUR", "CNY"]


def describe_currency(rates: dict, code: str = "") -> str:
    """Озвучивает курс.

    rates: результат get_currency_rates()
    code:  ISO-код валюты ("USD", "BYN", "KZT", ...). Пусто — основные.
    """
    if not rates:
        return "Не удалось узнать курс валют."

    valutes = rates.get("valutes", {})

    # Конкретная валюта
    if code:
        v = valutes.get(code.upper())
        if not v:
            return f"Курс валюты {code} не нашёл в базе ЦБ."
        nominal = v.get("nominal") or 1
        value = v.get("value")
        if value is None:
            return f"Курс валюты {code} не удалось прочитать."
        if nominal == 1:
            return f"{v['name']} — {value:.2f} рубля."
        return f"{v['name']} ({nominal} шт.) — {value:.2f} рубля."

    # Общий курс — основные валюты
    parts = []
    for c in _DEFAULT_CURRENCIES:
        v = valutes.get(c)
        if not v or v.get("value") is None:
            continue
        parts.append(f"{v['name']} — {v['value']:.2f} рубля")

    if not parts:
        return "Не удалось прочитать основные валюты."

    date = rates.get("date") or "сегодня"
    return f"Курс ЦБ на {date}: " + ", ".join(parts) + "."