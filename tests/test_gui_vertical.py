"""Вертикальный режим: чистая логика, полоса и переключение без окна и звука."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import Mock

import flet as ft
import pytest

from jarvis import gui as module
from jarvis import gui_vertical as vertical
from jarvis import profile, mood
from jarvis.config import Config


@pytest.mark.parametrize("value,expected", [
    (None, 240), ("", 240), ("abc", 240), (True, 240), (False, 240),
    (0, 240), (-50, 240), (100, 220), (999, 320), ("260", 260), (250.7, 250),
])
def test_width_is_clamped_and_broken_values_fall_back(value, expected):
    assert vertical.normalize_width(value) == expected


@pytest.mark.parametrize("value,expected", [
    ("notes", "notes"), ("PLAN", "plan"), (" Log ", "log"), ("x", "log"),
    (None, "log"), (5, "log"), (["log"], "log"),
])
def test_panel_accepts_only_known_names(value, expected):
    assert vertical.normalize_panel(value) == expected
    assert vertical.normalize_panel(value, default="plan") in (expected, "plan")


@pytest.mark.parametrize("value,expected", [
    (True, True), (False, False), (None, False), ("true", True), ("да", True),
    ("1", True), ("0", False), ("нет", False), ("выкл", False), (1, True), (0, False),
    ("maybe", False),
])
def test_enabled_flag_never_raises(value, expected):
    assert vertical.normalize_enabled(value) is expected


@pytest.mark.parametrize("state,expected", [
    ("idle", "idle"), ("listening", "listening"), ("recognizing", "listening"),
    ("thinking", "thinking"), ("speaking", "speaking"), ("error", "idle"),
    ("password", "idle"), (None, "idle"), (7, "idle"),
])
def test_aura_has_four_modes_and_unknown_state_is_idle(state, expected):
    assert vertical.aura_mode(state) == expected


def test_vertical_spec_without_screen_area_keeps_size_untouched():
    spec = vertical.vertical_window_spec(250)
    assert spec["width"] == 250 and spec["frameless"] is True
    assert spec["always_on_top"] is True and spec["min_width"] == 220
    assert "height" not in spec and "left" not in spec


def test_vertical_spec_fills_work_area_at_right_edge():
    spec = vertical.vertical_window_spec(240, (0, 0, 1920, 1040))
    assert spec["height"] == 1040 and spec["left"] == 1680 and spec["top"] == 0
    assert spec["max_width"] == 320


@pytest.mark.parametrize("area", [(10, 10, 5, 5), (0, 0, 0, 0), None, "screen",
                                  (1, 2, 3), ("a", "b", "c", "d")])
def test_broken_work_area_does_not_invent_geometry(area):
    spec = vertical.vertical_window_spec(240, area)
    assert "height" not in spec and "left" not in spec


def test_horizontal_spec_restores_window_and_releases_limits():
    spec = vertical.horizontal_window_spec()
    assert spec["width"] == 1100 and spec["height"] == 760
    assert spec["frameless"] is False and spec["always_on_top"] is False
    assert spec["min_width"] == 900 and spec["max_width"] is None


def test_documents_are_written_atomically_and_missing_file_is_empty(tmp_path):
    path = tmp_path / "notes.txt"
    assert vertical.read_doc(path) == ""
    assert vertical.write_doc(path, "строка один\nстрока два") is True
    assert vertical.read_doc(path) == "строка один\nстрока два"
    assert not (tmp_path / "notes.txt.tmp").exists()
    assert vertical.write_doc(path, "") is True and vertical.read_doc(path) == ""


def test_log_lines_trim_dialog_and_skip_empty(tmp_path):
    messages = [
        {"role": "user", "text": "  ", "time": "10:00"},
        {"role": "user", "text": "привет", "time": "10:01"},
        {"role": "assistant", "text": "здравствуйте", "time": "10:02"},
    ]
    rows = vertical.log_lines(messages)
    assert [r["role"] for r in rows] == ["user", "assistant"]
    assert rows[1]["text"] == "здравствуйте"
    assert len(vertical.log_lines(messages, limit=1)) == 1
    assert vertical.log_lines(None) == []


def test_shorten_keeps_text_in_one_line():
    assert vertical.shorten("  a\n b  ") == "a b"
    long = vertical.shorten("я" * 400, limit=20)
    assert len(long) <= 20 and long.endswith("…")


@pytest.fixture
def isolated_docs(tmp_path, monkeypatch):
    monkeypatch.setattr(vertical, "notes_path", lambda: tmp_path / "notes.txt")
    monkeypatch.setattr(vertical, "plan_path", lambda: tmp_path / "plan.txt")
    return tmp_path


def fake_gui(tmp_path):
    return NS(config=Config(tmp_path / "config.json"), _messages=[], _state="idle",
              _vertical_mode=True, _home_window_visible=True, _page=None, _rail=None)


def test_bar_shows_state_and_switches_panels(isolated_docs, tmp_path):
    bar = vertical.VerticalBar(fake_gui(tmp_path))
    assert bar.status.value
    bar.apply_state("thinking")
    assert bar.aura.mode == "thinking"
    bar.apply_state("ошибка-не-состояние")
    assert bar.aura.mode == "idle"

    assert bar.panel == "log"
    bar.set_panel("notes")
    assert bar.panel == "notes" and isinstance(bar.body.content, ft.TextField)
    bar._notes_field.value = "купть молоко"
    assert bar.save_doc("notes") is True
    assert vertical.read_doc(isolated_docs / "notes.txt") == "купть молоко"
    bar.set_panel("plan")
    assert isinstance(bar.body.content, ft.TextField) and bar.body.content is bar._plan_field
    assert vertical.read_doc(isolated_docs / "plan.txt") == ""


def test_bar_log_follows_messages_and_keeps_newest(isolated_docs, tmp_path):
    gui = fake_gui(tmp_path)
    gui._messages = [{"role": "user", "text": f"строка {i}", "time": "10:0%d" % i}
                     for i in range(vertical.LOG_LIMIT + 5)]
    bar = vertical.VerticalBar(gui)
    assert len(bar.log_list.controls) == vertical.LOG_LIMIT
    bar.set_panel("notes")
    bar.on_message({"role": "user", "text": "новое", "time": "11:00"})
    assert bar.panel == "notes"  # лог не перерисовывается вне панели «Лог»


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setattr(vertical, "notes_path", lambda: tmp_path / "notes.txt")
    monkeypatch.setattr(vertical, "plan_path", lambda: tmp_path / "plan.txt")
    monkeypatch.setattr(vertical, "work_area", lambda: (0, 0, 1920, 1040))
    gui = module.FenixGUI(None, Config(tmp_path / "config.json"))
    page = NS(add=Mock(), update=Mock(), window=NS(), run_task=Mock())
    gui._page = page
    gui._build_ui(page)
    yield gui
    gui.stop()
    gui._rail.dispose()
    profile.unsubscribe(gui._on_profile_switch)
    mood.unsubscribe(gui._on_mood_change)
    module._apply_palette("dark")


def test_vertical_mode_is_off_by_default(window):
    assert window._vertical_mode is False
    assert window._root.content is window._rail_row
    assert window.config.get("ui_vertical_enabled") is False
    assert window._vertical is None


def test_live_switch_reschedules_geometry_after_client_window_state(window):
    """Включение на показанном окне: размеры применяются повторно."""
    window._page.run_task.reset_mock()
    assert window.set_vertical_mode(True) is True
    tasks = [call.args[0] for call in window._page.run_task.call_args_list]
    assert window._reapply_vertical_geometry_later in tasks
    assert window._vertical_level_loop in tasks
    # Отключение обратно повторных размеров не просит.
    window._page.run_task.reset_mock()
    assert window.set_vertical_mode(False) is True
    assert not window._page.run_task.called


def test_reapply_later_stops_when_mode_is_off(window, monkeypatch):
    calls = []
    monkeypatch.setattr(window, "_reapply_vertical_geometry",
                        lambda: calls.append(1))
    window._vertical_mode = False
    asyncio.run(window._reapply_vertical_geometry_later())
    assert calls == []


def test_switching_mode_keeps_state_and_restores_window(window):
    home = window._home
    tabs = dict(window._tabs)
    messages = window._messages
    assert window.set_vertical_mode(True, update=False) is True
    assert window._vertical_mode is True and window._root.content is window._vertical
    assert window._page.window.frameless is True
    assert window._page.window.always_on_top is True
    assert window._page.window.width == 240 and window._page.window.left == 1680
    assert window.config.get("ui_vertical_enabled") is True

    window._apply_state("speaking")
    assert window._vertical.aura.mode == "speaking"
    window._apply_message("user", "привет")
    assert window._vertical.log_list.controls

    assert window.set_vertical_mode(False) is True
    assert window._root.content is window._rail_row
    assert window._page.window.frameless is False
    assert window._page.window.width == 1100
    assert window._home is home and window._content_area.content is home
    assert window._tabs == tabs and window._messages is messages


def test_mode_can_be_enabled_from_saved_config_at_startup(window):
    window.config.set("ui_vertical_enabled", True)
    window._page.update.reset_mock()
    assert window._vertical_snapshot() is True
    assert window._vertical_mode is True
    window._page.update.assert_not_called()  # старт не мигает лишней отрисовкой


def test_width_and_panel_changes_are_persisted(window):
    assert window.set_vertical_width(280) is True
    assert window.config.get("ui_vertical_width") == 280
    assert window.set_vertical_width("abc") is True
    assert window.config.get("ui_vertical_width") == 240
    assert window.set_vertical_panel("notes") is True
    assert window.config.get("ui_vertical_panel") == "notes"
    window.set_vertical_mode(True, update=False)
    assert window._vertical.width == 240


def test_vertical_mode_does_not_overwrite_horizontal_position(window):
    window.config.update({"gui_x": 100, "gui_y": 200})
    window.set_vertical_mode(True, update=False)
    event = NS(type=ft.WindowEventType.MOVED)
    window._on_window_event(event)
    assert window.config.get("gui_x") == 100 and window.config.get("gui_y") == 200


def test_shown_window_reapplies_bar_geometry(window):
    """Клиент Flet затирает размеры до handshake: после показа применяем снова."""
    window.set_vertical_mode(True, update=False)
    window._page.window.width = 1280
    window._page.update.reset_mock()
    window._show_window_now()
    assert window._page.window.width == 240
    assert window._page.window.frameless is True
    assert window._page.window.always_on_top is True
    assert window._page.update.call_count == 2  # показ + повторная геометрия


def test_showing_window_in_horizontal_mode_does_not_touch_geometry(window):
    window._page.update.reset_mock()
    window._show_window_now()
    assert window._page.update.call_count == 1


# --- шторка: геометрия, кадры, закрепление и наведение -------------------


@pytest.mark.parametrize("value,expected", [
    (True, True), (False, False), (None, False), ("true", True), ("да", True),
    ("0", False), (1, True), ("maybe", False),
])
def test_pinned_flag_never_raises(value, expected):
    assert vertical.normalize_pinned(value) is expected


@pytest.mark.parametrize("value,expected", [
    (None, vertical.TAB_WIDTH), (0, vertical.TAB_WIDTH), ("abc", vertical.TAB_WIDTH),
    (4, vertical.TAB_MIN), (99, vertical.TAB_MAX), ("20", 20), (18.6, 18),
])
def test_tab_width_is_clamped(value, expected):
    assert vertical.normalize_tab(value) == expected


@pytest.mark.parametrize("value,expected", [
    (None, vertical.AUTOHIDE_MS), ("abc", vertical.AUTOHIDE_MS),
    (-5, 0), (99999, 10000), ("1200", 1200),
])
def test_autohide_delay_is_clamped(value, expected):
    assert vertical.normalize_delay(value) == expected


def test_curtain_geometry_keeps_full_bar_and_edge_handle():
    positions = vertical.curtain_geometry(240, (0, 0, 1920, 1040))
    assert positions == {"shown": 1680, "hidden": 1902, "tab": 18,
                         "width": 240, "height": 1040, "top": 0}


def test_curtain_geometry_without_workarea_does_not_invent_coordinates():
    positions = vertical.curtain_geometry(240, None)
    assert positions["shown"] is None and positions["hidden"] is None
    assert positions["tab"] == 18 and positions["width"] == 240


def test_slide_frames_move_one_way_and_end_exactly():
    frames = vertical.slide_frames(1680, 1902)
    assert len(frames) == vertical.SLIDE_STEPS
    assert frames[-1] == 1902
    assert frames == sorted(frames) and len(set(frames)) == len(frames)
    assert vertical.slide_frames(1902, 1680)[-1] == 1680
    assert vertical.slide_frames(7, 7) == [7]
    assert vertical.slide_frames("abc", 5) == []


def test_curtain_state_machine_respects_pin_and_pointer():
    curtain = vertical.Curtain()
    assert curtain.open is True
    assert curtain.leave() is False  # уход курсора сам окно не двигает
    assert curtain.open is True and curtain.wants_autohide() is True
    assert curtain.hide() is True and curtain.open is False
    assert curtain.hide() is False  # уже спрятана
    assert curtain.enter() is True and curtain.open is True
    assert curtain.enter() is False
    assert curtain.hide() is False  # курсор внутри — не прячем
    assert curtain.open is True


def test_curtain_hides_only_after_pointer_left():
    curtain = vertical.Curtain()
    curtain.enter()
    assert curtain.hide() is False and curtain.open is True
    curtain.leave()
    assert curtain.wants_autohide() is True
    curtain.show()
    assert curtain.wants_autohide() is True


def test_curtain_pin_forces_open_and_blocks_autohide():
    curtain = vertical.Curtain()
    curtain.leave()
    assert curtain.open is True and curtain.wants_autohide() is True
    assert curtain.set_pinned(True) is True
    assert curtain.open is True and curtain.wants_autohide() is False
    assert curtain.hide() is False
    curtain.set_pinned(False)
    assert curtain.wants_autohide() is True


def _finish_slide(window):
    """Проигрывает запланированную анимацию шторки без настоящего окна."""
    task = window._page.run_task
    if not task.called:
        return
    fn, frames, gen = task.call_args.args
    task.reset_mock()
    asyncio.run(fn(frames, gen))


def test_vertical_mode_leaves_only_a_handle_visible(window):
    assert window.set_vertical_mode(True, update=False) is True
    assert window._page.window.left == 1680  # включаем открытой, чтобы заметили
    assert window._page.window.shadow is True
    assert window._curtain is not None and window._curtain.open is True
    assert window._vertical.tab.width == vertical.TAB_WIDTH
    assert window._vertical.tab_icon.name == ft.Icons.CHEVRON_RIGHT

    window._vertical_hover(False)
    assert window._vertical_hide_if_idle() is True
    _finish_slide(window)
    assert window._page.window.left == 1902  # осталась ручка 18 px
    assert window._vertical.tab_icon.name == ft.Icons.CHEVRON_LEFT


def test_hover_deploys_hidden_bar(window):
    window.set_vertical_mode(True, update=False)
    window._vertical_hover(False)
    window._vertical_hide_if_idle()
    _finish_slide(window)
    assert window._page.window.left == 1902
    window._page.run_task.reset_mock()
    window._vertical_hover(True)
    assert window._curtain.open is True
    assert window._vertical.tab_icon.name == ft.Icons.CHEVRON_RIGHT
    assert window._page.run_task.called  # выезд идёт кадрами, а не рывком
    _finish_slide(window)
    assert window._page.window.left == 1680


def test_tab_click_toggles_unpinned_bar(window):
    window.set_vertical_mode(True, update=False)
    window._vertical_tab_click()
    assert window._curtain.open is False
    _finish_slide(window)
    assert window._page.window.left == 1902
    window._vertical_tab_click()
    assert window._curtain.open is True
    _finish_slide(window)
    assert window._page.window.left == 1680


def test_pinned_bar_ignores_leave_and_tab_click(window):
    window.config.set("ui_vertical_pinned", True)
    window.set_vertical_mode(True, update=False)
    assert window._curtain.pinned is True
    assert window._vertical.pinned is True
    assert window._vertical.pin_btn.icon == ft.Icons.PUSH_PIN
    window._vertical_hover(False)
    assert window._vertical_hide_if_idle() is False
    window._vertical_tab_click()
    assert window._curtain.open is True and window._page.window.left == 1680


def test_pin_toggle_is_persisted_and_applied(window):
    window.set_vertical_mode(True, update=False)
    assert window.set_vertical_pinned(True) is True
    assert window.config.get("ui_vertical_pinned") is True
    assert window._vertical.pinned is True
    assert window.set_vertical_pinned(False) is True
    assert window.config.get("ui_vertical_pinned") is False
    assert window._vertical.pinned is False


def test_width_change_keeps_hidden_bar_hidden(window):
    window.set_vertical_mode(True, update=False)
    window._vertical_hover(False)
    window._vertical_hide_if_idle()
    assert window.set_vertical_width(280) is True
    assert window._page.window.width == 280
    assert window._page.window.left == 1902
    window._vertical_move(True, animate=False)
    assert window._page.window.left == 1640


def test_leaving_vertical_mode_removes_shadow_and_stops_curtain(window):
    window.set_vertical_mode(True, update=False)
    assert window._curtain is not None
    assert window.set_vertical_mode(False, update=False) is True
    assert window._curtain is None
    assert window._page.window.shadow is False
    assert window._page.window.frameless is False


def test_bar_uses_card_handle_and_segmented_panels(isolated_docs, tmp_path):
    bar = vertical.VerticalBar(fake_gui(tmp_path))
    radius = bar.card.border_radius
    assert radius.top_left == 16 and radius.bottom_left == 16
    assert radius.top_right == 0 and radius.bottom_right == 0
    assert bar.card.shadow.blur_radius == 26
    assert len(bar.card.gradient.colors) == 2
    assert bar.card.margin.left == 6
    assert set(bar.panel_buttons) == set(vertical.PANELS)
    assert bar.panel_buttons["log"].content.color == module.P.brand
    bar.set_panel("notes")
    assert bar.panel_buttons["notes"].content.color == module.P.brand
    assert bar.panel_buttons["log"].content.color == module.P.text_dim


def test_bar_handle_has_grip_and_chevron(isolated_docs, tmp_path):
    bar = vertical.VerticalBar(fake_gui(tmp_path))
    assert bar.tab.width == vertical.TAB_WIDTH
    assert bar.tab_line.height == 46 and bar.tab_line.width == 2
    assert len(bar.tab_line.gradient.colors) == 3
    assert isinstance(bar.tab.content, ft.Column)
    zones = bar.tab.content.controls
    assert len(zones) == 3  # бейдж сверху, ручка по центру, точки панелей снизу
    middle = zones[1].content
    assert isinstance(middle, ft.Column)
    assert middle.controls == [bar.tab_line, bar.level, bar.tab_icon]
    assert zones[2].content is bar.dots_column
    assert not bar.badge.visible


def test_hover_highlights_handle_and_notifies_gui(isolated_docs, tmp_path):
    seen = []
    gui = fake_gui(tmp_path)
    gui._vertical_hover = lambda entered: seen.append(entered)
    bar = vertical.VerticalBar(gui)
    bar._on_hover(NS(data=True))
    assert seen == [True] and bar.tab.bgcolor != ft.Colors.TRANSPARENT
    bar._on_hover(NS(data=False))
    assert seen == [True, False] and bar.tab.bgcolor == ft.Colors.TRANSPARENT


def test_bar_pin_button_updates_icon_and_tooltip(isolated_docs, tmp_path):
    bar = vertical.VerticalBar(fake_gui(tmp_path))
    assert bar.pinned is False
    assert bar.tab.tooltip == "Свернуть полосу"
    assert bar.set_pinned(True) is True
    assert bar.pin_btn.icon == ft.Icons.PUSH_PIN
    assert bar.pin_btn.tooltip == "Открепить полосу"
    assert bar.tab.tooltip == "Полоса закреплена"
    assert bar.set_pinned(True) is False  # повтор ничего не делает
    assert bar.set_pinned(False) is True
    assert bar.pin_btn.tooltip == "Закрепить полосу"
    assert bar.tab.tooltip == "Свернуть полосу"


def test_curtain_never_hide_keeps_bar_open():
    curtain = vertical.Curtain()
    assert curtain.wants_autohide() is True
    assert curtain.set_never_hide(True) is True
    assert curtain.never_hide is True
    curtain.leave()
    assert curtain.wants_autohide() is False
    assert curtain.hide() is False and curtain.open is True
    assert curtain.set_never_hide(False) is True
    assert curtain.wants_autohide() is True
    assert curtain.hide() is True and curtain.open is False


def test_bar_level_meter_clamps_and_grows(isolated_docs, tmp_path):
    bar = vertical.VerticalBar(fake_gui(tmp_path))
    assert bar.level.height == vertical.LEVEL_TRACK
    assert bar.set_level(-3) == 0.0 and bar.level_fill.height == 2
    assert bar.set_level(5) == 1.0 and bar.level_fill.height == vertical.LEVEL_TRACK
    assert bar.set_level("тишина") == 0.0
    assert bar.set_level(None) == 0.0


def test_bar_unread_badge_marks_and_clears(isolated_docs, tmp_path):
    bar = vertical.VerticalBar(fake_gui(tmp_path))
    assert not bar.badge.visible and bar.unread == 0
    assert bar.set_unread(2) == 2
    assert bar.badge.visible and bar.badge_zone.visible
    assert bar.set_unread(-5) == 0
    assert not bar.badge.visible and not bar.badge_zone.visible
    assert bar.set_unread("мусор") == 0


def test_bar_panel_dots_switch_without_toggling_curtain(isolated_docs, tmp_path):
    seen, toggled = [], []
    gui = fake_gui(tmp_path)
    gui.set_vertical_panel = lambda name: seen.append(name) or True
    gui._vertical_tab_click = lambda: toggled.append(1)
    bar = vertical.VerticalBar(gui)
    assert set(bar.panel_dots) == set(vertical.PANELS)
    bar._on_dot("notes")
    assert seen == ["notes"]
    bar._on_tab_click(None)  # тот же клик дошёл до ручки — шторку не дёргаем
    assert toggled == []
    bar._dot_touch -= 1.0  # прошлое нажатие: ручка снова работает
    bar._on_tab_click(None)
    assert toggled == [1]


def test_hidden_bar_counts_unread_and_clears_on_open(window):
    window.set_vertical_mode(True, update=False)
    window._curtain.open = False
    window._apply_message("assistant", "ответ")
    assert window._vertical.unread == 1
    window._apply_message("user", "ещё вопрос")  # свои реплики не считаем
    assert window._vertical.unread == 1
    window._apply_message("assistant", "второй ответ")
    assert window._vertical.unread == 2
    window._vertical_tab_click()
    assert window._curtain.open is True and window._vertical.unread == 0
    assert not window._vertical.badge.visible


def test_never_hide_is_persisted_and_blocks_autohide(window):
    window.set_vertical_mode(True, update=False)
    assert window.set_vertical_never_hide(True) is True
    assert window.config.get("ui_vertical_never_hide") is True
    assert window._curtain.never_hide is True
    assert window._vertical.never_hide is True
    assert window._vertical.never_btn.icon == ft.Icons.VISIBILITY
    window._vertical_hover(False)
    assert window._vertical_hide_if_idle() is False
    assert window.set_vertical_never_hide(False) is True
    assert window.config.get("ui_vertical_never_hide") is False
    assert window._vertical.never_btn.icon == ft.Icons.VISIBILITY_OFF


def test_never_hide_switch_on_bar_calls_gui(isolated_docs, tmp_path):
    seen = []
    gui = fake_gui(tmp_path)
    gui.set_vertical_never_hide = lambda value: seen.append(value) or True
    bar = vertical.VerticalBar(gui)
    bar._on_never_hide(None)
    assert seen == [True]
    bar.set_never_hide(True)
    bar._on_never_hide(None)
    assert seen == [True, False]


def test_level_loop_stops_when_mode_is_off(window):
    window._vertical_mode = False
    asyncio.run(window._vertical_level_loop(1))
    assert window._vertical_level_task is None
    window.set_vertical_mode(True, update=False)
    assert window._vertical_level_task is not None
    window.set_vertical_mode(False, update=False)
    assert window._vertical_level_task is None
