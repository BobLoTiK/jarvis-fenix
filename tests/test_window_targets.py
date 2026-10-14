"""Тесты выбора окна: голосовое имя → процессы → окно.

Почему это критично: до правки «переключись на телеграм» находил окно
Steam (нечёткий поиск по заголовку, score 0.62), «клод» — окно VS Code
(0.67), «диспетчер задач» — «Диспетчер устройств» (0.75), а «закрой клод»
убивал gcloud.exe (0.80). Русского имени приложения в заголовке обычно
нет (у Telegram — «Telegram», у Chrome — заголовок страницы), зато
известно имя процесса — по нему и ищем (`actions.windows_by_process`).

Окна и процессы замоканы: тесты идут и в CI, и без единого окна.
"""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from jarvis import actions
from jarvis.apps import App
from jarvis.intents import execute


def _window(title, hwnd=1, visible=True, minimized=False):
    """Окно как у pygetwindow: заголовок, видимость, приватный hwnd."""
    w = MagicMock()
    w.title = title
    w.visible = visible
    w.isMinimized = minimized
    w._hWnd = hwnd
    return w


APPS = [
    App("telegram", "Телеграм", ["телега", "телеграм"],
        [("exe", r"C:\fake\Telegram.exe")], ["Telegram.exe"]),
    App("explorer", "Проводник", ["проводник"],
        [("cmd", ["explorer.exe"])], ["explorer.exe"]),
]


@pytest.fixture
def fake_windows(monkeypatch):
    """Подменяет pygetwindow — окна без живого рабочего стола."""
    def _install(windows):
        module = SimpleNamespace(getAllWindows=lambda: list(windows))
        monkeypatch.setitem(sys.modules, "pygetwindow", module)
        return windows
    return _install


@pytest.fixture
def fake_apps(monkeypatch):
    """Каталог приложений без чтения реестра (путь к Steam и т.п.)."""
    monkeypatch.setattr("jarvis.apps.build_apps", lambda config: APPS)


# =================================================================
# Имя → процесс
# =================================================================

def test_process_base_drops_exe():
    assert actions._process_base("Telegram.exe") == "telegram"
    assert actions._process_base("") == ""


def test_matches_process_by_name_and_substring():
    assert actions._matches_process("telegram", "Telegram.exe")
    assert actions._matches_process("steam", "steamwebhelper.exe")


def test_matches_process_rejects_lookalikes():
    """«клод» не должен совпасть с gcloud — иначе закрыли бы чужое."""
    assert not actions._matches_process("клод", "gcloud.exe")
    assert not actions._matches_process("", "gcloud.exe")
    assert not actions._matches_process("клод", "")


def test_candidates_from_app_catalog():
    """«телега» → процессы из каталога + синоним окна (оба — telegram)."""
    assert actions._window_process_candidates("телега", apps=APPS) == {
        "Telegram.exe", "telegram"}


def test_candidates_from_window_synonyms():
    """«хром» — слово из _WINDOW_SYNONYMS, каталог для него не нужен."""
    assert "chrome" in actions._window_process_candidates("хром", apps=[])


def test_candidates_unknown_name_falls_back_to_itself():
    assert actions._window_process_candidates("фубар", apps=[]) == {"фубар"}


def test_candidates_empty_name():
    assert actions._window_process_candidates("", apps=APPS) == set()


# =================================================================
# Поиск окна
# =================================================================

def test_windows_by_process_picks_owner(monkeypatch, fake_windows):
    monkeypatch.setattr(actions, "window_processes",
                        lambda: [(101, "Telegram", "telegram"),
                                 (102, "Steam", "steam")])
    telegram, steam = _window("Telegram", hwnd=101), _window("Steam", hwnd=102)
    fake_windows([telegram, steam])

    assert actions.windows_by_process(["Telegram.exe"]) == [telegram]


def test_windows_by_process_without_process_info(monkeypatch, fake_windows):
    """Нет данных о процессах (CI, нет pywin32) — пустой список."""
    monkeypatch.setattr(actions, "window_processes", lambda: [])
    fake_windows([_window("Telegram", hwnd=101)])

    assert actions.windows_by_process(["Telegram.exe"]) == []


def test_find_window_resolves_russian_name_by_process(monkeypatch,
                                                     fake_windows, fake_apps):
    """«телега» → окно «Telegram»: русского имени в заголовке нет."""
    monkeypatch.setattr(actions, "window_processes",
                        lambda: [(101, "Telegram", "telegram"),
                                 (102, "Steam", "steam")])
    telegram = _window("Telegram", hwnd=101)
    fake_windows([telegram, _window("Steam", hwnd=102)])

    assert actions._find_window("телега") is telegram


def test_find_window_rejects_weak_fuzzy_match(monkeypatch, fake_windows,
                                              fake_apps):
    """«телеграм» не должен находить Steam по сходству 0.62."""
    assert actions._FUZZY_TITLE_MIN >= 0.75
    monkeypatch.setattr(actions, "window_processes",
                        lambda: [(102, "Steam", "steam")])
    fake_windows([_window("Steam", hwnd=102)])

    assert actions._find_window("телеграм") is None


def test_find_window_prefers_visible_window(monkeypatch, fake_windows,
                                            fake_apps):
    """Из свёрнутого и видимого окон берём видимое."""
    monkeypatch.setattr(actions, "window_processes",
                        lambda: [(101, "Telegram", "telegram"),
                                 (102, "Telegram (2)", "telegram")])
    hidden = _window("Telegram", hwnd=101, visible=False)
    shown = _window("Telegram (2)", hwnd=102)
    fake_windows([hidden, shown])

    assert actions._find_window("телега") is shown


def test_all_windows_skips_desktop(fake_windows):
    """«Program Manager» — рабочий стол (процесс тоже explorer.exe)."""
    fake_windows([_window("Program Manager", hwnd=1),
                  _window("Загрузки — проводник", hwnd=2)])

    assert [w.title for w in actions._all_windows()] == ["Загрузки — проводник"]


def test_close_windows_skips_desktop(monkeypatch, fake_windows):
    """Массовое закрытие проводника не заденет рабочий стол."""
    monkeypatch.setattr(actions, "window_processes",
                        lambda: [(1, "Program Manager", "explorer"),
                                 (2, "Загрузки — проводник", "explorer")])
    desktop = _window("Program Manager", hwnd=1)
    folder = _window("Загрузки — проводник", hwnd=2)
    fake_windows([desktop, folder])

    assert actions.close_windows_by_process(["explorer.exe"]) == 1
    desktop.close.assert_not_called()
    folder.close.assert_called_once_with()


# =================================================================
# Закрытие
# =================================================================

def test_close_windows_by_process_closes_every_window(monkeypatch,
                                                      fake_windows):
    monkeypatch.setattr(actions, "window_processes",
                        lambda: [(201, "Загрузки", "explorer"),
                                 (202, "Документы", "explorer")])
    first = _window("Загрузки", hwnd=201)
    second = _window("Документы", hwnd=202)
    fake_windows([first, second])

    assert actions.close_windows_by_process(["explorer.exe"]) == 2
    first.close.assert_called_once_with()
    second.close.assert_called_once_with()


def test_kill_process_refuses_protected_explorer():
    """Оболочку Windows не убиваем никогда — закрываем её окна."""
    assert actions.is_protected_process("explorer.exe")
    assert actions.kill_process("explorer.exe") is False


def test_kill_process_refuses_uppercase_protected():
    assert actions.kill_process("Explorer.exe") is False


# =================================================================
# Обработчики: execute._do_close / _do_hotkey
# =================================================================

def _handler():
    return SimpleNamespace(apps=APPS)


def test_close_mass_windows_never_kills_explorer(monkeypatch):
    """«закрой все окна проводника»: закрываем окна, процесс не трогаем."""
    kill = MagicMock(return_value=True)
    closed = MagicMock(return_value=2)
    monkeypatch.setattr(actions, "kill_process", kill)
    monkeypatch.setattr(actions, "close_windows_by_process", closed)

    assert execute._do_close(_handler(), "все окна проводника") == "Закрыл окон: 2."
    closed.assert_called_once_with(["explorer.exe"])
    kill.assert_not_called()


def test_close_app_still_kills_its_process(monkeypatch):
    kill = MagicMock(return_value=True)
    closed = MagicMock()
    monkeypatch.setattr(actions, "kill_process", kill)
    monkeypatch.setattr(actions, "close_windows_by_process", closed)

    assert execute._do_close(_handler(), "телеграм") == "Закрываю Телеграм."
    kill.assert_called_once_with("Telegram.exe")
    closed.assert_not_called()


def test_close_unknown_app_needs_confident_process(monkeypatch):
    """«закрой клод» не убивает gcloud.exe (было 0.80 при пороге 0.7)."""
    find = MagicMock(return_value=None)
    kill = MagicMock(return_value=True)
    monkeypatch.setattr(actions, "find_process", find)
    monkeypatch.setattr(actions, "kill_process", kill)

    reply = execute._do_close(_handler(), "клод")

    assert reply == "Не нашёл запущенной программы клод."
    assert find.call_args.kwargs["threshold"] == 0.9
    kill.assert_not_called()


def test_close_browser_uses_browser_path(monkeypatch):
    monkeypatch.setattr(actions, "close_browser", MagicMock(return_value=True))
    assert execute._do_close(_handler(), "хром") == "Закрываю браузер."


def test_close_without_target_asks():
    assert execute._do_close(_handler(), "") == "Что именно закрыть?"


# =================================================================
# Горячие клавиши
# =================================================================

@pytest.mark.parametrize("spoken,expected", [
    ("контрл эс", ["ctrl", "s"]),
    ("ctrl+s", ["ctrl", "s"]),
    ("alt таб", ["alt", "tab"]),
    ("shift f5", ["shift", "f5"]),
    ("мусор", []),
    ("", []),
])
def test_parse_hotkey(spoken, expected):
    assert execute._parse_hotkey(spoken) == expected


def test_do_hotkey_sends_combo(monkeypatch):
    hk = MagicMock(return_value=True)
    monkeypatch.setattr(actions, "hotkey", hk)

    reply = execute._do_hotkey(None, {"keys": ["ctrl", "s"]}, "ctrl+s", "")

    assert reply == "Нажимаю ctrl, s."
    hk.assert_called_once_with(["ctrl", "s"])


def test_do_hotkey_without_keys_asks(monkeypatch):
    monkeypatch.setattr(actions, "hotkey", MagicMock(return_value=True))
    assert execute._do_hotkey(None, {}, "", "непонятно") == \
        "Не понял, какие клавиши нажать."


def test_hotkey_action_is_dispatched():
    assert execute._DISPATCH["hotkey"] is execute._do_hotkey

