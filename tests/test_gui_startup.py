"""Startup ordering, tray failure recovery, old EXE mutex handoff; no desktop needed."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
from jarvis import gui as module, profile, mood
from jarvis.config import Config

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def gui(tmp_path):
    g = module.FenixGUI(None, Config(tmp_path/'config.json'))
    yield g
    g.stop()
    profile.unsubscribe(g._on_profile_switch)
    mood.unsubscribe(g._on_mood_change)

@pytest.mark.parametrize('method', ['run_main', '_run'])
def test_native_client_starts_hidden(gui, monkeypatch, method):
    runner = Mock()
    monkeypatch.setattr(module.ft, 'run', runner)
    getattr(gui, method)()
    assert runner.call_args.kwargs['view'] == module.ft.AppView.FLET_APP_HIDDEN

@pytest.mark.parametrize('hidden', [False, True])
def test_brand_and_first_layout_precede_show(gui, hidden):
    gui.start_hidden = hidden
    page = NS(window=NS(), add=Mock(), update=Mock(), run_task=Mock())
    def build(p):
        assert p.title == 'Феникс'
        assert p.window.visible is False
        assert p.window.icon.endswith('icon.ico')
    gui._build_ui = Mock(side_effect=build)
    gui._main(page)
    assert page.window.visible is (not hidden)
    if not hidden:
        assert page.window.minimized is False
        page.update.assert_called_once()
    assert page.run_task.call_count == 2


def test_tray_state_is_applied_by_gui_worker(gui):
    gui._page = NS(window=NS(prevent_close=False), update=Mock())
    gui.set_tray_active(True)
    assert not gui._page.window.prevent_close
    gui._queue.put(('stop', None))
    gui._running = True
    asyncio.run(gui._process_queue())
    assert gui._page.window.prevent_close


def source_function(name):
    tree = ast.parse((ROOT/'jarvis/main.py').read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    return node

@pytest.mark.parametrize('codes,expected', [([0], True), ([183,0],True), ([183]*40,False)])
def test_old_launcher_mutex_handoff(codes, expected, monkeypatch):
    import ctypes
    clock = [0.0]
    codes = iter(codes)
    k = NS(CreateMutexW=Mock(return_value=123456789123), CloseHandle=Mock(),
           GetLastError=Mock(side_effect=lambda: next(codes)))
    monkeypatch.setattr(ctypes, 'windll', NS(kernel32=k), raising=False)
    env = {'_MUTEX_HANDLE':None, 'time':NS(monotonic=lambda:clock[0],
                   sleep=lambda dt:clock.__setitem__(0,clock[0]+dt))}
    exec(compile(ast.Module(body=[source_function('_single_instance')],type_ignores=[]),'<test>','exec'),env)
    assert env['_single_instance']() is expected
    if expected:
        assert env['_MUTEX_HANDLE'] == 123456789123
    else:
        assert env['_MUTEX_HANDLE'] is None
    assert k.CreateMutexW.restype == ctypes.wintypes.HANDLE


def tray_callbacks(gui):
    main = source_function('main')
    nodes = [n for n in main.body if isinstance(n,ast.FunctionDef) and n.name in ('_tray_failed','_apply_tray')]
    import threading
    env = dict(tray_holder={'icon':None}, tray_lock=threading.RLock(),
               jarvis=NS(stop_event=threading.Event()), gui=gui, log=Mock())
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'<tray-callbacks>','exec'),env)
    return env


def test_tray_failure_before_page_restores_startup_intent(gui):
    gui.start_hidden = True
    env = tray_callbacks(gui)
    icon = object(); env['tray_holder']['icon'] = icon
    env['_tray_failed'](icon)
    assert not gui.start_hidden and not gui.tray_active
    assert gui._queue.get_nowait() == ('show_window',None)


def test_stale_or_shutdown_tray_callback_does_not_show_window(gui):
    env = tray_callbacks(gui)
    env['tray_holder']['icon'] = object()
    env['_tray_failed'](object())
    assert gui._queue.empty()
    env['jarvis'].stop_event.set()
    env['_tray_failed'](env['tray_holder']['icon'])
    assert gui._queue.empty()
