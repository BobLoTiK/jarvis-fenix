"""Action orbit: real callbacks, continuous hover zone, keyboard and lifecycle."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import Mock, AsyncMock
import flet as ft
import pytest
from jarvis import gui as module, profile, mood
from jarvis.config import Config

@pytest.fixture
def gui(tmp_path):
    g = module.FenixGUI(None, Config(tmp_path/'config.json'))
    g._page = NS(add=Mock(), update=Mock(), window=NS(visible=True,minimized=False))
    g._build_ui(g._page)
    g.jarvis = NS(listening_enabled=True,speaker=NS(stop=Mock()),
                  handler=NS(_pending_password=None,_pending_question=None))
    g._home.apply_state('idle')
    yield g
    g.stop();g._rail.dispose()
    profile.unsubscribe(g._on_profile_switch);mood.unsubscribe(g._on_mood_change)
    module._apply_palette('dark')


def event(value=True): return NS(data=value)


def attach(ring):
    ring._mounted = True
    ring._host = NS(update=Mock(),run_task=lambda f,*a:asyncio.create_task(f(*a)))
    return ring._host


def test_closed_orbit_keeps_same_footprint_and_hidden_actions_out_of_tab_order(gui):
    r=gui._home.actions
    assert r.width == r.height == r.aura.width == r.aura.height == 300
    assert not r.opened
    assert len(r.buttons)==3
    assert all(b.disabled for b in r.buttons.values())
    assert all(s.opacity==0 and s.ignore_interactions for s in r.slots.values())
    assert r.center.disabled is False
    assert r.aura.ignore_interactions is True


@pytest.mark.parametrize('value',[True,'true','True'])
def test_bird_hover_opens_but_outer_zone_alone_does_not(gui,value):
    r=gui._home.actions
    r._zone_hover(event(value))
    assert not r.opened
    r._center_hover(event(value))
    assert r.opened and r.guide.opacity==1
    assert not r.buttons['dialog'].disabled and not r.buttons['mic'].disabled
    assert r.buttons['stop'].disabled
    assert all(s.opacity==1 and s.scale==1 and not s.ignore_interactions for s in r.slots.values())


def test_click_after_hover_does_not_accidentally_close(gui):
    r=gui._home.actions;r._center_hover(event());r._toggle()
    assert r.opened


def test_shared_zone_survives_pointer_trip_to_buttons_then_closes(gui):
    async def run():
        r=gui._home.actions;attach(r)
        r._zone_hover(event());r._center_hover(event())
        r._center_hover(event(False));r._action_hover('mic',event())
        await asyncio.sleep(.27)
        assert r.opened and r.hint.value=='Выключить микрофон'
        r._zone_hover(event(False))
        await asyncio.sleep(.1)
        assert r.opened
        r._zone_hover(event())
        await asyncio.sleep(.2)
        assert r.opened
        r._zone_hover(event(False));await asyncio.sleep(.27)
        assert not r.opened
    asyncio.run(run())


def test_keyboard_tab_focus_bridge_and_escape_no_reopening(gui):
    async def run():
        r=gui._home.actions;attach(r);r.center.focus=AsyncMock(side_effect=lambda:r._focus('center'))
        await gui._on_home_key(NS(key='Tab'))
        r._focus('center');assert r.opened
        r._blur('center');r._focus('dialog')
        await asyncio.sleep(.27);assert r.opened
        await gui._on_home_key(NS(key='Escape'))
        assert not r.opened
        r.center.focus.assert_awaited_once()
        await gui._on_home_key(NS(key='Tab'));r._focus('dialog')
        assert r.opened
        r._blur('dialog');await asyncio.sleep(.27)
        assert not r.opened
    asyncio.run(run())


def test_dialog_uses_existing_navigation_and_never_sends_message(gui):
    r=gui._home.actions;r.set_open(True)
    gui._run_command=Mock()
    r._act('dialog')
    assert gui._rail.selected_index==0 and gui._content_area.content is gui._tabs[0]
    assert not r.opened
    gui._run_command.assert_not_called()


def test_mic_toggles_real_core_and_syncs_chat_button_and_home(gui):
    r=gui._home.actions;r.set_open(True)
    r._act('mic')
    assert not gui.jarvis.listening_enabled
    assert gui._mic_btn.icon==ft.Icons.MIC_OFF
    assert r.buttons['mic'].icon==ft.Icons.MIC_OFF_OUTLINED
    assert r.semantics['mic'].label=='Включить микрофон'
    assert gui._home.status.value=='Микрофон на паузе'
    r._act('mic')
    assert gui.jarvis.listening_enabled and r.semantics['mic'].label=='Выключить микрофон'


def test_stop_only_stops_existing_speech_and_does_not_claim_cancellation(gui):
    r=gui._home.actions;r.set_open(True)
    r._act('stop');gui.jarvis.speaker.stop.assert_not_called()
    gui._apply_state('speaking');assert not r.buttons['stop'].disabled
    r._act('stop');gui.jarvis.speaker.stop.assert_called_once()
    assert gui._rail.selected_index==module.HOME_TAB
    gui._apply_state('idle');assert r.buttons['stop'].disabled
    r._act('stop');gui.jarvis.speaker.stop.assert_called_once()


def test_without_core_dialog_works_audio_actions_disabled(gui):
    gui.jarvis=None;r=gui._home.actions;r.set_open(True)
    assert not r.buttons['dialog'].disabled
    assert r.buttons['mic'].disabled and r.buttons['stop'].disabled
    r._act('mic');r._act('stop')
    assert gui.jarvis is None
    assert r.semantics['mic'].label=='Ядро ещё не готово'


def test_hidden_action_cannot_execute_stale_click(gui):
    r=gui._home.actions
    r._act('dialog');r._act('mic');r._act('stop')
    assert gui._rail.selected_index==module.HOME_TAB and gui.jarvis.listening_enabled
    gui.jarvis.speaker.stop.assert_not_called()


@pytest.mark.parametrize('reason',['config','os','rail'])
def test_reduced_motion_removes_orbit_transitions(gui,reason):
    r=gui._home.actions
    if reason=='config':gui.config.set('gui_motion_enabled',False)
    elif reason=='os':r.aura._os_reduced=True
    else:gui._rail.motion_enabled=False
    r.set_open(True)
    assert all(s.animate_opacity is None and s.animate_scale is None for s in r.slots.values())
    assert all(s.opacity==1 and s.scale==1 for s in r.slots.values())


def test_dispose_cancels_delayed_close_resets_state_and_does_not_touch_aura(gui):
    async def run():
        r=gui._home.actions;host=attach(r)
        r.set_open(True);r._zone_hover(event(False));task=r._close_task
        r.dispose();await asyncio.sleep(0)
        assert task.cancelled() and r._close_task is None and not r.opened
        assert r._host is None and not r._mounted
        assert gui._home.aura.mode=='idle'
    asyncio.run(run())


def test_theme_rebuild_disposes_old_ring_and_does_not_leave_open_menu(gui):
    old=gui._home.actions;old.set_open(True)
    gui._home._theme('Светлая')
    assert gui._home.actions is not old and not old.opened
    assert not gui._home.actions.opened


def test_no_background_updates_for_unchanged_state_and_only_local_orbit_update(gui):
    r=gui._home.actions;r._mounted=True;r._host=NS(update=Mock())
    for _ in range(10):r.sync_state()
    r._host.update.assert_not_called()
    r.set_open(True)
    assert all(c.args==(r,) for c in r._host.update.call_args_list)


def test_custom_captions_do_not_duplicate_native_tooltips_and_hidden_semantics(gui):
    r=gui._home.actions
    assert all(b.tooltip is None for b in r.buttons.values())
    assert all(s.hidden for s in r.semantics.values())
    r.set_open(True)
    assert all(not s.hidden for s in r.semantics.values())
    assert r.semantics['dialog'].label=='Открыть диалог'
    assert r.semantics['mic'].toggled is True
    r.set_open(False)
    assert all(s.hidden for s in r.semantics.values())
