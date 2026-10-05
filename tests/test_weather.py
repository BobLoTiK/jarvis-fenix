"""Тесты weather: структура ответов, describe_*. Сеть не нужна — мокаем."""
from unittest.mock import patch

from jarvis import weather


def test_describe_weather_none():
    assert "Не удалось" in weather.describe_weather(None)


def test_describe_weather_today():
    w = {
        "city": "Москва", "country": "Россия", "day": "сегодня",
        "temp": 5, "feels": 2, "code": 3, "wind": 4,
        "humidity": 70, "temp_min": 1, "temp_max": 8, "precip": 0.2,
    }
    s = weather.describe_weather(w)
    assert "Москва" in s
    assert "5 градусов" in s
    assert "Россия" in s


def test_describe_weather_tomorrow():
    w = {
        "city": "Казань", "country": "Россия", "day": "завтра",
        "temp_min": -2, "temp_max": 3, "code": 71, "precip": 1.5,
    }
    s = weather.describe_weather(w)
    assert "Казань" in s
    assert "завтра" in s


def test_describe_currency_specific():
    rates = {
        "date": "2026-10-04",
        "valutes": {
            "USD": {"name": "Доллар США", "value": 83.48, "nominal": 1},
            "BYN": {"name": "Белорусский рубль", "value": 27.5, "nominal": 1},
        },
    }
    s = weather.describe_currency(rates, code="BYN")
    assert "Белорусский" in s
    assert "27.50" in s


def test_describe_currency_default():
    rates = {
        "date": "2026-10-04",
        "valutes": {
            "USD": {"name": "Доллар США", "value": 83.48, "nominal": 1},
            "EUR": {"name": "Евро", "value": 94.32, "nominal": 1},
        },
    }
    s = weather.describe_currency(rates)
    assert "Доллар" in s and "Евро" in s


def test_describe_currency_unknown():
    rates = {"date": "2026-10-04", "valutes": {}}
    s = weather.describe_currency(rates, code="XXX")
    assert "не нашёл" in s