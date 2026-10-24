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
