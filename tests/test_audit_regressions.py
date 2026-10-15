"""Regression tests for the six audited bugs and related edge cases.
No real system commands, user data, or timers are used.
"""
from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock, patch
import time
import ast
import json
import logging
import queue
import threading
from pathlib import Path

import pytest

from jarvis import timers, tasks, actions, memory, mood
from jarvis.intents.handler import IntentHandler
from jarvis.intents.context import Ctx
from jarvis.intents.password import hash_password
from jarvis.intents.stages.password import PasswordStage
from jarvis.intents.stages.fast import FastHandlersStage
from jarvis.intents.fast.custom import load_custom, match_custom
from jarvis.intents.fast.timers import timers_fast
from jarvis.text_utils import normalize


def handler(password='1234'):
    h = IntentHandler.__new__(IntentHandler)
    h.config = {'danger_password': hash_password(password)}
    h.mode = 'combo'
    h._pending_password = None
    h._pipeline = [PasswordStage(), FastHandlersStage()]
    h._fast_handlers_cache = []
    h._recent_phrases = deque(maxlen=10)
    h.dialog = deque(maxlen=100)
    return h


def test_system_pack_shutdown_requires_password():
    h = handler()
    h.custom = load_custom({'active_packs': ['system']})
    h._fast_handlers_cache = [('custom', lambda cmd: match_custom(h, cmd))]
    with patch.object(actions, 'run_spec') as run, patch.object(memory, 'append'), patch.object(mood, 'apply_from_text'):
        h.handle('выключи компьютер')
    run.assert_not_called()
    assert h._pending_password is not None


def test_password_not_written_to_dialog():
    h = handler()
    h._ask_password({'action': 'clear_tasks'})
    with patch('jarvis.intents.execute.execute_intent', return_value='Готово.'), patch.object(memory, 'append') as append, patch.object(mood, 'apply_from_text'):
        h.handle('пароль 1234')
    assert not any('1234' in str(call) for call in append.call_args_list)
    assert not any('1234' in msg['content'] for msg in h.dialog)


def test_password_retains_case_and_punctuation():
    h = handler('AbC-42!')
    h._ask_password({'action': 'clear_tasks'})
    with patch('jarvis.intents.execute.execute_intent', return_value='Готово.') as execute, patch.object(memory, 'append'), patch.object(mood, 'apply_from_text'):
        reply = h.handle('пароль AbC-42!')
    execute.assert_called_once()
    assert reply.text == 'Готово.'


def test_absolute_reminder_survives_command_normalization():
    h = handler()
    with patch.object(timers, 'add', return_value={}) as add:
        reply = timers_fast(h, normalize('напомни в 18:30 позвонить маме'))
    add.assert_called_once()
    assert '18:30' in reply


def test_half_hour_does_not_eat_reminder_text():
    assert timers._parse_duration('напомни через полчаса выпить чай') == 1800
    assert timers._extract_reminder_text('напомни через полчаса выпить чай') == 'выпить чай'


def test_task_save_failure_must_not_report_success(tmp_path):
    with patch.object(tasks, '_tasks_file', return_value=tmp_path/'tasks.json'), patch.object(tasks.os, 'replace', side_effect=PermissionError('simulated locked file')):
        try:
            result = tasks.add('купить хлеб')
        except OSError:
            return
    assert result is None or result is False, 'Task returned as added although persistence failed'


@pytest.mark.parametrize('phrase', ['выключи компьютер', 'перезагрузи компьютер'])
def test_system_pack_runs_only_after_correct_password(phrase):
    h = handler()
    h.custom = load_custom({'active_packs': ['system']})
    h._fast_handlers_cache = [('custom', lambda cmd: match_custom(h, cmd))]
    with patch.object(actions, 'run_spec', return_value=True) as run, patch.object(memory, 'append'), patch.object(mood, 'apply_from_text'):
        h.handle(phrase)
        run.assert_not_called()
        h.handle('пароль 1234')
        run.assert_called_once()
    assert h._pending_password is None


def test_custom_macro_checks_all_steps_before_execution():
    h = handler()
    h.custom = [(['рабочий сценарий'], [{'action':'screenshot'}, {'action':'clear_tasks'}], 'Готово.')]
    h._fast_handlers_cache = [('custom', lambda cmd: match_custom(h, cmd))]
    with patch('jarvis.intents.execute.execute_steps', return_value='Готово.') as execute, patch.object(memory, 'append'), patch.object(mood, 'apply_from_text'):
        h.handle('рабочий сценарий')
        execute.assert_not_called()
        h.handle('пароль 1234')
        execute.assert_called_once()


@pytest.mark.parametrize('answer', ['пароль 9999', 'стоп', 'пароль 1234'])
def test_sensitive_input_skips_logs_corrections_and_history(answer, caplog):
    h = handler()
    h._ask_password({'action': 'clear_tasks'})
    with caplog.at_level(logging.DEBUG), patch('jarvis.intents.execute.execute_intent', return_value='Готово.'), patch.object(h, '_handle_single') as pipeline, patch.object(memory, 'append') as append:
        h.handle(answer)
    pipeline.assert_not_called()
    append.assert_not_called()
    assert not h.dialog and not h._recent_phrases
    assert h._raw_cmd == ''
    assert answer not in caplog.text


def test_expired_password_is_not_executed_or_recorded():
    h = handler()
    h._ask_password({'action': 'clear_tasks'})
    h._pending_password['expires_at'] = time.time() - 1
    with patch('jarvis.intents.execute.execute_intent') as execute, patch.object(memory, 'append') as append:
        result = h.handle('пароль 1234')
    execute.assert_not_called()
    append.assert_not_called()
    assert 'истекло' in result.text
    assert h._pending_password is None


@pytest.mark.parametrize('password', ['AbC-42!', 'ёжик_ЁЖ', 'парольник', '1234'])
def test_raw_password_values(password):
    h = handler(password)
    h._ask_password({'action': 'clear_tasks'})
    with patch('jarvis.intents.execute.execute_intent', return_value='Готово.') as execute:
        result = h.handle('Пароль ' + password)
    execute.assert_called_once()
    assert result.text == 'Готово.'


@pytest.mark.parametrize('time_text', ['18:30', '18.30', '18 30'])
def test_reminder_time_formats_end_to_end(time_text):
    h = handler()
    h._fast_handlers_cache = [('timers', lambda cmd: timers_fast(h, cmd))]
    with patch.object(timers, 'add', return_value={}) as add, patch.object(memory, 'append'), patch.object(mood, 'apply_from_text'):
        reply = h.handle(f'напомни в {time_text} позвонить маме')
    add.assert_called_once()
    assert add.call_args.args[0] == 'позвонить маме'
    assert '18:30' in reply.text


@pytest.mark.parametrize('phrase,seconds,text', [
    ('напомни через полчаса выпить чай', 1800, 'выпить чай'),
    ('напомни через пол часа выпить чай', 1800, 'выпить чай'),
    ('напомни через час позвонить маме', 3600, 'позвонить маме'),
    ('напомни через минуту проверить чай', 60, 'проверить чай'),
    ('напомни через 10 минут выпить чай', 600, 'выпить чай'),
    ('напомни через пять минут выпить чай', 300, 'выпить чай'),
    ('напомни через 5 выпить чай', 300, 'выпить чай'),
    ('таймер на полчаса', 1800, ''),
    ('таймер на 5 минут', 300, ''),
    ('напомни через 5 минут проверить таймер через полчаса', 300, 'проверить таймер через полчаса'),
])
def test_duration_and_reminder_text(phrase, seconds, text):
    assert timers._parse_duration(phrase) == seconds
    assert timers._extract_reminder_text(phrase) == text


def test_task_command_reports_persistence_error(tmp_path):
    with patch.object(tasks, '_tasks_file', return_value=tmp_path/'tasks.json'), patch.object(tasks.os, 'replace', side_effect=PermissionError('locked')):
        reply = tasks.handle_task_command('добавь в список купить хлеб')
    assert 'Не удалось сохранить' in reply
    assert not (tmp_path/'tasks.json').exists()


def test_task_intent_reports_persistence_error(tmp_path):
    from jarvis.intents.execute import execute_intent
    with patch.object(tasks, '_tasks_file', return_value=tmp_path/'tasks.json'), patch.object(tasks.os, 'replace', side_effect=PermissionError('locked')):
        reply = execute_intent(handler(), {'action':'add_task', 'text':'купить хлеб'})
    assert 'Не удалось выполнить' in reply


def source_method(filename, classname, method, namespace):
    """Run actual method source without importing Windows/audio/GUI dependencies.
    This is a component test, not a substitute for desktop integration tests.
    """
    source = Path(__file__).resolve().parents[1] / filename
    tree = ast.parse(source.read_text(encoding='utf-8'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == classname)
    fn = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == method)
    module = ast.Module(body=[fn], type_ignores=[])
    exec(compile(module, str(source), 'exec'), namespace)
    return namespace[method]


def test_voice_input_redacts_gui_and_skips_observer():
    from jarvis.reply import Reply
    process = source_method('jarvis/main.py', 'Jarvis', '_process', {
        'time':time, 'normalize':normalize, 'log':logging.getLogger('audit.voice'), 'Reply':Reply,
    })
    h = handler('AbC-42!')
    h._ask_password({'action':'clear_tasks'})
    app = SimpleNamespace(handler=h, _awaiting_until=0, _is_wake=lambda word:word=='феникс', config={'prosody_enabled':False}, whisper=None, gui=Mock(), observer=Mock(), cmd_lock=threading.Lock(), speaker=Mock(), say=Mock(return_value=False))
    with patch('jarvis.intents.execute.execute_intent', return_value='Готово.') as execute:
        process(app, 'феникс пароль AbC-42!', b'')
    execute.assert_called_once()
    app.gui.add_message.assert_any_call('user','[Ввод пароля скрыт]')
    assert 'AbC-42!' not in str(app.gui.mock_calls)
    assert 'AbC-42!' not in str(app.observer.mock_calls)
    assert all(call.args[0] != 'user' for call in app.observer.observe.call_args_list)


def test_gui_input_redacts_history(tmp_path):
    # Exercise the imported GUI method, not a copy compiled from AST.
    pytest.importorskip("flet")
    from jarvis.gui import FenixGUI
    from jarvis.config import Config
    from jarvis import profile, mood
    h = handler('AbC-42!')
    h._ask_password({'action':'clear_tasks'})
    app = FenixGUI(SimpleNamespace(handler=h, speaker=Mock(), cmd_lock=threading.Lock(), say=Mock()),
                   Config(tmp_path / "gui-config.json"))
    app.add_message = Mock()
    try:
        with patch('jarvis.intents.execute.execute_intent', return_value='Готово.') as execute:
            assert app._run_command('пароль AbC-42!')
            app._command_thread.join(timeout=5)
            assert not app._command_thread.is_alive()
        execute.assert_called_once()
        app.add_message.assert_any_call('user','[Ввод пароля скрыт]')
        assert 'AbC-42!' not in str(app.add_message.mock_calls)
    finally:
        profile.unsubscribe(app._on_profile_switch)
        mood.unsubscribe(app._on_mood_change)


def test_stt_does_not_retain_sensitive_recognition(caplog):
    method = source_method('jarvis/stt.py','Listener','phrases', {
        'sd':SimpleNamespace(RawInputStream=Mock(return_value=Mock())),
        'queue':queue, 'json':json, 'log':logging.getLogger('audit.stt'),
    })
    audio = queue.Queue();audio.put(b'\0\0')
    listener = SimpleNamespace(_sample_rate=16000,_block_size=2048,_device=None,_callback=Mock(),device_name='fake',_audio=audio,_utt_buf=[],_utt_len=0,_rec=Mock(),utterances=0,recent_phrases=deque(),sensitive_input=lambda:True)
    # phrases delegates endpoint parsing to the shared live/file consumer.
    listener._file_mode = False
    consume = source_method('jarvis/stt.py', 'Listener', '_consume_audio', {
        'json': json, 'log': logging.getLogger('audit.stt'),
    })
    listener._consume_audio = lambda data: consume(listener, data)
    listener._rec.AcceptWaveform.return_value=True
    listener._rec.Result.return_value=json.dumps({'text':'пароль 1234'})
    gen=method(listener,threading.Event())
    with caplog.at_level(logging.INFO):
        assert next(gen)[0]=='пароль 1234'
        gen.close()
    assert not listener.recent_phrases
    assert '1234' not in caplog.text
