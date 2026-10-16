"""Трей (jarvis.tray): пункты меню реально дёргают ядро и GUI.

Трей был отключён («pystray требует свой message loop»), и меню
проверялось только руками. Здесь пункты меню вызываются напрямую —
message loop не запускается, иконка в трей не ставится.

Проверяем:
    - «Слушать микрофон» → jarvis.listening_enabled;
    - «Открыть окно» / «Настройки» → gui.show_window()/open_settings_tab();
    - «Выход» → jarvis.shutdown() + gui.quit() + icon.stop();
    - без GUI пункты окна не падают;
    - start_tray(): иконка в daemon-потоке, ошибки pystray не роняют Феникса.
"""

import importlib.util
import threading

import pytest

for _mod in ("pystray", "PIL"):
    if importlib.util.find_spec(_mod) is None:
        pytest.skip("нет pystray/Pillow — тесты трея пропущены",
                    allow_module_level=True)

from jarvis import tray  # noqa: E402


class FakeIcon:
    """Заглушка pystray.Icon: помнит, что её сняли."""

    def __init__(self):
        self.stopped = False
        self.visible = True

    def stop(self):
        self.stopped = True


class FakeGUI:
    """Заглушка FenixGUI: пишет, какие методы звали."""

    def __init__(self):
        self.calls = []

    def show_window(self):
        self.calls.append("show_window")

    def open_settings_tab(self):
        self.calls.append("open_settings_tab")

    def quit(self):
        self.calls.append("quit")


class FakeJarvis:
    def __init__(self):
        self.listening_enabled = True
        self.gui = FakeGUI()
        self.shutdown_calls = 0

    def shutdown(self):
        self.shutdown_calls += 1


def _item(menu, text: str):
    """Ищет пункт меню по тексту (pystray.Menu.items — плоский список)."""
    for item in menu.items:
        if getattr(item, "text", None) == text:
            return item
    raise AssertionError(
        "пункт %r не найден в меню: %r"
        % (text, [getattr(i, "text", None) for i in menu.items])
    )


# =================================================================
# Меню
# =================================================================

def test_toggle_listening_flips_flag():
    jarvis = FakeJarvis()
    item = _item(tray.build_menu(jarvis), "Слушать микрофон")

    item(FakeIcon())
    assert jarvis.listening_enabled is False

    item(FakeIcon())
    assert jarvis.listening_enabled is True


def test_show_window_and_settings_reach_gui():
    jarvis = FakeJarvis()
    menu = tray.build_menu(jarvis)

    _item(menu, "Открыть окно")(FakeIcon())
    assert jarvis.gui.calls == ["show_window"]

    _item(menu, "Настройки")(FakeIcon())
    assert jarvis.gui.calls == ["show_window", "show_window",
                               "open_settings_tab"]


def test_menu_works_without_gui():
    """GUI выключен — пункты про окно не падают (только warning в лог)."""
    jarvis = FakeJarvis()
    jarvis.gui = None
    menu = tray.build_menu(jarvis)

    _item(menu, "Открыть окно")(FakeIcon())
    _item(menu, "Настройки")(FakeIcon())


def test_exit_stops_everything():
    """«Выход» — это правда выход: микрофон стоп + окно + иконка."""
    jarvis = FakeJarvis()
    icon = FakeIcon()

    _item(tray.build_menu(jarvis), "Выход")(icon)

    assert jarvis.shutdown_calls == 1
    assert "quit" in jarvis.gui.calls
    assert icon.stopped is True


def test_exit_survives_gui_errors():
    """GUI упал — иконка всё равно снимается, микрофон останавливается."""
    class BrokenGUI:
        def quit(self):
            raise RuntimeError("окно уже мертво")

    jarvis = FakeJarvis()
    jarvis.gui = BrokenGUI()
    icon = FakeIcon()

    _item(tray.build_menu(jarvis), "Выход")(icon)

    assert jarvis.shutdown_calls == 1
    assert icon.stopped is True


def test_build_icon_title_and_menu():
    jarvis = FakeJarvis()
    icon = tray.build_icon(jarvis)

    assert "Феникс" in icon.title
    assert icon.menu is not None


# =================================================================
# start_tray()
# =================================================================

def test_start_tray_runs_in_background(monkeypatch):
    """Иконка поднимается в daemon-потоке: главный поток нужен Flet'у."""
    started = threading.Event()

    stopped = threading.Event()
    class FakePystrayIcon:
        visible = False
        def run(self):
            self.visible = True
            started.set()
            stopped.wait(3)
        def stop(self):
            stopped.set()

    monkeypatch.setattr(tray, "build_icon", lambda jarvis: FakePystrayIcon())
    icon = tray.start_tray(FakeJarvis(), check_after=1.0)
    assert icon is not None and icon.visible
    assert started.is_set()
    icon.stop()


def test_start_tray_without_pystray_is_not_fatal(monkeypatch):
    """Сборка иконки упала — Феникс работает без трея, а не падает."""
    def _boom(jarvis):
        raise RuntimeError("нет pystray")

    monkeypatch.setattr(tray, "build_icon", _boom)

    assert tray.start_tray(FakeJarvis()) is None


def test_invisible_tray_is_not_returned_as_ready(monkeypatch):
    stopped = threading.Event()
    class Invisible:
        visible = False
        def run(self):
            stopped.wait(2)
        def stop(self):
            stopped.set()
    monkeypatch.setattr(tray, 'build_icon', lambda j: Invisible())
    assert tray.start_tray(FakeJarvis(), check_after=.02) is None
    assert stopped.wait(1)


def test_dead_tray_restores_window_callback(monkeypatch):
    stopped = threading.Event()
    called = threading.Event()
    class Icon:
        visible = False
        def run(self):
            self.visible = True
            stopped.wait(2)
        def stop(self):
            stopped.set()
    icon = Icon()
    monkeypatch.setattr(tray, 'build_icon', lambda j: icon)
    received = []
    def failed(value):
        received.append(value)
        called.set()
    assert tray.start_tray(FakeJarvis(), on_fail=failed) is icon
    stopped.set()
    assert called.wait(1)
    assert received == [icon]


@pytest.mark.parametrize('results,raises', [([True],False), ([False,False,True],False), ([False]*30,True)])
def test_windows_shell_must_accept_icon(monkeypatch, results, raises):
    import ctypes
    from types import SimpleNamespace as NS
    results = iter(results)
    clock = [0.0]
    monkeypatch.setattr(tray.time, 'monotonic', lambda:clock[0])
    monkeypatch.setattr(tray.time, 'sleep', lambda dt:clock.__setitem__(0,clock[0]+dt))
    class Payload(ctypes.Structure):
        _fields_ = []
        def __init__(self, **kw):
            self.kw = kw
    calls = []
    def shell(code, payload):
        calls.append((code,payload.kw))
        return next(results)
    win32 = NS(NOTIFYICONDATAW=Payload, Shell_NotifyIcon=shell,
               NIM_ADD=0, NIF_MESSAGE=1,NIF_ICON=2,NIF_TIP=4,WM_NOTIFY=1024)
    class Base:
        _hwnd=123; _icon_handle=456; title='Феникс'
        def _assert_icon_handle(self): pass
    icon = tray._windows_icon_type(Base,win32)()
    if raises:
        with pytest.raises(OSError,match='Windows'):
            icon._show()
    else:
        icon._show()
    assert calls[0][1]['hWnd'] == 123
    assert calls[0][1]['hIcon'] == 456
    assert calls[0][1]['szTip'] == 'Феникс'
    assert calls[0][1]['uFlags'] == 7
