"""Real config JSON and project atomic writer; never uses personal settings."""
import json
from pathlib import Path
import subprocess
import shutil
import venv
import filelock
import sys

import pytest
from jarvis import config_manager
from jarvis.config import DEFAULT_CONFIG
from scripts import bootstrap_ollama_config as bridge
import launcher_ollama


@pytest.fixture
def path(tmp_path):
    return tmp_path / 'config.json'


def read(path):
    return bridge.process({'operation': 'read'}, path)


def expected(path):
    return {k: v for k, v in read(path).items() if k != 'ok'}


def choose(path, model='qwen2.5:1.5b-instruct', snapshot=None):
    return bridge.process({'operation': 'select', 'model': model,
                           'expected': snapshot if snapshot is not None else expected(path)}, path)


def test_read_missing_config_uses_real_defaults_without_creating_file(path):
    data = read(path)
    assert data == {'ok': True, **{k: DEFAULT_CONFIG[k] for k in ('llm_model', 'ollama_url', 'mode')}}
    assert not path.exists()


def test_selected_model_only_is_written_and_other_fields_survive(path):
    original = {'llm_model': 'old:latest', 'ollama_url': 'http://localhost:12345',
                'mode': 'commands', 'tts_backend': 'silero', 'private': {'keep': 123}}
    path.write_text(json.dumps(original), encoding='utf-8')
    assert choose(path)['ok']
    assert json.loads(path.read_text(encoding="utf-8")) == {**original, 'llm_model': 'qwen2.5:1.5b-instruct'}


@pytest.mark.parametrize('raw', ['{broken', '[]', 'null', '{"llm_model": null}'])
def test_bad_config_is_never_replaced(path, raw):
    path.write_text(raw, encoding='utf-8')
    with pytest.raises((ValueError, TypeError)):
        read(path)
    with pytest.raises((ValueError, TypeError)):
        choose(path, snapshot={})
    assert path.read_text(encoding="utf-8") == raw


@pytest.mark.parametrize('field,value', [('llm_model','changed:latest'),
    ('ollama_url','http://127.0.0.1:12345'), ('mode','commands')])
def test_changed_settings_are_not_overwritten(path, field, value):
    snapshot = expected(path)
    path.write_text(json.dumps({field: value, 'another_key': 42}), encoding='utf-8')
    before = path.read_bytes()
    assert choose(path, snapshot=snapshot) == {'ok': False, 'error': 'conflict'}
    assert path.read_bytes() == before


def test_unrelated_changes_while_downloading_are_preserved(path):
    snapshot = expected(path)
    path.write_text('{"another_key": 42}', encoding='utf-8')
    assert choose(path, snapshot=snapshot)['ok']
    assert json.loads(path.read_text(encoding="utf-8")) == {'another_key': 42, 'llm_model': 'qwen2.5:1.5b-instruct'}


def test_write_error_is_not_success(path, monkeypatch):
    path.write_text('{"another_key": 1}', encoding='utf-8')
    monkeypatch.setattr(config_manager, 'save', lambda *a, **kw: False)
    assert choose(path) == {'ok': False, 'error': 'write'}
    assert json.loads(path.read_text(encoding="utf-8")) == {'another_key': 1}


@pytest.mark.parametrize('name', ['bad;command', 'x\nscript', 'qwen:cloud', 'x:7b-cloud', '', None])
def test_invalid_or_cloud_model_cannot_be_saved(path, name):
    with pytest.raises(ValueError):
        choose(path, model=name)
    assert not path.exists()


def test_existing_same_selection_does_not_write(path, monkeypatch):
    path.write_text('{"llm_model": "qwen2.5:1.5b-instruct"}', encoding='utf-8')
    monkeypatch.setattr(config_manager, 'save', lambda *a, **kw: pytest.fail('unneeded write'))
    assert choose(path)['ok']


def test_real_bridge_subprocess_reads_and_writes_appdata_only(tmp_path, monkeypatch):
    appdata = tmp_path / 'appdata'
    monkeypatch.setenv('APPDATA', str(appdata))
    native_run = subprocess.run
    # Keep the real process/protocol; strip only Windows console flags on Linux.
    def portable_run(*args, **kwargs):
        if sys.platform != 'win32': kwargs.pop('creationflags', None)
        return native_run(*args, **kwargs)
    monkeypatch.setattr(launcher_ollama.subprocess, 'run', portable_run)
    root = Path(__file__).resolve().parents[1]
    runtime = tmp_path / 'runtime'
    venv.EnvBuilder(with_pip=False).create(runtime)
    python = runtime / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    # Match the installed runtime: dependency inside venv, not user site ignored by -I.
    purelib = Path(subprocess.check_output(
        [str(python), '-I', '-c', 'import sysconfig; print(sysconfig.get_path("purelib"))'],
        text=True).strip())
    shutil.copytree(Path(filelock.__file__).parent, purelib / 'filelock')
    client = launcher_ollama.ConfigBridge(root, None, python_exe=python)
    snapshot = client.read()
    file = appdata / 'Phoenix/config.json'
    assert not file.exists()
    client.select('qwen2.5:3b-instruct', snapshot)
    assert json.loads(file.read_text(encoding="utf-8")) == {'llm_model': 'qwen2.5:3b-instruct'}
    assert client.read()['llm_model'] == 'qwen2.5:3b-instruct'
