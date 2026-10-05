"""Тесты weather: структура ответов, describe_*, geocode с моками.

Сеть не нужна — мокаем _http_get_json.
"""

from unittest.mock import patch

from jarvis import weather


# --- describe_weather ------------------------------------------------------

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


# --- describe_currency -----------------------------------------------------

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


# --- geocode с моками ------------------------------------------------------

def test_geocode_ok():
    """geocode возвращает нормализованный dict при успешном ответе."""
    fake = {
        "results": [{
            "name": "Москва",
            "country": "Россия",
            "admin1": "Москва",
            "latitude": 55.75,
            "longitude": 37.62,
        }],
    }
    with patch.object(weather, "_http_get_json", return_value=fake):
        weather._CACHE.clear()
        geo = weather.geocode("Москва")
    assert geo is not None
    assert geo["name"] == "Москва"
    assert geo["country"] == "Россия"
    assert geo["lat"] == 55.75
    assert geo["lon"] == 37.62


def test_geocode_not_found():
    """geocode возвращает None, если результатов нет."""
    with patch.object(weather, "_http_get_json", return_value={"results": []}):
        weather._CACHE.clear()
        assert weather.geocode("НесуществующийГород12345") is None


def test_geocode_http_error():
    """geocode возвращает None, если _http_get_json вернул None (сеть упала)."""
    with patch.object(weather, "_http_get_json", return_value=None):
        weather._CACHE.clear()
        assert weather.geocode("Москва") is None


# --- _get_weather_uncached с моками ----------------------------------------

def test_get_weather_today_ok():
    """get_weather парсит ответ open-meteo и возвращает dict."""
    geo = {"name": "Москва", "country": "Россия", "lat": 55.75, "lon": 37.62}
    api = {
        "current": {
            "temperature_2m": 5.4,
            "apparent_temperature": 2.1,
            "weather_code": 3,
            "wind_speed_10m": 4.2,
            "relative_humidity_2m": 70,
        },
        "daily": {
            "temperature_2m_min": [1.0, -2.0],
            "temperature_2m_max": [8.0, 3.0],
            "weather_code": [3, 71],
            "precipitation_sum": [0.2, 1.5],
        },
    }
    with patch.object(weather, "geocode", return_value=geo), \
         patch.object(weather, "_http_get_json", return_value=api):
        weather._CACHE.clear()
        w = weather.get_weather("Москва", day="today")
    assert w is not None
    assert w["city"] == "Москва"
    assert w["temp"] == 5
    assert w["feels"] == 2
    assert w["code"] == 3
    assert w["wind"] == 4
    assert w["humidity"] == 70
    assert w["temp_min"] == 1
    assert w["temp_max"] == 8


def test_get_weather_tomorrow_ok():
    """get_weather(day='tomorrow') берёт индексы [1] из daily."""
    geo = {"name": "Казань", "country": "Россия", "lat": 55.79, "lon": 49.11}
    api = {
        "current": {
            "temperature_2m": 5.4, "apparent_temperature": 2.1,
            "weather_code": 3, "wind_speed_10m": 4.2, "relative_humidity_2m": 70,
        },
        "daily": {
            "temperature_2m_min": [1.0, -2.0],
            "temperature_2m_max": [8.0, 3.0],
            "weather_code": [3, 71],
            "precipitation_sum": [0.2, 1.5],
        },
    }
    with patch.object(weather, "geocode", return_value=geo), \
         patch.object(weather, "_http_get_json", return_value=api):
        weather._CACHE.clear()
        w = weather.get_weather("Казань", day="tomorrow")
    assert w is not None
    assert w["day"] == "завтра"
    assert w["temp_min"] == -2
    assert w["temp_max"] == 3
    assert w["code"] == 71


def test_get_weather_no_geocode():
    """Если geocode не нашёл город — get_weather возвращает None."""
    with patch.object(weather, "geocode", return_value=None):
        weather._CACHE.clear()
        assert weather.get_weather("НесуществующийГород12345") is None


# --- get_currency_rates с моками -------------------------------------------

def test_get_currency_rates_ok():
    """get_currency_rates парсит ответ ЦБ."""
    api = {
        "Date": "2026-10-04T11:30:00+03:00",
        "Valute": {
            "USD": {"Name": "Доллар США", "Value": 83.48, "Nominal": 1},
            "EUR": {"Name": "Евро", "Value": 94.32, "Nominal": 1},
            "BYN": {"Name": "Белорусский рубль", "Value": 27.5, "Nominal": 1},
        },
    }
    with patch.object(weather, "_http_get_json", return_value=api):
        weather._CACHE.clear()
        r = weather.get_currency_rates()
    assert r is not None
    assert r["date"] == "2026-10-04"
    assert r["valutes"]["USD"]["value"] == 83.48
    assert r["valutes"]["BYN"]["name"] == "Белорусский рубль"


def test_get_currency_rates_http_error():
    """get_currency_rates возвращает None при падении сети."""
    with patch.object(weather, "_http_get_json", return_value=None):
        weather._CACHE.clear()
        assert weather.get_currency_rates() is None


# --- кэш -------------------------------------------------------------------

def test_cache_used():
    """Второй вызов geocode не дёргает _http_get_json — берёт из кэша."""
    fake = {
        "results": [{
            "name": "Москва", "country": "Россия",
            "latitude": 55.75, "longitude": 37.62,
        }],
    }
    weather._CACHE.clear()
    with patch.object(weather, "_http_get_json", return_value=fake) as mock:
        weather.geocode("Москва")
        weather.geocode("Москва")
    assert mock.call_count == 1, "Второй вызов должен брать из кэша"


def test_cache_different_cities():
    """Разные города — разные ключи кэша, _http_get_json вызывается дважды."""
    fake_msk = {
        "results": [{"name": "Москва", "country": "Россия",
                     "latitude": 55.75, "longitude": 37.62}],
    }
    fake_kzn = {
        "results": [{"name": "Казань", "country": "Россия",
                     "latitude": 55.79, "longitude": 49.11}],
    }
    weather._CACHE.clear()
    with patch.object(weather, "_http_get_json") as mock:
        mock.side_effect = [fake_msk, fake_kzn]
        weather.geocode("Москва")
        weather.geocode("Казань")
    assert mock.call_count == 2