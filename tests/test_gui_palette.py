# -*- coding: utf-8 -*-
"""Палитра команд (Ctrl+K) и фокус-режим: чистые функции и привязка к GUI."""
from types import SimpleNamespace as NS
from unittest.mock import Mock

import flet as ft
import pytest
from jarvis import gui as module, profile, mood
from jarvis import gui_palette as palette
from jarvis.config import Config


def test_default_commands_cover_tabs_actions_and_themes():
    commands = palette.default_commands()
    titles = [command["title"] for command in commands]
    assert "Главная" in titles and "Диалог" in titles and "Движки" in titles
    assert "Микрофон: пауза или продолжить" in titles
    assert {"Вкладки", "Действия", "Темы"} <= {command["group"] for command in commands}
    keys = [command["key"] for command in commands]
    assert len(keys) == len(set(keys)) == 16


def test_filter_prefers_title_start_and_falls_back_to_group():
    commands = palette.default_commands()
    first = palette.filter_commands(commands, "микро")[0]
    assert first["title"] == first["title"]  # палитра не меняет команду
    assert first["key"] in ("tab:1", "mic")
    assert [c["key"] for c in palette.filter_commands(commands, "тема")]  # группа
    assert palette.filter_commands(commands, "") == commands[:palette.TYPE_LIMIT]
    assert palette.filter_commands(commands, "абракадабра") == []
    assert palette.filter_commands(commands, "ГЛАВНАЯ")[0]["key"] == "tab:6"


def test_describe_joins_group_and_title():
    command = {"group": "Действия", "title": "Микрофон"}
    assert palette.describe(command) == "Действия · Микрофон"


@pytest.fixture
def fake_gui():
    seen = []
    gui = NS(_page=None, _select_tab=lambda index: seen.append(("tab", index)),
             _on_mic_toggle=lambda e: seen.append("mic"), seen=seen)
    return gui


def test_palette_rows_render_and_run_selected_command(fake_gui):
    widget = palette.CommandPalette(fake_gui)
    assert not widget.opened
    assert len(widget.visible_rows) == palette.TYPE_LIMIT
    widget._render("Микрофон: пауза")
    assert [row for row in widget.visible_rows]
    first = widget.visible_rows[0]
    assert widget.run(first) is True
    assert fake_gui.seen == ["mic"]
    assert not widget.opened


def test_palette_submit_runs_first_visible_command(fake_gui):
    widget = palette.CommandPalette(fake_gui)
    widget._render("Диалог")
    widget._on_submit(None)
    assert fake_gui.seen == [("tab", 0)]


def test_palette_list_grows_with_results_and_stops_at_limit(fake_gui):
    widget = palette.CommandPalette(fake_gui)
    assert widget.rows.height == 48 * palette.TYPE_LIMIT
    widget._render("Микро")
    assert widget.rows.height == 48 * len(widget.visible_rows)
    widget._render("абракадабра")
    assert widget.rows.height == 48  # одна строка «Ничего не нашлось»


def test_palette_has_backdrop_field_and_hint(fake_gui):
    widget = palette.CommandPalette(fake_gui)
    assert isinstance(widget.content, ft.Stack)
    assert widget.field.autofocus is True
    assert "Enter" in widget.hint.value


@pytest.fixture
def window(tmp_path, monkeypatch):
    gui = module.FenixGUI(None, Config(tmp_path / "config.json"))
    page = NS(add=Mock(), update=Mock(), window=NS(width=1100, height=760),
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


def test_ctrl_k_toggles_palette_and_escape_closes(window):
    assert window._palette is None
    assert window._handle_shortcut(NS(key="k", ctrl=True, shift=False)) is True
    assert window._palette is not None and window._palette.opened
    assert window._palette in window._page.overlay
    assert window._handle_shortcut(NS(key="K", ctrl=True, shift=False)) is True
    assert not window._palette.opened and not window._page.overlay
    window._handle_shortcut(NS(key="k", ctrl=True, shift=False))
    assert window._handle_shortcut(NS(key="Escape", ctrl=False, shift=False)) is True
    assert not window._palette.opened


def test_plain_letter_is_not_a_shortcut(window):
    assert window._handle_shortcut(NS(key="k", ctrl=False, shift=False)) is False
    assert window._handle_shortcut(NS(key="f", ctrl=True, shift=False)) is False


def test_focus_mode_hides_rail_and_home_chrome(window):
    assert window._focus_mode is False
    assert window._handle_shortcut(NS(key="f", ctrl=True, shift=True)) is True
    assert window._focus_mode is True
    assert window._rail.visible is False
    assert window._home.header.visible is False
    assert window._home.status_bar.visible is False
    assert window._home.hints.visible is False
    assert window._handle_shortcut(NS(key="F", ctrl=True, shift=True)) is True
    assert window._focus_mode is False
    assert window._rail.visible is True
    assert window._home.header.visible is True
    assert window._home.hints.visible is True
    window._home._dismiss_hints()
    window.set_focus_mode(True)
    window.set_focus_mode(False)
    assert window._home.hints.visible is False  # отключённые подсказки не воскресают
    assert window.toggle_focus_mode() is True
    assert window.set_focus_mode(True) is False  # повтор ничего не делает


def test_palette_stop_speech_calls_speaker():
    speaker = Mock()
    gui = NS(jarvis=NS(speaker=speaker))
    assert module.FenixGUI._palette_stop_speech(gui) is True
    speaker.stop.assert_called_once()
    assert module.FenixGUI._palette_stop_speech(NS(jarvis=None)) is False
