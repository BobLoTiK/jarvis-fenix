"""Actual dispatch function isolated from Windows imports; no apps launched."""
import ast
import logging
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest

ROOT=Path(__file__).resolve().parents[1]

def dispatch(monkeypatch,ok=True,kind='app'):
    app=NS(title='Блокнот',resolve_open=lambda:('cmd','notepad.exe'))
    monkeypatch.setitem(sys.modules,'jarvis.apps',NS(find_app=lambda *a:app if kind!='game' else None))
    monkeypatch.setitem(sys.modules,'jarvis.installed',NS(find_installed=lambda *a:None))
    monkeypatch.setitem(sys.modules,'jarvis.steam',NS(find_game=lambda *a:('Игра','123') if kind=='game' else None))
    monkeypatch.setitem(sys.modules,'jarvis.intents.sites',NS(get_sites=lambda:{}))
    actions=NS(run_spec=Mock(return_value=ok),focus_browser=lambda *a:False)
    env=dict(actions=actions,files=NS(resolve_folder=lambda *a,**k:None),_BROWSER_PROCS={'хром':'chrome.exe'},BROWSER_WORDS=set())
    tree=ast.parse((ROOT/'jarvis/intents/execute.py').read_text(encoding="utf-8"))
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_do_open')
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'execute.py','exec'),env)
    return env['_do_open'],actions

@pytest.mark.parametrize('target,kind',[('блокнот','app'),('хром','app'),('игра','game')])
@pytest.mark.parametrize('ok',[True,False])
def test_run_spec_result_controls_confirmation(monkeypatch,target,kind,ok):
    fn,actions=dispatch(monkeypatch,ok,kind)
    response=fn(NS(apps={},steam_games={},installed={}),target)
    assert ('Не удалось' in response) is (not ok)
    if not ok: assert not response.startswith(('Открываю','Запускаю'))
    actions.run_spec.assert_called_once()


def site_fn(monkeypatch, sites=None):
    """_open_site отдельно от Windows-импортов: только действия-открывашки."""
    monkeypatch.setitem(sys.modules, 'jarvis.intents.sites',
                        NS(get_sites=lambda: sites or {}))
    actions = NS(spoken_domain=lambda n: None, guess_site=lambda n: None,
                 open_url=Mock())
    env = dict(actions=actions)
    tree = ast.parse((ROOT / 'jarvis/intents/execute.py').read_text(encoding='utf-8'))
    fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    exec(compile(ast.Module(body=[fns['_open_site']], type_ignores=[]),
                 'execute.py', 'exec'), env)
    return env['_open_site'], actions


def test_unknown_app_target_is_not_reported_as_a_site(monkeypatch):
    """«Открыть приложение» с неизвестной целью не врёт про сайт."""
    fn, _ = site_fn(monkeypatch)
    text = fn('нотепад', from_app=True)
    assert 'ни среди приложений, ни как сайт' in text
    assert not text.startswith('Сайт')


def test_unknown_site_keeps_site_wording(monkeypatch):
    fn, _ = site_fn(monkeypatch)
    text = fn('нотепад')
    assert text.startswith('Сайт нотепад')


def test_known_site_still_opens(monkeypatch):
    fn, actions = site_fn(monkeypatch, {'ютуб': ('YouTube', 'https://youtube.com')})
    text = fn('ютуб', from_app=True)
    assert text == 'Открываю YouTube.'
    actions.open_url.assert_called_once_with('https://youtube.com')
