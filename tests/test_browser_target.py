"""№1: Феникс работает в том браузере, в котором сидит пользователь.

До этой правки `actions.open_url` всегда звал `os.startfile(url)` — Windows
открывал браузер ПО УМОЛЧАНИЮ, даже если человек сидел в другом. Теперь URL
уходит в .exe уже запущенного браузера (окно в фокусе → самое верхнее
запущенное), «открой браузер» переключает на работающее окно, а «открой хром» —
именно Chrome. Браузеров не запущено — прежнее поведение (браузер по умолчанию).

Браузеры, окна и процессы замоканы: тесты идут и в CI, где нет ни окон,
ни браузеров.
"""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from jarvis import actions, uia
from jarvis.apps import App
from jarvis.intents import execute


def _window(title="YouTube — Chrome", hwnd=1, visible=True, minimized=False):
    """Окно как у pygetwindow: заголовок, видимость, приватный hwnd."""
    w = MagicMock()
    w.title = title
    w.visible = visible
    w.isMinimized = minimized
    w._hWnd = hwnd
    return w


@pytest.fixture
def fake_processes(monkeypatch):
    """psutil без живой системы: список процессов + поиск по pid."""

    def _install(procs, pids=None):
        class Proc:
            def __init__(self, name, exe):
                self.info = {"name": name}
                self._exe = exe

            def name(self):
                return self.info["name"]

            def exe(self):
                if self._exe is None:
                    raise PermissionError("нет доступа к пути")
                return self._exe

        objects = [Proc(name, exe) for name, exe in procs]
        by_pid = {pid: objects[i] for pid, i in (pids or {}).items()}

        def _by_pid(pid):
            if pid not in by_pid:
                raise ValueError("нет процесса с таким pid")
            return by_pid[pid]

        module = SimpleNamespace(process_iter=lambda attrs=None: list(objects),
                                 Process=_by_pid)
        monkeypatch.setitem(sys.modules, "psutil", module)
        return objects

    return _install


HANDLER = SimpleNamespace(apps=[], steam_games=[], installed={},
                          last_file=None, last_folder=None)


# =================================================================
# uia: какой браузер сейчас у пользователя
# =================================================================

def test_browser_name_known_and_unknown():
    assert uia.browser_name("Chrome.exe") == "Chrome"
    assert uia.browser_name("msedge.exe") == "Edge"
    assert uia.browser_name("explorer.exe") is None


def test_active_browser_process_from_foreground(monkeypatch, fake_processes):
    fake_processes([("chrome.exe", None)], {111: 0})
    monkeypatch.setattr(uia, "get_active_window",
                        lambda: SimpleNamespace(ProcessId=111))

    assert uia.active_browser_process() == "chrome.exe"


def test_active_browser_process_falls_back_to_top_window(monkeypatch,
                                                         fake_processes):
    """Фокус в проводнике — берём самое верхнее окно браузера."""
    fake_processes([("explorer.exe", None), ("firefox.exe", None)],
                   {111: 0, 222: 1})
    monkeypatch.setattr(uia, "get_active_window",
                        lambda: SimpleNamespace(ProcessId=111))
    monkeypatch.setattr(uia, "_find_window_by_process",
                        lambda names, timeout=2.0: SimpleNamespace(ProcessId=222))

    assert uia.active_browser_process() == "firefox.exe"


def test_active_browser_process_none(monkeypatch, fake_processes):
    """Ни фокуса в браузере, ни окон браузера — None (значит браузер по умолчанию)."""
    fake_processes([("explorer.exe", None)], {111: 0})
    monkeypatch.setattr(uia, "get_active_window",
                        lambda: SimpleNamespace(ProcessId=111))
    monkeypatch.setattr(uia, "_find_window_by_process",
                        lambda names, timeout=2.0: None)

    assert uia.active_browser_process() is None


def test_active_browser_process_survives_uia_error(monkeypatch,
                                                   fake_processes):
    """UIA недоступен (CI-раннер) — не падаем, идём по процессам."""
    fake_processes([("brave.exe", None)], {222: 0})

    def _boom():
        raise RuntimeError("UIA нет")

    monkeypatch.setattr(uia, "get_active_window", _boom)
    monkeypatch.setattr(uia, "_find_window_by_process",
                        lambda names, timeout=2.0: SimpleNamespace(ProcessId=222))

    assert uia.active_browser_process() == "brave.exe"


# =================================================================
# actions._running_browser: чей браузер открывать
# =================================================================

def test_running_browser_single(monkeypatch, fake_processes):
    """Один запущенный браузер — берём его, UIA не спрашиваем."""
    fake_processes([("chrome.exe", None)])

    def _no_uia():
        raise AssertionError("UIA не нужен, если браузер один")

    monkeypatch.setattr(uia, "active_browser_process", _no_uia)

    assert actions._running_browser() == "chrome.exe"


def test_running_browser_prefers_user_browser(monkeypatch, fake_processes):
    """Два браузера — берём тот, в котором сидит пользователь."""
    fake_processes([("chrome.exe", None), ("firefox.exe", None)])
    monkeypatch.setattr(uia, "active_browser_process", lambda: "firefox.exe")

    assert actions._running_browser() == "firefox.exe"


def test_running_browser_none_without_browsers(monkeypatch, fake_processes):
    fake_processes([("explorer.exe", None)])

    assert actions._running_browser() is None


def test_running_browser_specific_not_running(monkeypatch, fake_processes):
    fake_processes([("firefox.exe", None)])

    assert actions._running_browser("chrome.exe") is None


# =================================================================
# actions.open_url: сайт в браузере пользователя
# =================================================================

def test_open_url_opens_in_user_browser(monkeypatch, fake_processes):
    """Главное требование №1: сайт открывается там, где сидит человек."""
    fake_processes([("chrome.exe", r"C:\fake\chrome.exe")])
    popen, startfile = MagicMock(), MagicMock()
    monkeypatch.setattr(actions.subprocess, "Popen", popen)
    monkeypatch.setattr(actions.os, "startfile", startfile)

    assert actions.open_url("https://ya.ru") is True

    popen.assert_called_once_with([r"C:\fake\chrome.exe", "https://ya.ru"])
    startfile.assert_not_called()


def test_open_url_falls_back_to_default_browser(monkeypatch, fake_processes):
    """Браузеров нет — прежнее поведение (браузер по умолчанию)."""
    fake_processes([("explorer.exe", None)])
    popen, startfile = MagicMock(), MagicMock()
    monkeypatch.setattr(actions.subprocess, "Popen", popen)
    monkeypatch.setattr(actions.os, "startfile", startfile)

    assert actions.open_url("https://ya.ru") is True

    startfile.assert_called_once_with("https://ya.ru")
    popen.assert_not_called()


def test_open_url_falls_back_when_exe_path_hidden(monkeypatch, fake_processes):
    """Путь к .exe не читается (защищённый процесс) — открываем как раньше."""
    fake_processes([("chrome.exe", None)])
    popen, startfile = MagicMock(), MagicMock()
    monkeypatch.setattr(actions.subprocess, "Popen", popen)
    monkeypatch.setattr(actions.os, "startfile", startfile)

    assert actions.open_url("https://ya.ru") is True

    popen.assert_not_called()
    startfile.assert_called_once_with("https://ya.ru")


# =================================================================
# actions.open_browser: запущенный — на передний план
# =================================================================

def test_open_browser_focuses_running_window(monkeypatch, fake_processes):
    """«открой браузер» при запущенном Chrome — переключаемся, не плодим окно."""
    fake_processes([("chrome.exe", None)])
    monkeypatch.setattr(uia, "active_browser_process", lambda: None)
    win = _window()
    monkeypatch.setattr(actions, "windows_by_process", lambda names: [win])
    startfile = MagicMock()
    monkeypatch.setattr(actions.os, "startfile", startfile)

    assert actions.open_browser() is True

    win.activate.assert_called_once()
    startfile.assert_not_called()


def test_open_browser_restores_minimized(monkeypatch, fake_processes):
    """Свёрнутый браузер разворачиваем, а не открываем второй."""
    fake_processes([("chrome.exe", None)])
    monkeypatch.setattr(uia, "active_browser_process", lambda: None)
    win = _window(minimized=True)
    monkeypatch.setattr(actions, "windows_by_process", lambda names: [win])
    monkeypatch.setattr(actions.os, "startfile", MagicMock())

    assert actions.open_browser() is True

    win.restore.assert_called_once()
    win.activate.assert_called_once()


def test_open_browser_named_launches_tab_when_window_missing(monkeypatch,
                                                             fake_processes):
    """Окна не видно, но процесс есть — вкладка в нём, а не в браузере по умолчанию."""
    fake_processes([("chrome.exe", r"C:\fake\chrome.exe")])
    monkeypatch.setattr(actions, "windows_by_process", lambda names: [])
    popen, startfile = MagicMock(), MagicMock()
    monkeypatch.setattr(actions.subprocess, "Popen", popen)
    monkeypatch.setattr(actions.os, "startfile", startfile)

    assert actions.open_browser("chrome.exe") is True

    popen.assert_called_once_with([r"C:\fake\chrome.exe", actions._DEFAULT_URL])
    startfile.assert_not_called()


def test_open_browser_without_browsers_uses_default(monkeypatch, fake_processes):
    fake_processes([("explorer.exe", None)])
    monkeypatch.setattr(uia, "active_browser_process", lambda: None)
    monkeypatch.setattr(actions, "windows_by_process", lambda names: [])
    startfile = MagicMock()
    monkeypatch.setattr(actions.os, "startfile", startfile)

    assert actions.open_browser() is True

    startfile.assert_called_once_with(actions._DEFAULT_URL)


def test_focus_browser_false_without_windows(monkeypatch, fake_processes):
    fake_processes([("chrome.exe", None)])
    monkeypatch.setattr(uia, "active_browser_process", lambda: None)
    monkeypatch.setattr(actions, "windows_by_process", lambda names: [])

    assert actions.focus_browser() is False


# =================================================================
# execute._do_open: «открой хром» ≠ браузер по умолчанию
# =================================================================

def test_do_open_chrome_switches_to_running_window(monkeypatch):
    seen = []
    monkeypatch.setattr(actions, "focus_browser",
                        lambda process=None: seen.append(process) or True)
    monkeypatch.setattr(actions, "open_browser",
                        lambda process=None: seen.append("open") or True)

    assert execute._do_open(HANDLER, "хром") == "Переключаюсь на хром."
    assert seen == ["chrome.exe"]


def test_do_open_chrome_from_catalog_when_not_running(monkeypatch):
    """Chrome не запущен — стартуем Chrome из каталога, не браузер по умолчанию."""
    app = App("chrome", "Chrome", ["хром"], [("uri", "https://www.google.com")],
              ["chrome.exe"])
    handler = SimpleNamespace(apps=[app], steam_games=[], installed={},
                              last_file=None, last_folder=None)
    monkeypatch.setattr(actions, "focus_browser", lambda process=None: False)
    run_spec, open_browser = MagicMock(), MagicMock()
    monkeypatch.setattr(actions, "run_spec", run_spec)
    monkeypatch.setattr(actions, "open_browser", open_browser)

    assert execute._do_open(handler, "хром") == "Открываю хром."
    run_spec.assert_called_once_with(("uri", "https://www.google.com"))
    open_browser.assert_not_called()


def test_do_open_browser_word_uses_user_browser(monkeypatch):
    monkeypatch.setattr(actions, "open_browser",
                        lambda process=None: process is None)

    assert execute._do_open(HANDLER, "браузер") == "Открываю браузер."


def test_do_open_site_goes_through_open_url(monkeypatch):
    """«открой ютуб» идёт через open_url — то есть в браузер пользователя."""
    from jarvis.intents.sites import get_sites

    title, url = get_sites()["ютуб"]
    opened = []
    monkeypatch.setattr(actions, "open_url", lambda u: opened.append(u) or True)

    assert execute._do_open(HANDLER, "ютуб") == f"Открываю {title}."
    assert opened == [url]


def test_do_open_site_in_browser_word(monkeypatch):
    """«открой браузер ютуб» — сайт в своём браузере, чужое окно не трогаем."""
    from jarvis.intents.sites import get_sites

    title, url = get_sites()["ютуб"]
    opened = []
    monkeypatch.setattr(actions, "open_url", lambda u: opened.append(u) or True)
    focus = MagicMock()
    monkeypatch.setattr(actions, "focus_browser", focus)

    assert execute._do_open(HANDLER, "браузер ютуб") == f"Открываю {title}."
    assert opened == [url]
    focus.assert_not_called()
