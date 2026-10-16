"""Native solar aura lifecycle; no audio device, model or Windows session."""
import asyncio
import math
import re
import time
from types import SimpleNamespace as NS
from unittest.mock import Mock

import flet as ft
import flet.canvas as cv
import pytest
from jarvis import gui as module, profile, mood
from jarvis.config import Config
from jarvis.gui_home_fx import solar_shapes, FPS, IDLE_FPS, MODES, transition_weights


@pytest.fixture
def gui(tmp_path, monkeypatch):
    window = module.FenixGUI(None, Config(tmp_path / "config.json"))
    window._page = NS(add=Mock(), update=Mock(), window=NS(visible=True, minimized=False))
    monkeypatch.setattr(window, "_get_voice_options", lambda: [ft.dropdown.Option("ruslan")])
    window._build_ui(window._page)
    window.jarvis = NS(listening_enabled=True,
        listener=NS(current_rms=0, level_updated_at=time.monotonic(), muted=False),
        handler=NS(_pending_password=None, _pending_question=None))
    yield window
    window.stop(); window._rail.dispose()
    profile.unsubscribe(window._on_profile_switch); mood.unsubscribe(window._on_mood_change)
    module._apply_palette("dark")


def attach(aura):
    aura._mounted = True
    aura._host = NS(run_task=lambda fn, *args: asyncio.create_task(fn(*args)), update=Mock())
    return aura._host


@pytest.mark.parametrize("mode", ["idle", "listening", "speaking", "thinking"])
def test_shapes_are_bounded_deterministic_and_change_smoothly(mode):
    a = solar_shapes(mode, .5, .3, "#d8a786")
    b = solar_shapes(mode, 1, .3, "#d8a786")
    assert len(a) == 35
    clean = lambda shapes: re.sub(r"_i=\d+", "_i=ID", repr(shapes))
    assert clean(a) == clean(solar_shapes(mode, .5, .3, "#d8a786"))
    assert clean(a) != clean(b)
    assert FPS == 24 and IDLE_FPS == 16
    for shape in a:
        if isinstance(shape, cv.Arc):
            assert shape.use_center is False and isinstance(shape.paint,ft.Paint)
        if hasattr(shape, "radius"):
            assert 0 < shape.radius < 150
            assert 0 < shape.x < 300 and 0 < shape.y < 300


@pytest.mark.parametrize("state", ["idle", "error", "password", "awaiting"])
def test_idle_error_or_sensitive_states_keep_only_decorative_ambient(gui, state):
    gui._apply_state(state)
    assert gui._home.aura.mode == "idle"
    assert gui._home.aura.canvas.shapes
    assert gui._home.aura._future is None


@pytest.mark.parametrize("state,mode", [("speaking","speaking"),("listening","listening"),
    ("thinking","thinking"),("recognizing","thinking")])
def test_real_states_select_their_own_motion_without_opening_chat(gui, state, mode):
    gui._apply_state(state)
    assert gui._home.aura.mode == mode and gui._home.aura.canvas.shapes
    assert gui._rail.selected_index == module.HOME_TAB
    assert gui._home.aura._future is None  # Not mounted, no background task.


def test_only_existing_fresh_rms_can_light_idle_home(gui):
    home, listener = gui._home, gui.jarvis.listener
    gui._apply_state("idle")
    listener.current_rms = 800
    home.poll_signal()
    assert home.aura.mode == "listening" and home.aura.energy == .4
    assert home.status.value == "Рядом, когда нужен"  # Signal is not a recognition claim.
    listener.level_updated_at -= 2
    home.poll_signal()
    assert home.aura.mode == "idle" and home.aura.energy == 0


@pytest.mark.parametrize("changes", [dict(muted=True), dict(current_rms=float("nan")),
    dict(current_rms=float("inf")), dict(level_updated_at="bad"), dict(current_rms=0)])
def test_invalid_quiet_or_muted_input_cannot_start_glow(gui, changes):
    gui.jarvis.listener.current_rms = 800
    for key,value in changes.items():setattr(gui.jarvis.listener,key,value)
    gui._home.poll_signal()
    assert gui._home.aura.mode == "idle"


def test_pause_clears_signal_and_speaking_has_priority_over_input(gui):
    listener = gui.jarvis.listener
    listener.current_rms = 1200
    gui._home.poll_signal()
    assert gui._home.aura.mode == "listening"
    gui.jarvis.listening_enabled = False
    gui._apply_state("idle");gui._home.poll_signal()
    assert gui._home.aura.mode == "idle"
    assert gui._home.status.value == "Микрофон на паузе"
    gui.jarvis.listening_enabled = True
    gui._apply_state("speaking");gui._home.poll_signal()
    assert gui._home.aura.mode == "speaking"


def test_one_task_targeted_updates_and_idle_keeps_same_phase(gui):
    async def scenario():
        aura = gui._home.aura
        host = attach(aura)
        gui._apply_state("speaking")
        task = aura._future
        aura.sync_motion();aura.sync_motion()
        assert aura._future is task
        await asyncio.sleep(.14)
        # State frame + at most four animation frames, not page.update at 24 Hz.
        assert 2 <= host.update.call_count <= 6
        assert all(c.args == (aura.canvas,) for c in host.update.call_args_list)
        gui._apply_state("idle")
        await asyncio.sleep(0)
        assert not task.cancelled() and aura._future is task and aura.canvas.shapes
        aura.dispose()
        await asyncio.sleep(0)
        assert task.cancelled() and aura._future is None
    asyncio.run(scenario())


@pytest.mark.parametrize("reason", ["tab", "hidden", "minimized", "config", "os", "rail"])
def test_background_and_reduced_motion_stop_animation(gui, reason):
    async def scenario():
        aura = gui._home.aura;attach(aura)
        gui._apply_state("speaking");task=aura._future
        await asyncio.sleep(.01)
        if reason=="tab":gui._select_tab(0)
        elif reason=="hidden":gui._page.window.visible=False
        elif reason=="minimized":gui._page.window.minimized=True
        elif reason=="config":gui.config.set("gui_motion_enabled",False)
        elif reason=="os":aura._os_reduced=True
        elif reason=="rail":gui._rail.motion_enabled=False
        aura.sync_motion();await asyncio.sleep(0)
        assert task.cancelled() and aura._future is None
        aura.dispose()
    asyncio.run(scenario())


def test_unmount_and_theme_dispose_old_aura_task(gui):
    async def scenario():
        old=gui._home.aura;attach(old)
        gui._apply_state("listening");task=old._future
        await asyncio.sleep(.01)
        gui._home._theme("Светлая")
        await asyncio.sleep(0)
        assert task.cancelled() and old._host is None and not old._mounted
        assert gui._home.aura is not old and gui._home.aura.mode=="listening"
    asyncio.run(scenario())


def test_os_reduce_motion_keeps_static_state_without_animation(gui, monkeypatch):
    async def scenario():
        aura=gui._home.aura;host=attach(aura)
        async def flags():return NS(disable_animations=False, reduce_motion=True)
        monkeypatch.setattr(ft,"SemanticsService",lambda:NS(get_accessibility_features=flags))
        gui._apply_state("speaking");task=aura._future
        await aura._read_accessibility(host)
        await asyncio.sleep(0)
        assert aura._os_reduced and task.cancelled() and aura._future is None
        assert aura.canvas.shapes  # Useful static state feedback, no motion.
    asyncio.run(scenario())


@pytest.mark.parametrize("event", [ft.WindowEventType.MINIMIZE, ft.WindowEventType.HIDE])
def test_native_window_events_stop_and_restore_motion(gui, event):
    async def scenario():
        aura=gui._home.aura;attach(aura)
        gui._apply_state("speaking");task=aura._future
        await asyncio.sleep(.01)
        gui._on_window_event(NS(type=event))
        await asyncio.sleep(0)
        assert task.cancelled() and aura._future is None
        gui._on_window_event(NS(type=ft.WindowEventType.RESTORE))
        assert aura._future is not None
        aura.dispose()
    asyncio.run(scenario())


def test_visible_idle_animates_without_core_or_microphone(gui):
    async def scenario():
        gui.jarvis=None
        aura=gui._home.aura;host=attach(aura)
        gui._apply_state("idle");task=aura._future
        assert task is not None and aura.mode=="idle"
        await asyncio.sleep(.14)
        assert 2 <= host.update.call_count <= 5
        assert gui._home.status.value=="Ядро ещё не готово"
        aura.dispose();await asyncio.sleep(0)
        assert task.cancelled()
    asyncio.run(scenario())


def test_fixed_layers_fade_instead_of_appearing():
    scenes=[solar_shapes(mode,1,.5,"#d8a786") for mode in ("idle","listening","speaking")]
    assert all(len(scene)==35 for scene in scenes)
    assert all(sum(isinstance(s,cv.Path) for s in scene)==9 for scene in scenes)
    # Layer count/type/order stays stable across modes; only geometry/alpha changes.
    assert [type(s) for s in scenes[0]] == [type(s) for s in scenes[2]]


def test_transition_eases_rise_fall_and_midflight_reversal():
    weights={m:float(m=="idle") for m in MODES}
    first=transition_weights(weights,"speaking",1/24)
    assert 0 < first["speaking"] < .2 and first["idle"] > .8
    for _ in range(24):weights=transition_weights(weights,"speaking",1/24)
    assert .95 < weights["speaking"] < 1
    previous=weights.copy()
    weights=transition_weights(weights,"listening",1/24)
    assert 0 < weights["listening"] < .2
    assert weights["speaking"] > previous["speaking"]-.15
    for _ in range(48):weights=transition_weights(weights,"idle",1/24)
    assert .98 < weights["idle"] < 1
    assert sum(weights.values())==pytest.approx(1)
    assert all(0 <= v <= 1 for v in weights.values())


def test_mounted_target_change_does_not_pop_or_restart_phase(gui):
    async def scenario():
        aura=gui._home.aura;host=attach(aura)
        aura.set_mode("idle");await asyncio.sleep(.08)
        task=aura._future;phase=aura._phase;before=aura.canvas.shapes
        weights=aura._weights.copy();count=host.update.call_count
        aura.set_mode("speaking",.8)
        assert aura._future is task and aura._phase==phase
        assert aura.canvas.shapes is before and aura._weights==weights
        assert host.update.call_count==count
        await asyncio.sleep(.08)
        assert phase < aura._phase and 0 < aura._weights["speaking"] < .5
        aura.dispose()
    asyncio.run(scenario())


def test_energy_is_smoothed_not_applied_as_a_step(gui):
    aura=gui._home.aura
    aura._mounted=True;aura._host=NS(update=Mock())
    aura.energy=1;aura.mode="listening"
    aura._last_frame=time.monotonic()-.04
    aura._draw(1)
    assert 0 < aura._visual_energy < .2
    assert 0 < aura._weights["listening"] < .2
    aura.dispose()


def test_waves_have_more_travel_but_stay_inside_canvas():
    spreads=[]
    for mode in ("idle","listening","speaking"):
        shapes=solar_shapes(mode,1,.5,"#d8a786",phase=1)
        paths=[s for s in shapes if isinstance(s,cv.Path)]
        for path in paths:
            assert all(5 < p.x < 295 and 5 < p.y < 295 for p in path.elements)
        radii=[math.hypot(p.x-150,p.y-150) for p in paths[0].elements]
        spreads.append(max(radii)-min(radii))
    assert spreads[1] > 2*spreads[0]
    assert spreads[2] > spreads[1]
