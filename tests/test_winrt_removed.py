"""Retired speech backend must not return through config, probes or caches."""
import importlib
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from jarvis.config import Config
from jarvis.tts import Speaker
from jarvis.tts_engines import factory
from jarvis import voices


def test_legacy_config_is_normalized_without_rewriting_file(tmp_path, caplog):
    path = tmp_path / 'config.json'
    original = json.dumps({'tts_backend':'winrt', 'tts_voice':'Pavel', 'voice_rate':1.2})
    path.write_text(original)
    config = Config(path)
    assert config.get('tts_backend') == 'auto'
    assert config.get('tts_voice') == 'Pavel' and config.get('voice_rate') == 1.2
    assert path.read_text() == original
    assert 'WinRT speech removed' in caplog.text


def test_direct_legacy_factory_call_uses_auto_without_trying_winrt(monkeypatch):
    calls = []
    engine = NS(name='piper')
    def create(name, *args):
        calls.append(name)
        return engine if name == 'piper' else None
    monkeypatch.setattr(factory, '_try_create', create)
    assert factory.get_engine('winrt', 'Pavel') is engine
    assert calls == ['silero', 'piper']


def test_old_cache_entries_cannot_revive_removed_engine(monkeypatch):
    monkeypatch.setitem(factory._ENGINE_CACHE, ('winrt', 'Pavel'), object())
    monkeypatch.setitem(factory._PROBE_CACHE, 'winrt', object())
    assert factory._try_create('winrt', 'Pavel', 'medium', 1.15) is None
    assert factory._try_create('winrt', '', 'medium', 1.15) is None
    assert factory._probe_engine('winrt') is None


def test_auto_and_list_have_no_winrt_even_if_all_engines_available(monkeypatch):
    calls = []
    def create(name, *args):
        calls.append(name)
        return NS(name=name)
    monkeypatch.setattr(factory, '_try_create', create)
    assert factory.list_engines() == ['silero', 'piper', 'sapi']
    assert factory.get_engine('auto', 'ruslan').name == 'silero'
    assert 'winrt' not in calls


def test_speaker_legacy_selection_uses_auto_and_leaves_input_config_intact(monkeypatch):
    monkeypatch.setattr(Speaker, '_init_engine', lambda self:None)
    config = {'tts_backend':'winrt', 'tts_voice':'Pavel'}
    obj = Speaker(config)
    assert obj._backend == 'auto' and config['tts_backend'] == 'winrt'
    obj._engine = NS(name='piper')
    assert obj.switch_backend('winrt') is True
    assert obj._backend == 'auto'


def test_old_voice_cache_does_not_offer_winrt(monkeypatch):
    monkeypatch.setattr(voices, '_VOICES_CACHE', {'winrt':{'Pavel':'retired'}})
    monkeypatch.setattr(voices, '_try_create', lambda *args:NS(voices={'ruslan':'Руслан'}))
    assert voices.current_backend({'tts_backend':'winrt'}) == 'auto'
    assert voices._voices_for_backend('winrt') == {'ruslan':'Руслан'}
    assert 'winrt' not in voices._BACKEND_HINT and 'winrt' not in voices._FALLBACK_VOICES


def test_removed_module_is_an_explicit_overlay_marker():
    with pytest.raises(ImportError, match='WinRT TTS removed'):
        importlib.import_module('jarvis.tts_engines.winrt')


def test_gui_and_runtime_dependencies_do_not_offer_speech_winrt():
    from jarvis.gui import TTS_BACKENDS
    assert TTS_BACKENDS == ['auto', 'piper', 'silero', 'sapi']
    requirements = (Path(__file__).parents[1] / 'requirements.txt').read_text()
    assert 'winrt-Windows.Media.SpeechSynthesis' not in requirements
    assert 'winrt-Windows.Media.Control' in requirements  # media controls are not TTS


def test_offline_corpus_does_not_import_retired_tts_engine():
    from tests.audio import corpus
    source = Path(corpus.__file__).read_text()
    assert 'jarvis.tts_engines.winrt' not in source
    assert 'class LocalSynth' in source
