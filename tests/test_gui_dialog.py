# -*- coding: utf-8 -*-
"""Детали диалога: разделители дней, «печатает…», повтор сообщения."""
from datetime import date, timedelta
from types import SimpleNamespace as NS
from unittest.mock import Mock

import flet as ft
import pytest
from jarvis import gui as module, profile, mood
from jarvis import gui_dialog
from jarvis.config import Config


def test_day_label_today_yesterday_and_older():
    today = date(2026, 11, 8)
    assert gui_dialog.day_label({"date": "2026-11-08"}, today) == "Сегодня"
    assert gui_dialog.day_label({"date": "2026-11-07"}, today) == "Вчера"
    assert gui_dialog.day_label({"date": "2026-11-05"}, today) == "5 ноября"
    assert gui_dialog.day_label({"date": "2026-01-02"}, today) == "2 января"
    assert gui_dialog.day_label({}, today) == ""
    assert gui_dialog.day_label({"date": "вчера"}, today) == ""


def test_needs_separator_only_on_day_change():
    today = date(2026, 11, 8)
    first = {"date": "2026-11-08"}
    assert gui_dialog.needs_separator(None, first, today) is True
    assert gui_dialog.needs_separator(first, {"date": "2026-11-08"}, today) is False
    assert gui_dialog.needs_separator(first, {"date": "2026-11-07"}, today) is True
    assert gui_dialog.needs_separator(first, {}, today) is False


def test_next_day_is_iso_today():
    today = date(2026, 11, 8)
    assert gui_dialog.next_day(today) == "2026-11-08"
    assert gui_dialog.next_day() == date.today().isoformat()


def test_day_separator_and_typing_bubble_build_controls():
    palette = NS(border="#333333", text_dim="#999999", brand="#ffcc00",
                 bg_card="#181823")
    separator = gui_dialog.day_separator(palette, "Сегодня")
    assert isinstance(separator, ft.Row) and len(separator.controls) == 3
    typing = gui_dialog.typing_bubble(palette)
    assert isinstance(typing, ft.Container)
    assert "печатает" in typing.content.controls[1].value


@pytest.fixture
def window(tmp_path):
    gui = module.FenixGUI(None, Config(tmp_path / "config.json"))
    page = NS(add=Mock(), update=Mock(), window=NS(width=1100, height=760),
              run_task=Mock(), overlay=[])
    gui._page = page
    gui._build_ui(page)
    gui._select_tab(0)
    yield gui
    gui.close_palette()
    gui.stop()
    gui._rail.dispose()
    profile.unsubscribe(gui._on_profile_switch)
    mood.unsubscribe(gui._on_mood_change)
    module._apply_palette("dark")


def test_first_message_gets_day_separator(window):
    window._apply_message("user", "Привет")
    controls = window._history_list.controls
    assert isinstance(controls[0], ft.Row)  # разделитель дня
    assert controls[-1] is not controls[0]
    window._apply_message("assistant", "Здравствуйте")
    assert len(window._history_list.controls) == 3  # разделитель и два сообщения


def test_same_day_messages_do_not_repeat_separator(window):
    window._apply_message("user", "Раз")
    window._apply_message("assistant", "Два")
    window._apply_message("user", "Три")
    assert sum(isinstance(c, ft.Row) for c in window._history_list.controls) == 1


def test_typing_bubble_appears_while_thinking_and_goes_on_answer(window):
    window._apply_state("thinking")
    assert window._typing in window._history_list.controls
    window._apply_stream_chunk("ответ")
    assert window._typing is None
    assert window._typing not in window._history_list.controls


def test_typing_bubble_removed_when_state_returns_to_idle(window):
    window._apply_state("thinking")
    assert window._typing is not None
    window._apply_state("idle")
    assert window._typing is None


def test_chat_measure_keeps_line_length_in_check(window):
    window._page.window.width = 1600
    assert window._chat_measure() == module.CHAT_MEASURE
    window._page.window.width = 800
    assert window._chat_measure() == 640
    window._page.window.width = 400
    assert window._chat_measure() == 240
    window._page.window.width = 1100
    assert window._history_list.width == module.CHAT_MEASURE


def test_history_list_width_is_not_overridden_by_expand(window):
    """expand=True на ListView в Row перебивает width: живое окно растягивало
    пузыри на 1280 px при заданной мере 760. Мера должна оставаться мерой."""
    assert not getattr(window._history_list, "expand", False)
    assert window._history_list.width == module.CHAT_MEASURE
    window._page.window.width = 1600
    window._on_window_event(NS(type=ft.WindowEventType.RESIZED))
    assert window._history_list.width == module.CHAT_MEASURE
    assert not getattr(window._history_list, "expand", False)


def test_resize_updates_chat_measure(window):
    window._page.window.width = 900
    window._on_window_event(NS(type=ft.WindowEventType.RESIZE))
    assert window._history_list.width == 740
    window._page.window.width = 1500
    window._on_window_event(NS(type=ft.WindowEventType.RESIZED))
    assert window._history_list.width == module.CHAT_MEASURE


def test_user_message_has_repeat_action_that_fills_input(window):
    window._apply_message("user", "напомни через час")
    bubble = window._history_list.controls[-1]
    header = bubble.content.controls[0].controls
    # Кнопки обёрнуты в Semantics: скринридеру нужна метка, не только tooltip.
    wrappers = [c for c in header if isinstance(c, ft.Semantics)]
    assert [w.label for w in wrappers] == ["Копировать сообщение", "Повторить в поле ввода"]
    assert all(w.button for w in wrappers)
    buttons = [w.content for w in wrappers]
    assert all(isinstance(b, ft.IconButton) for b in buttons)
    assert [b.tooltip for b in buttons] == ["Копировать сообщение", "Повторить в поле ввода"]
    assert all(b.width == 44 and b.height == 44 for b in buttons)
    buttons[-1].on_click(NS(control=buttons[-1]))
    assert window._input_field.value == "напомни через час"
