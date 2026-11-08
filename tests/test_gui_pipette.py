# -*- coding: utf-8 -*-
"""Мини-режим «пипетка»: свойства окна 56×56, возврат и тосты."""
from types import SimpleNamespace as NS
from unittest.mock import Mock

import flet as ft
import pytest
from jarvis import gui as module, profile, mood
from jarvis import gui_pipette, gui_toast
from jarvis.config import Config


class FakeWindow:
    def __init__(self):
        for key, value in (("width", 1100), ("height", 760), ("left", 100),
                           ("top", 80), ("min_width", 900), ("min_height", 600),
                           ("max_width", None), ("max_height", None),
                           ("resizable", True), ("movable", True),
                           ("frameless", False), ("always_on_top", False),
                           ("shadow", False), ("visible", True), ("minimized", False)):
            setattr(self, key, value)

    def as_dict(self):
        return dict(self.__dict__)


def test_pipette_spec_is_pill_frameless_and_pinned_corner():
    spec = gui_pipette.pipette_window_spec(workarea=(0, 0, 1920, 1080))
    assert spec["width"] == gui_pipette.PIP_W == 136
    assert spec["height"] == gui_pipette.PIP_H == 56
    assert spec["frameless"] is True and spec["always_on_top"] is True
    assert spec["resizable"] is False
    assert spec["left"] == 1920 - 136 - 12 and spec["top"] == 1080 - 56 - 12


def test_pipette_spec_without_workarea_does_not_invent_position():
    spec = gui_pipette.pipette_window_spec(workarea=None)
    assert "left" not in spec and "top" not in spec
    assert spec["min_width"] == spec["max_width"] == 136
    assert spec["min_height"] == spec["max_height"] == 56


def test_saved_window_round_trip_restores_geometry():
    window = FakeWindow()
    saved = gui_pipette.saved_window_spec(window)
    assert saved["width"] == 1100 and saved["left"] == 100
    window.width = window.height = 56
    window.frameless = True
    applied = gui_pipette.restore_window_spec(window, saved)
    assert window.width == 1100 and window.height == 760
    assert window.frameless is False and window.always_on_top is False
    assert applied["resizable"] is True


def test_restore_skips_missing_values():
    window = FakeWindow()
    applied = gui_pipette.restore_window_spec(window, {"width": None, "resizable": False})
    assert applied == {"resizable": False}
    assert window.width == 1100


def test_toast_colors_and_kinds():
    palette = NS(brand="#ffcc00", success="#00c853", error="#ff1744",
                 bg_card="#181823", text="#eaf0f6")
    assert gui_toast.normalize_kind("unknown") == "info"
    assert gui_toast.toast_colors(palette, "error")["accent"] == "#ff1744"
    assert gui_toast.toast_colors(palette, "success")["surface"] == "#181823"
    assert gui_toast.DURATION_MS["error"] > gui_toast.DURATION_MS["info"]


def test_toasts_hide_bottom_center_and_limit_three():
    page = NS(overlay=[], update=Mock(), run_task=Mock(),
              window=NS(width=1100, height=760))
    gui = NS(_page=page)
    toasts = gui_toast.Toasts(gui, limit=3)
    for index in range(5):
        assert toasts.show(f"сообщение {index}") is True
    assert len(toasts.entries) == 3
    assert len(page.overlay) == 3
    newest = toasts.entries[-1]
    assert newest.left == (1100 - 320) // 2
    assert newest.top < 760
    assert page.run_task.call_count == 5


def test_toasts_without_page_fall_back():
    toasts = gui_toast.Toasts(NS(_page=None))
    assert toasts.show("нет окна") is False


def test_toasts_clear_removes_everything():
    page = NS(overlay=[], update=Mock(), run_task=Mock(),
              window=NS(width=900, height=700))
    toasts = gui_toast.Toasts(NS(_page=page))
    toasts.show("раз")
    toasts.show("два")
    toasts.clear()
    assert toasts.entries == [] and page.overlay == []


@pytest.fixture
def window(tmp_path):
    gui = module.FenixGUI(None, Config(tmp_path / "config.json"))
    page = NS(add=Mock(), update=Mock(), window=FakeWindow(),
              run_task=Mock(), overlay=[])
    gui._page = page
    gui._build_ui(page)
    yield gui
    gui.close_palette()
    gui.stop()
    gui._rail.dispose()
    profile.unsubscribe(gui._on_profile_switch)
    mood.unsubscribe(gui._on_mood_change)
    module._apply_palette("dark")


def test_pipette_mode_shrinks_window_and_restores(window):
    window._show_window_now()
    before = window._page.window.as_dict()
    assert window.set_pipette_mode(True) is True
    assert window._pipette_mode is True
    assert window._root.content is window._pipette
    assert window._page.window.width == gui_pipette.PIP_W == 136
    assert window._page.window.height == gui_pipette.PIP_H == 56
    assert window._page.window.frameless is True and window._page.window.always_on_top is True
    assert window.set_pipette_mode(True) is False  # повтор ничего не делает
    assert window.set_pipette_mode(False) is True
    assert window._root.content is window._rail_row
    assert window._page.window.width == before["width"]
    assert window._page.window.left == before["left"]
    assert window._page.window.always_on_top is False


def test_pipette_click_returns_to_normal(window):
    window.set_pipette_mode(True)
    window._pipette.on_click(None)
    assert window._pipette_mode is False


def test_ctrl_shift_p_toggles_pipette(window):
    assert window._handle_shortcut(NS(key="p", ctrl=True, shift=True)) is True
    assert window._pipette_mode is True
    assert window._handle_shortcut(NS(key="P", ctrl=True, shift=True)) is True
    assert window._pipette_mode is False


def test_pipette_disables_home_keys(window):
    window.set_pipette_mode(True)
    import asyncio
    assert asyncio.run(window._on_home_key(NS(key="Tab", ctrl=False, shift=False))) is None
    window.set_pipette_mode(False)


def test_palette_leaves_pipette_before_opening(window):
    window.set_pipette_mode(True)
    assert window._pipette_mode is True
    assert window.open_palette() is True
    assert window._pipette_mode is False
    assert window._root.content is window._rail_row
    assert window._page.window.width == 1100
    assert window._palette.opened is True


def test_toast_helper_delegates_to_stack(window):
    assert window.toast("готово", "success") is True
    assert len(window._toasts.entries) == 1
