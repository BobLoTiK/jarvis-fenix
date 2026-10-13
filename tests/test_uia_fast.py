"""Тесты быстрых UIA-команд — `jarvis/intents/fast/uia.py`.

Главный случай — библиотеки `uiautomation` нет (CI-раннер, «голая»
Windows). Раньше обработчик падал, стадия глотала исключение, и человек
получал «LLM недоступна» — понять, что случилось, было нельзя.
Теперь такие команды отвечают понятным отказом.
"""

from unittest.mock import patch

from jarvis import uia
from jarvis.intents.fast.uia import UIA_MISSING_REPLY, uia_fast


def test_uia_command_without_library_answers_clearly():
    """Нет библиотеки → честный отказ, а не падение и не «LLM недоступна»."""
    with patch.object(uia, "_ensure_init", side_effect=uia.UIAUnavailable()):
        reply = uia_fast(None, "какие вкладки открыты")

    assert reply == UIA_MISSING_REPLY
    assert "uiautomation" in reply
    assert "pip install" in reply


def test_uia_read_window_without_library_answers_clearly():
    """«прочитай окно» — та же ветка отказа (текст окна читать нечем)."""
    with patch.object(uia, "_ensure_init", side_effect=uia.UIAUnavailable()):
        reply = uia_fast(None, "прочитай окно")

    assert reply == UIA_MISSING_REPLY


def test_not_our_command_returns_none():
    """Не наша фраза → None: дальше подключаются другие стадии."""
    assert uia_fast(None, "привет") is None
