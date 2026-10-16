"""Native minimal Home; no OS/model/mic/network. Old navigation IDs stay stable."""
import asyncio
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import Mock

import flet as ft
import pytest
from jarvis import gui as module, profile, mood
from jarvis.config import Config
from jarvis.gui_home import HomeScreen, clock_labels


def walk(control):
    yield control
    content = getattr(control, "content", None)
    if isinstance(content, ft.Control):
        yield from walk(content)
    for child in getattr(control, "controls", []) or []:
        yield from walk(child)


@pytest.fixture
def gui(tmp_path, monkeypatch):
    window = module.FenixGUI(None, Config(tmp_path / "config.json"))
    window._page = NS(add=Mock(), update=Mock(), window=NS())
    monkeypatch.setattr(window, "_get_voice_options", lambda: [ft.dropdown.Option("ruslan")])
    window._build_ui(window._page)
    yield window
    window.stop()
    window._rail.dispose()
    profile.unsubscribe(window._on_profile_switch)
    mood.unsubscribe(window._on_mood_change)
    module._apply_palette("dark")


def test_startup_is_home_and_chat_ids_do_not_shift(gui):
    assert module.HOME_TAB == 6
    assert gui._rail.selected_index == module.HOME_TAB
    assert gui._content_area.content is gui._home
    assert [module.NAV_ITEMS[i][0] for i in module.NAV_ORDER] == [
        "Главная", "Диалог", "Микрофон", "Голос и звук", "Персона", "Настройки", "Мои команды"]
    assert gui._rail.navigation.controls[0] is gui._rail.nav_buttons[module.HOME_TAB]
    gui._select_tab(0)
    assert gui._content_area.content is gui._tabs[0]
    assert gui._input_field in list(walk(gui._tabs[0]))


def test_minimal_home_has_no_composer_cards_widgets_or_fake_actions(gui):
    controls = list(walk(gui._home))
    assert not any(isinstance(c, (ft.TextField, ft.Dropdown, ft.ListView)) for c in controls)
    buttons = [c for c in controls if isinstance(c, ft.Button)]
    assert buttons == gui._home.theme_buttons
    assert not hasattr(gui._home, "on_click") or gui._home.on_click is None
    assert "Модель" not in " ".join(str(getattr(c, "value", "")) for c in controls)
    assert gui._home.status.value == "Ядро ещё не готово"


def test_local_date_labels_include_midnight_and_new_year():
    assert clock_labels(datetime(2026, 12, 31, 23, 59)) == ("четверг, 31 декабря", "23:59")
    assert clock_labels(datetime(2027, 1, 1, 0, 0)) == ("пятница, 1 января", "00:00")


def test_clock_only_marks_changes_at_minute_or_date_boundary(gui):
    home = gui._home
    assert home.refresh_clock(datetime(2027, 1, 1, 8, 30))
    assert not home.refresh_clock(datetime(2027, 1, 1, 8, 30, 59))
    assert home.refresh_clock(datetime(2027, 1, 1, 8, 31))
    assert home.clock.value == "08:31"


@pytest.mark.parametrize("state,label", [("listening", "Слушаю"), ("thinking", "Обрабатываю"),
    ("speaking", "Говорю"), ("error", "Ошибка"), ("password", "Нужен пароль")])
def test_home_mirrors_real_state_without_auto_opening_chat(gui, state, label):
    gui.jarvis = NS(listening_enabled=True, handler=NS(_pending_password=None, _pending_question=None))
    gui._apply_state(state)
    assert gui._home.status.value == label
    assert gui._rail.selected_index == module.HOME_TAB
    assert gui._content_area.content is gui._home


def test_paused_mic_does_not_claim_listening(gui):
    gui.jarvis = NS(listening_enabled=False, handler=NS(_pending_password=None, _pending_question=None))
    gui._apply_state("idle")
    assert gui._home.status.value == "Микрофон на паузе"


def test_incoming_chat_does_not_replace_home_and_is_available_in_dialog(gui):
    gui._apply_message("user", "Проверка")
    gui._apply_stream_chunk("Ответ")
    assert gui._content_area.content is gui._home
    gui._select_tab(0)
    assert gui._messages[-1]["text"] == "Ответ"
    gui._select_tab(module.HOME_TAB)
    assert gui._content_area.content is gui._home


def test_theme_rebuild_keeps_home_selected_and_preserves_chat_draft_and_stream(gui):
    old_home = gui._home
    old_home.dispose = Mock(wraps=old_home.dispose)
    gui._input_field.value = "Несохранённый черновик"
    gui._apply_stream_chunk("Часть ответа")
    gui._home._theme("Светлая")
    old_home.dispose.assert_called()
    assert gui.config.get("gui_theme") == "Светлая"
    assert gui._rail.selected_index == module.HOME_TAB
    assert gui._content_area.content is gui._home and gui._home is not old_home
    assert gui._input_field.value == "Несохранённый черновик"
    assert gui._messages[-1]["text"] == "Часть ответа"
    gui._select_tab(0)
    gui._home._theme("Тёмная")
    assert gui._rail.selected_index == 0
    assert gui._content_area.content is gui._tabs[0]


def test_home_navigation_does_not_break_tray_mic_or_settings(gui):
    gui._open_mic_tab()
    assert gui._rail.selected_index == 1 and gui._content_area.content is gui._tabs[1]
    gui._select_tab(module.HOME_TAB)
    gui._open_settings_tab()
    assert gui._rail.selected_index == 4 and gui._content_area.content is gui._tabs[4]
    gui._show_window_now()
    assert gui._page.window.visible and gui._page.window.minimized is False


def test_unmounted_home_has_no_clock_task_and_stop_disposes_it(gui):
    assert not gui._home._mounted and gui._home._future is None
    future = Mock()
    gui._home._future = future
    gui.stop()
    future.cancel.assert_called_once()
    assert gui._home._future is None and gui._home._host is None


def test_clock_updates_only_date_controls_and_dispose_cancels_task(gui):
    async def scenario():
        home = gui._home
        home._mounted = True
        home._epoch = 12
        host = home._host = NS(update=Mock())
        home.refresh_clock = Mock(return_value=True)
        home._future = asyncio.create_task(home._clock_loop(12))
        await asyncio.sleep(.01)
        host.update.assert_called_once_with(home.date, home.clock)
        task = home._future
        home.will_unmount()
        await asyncio.sleep(0)
        assert task.cancelled() and home._host is None
        home.refresh_clock.reset_mock()
        await home._clock_loop(12)
        home.refresh_clock.assert_not_called()
    asyncio.run(scenario())
