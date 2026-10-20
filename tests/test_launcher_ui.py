"""Bootstrap presentation tests; no Tk display, installation, downloads or Windows needed."""
import ast
import logging
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import launcher
from launcher_ui import PreparationWindow, Session, StageLogHandler

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture(autouse=True)
def reset_session(monkeypatch):
    monkeypatch.setattr(launcher,'_PREPARATION',None)

@pytest.mark.parametrize('answer',[True,False])
def test_question_queue_round_trip(answer):
    session=Session(); result=[]
    worker=threading.Thread(target=lambda:result.append(session.ask('question','title')))
    worker.start()
    kind,data=session.events.get(timeout=2)
    assert kind=='question'
    data['question'].resolve(answer)
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert result==[answer]

@pytest.mark.parametrize('answer,expected',[(True,launcher.IDOK),(False,launcher.IDCANCEL)])
def test_inline_consent_preserves_result(monkeypatch,answer,expected):
    session=Session();session.ask=Mock(return_value=answer)
    monkeypatch.setattr(launcher,'_PREPARATION',session)
    assert launcher.msg_box('prepare','title',launcher.MB_OKCANCEL|launcher.MB_ICONQUESTION)==expected
    assert session.declined is (not answer)

@pytest.mark.parametrize('answer,expected',[(True,launcher.IDYES),(False,launcher.IDNO)])
def test_inline_optional_question_preserves_result(monkeypatch,answer,expected):
    session=Session();session.ask=Mock(return_value=answer)
    monkeypatch.setattr(launcher,'_PREPARATION',session)
    assert launcher.msg_box('Ollama','title',launcher.MB_YESNO|launcher.MB_ICONQUESTION)==expected
    assert not session.declined


def test_information_never_waits_for_acknowledgement(monkeypatch):
    session=Session();session.ask=Mock(side_effect=AssertionError('unexpected modal'))
    monkeypatch.setattr(launcher,'_PREPARATION',session)
    launcher.info('Создаю окружение','Подготовка')
    kind,data=session.events.get_nowait()
    assert kind=='stage' and data['show']
    launcher.error('disk failure')
    assert session.last_error=='disk failure'
    launcher.warn('warning')
    assert session.events.get_nowait()[0]=='detail'


def test_already_running_is_inline_notice(monkeypatch):
    session=Session();monkeypatch.setattr(launcher,'_PREPARATION',session)
    launcher.info('Феникс уже запущен. Проверь трей.')
    assert 'уже запущен' in session.notice


def test_real_byte_progress_and_unknown_length(monkeypatch):
    session=Session();monkeypatch.setattr(launcher,'_PREPARATION',session)
    launcher._download_progress(0,1024,4096)
    _,data=session.events.get_nowait();assert data['value']==0
    session._last_progress=0
    launcher._download_progress(2,1024,4096)
    _,data=session.events.get_nowait();assert data['value']==.5
    launcher._download_progress(9,1024,4096)
    _,data=session.events.get_nowait();assert data['value']==1
    session._last_progress=0
    launcher._download_progress(2,1024,-1)
    _,data=session.events.get_nowait();assert data['value'] is None


def test_pip_is_indeterminate_not_a_fake_percentage():
    session=Session();handler=StageLogHandler(session)
    handler.emit(logging.LogRecord('launcher',logging.INFO,'',1,'pip install -r requirements.txt',(),None))
    kind,data=session.events.get_nowait()
    assert kind=='stage'
    assert data['title']=='Устанавливаем зависимости'
    assert 'неизвестен' in data['detail']


@pytest.fixture
def window(tmp_path):
    w=PreparationWindow(tmp_path,tmp_path/'launcher.log')
    for name in ('primary_button','cancel_button','stage_label','progress_label','root'):
        setattr(w,name,Mock())
    w._show=Mock();w._detail=Mock()
    return w


def test_busy_close_does_not_stop_active_installation(window):
    window.state='busy';window.session=Session()
    window._secondary()
    window.root.destroy.assert_not_called()
    assert 'дождись' in window._detail.call_args.args[0].lower()


def test_question_close_declines_without_process_operations(window):
    from launcher_ui import Question
    window.question=Question('q','t','yes','no');q=window.question
    window.state='question'
    window._secondary()
    assert q.ready.is_set() and not q.answer
    assert window.state=='busy'


def test_worker_error_becomes_retry_in_same_window(window):
    window.job=Mock(side_effect=RuntimeError('test failure'))
    window._start();window.worker.join(timeout=2)
    kind,data=window.session.events.get(timeout=2)
    assert kind=='finished' and data['status']=='failed'
    window._event(kind,data)
    assert window.state=='failed'
    window.root.destroy.assert_not_called()
    window.primary_button.configure.assert_called_with(text='Повторить',state='normal')


def test_decline_finishes_without_error_or_retry(window):
    window.job=lambda session:setattr(session,'declined',True)
    window._start();window.worker.join(timeout=2)
    kind,data=window.session.events.get(timeout=2)
    assert data['status']=='ok'
    assert window._event(kind,data) is False
    window.root.destroy.assert_called_once()


def test_logged_failure_is_not_silently_treated_as_success(window):
    window.job=lambda session:setattr(session,'last_error','missing requirements')
    window._start();window.worker.join(timeout=2)
    _,data=window.session.events.get(timeout=2)
    assert data['status']=='failed' and 'missing requirements' in data['text']


def test_completed_launch_closes_preparation_window(window):
    assert window._event('finished',{'status':'ok'}) is False
    window.root.destroy.assert_called_once()


def test_ui_module_has_no_installation_or_process_engine():
    source=(ROOT/'launcher_ui.py').read_text()
    tree=ast.parse(source)
    imports=[n for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom))]
    assert not any('subprocess' in ast.dump(n) or 'urllib' in ast.dump(n) for n in imports)
    assert 'def request_cancel' not in source
    assert 'import tkinter' in source


def test_builder_reports_missing_tk_without_building(monkeypatch):
    from scripts import build_exe
    monkeypatch.setitem(sys.modules,'tkinter',None)
    with pytest.raises(RuntimeError,match='Tcl/Tk'):
        build_exe.check_bootstrap_ui()


def test_builder_checks_tcl_interpreter(monkeypatch):
    from scripts import build_exe
    interp=Mock();monkeypatch.setitem(sys.modules,'tkinter',SimpleNamespace(Tcl=lambda:interp))
    build_exe.check_bootstrap_ui()
    interp.eval.assert_called_once_with('info patchlevel')


def test_source_payload_requires_bootstrap_ui():
    from scripts.release_payload import collect_payload
    assert 'launcher_ui.py' in collect_payload(ROOT,include_exe=False)


def test_supported_windows_minimum_is_explicit():
    assert "MinVersion=10.0" in (ROOT/"installer.iss").read_text()


def test_retry_double_click_schedules_only_once(window):
    window.state='failed';window._start=Mock()
    window._primary();window._primary()
    window._start.assert_called_once()
    assert window.state=='retry_pending'


def test_ui_patch_preserves_210_process_commands():
    # The 2.1.0 process commands stay intact, including interactive Python install.
    # New HTTPS/signature and config-bridge subprocesses live in launcher_download.py
    # and launcher_ollama.py. Their behavioral tests are separate; this hash is NOT
    # coverage of the new bootstrap engine.
    import hashlib
    tree=ast.parse((ROOT/'launcher.py').read_text(encoding='utf-8'))
    # Python 3.13 omits empty lists by default; 3.11 includes them.
    # Normalize to the 3.11 representation, preserving the command guard.
    dump_options = {'show_empty': True} if sys.version_info >= (3, 13) else {}
    calls=sorted(ast.dump(n, **dump_options) for n in ast.walk(tree)
                 if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
                 and isinstance(n.func.value,ast.Name) and n.func.value.id=='subprocess')
    assert len(calls)==9
    assert hashlib.sha256('\n'.join(calls).encode()).hexdigest()==\
        '8bf329cc14ffd9398c08f01d6c995f04df5ff6955e9dd7be0dba02c833cdb727'
