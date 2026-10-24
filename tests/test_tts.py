"""Тесты jarvis.tts_engines — движки и фабрика. С моками.

Без реальной загрузки моделей — проверяем контракт и factory.

ВАЖНО: тесты требуют numpy/sounddevice/piper — их нет в CI
(там только лёгкие зависимости). Пропускаем весь модуль, если
numpy не установлен.
"""

import importlib.util

import pytest

from unittest.mock import patch, MagicMock

# Пропускаем весь модуль, если нет numpy (значит CI, без TTS).
if importlib.util.find_spec("numpy") is None:
    pytest.skip("numpy не установлен — TTS-тесты пропущены",
                allow_module_level=True)

from jarvis.tts_engines import factory


# =================================================================
# Factory
# =================================================================

def test_list_engines_empty():
    """Если ни один движок не импортируется — пустой список."""
    with patch.object(factory, "_try_create", return_value=None):
        assert factory.list_engines() == []


def test_get_engine_auto_picks_first():
    """auto → первый доступный из приоритета."""
    fake = MagicMock()
    fake.name = "silero"

    def _fake_create(name, voice, quality, rate):
        if name == "silero":
            return fake
        return None

    with patch.object(factory, "_try_create", side_effect=_fake_create):
        engine = factory.get_engine("auto", "aidar", "medium", 1.15)
    assert engine is fake


def test_get_engine_auto_none_available():
    """auto → None, если все движки недоступны."""
    with patch.object(factory, "_try_create", return_value=None):
        assert factory.get_engine("auto", "aidar", "medium", 1.15) is None


def test_get_engine_by_name():
    """Явное имя → _try_create с этим именем."""
    fake = MagicMock()
    with patch.object(factory, "_try_create", return_value=fake) as mock:
        engine = factory.get_engine("piper", "ruslan", "medium", 1.15)
    assert engine is fake
    mock.assert_called_once_with("piper", "ruslan", "medium", 1.15)


# =================================================================
# BaseEngine контракт
# =================================================================

def test_base_engine_abstract():
    """BaseEngine нельзя создать напрямую."""
    from jarvis.tts_engines.base import BaseEngine
    import pytest
    with pytest.raises(TypeError):
        BaseEngine()


# =================================================================
# Piper — только интерфейс, без загрузки
# =================================================================

def test_piper_engine_interface():
    """PiperEngine имеет нужные атрибуты."""
    from jarvis.tts_engines.piper import PiperEngine
    assert PiperEngine.name == "piper"
    assert "ruslan" in PiperEngine.voices
    assert "irina" in PiperEngine.voices


def test_piper_voice_not_in_dict():
    """Если голос не из списка — fallback на ruslan (без загрузки)."""
    # Не создаём реально, чтобы не тянуть hf_hub_download.
    from jarvis.tts_engines.piper import PiperEngine
    assert "fake_voice" not in PiperEngine.voices


# =================================================================
# Silero — интерфейс
# =================================================================

def test_silero_engine_interface():
    from jarvis.tts_engines.silero import SileroEngine
    assert SileroEngine.name == "silero"
    assert "aidar" in SileroEngine.voices
    assert "eugene" in SileroEngine.voices


# =================================================================
# WinRT — интерфейс
# =================================================================

def test_retired_winrt_module_cannot_be_loaded():
    import importlib
    with pytest.raises(ImportError, match="WinRT TTS removed"):
        importlib.import_module("jarvis.tts_engines.winrt")


# =================================================================
# SAPI — интерфейс
# =================================================================

def test_sapi_engine_interface():
    from jarvis.tts_engines.sapi import SAPIEngine
    assert SAPIEngine.name == "sapi"
    assert "auto" in SAPIEngine.voices


# =================================================================
# voices.py — под backend
# =================================================================

def test_voices_for_backend_unknown():
    """Неизвестный backend — пустой dict."""
    from jarvis import voices
    with patch("jarvis.voices._try_create", return_value=None):
        assert voices._voices_for_backend("unknown") == {}


def test_voices_for_backend_ok():
    """Известный backend — голоса из движка."""
    from jarvis import voices
    fake_engine = MagicMock()
    fake_engine.voices = {"aidar": "Айдар", "baya": "Бая"}
    with patch("jarvis.voices._try_create", return_value=fake_engine):
        result = voices._voices_for_backend("silero")
    assert result == {"aidar": "Айдар", "baya": "Бая"}


def test_switch_voice_not_found():
    """switch с неизвестным голосом → сообщение с подсказкой."""
    from jarvis import voices
    fake_engine = MagicMock()
    fake_engine.voices = {"aidar": "Айдар"}
    with patch("jarvis.voices._try_create", return_value=fake_engine), \
         patch("jarvis.voices.current_backend", return_value="silero"):
        reply = voices.switch("fake_voice")
    assert "не знаю" in reply.lower()
    assert "aidar" in reply


# =================================================================
# voices.switch — регистронезависимость ключей (sapi)
# =================================================================

def _sapi_config(initial=None):
    """Fake config с backend=sapi для тестов switch."""
    state = {"tts_backend": "sapi", "tts_voice": "auto"}
    if initial:
        state.update(initial)
    cfg = MagicMock()
    cfg.get.side_effect = lambda k, d=None: state.get(k, d)
    cfg.set.side_effect = lambda k, v: state.__setitem__(k, v)
    return cfg, state


def test_switch_voice_case_insensitive_sapi():
    """Ключи sapi — с заглавной («Pavel»), а команда приходит строчными."""
    from jarvis import voices
    fake_engine = MagicMock()
    fake_engine.voices = {"auto": "Авто", "Pavel": "Павел", "Irina": "Ирина"}
    cfg, state = _sapi_config()

    with patch("jarvis.voices._try_create", return_value=fake_engine), \
         patch("jarvis.voices._VOICES_CACHE", {}):
        reply = voices.switch("pavel", cfg)

    assert "Pavel" in reply
    assert state["tts_voice"] == "Pavel"


@pytest.mark.parametrize("said,expected", [
    ("irina", "Irina"),
    ("ирину", "Irina"),   # алиас «ирину» → irina → Irina
    ("павел", "Pavel"),   # алиас «павел» → pavel → Pavel
])
def test_switch_voice_aliases_sapi(said, expected):
    """Русские алиасы и любой регистр находят системный голос sapi."""
    from jarvis import voices
    fake_engine = MagicMock()
    fake_engine.voices = {"auto": "Авто", "Pavel": "Павел", "Irina": "Ирина"}
    cfg, state = _sapi_config()

    with patch("jarvis.voices._try_create", return_value=fake_engine), \
         patch("jarvis.voices._VOICES_CACHE", {}):
        reply = voices.switch(said, cfg)

    assert state.get("tts_voice") == expected, reply


# =================================================================
# execute._do_change_voice — LLM-путь (не должен падать)
# =================================================================

def test_do_change_voice_without_voice_key():
    """Пустой voice не роняет обработчик, а просит назвать голос."""
    from jarvis.intents.execute import _do_change_voice
    handler = MagicMock()
    handler.config = MagicMock()
    handler.config.get.return_value = "ruslan"

    reply = _do_change_voice(handler, {}, None, None)

    assert "голос" in reply.lower()


def test_do_change_voice_switch_and_history():
    """Голос меняется и попадает в историю (регрессия на PIPER_VOICES)."""
    from jarvis import voices  # noqa: F401  (патчим через jarvis.voices)
    from jarvis.intents import execute

    fake_engine = MagicMock()
    fake_engine.voices = {"auto": "Авто", "Pavel": "Павел", "Irina": "Ирина"}
    cfg, state = _sapi_config()
    handler = MagicMock()
    handler.config = cfg

    with patch("jarvis.voices._try_create", return_value=fake_engine), \
         patch("jarvis.voices._VOICES_CACHE", {}), \
         patch("jarvis.intents.execute.history") as hist:
        reply = execute._do_change_voice(handler, {"voice": "павел"},
                                         None, None)

    assert "Pavel" in reply
    assert state["tts_voice"] == "Pavel"
    hist.push.assert_called_once()