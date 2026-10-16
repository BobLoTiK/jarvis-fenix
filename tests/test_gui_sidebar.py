"""Native controls and bounded asyncio tasks; no desktop, microphone or model."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import Mock

import flet as ft
import pytest

from jarvis import gui as module
from jarvis.config import Config
from jarvis.gui_sidebar import Sidebar, COMPACT, EXPANDED, mix, rounded_outline, stroke_shapes


def hover(value):
    return NS(data="true" if value else "false")


@pytest.fixture
def rail(tmp_path):
    cfg = Config(tmp_path / "config.json")
    panel = Sidebar(Mock(), cfg)
    yield panel
    panel.dispose()
    module._apply_palette("dark")


def attach(panel):
    calls = []
    panel._mounted = True
    panel._host = NS(run_task=lambda fn, *args: asyncio.create_task(fn(*args)),
                     update=lambda *controls: calls.append(controls))
    return calls


def test_wide_hover_pushes_content_with_matching_animation(rail):
    content = ft.Container()
    layout = rail.layout(content)
    assert isinstance(layout, ft.Stack)
    assert rail.width == COMPACT == rail._reserve.width
    rail._set_expanded(True)
    assert rail.width == EXPANDED
    assert rail._reserve.width == EXPANDED
    assert rail._reserve.animate.duration == rail.animate.duration == 200
    assert layout.controls[0].controls[1] is content
    assert all(b.width == EXPANDED - 24 for b in rail.nav_buttons)
    rail._set_expanded(False)
    assert rail.width == COMPACT
    assert all(not label.visible for label in rail.labels)


def test_selection_and_click_use_real_callback_without_replacing_buttons(rail):
    identities = [id(b) for b in rail.nav_buttons]
    rail.selected_index = 2
    rail._on_select.assert_not_called()
    rail.nav_buttons[3].on_click(None)
    rail._on_select.assert_called_once_with(3)
    assert identities == [id(b) for b in rail.nav_buttons]
    rail.selected_index = 999
    assert rail.selected_index == 2


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_hover_stays_in_selected_color_family_and_selection_stays_distinct(rail, theme):
    module._apply_palette(theme)
    rail.refresh_palette(); rail.selected_index = 2
    asyncio.run(rail._on_nav_hover(3, hover(True)))
    assert rail.nav_buttons[2].bgcolor == module.P.selected
    assert rail.nav_buttons[3].bgcolor == mix(module.P.selected, module.P.bg_card)
    assert rail.nav_buttons[3].bgcolor != module.P.brand
    assert rail.markers[2].visible and not rail.markers[3].visible
    asyncio.run(rail._on_nav_hover(2, hover(True)))
    assert rail.nav_buttons[2].bgcolor == module.P.selected


def test_pin_is_persistent_and_changes_reserve_only_after_success(rail):
    rail.layout(ft.Container())
    asyncio.run(rail._toggle_pin())
    assert rail.pinned and rail.expanded
    assert rail.config.get("gui_sidebar_pinned") is True
    assert rail._reserve.width == EXPANDED
    restored = Sidebar(Mock(), Config(rail.config.path))
    assert restored.pinned and restored.width == EXPANDED
    asyncio.run(rail._toggle_pin())
    assert not rail.pinned and rail._reserve.width == EXPANDED


def test_pin_write_failure_retains_previous_state(rail, monkeypatch):
    rail.layout(ft.Container())
    monkeypatch.setattr(rail.config, "set", lambda *a: False)
    asyncio.run(rail._toggle_pin())
    assert not rail.pinned
    assert rail._reserve.width == COMPACT
    assert "Не удалось" in rail.pin_button.tooltip


def test_hover_delay_reentry_and_collapse_after_mouse_click(rail):
    async def scenario():
        attach(rail)
        await rail._on_panel_hover(hover(True));await asyncio.sleep(.13)
        assert rail.expanded
        await rail._on_panel_hover(hover(False));await asyncio.sleep(.1)
        await rail._on_panel_hover(hover(True));await asyncio.sleep(.28)
        assert rail.expanded
        rail._focused = 2  # mouse click focus must not lock the panel open
        rail._click(2)
        await rail._on_panel_hover(hover(False));await asyncio.sleep(.36)
        assert not rail.expanded
        rail.dispose()
    asyncio.run(scenario())


def test_brief_pointer_pass_does_not_expand(rail):
    async def scenario():
        attach(rail)
        await rail._on_panel_hover(hover(True))
        await rail._on_panel_hover(hover(False))
        await asyncio.sleep(.15)
        assert not rail.expanded
        rail.dispose()
    asyncio.run(scenario())


def test_keyboard_focus_keeps_open_escape_closes_and_pinned_ignores_escape(rail):
    async def scenario():
        attach(rail)
        await rail.on_key(NS(key="Tab"));await rail._on_focus(2)
        assert rail.expanded
        await rail._close_later()
        assert rail.expanded
        await rail.on_key(NS(key="Escape"))
        assert not rail.expanded
        await rail._toggle_pin();await rail.on_key(NS(key="Escape"))
        assert rail.expanded and rail.pinned
        rail.dispose()
    asyncio.run(scenario())


def test_blur_outside_sidebar_closes_keyboard_expansion(rail):
    async def scenario():
        attach(rail)
        await rail.on_key(NS(key="Tab"));await rail._on_focus(2)
        await rail._on_blur(2);await asyncio.sleep(.36)
        assert not rail.expanded
        rail.dispose()
    asyncio.run(scenario())


def test_motion_disabled_removes_animation_and_does_not_schedule_stroke(rail):
    async def scenario():
        attach(rail);rail.set_motion(False)
        await rail._on_nav_hover(2, hover(True))
        assert "stroke" not in rail._tasks
        assert rail.animate is None
        assert all(not c.shapes for c in rail.canvases)
        assert all(c.scale == 1 for c in rail.icon_controls)
        rail.dispose()
    asyncio.run(scenario())


def test_expansion_does_not_cancel_first_hover_stroke(rail):
    async def scenario():
        calls = attach(rail)
        await rail._on_panel_hover(hover(True));await rail._on_nav_hover(2, hover(True))
        await asyncio.sleep(.65)
        assert rail.expanded and rail.canvases[2].shapes
        assert any(call == (rail.canvases[2],) for call in calls)
        rail.dispose()
    asyncio.run(scenario())


def test_stroke_finishes_without_idle_animation_loop(rail):
    async def scenario():
        calls = attach(rail);rail._set_expanded(True)
        await rail._on_nav_hover(2, hover(True));await asyncio.sleep(1.3)
        assert not rail.canvases[2].shapes
        assert rail._tasks["stroke"].done()
        count = len(calls);await asyncio.sleep(.1)
        assert len(calls) == count
        rail.dispose()
    asyncio.run(scenario())


def test_stale_hover_exit_does_not_cancel_next_button(rail):
    async def scenario():
        attach(rail)
        await rail._on_nav_hover(2, hover(True))
        await rail._on_nav_hover(3, hover(True))
        task = rail._tasks["stroke"]
        await rail._on_nav_hover(2, hover(False))
        assert rail._hovered == 3 and rail._tasks["stroke"] is task
        assert not task.cancelled()
        rail.dispose()
    asyncio.run(scenario())


def test_theme_refresh_preserves_selected_expanded_pin_and_invalidates_old_stroke(rail):
    rail.selected_index = 4
    asyncio.run(rail._toggle_pin())
    previous = rail._epoch
    module._apply_palette("light");rail.refresh_palette()
    assert rail.selected_index == 4 and rail.pinned and rail.expanded
    assert rail.width == EXPANDED and rail._epoch > previous
    assert not rail._stroke_valid(4, previous)
    assert rail.bgcolor == module.P.sidebar
    assert rail.nav_buttons[4].bgcolor == module.P.selected


def test_dispose_cancels_pending_tasks_and_suppresses_future_updates(rail):
    async def scenario():
        calls = attach(rail)
        await rail._on_panel_hover(hover(True));await rail._on_nav_hover(2, hover(True))
        futures = list(rail._tasks.values());rail.dispose();await asyncio.sleep(0)
        assert not rail._tasks and all(t.cancelled() for t in futures)
        count = len(calls);rail._update();await asyncio.sleep(.12)
        assert len(calls) == count
    asyncio.run(scenario())


@pytest.mark.parametrize("width", [COMPACT - 24, EXPANDED - 24])
def test_native_stroke_stays_on_rounded_outline(width):
    points = rounded_outline(width)
    assert all(1.49 <= x <= width - 1.49 and 1.49 <= y <= 48 - 1.49 for x, y in points)
    assert stroke_shapes(width, 0, "#d8a786") == []
    assert stroke_shapes(width, 1, "#d8a786") == []
    a, b = stroke_shapes(width, .25, "#d8a786"), stroke_shapes(width, .6, "#d8a786")
    assert len(a) == len(b) == 3
    assert a[-1].elements[0].x != b[-1].elements[0].x


def test_canvas_is_not_positioned_inside_a_non_stack_parent(rail):
    # This matters at the Flutter renderer level; Python construction alone accepts it.
    for canvas in rail.canvases:
        assert canvas.left is None and canvas.right is None
        assert canvas.top is None and canvas.bottom is None


def test_config_motion_override_disables_native_animation_on_start(tmp_path):
    cfg = Config(tmp_path / "motion.json");cfg.set("gui_motion_enabled", False)
    panel = Sidebar(Mock(), cfg)
    assert not panel.motion_enabled and panel.animate is None


def test_navigation_scrolls_without_displacing_fixed_footer(rail):
    assert rail.navigation.expand is True
    assert rail.navigation.scroll == ft.ScrollMode.AUTO


def test_accessibility_reduce_motion_disables_animation(rail, monkeypatch):
    async def flags():
        return NS(disable_animations=False, reduce_motion=True)
    monkeypatch.setattr(ft, "SemanticsService", lambda: NS(get_accessibility_features=flags))
    asyncio.run(rail._read_accessibility())
    assert not rail.motion_enabled and rail.animate is None


def test_theme_refresh_cancels_delayed_pointer_actions(rail):
    async def scenario():
        attach(rail)
        await rail._on_panel_hover(hover(True))
        rail.refresh_palette()
        await asyncio.sleep(.15)
        assert not rail.expanded
        assert "open" not in rail._tasks and "close" not in rail._tasks
    asyncio.run(scenario())


@pytest.mark.parametrize("width", [600, 812, 900, 1099, 1100, 1280])
def test_hover_always_pushes_without_width_threshold(rail, width):
    layout = rail.layout(ft.Container(expand=True))
    layout.width = width
    assert rail._reserve.width == COMPACT
    rail._set_expanded(True)
    assert rail.width == rail._reserve.width == EXPANDED
    assert rail._reserve.animate.duration == rail.animate.duration == 200
    # Resizing the parent must never switch expanded navigation to overlay.
    layout.width = 812 if width >= 1100 else 1280
    assert rail._reserve.width == EXPANDED
    rail._set_expanded(False)
    assert rail.width == rail._reserve.width == COMPACT
    asyncio.run(rail._toggle_pin())
    assert rail._reserve.width == EXPANDED
    rail.set_motion(False)
    assert rail._reserve.animate is None
