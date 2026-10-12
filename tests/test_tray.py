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

    class FakePystrayIcon:
        visible = False

        def run(self):
            started.set()

        def stop(self):
            pass

    monkeypatch.setattr(tray, "build_icon", lambda jarvis: FakePystrayIcon())
    icon = tray.start_tray(FakeJarvis(), check_after=0.0)

    assert icon is not None
    assert started.wait(3.0), "icon.run() не запустился в фоновом потоке"


def test_start_tray_without_pystray_is_not_fatal(monkeypatch):
    """Сборка иконки упала — Феникс работает без трея, а не падает."""
    def _boom(jarvis):
        raise RuntimeError("нет pystray")

    monkeypatch.setattr(tray, "build_icon", _boom)

    assert tray.start_tray(FakeJarvis()) is None
