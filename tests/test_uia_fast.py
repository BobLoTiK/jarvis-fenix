"""Тесты быстрых UIA-команд — `jarvis/intents/fast/uia.py`.

Главный случай — библиотеки `uiautomation` нет (CI-раннер, «голая»
Windows). Раньше обработчик падал, стадия глотала исключение, и человек
получал «LLM недоступна» — понять, что случилось, было нельзя.
Теперь такие команды отвечают понятным отказом.

Важно: «нет библиотеки» и «нет браузера» — разные вещи. На CI-раннере
нет и того, и другого, поэтому команда обязана сказать именно про
библиотеку, а не «не вижу открытых вкладок».
"""

from contextlib import contextmanager
from unittest.mock import patch

from jarvis import actions, uia
from jarvis.intents.fast.uia import UIA_MISSING_REPLY, uia_fast


@contextmanager
def _without_uiautomation():
    """Контекст «библиотеки нет»: блокируем импорт и сбрасываем кэш `_uia`."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "uiautomation":
            raise ImportError("No module named 'uiautomation' (CI)")
        return real_import(name, *args, **kwargs)

    # `_uia=None` — иначе после других тестов библиотека уже проинициализирована.
    with patch.object(builtins, "__import__", fake_import), \
            patch.object(uia, "_uia", None):
        yield


def test_uia_command_without_library_answers_clearly():
    """Нет библиотеки → честный отказ, а не падение и не «LLM недоступна»."""
    with _without_uiautomation():
        reply = uia_fast(None, "какие вкладки открыты")

    assert reply == UIA_MISSING_REPLY
    assert "uiautomation" in reply
    assert "pip install" in reply


def test_uia_read_window_without_library_answers_clearly():
    """«прочитай окно» — та же ветка отказа (текст окна читать нечем)."""
    with _without_uiautomation():
        reply = uia_fast(None, "прочитай окно")

    assert reply == UIA_MISSING_REPLY


def test_when_no_browser_is_running_still_blames_library():
    """CI: нет библиотеки И нет браузера — всё равно отказ про библиотеку.

    Раньше эта ветка отвечала «Не вижу открытых вкладок. Возможно,
    активное окно — не браузер»: поиск окна отдавал None раньше, чем
    дело доходило до UIA, и настоящая причина терялась.
    """
    with _without_uiautomation(), \
            patch.object(uia, "find_browser_window", return_value=None):
        reply = uia_fast(None, "список вкладок")

    assert reply == UIA_MISSING_REPLY


def test_key_command_works_without_library():
    """«нажми enter» — это клавиша, а не UIA: работает и без библиотеки."""
    with _without_uiautomation(), \
            patch.object(actions, "key_press") as press:
        reply = uia_fast(None, "нажми enter")

    assert reply == "Нажал enter."
    press.assert_called_once_with("enter")


def test_close_named_tab_falls_back_to_ctrl_w():
    """UIA вкладок не отдал (видна одна активная), но нужная активна → Ctrl+W.

    Яндекс с группировкой вкладок: `close_browser_tab` их не находит.
    Тогда, если активная вкладка — та самая, хватает Ctrl+W.
    """
    hotkeys = []
    with patch.object(uia, "is_supported", return_value=True), \
            patch.object(uia, "close_browser_tab", return_value=False), \
            patch.object(uia, "read_browser_tabs", return_value=["DeepSeek"]), \
            patch.object(uia, "active_tab_matches", return_value=True), \
            patch.object(actions, "hotkey", side_effect=hotkeys.append):
        reply = uia_fast(None, "закрой вкладку ютуб")

    assert reply == "Закрыл вкладку ютуб."
    assert hotkeys == [["ctrl", "w"]]


def test_no_extra_ctrl_w_when_tab_list_is_readable():
    """Список вкладок виден → Ctrl+W уже нажал `close_browser_tab`.

    Второе нажатие закрыло бы следующую вкладку с тем же названием:
    «ютуб» часто открыт не в одном экземпляре.
    """
    hotkeys = []
    with patch.object(uia, "is_supported", return_value=True), \
            patch.object(uia, "close_browser_tab", return_value=False), \
            patch.object(uia, "read_browser_tabs",
                         return_value=["ютуб", "Почта"]), \
            patch.object(uia, "active_tab_matches", return_value=True), \
            patch.object(actions, "hotkey", side_effect=hotkeys.append):
        reply = uia_fast(None, "закрой вкладку ютуб")

    assert hotkeys == []
    assert "не нашёл" in reply


def test_tab_list_read_error_counts_as_unreadable():
    """`read_browser_tabs` упал (COM) → считаем, что вкладок не видно.

    Тогда срабатывает Ctrl+W: молчание вместо закрытия здесь хуже.
    """
    hotkeys = []
    with patch.object(uia, "is_supported", return_value=True), \
            patch.object(uia, "close_browser_tab", return_value=False), \
            patch.object(uia, "read_browser_tabs",
                         side_effect=RuntimeError("COM")), \
            patch.object(uia, "active_tab_matches", return_value=True), \
            patch.object(actions, "hotkey", side_effect=hotkeys.append):
        reply = uia_fast(None, "закрой вкладку ютуб")

    assert reply == "Закрыл вкладку ютуб."
    assert hotkeys == [["ctrl", "w"]]


def test_close_named_tab_not_found_answers_honestly():
    """Ни по имени, ни в активной — честное «не нашёл», без Ctrl+W."""
    hotkeys = []
    with patch.object(uia, "is_supported", return_value=True), \
            patch.object(uia, "close_browser_tab", return_value=False), \
            patch.object(uia, "active_tab_matches", return_value=False), \
            patch.object(actions, "hotkey", side_effect=hotkeys.append):
        reply = uia_fast(None, "закрой вкладку зптщклмн")

    assert "не нашёл" in reply
    assert hotkeys == []


def test_switch_to_active_tab_is_not_a_failure():
    """Вкладка уже активна (UIA её не видит) → не врём про «не нашёл»."""
    with patch.object(uia, "is_supported", return_value=True), \
            patch.object(uia, "switch_browser_tab", return_value=False), \
            patch.object(uia, "active_tab_matches", return_value=True):
        reply = uia_fast(None, "переключись на вкладку ютуб")

    assert reply == "Переключился на ютуб."


def test_not_our_command_returns_none():
    """Не наша фраза → None: дальше подключаются другие стадии."""
    assert uia_fast(None, "привет") is None
