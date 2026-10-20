"""Execute real startup functions with stub peripherals, no models/mic/Windows.

AST isolates main.py's actual functions from unrelated native module imports.
The main() harness stops at core construction, after Vosk and GUI are created;
this is not a live Flet-client, Windows DLL-loader or audio acceptance test.
"""
import ast
import builtins
import logging
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def functions(importer, **extra):
    path = ROOT / 'jarvis/main.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    names = {'_preload_whisper_backend', 'main'}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in nodes} == names
    env = {'__builtins__': {**vars(builtins), '__import__': importer},
           'log': logging.getLogger('test.optional_whisper'), **extra}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), env)
    return env


def dll_error(kind):
    return {'import': ImportError('DLL load failed'),
            'missing': FileNotFoundError('ctranslate2.dll or one of its dependencies'),
            'win126': OSError(126, 'The specified module could not be found'),
            'win193': OSError(193, 'Not a valid Win32 application')}[kind]


@pytest.mark.parametrize('bad_module', ['faster_whisper', 'ctranslate2'])
@pytest.mark.parametrize('kind', ['import', 'missing', 'win126', 'win193'])
def test_optional_import_failure_returns_false_with_original_traceback(bad_module, kind, caplog):
    calls = []
    failure = dll_error(kind)
    def importer(name, *args, **kwargs):
        calls.append(name)
        if name == bad_module:
            raise failure
        return NS()
    with caplog.at_level(logging.WARNING, logger='test.optional_whisper'):
        assert functions(importer)['_preload_whisper_backend']() is False
    assert calls == (['faster_whisper'] if bad_module == 'faster_whisper'
                     else ['faster_whisper', 'ctranslate2'])
    record, = caplog.records
    assert record.exc_info[1] is failure
    assert bad_module in record.getMessage() and 'Vosk' in record.getMessage()


def test_success_preserves_import_order():
    calls = []
    assert functions(lambda name: calls.append(name))['_preload_whisper_backend']() is True
    assert calls == ['faster_whisper', 'ctranslate2']


@pytest.mark.parametrize('error', [RuntimeError('unrelated bug'), KeyboardInterrupt(), SystemExit(4)])
def test_unrelated_errors_are_not_swallowed(error):
    def importer(name):
        raise error
    with pytest.raises(type(error)) as caught:
        functions(importer)['_preload_whisper_backend']()
    assert caught.value is error


class CoreReached(BaseException):
    pass


@pytest.mark.parametrize('bad_module', [None, 'faster_whisper', 'ctranslate2'])
@pytest.mark.parametrize('kind', ['import', 'missing', 'win126'])
@pytest.mark.parametrize('use_whisper', [True, False])
def test_real_main_continues_to_vosk_gui_and_core_without_retry(
        tmp_path, bad_module, kind, use_whisper):
    calls = []
    config = {'use_whisper': use_whisper, 'use_llm': False,
              'sample_rate': 16000, 'gui_enabled': True}
    before = dict(config)
    transcriber = Mock()
    modules = {
        'profile': NS(init=Mock()),
        'vectormem': NS(set_config=Mock(), warmup_async=Mock()),
        'weather': NS(set_config=Mock()),
    }
    def importer(name, globals=None, locals=None, fromlist=(), level=0):
        calls.append(name)
        if name in ('faster_whisper', 'ctranslate2'):
            if name == bad_module:
                raise dll_error(kind)
            return NS()
        if name == 'jarvis':
            assert all(k in modules for k in fromlist)
            return NS(**modules)
        if name == 'jarvis.stt':
            assert bad_module is None, 'Failed backend must not be retried'
            return NS(WhisperTranscriber=transcriber)
        raise AssertionError(f'Unexpected import {name}')
    model_dir = tmp_path / 'vosk-model'
    vosk = Mock()
    gui = Mock()
    speaker = Mock()
    core = Mock(side_effect=CoreReached)
    env = functions(
        importer, setup_logging=Mock(), APP_NAME='Феникс', __version__='test',
        _single_instance=lambda: True, BASE_DIR=tmp_path, load_config=lambda _: config,
        ensure_model=Mock(return_value=model_dir), Speaker=speaker, Listener=vosk,
        FenixGUI=gui, IntentHandler=Mock(), build_apps=Mock(return_value={}), Jarvis=core,
    )
    with pytest.raises(CoreReached):
        env['main']()
    vosk.assert_called_once_with(model_dir, 16000, None, config=config)
    gui.assert_called_once_with(None, config)
    speaker.assert_called_once_with(config, lazy=True)
    enabled = bad_module is None and use_whisper
    if enabled:
        transcriber.assert_called_once_with('auto', 'auto', lazy=True, config=config)
        transcriber.return_value.preload_async.assert_called_once_with()
    else:
        transcriber.assert_not_called()
    assert core.call_args.args[5] is (transcriber.return_value if enabled else None)
    assert core.call_args.kwargs['gui'] is gui.return_value
    native = [n for n in calls if n in ('faster_whisper', 'ctranslate2')]
    assert native == (['faster_whisper'] if bad_module == 'faster_whisper'
                      else ['faster_whisper', 'ctranslate2'])
    assert config == before  # fallback is per-process; no permanent settings edit
