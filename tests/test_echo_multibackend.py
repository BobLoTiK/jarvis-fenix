"""Diagnostic-only PCM support; normal production backend scope stays unchanged."""
import io
import json
import queue
import sys
import threading
import wave
from types import SimpleNamespace as NS
from unittest.mock import Mock

import numpy as np
import pytest

from jarvis import audio_output
from jarvis.echo import EchoPath
from jarvis.echo_trace import EchoTrace
from jarvis.tts import Speaker
from tests.test_echo import Processor, PCM
from tests.test_echo_trace import read_trace
from tests.test_nonverbal import wav


def speaker(engine, path):
    obj = Speaker.__new__(Speaker)
    obj._engine_name = engine
    obj._echo_path = path
    obj._nonverbal = None
    obj._token_lock = threading.Lock()
    obj.voice = 'test-voice'
    return obj


@pytest.mark.parametrize('engine', ['piper', 'silero'])
def test_diagnostic_wav_engines_register_reference_and_do_not_suspend(monkeypatch, tmp_path, engine):
    trace = EchoTrace(tmp_path)
    path = EchoPath(trace=trace)
    path.suspend_render = Mock()
    play = Mock(); monkeypatch.setattr(audio_output, 'play_wav', play)
    obj = speaker(engine, path)
    try:
        token = obj._new_token()
        obj._play_wav(b'placeholder', token)
        assert play.call_args.kwargs['echo'] is path
        path.suspend_render.assert_not_called()
    finally:
        path.close()
    summary, events = read_trace(trace)
    assert summary['backends'] == [{'backend':engine, 'voice':'test-voice',
                                    'reference_available':True}]
    assert len([e for e in events if e['kind'] == 'backend']) == 1


@pytest.mark.parametrize('engine,reference', [('piper', True), ('silero', False), ('winrt', False), ('sapi', False)])
def test_normal_session_scope_and_backend_guard_are_unchanged(monkeypatch, engine, reference):
    path = EchoPath()
    path.suspend_render = Mock()
    play = Mock(); monkeypatch.setattr(audio_output, 'play_wav', play)
    obj = speaker(engine, path)
    try:
        token = obj._new_token()
        if engine != 'sapi':
            obj._play_wav(b'placeholder', token)
            assert ('echo' in play.call_args.kwargs) is reference
        assert path.suspend_render.call_count == (0 if reference else 1)
        assert not path.diagnostic_mode
    finally:
        path.close()


def test_sapi_is_marked_unsupported_without_fake_audio(tmp_path, caplog):
    trace = EchoTrace(tmp_path)
    path = EchoPath(trace=trace)
    obj = speaker('sapi', path)
    try:
        obj._new_token()
        assert obj._pcm_echo_path() is None
        assert not path._rendering
    finally:
        path.close()
    summary, events = read_trace(trace)
    assert summary['trace_status'] == 'metadata_only_no_pcm'
    assert summary['capture_frames'] == summary['render_bytes'] == 0
    assert summary['backends'][0]['reference_available'] is False
    assert not [e for e in events if e['kind'] in ('capture', 'render')]
    assert 'NO PCM REFERENCE' in caplog.text


def test_switching_backend_records_actual_resolved_engine_and_invalidates_sapi_reference(tmp_path):
    trace = EchoTrace(tmp_path)
    path = EchoPath(trace=trace)
    obj = speaker('silero', path)
    try:
        obj._new_token()
        path.begin_render()
        obj._engine_name = 'sapi'
        obj._new_token()
        assert not path._rendering and not path._references
        obj._engine_name = 'piper'
        obj._new_token()
        assert obj._pcm_echo_path() is path
    finally:
        path.close()
    summary, events = read_trace(trace)
    assert [e['backend'] for e in events if e['kind'] == 'backend'] == ['silero', 'sapi', 'piper']
    assert [e['backend'] for e in summary['backends']] == ['silero', 'sapi', 'piper']


@pytest.mark.parametrize('engine,rate', [('piper', 22050), ('silero', 48000)])
def test_each_wav_backend_records_exact_common_output_and_capture(monkeypatch, tmp_path, engine, rate):
    trace = EchoTrace(tmp_path)
    received = queue.Queue()
    path = EchoPath(factory=Processor, trace=trace, clock=lambda:100.)
    path.start(lambda data, **kw:received.put((data, kw)))
    assert path.ready.wait(1)
    obj = speaker(engine, path)
    writes = []
    class Output:
        latency = 0.
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def write(self, data):writes.append(data.copy())
    monkeypatch.setitem(sys.modules, 'sounddevice', NS(OutputStream=lambda **kw:Output()))
    monkeypatch.setattr(audio_output.time, 'monotonic', lambda:100.)
    count = rate // 5
    audio = np.sin(2 * np.pi * 800 * np.arange(count) / rate).astype(np.float32)[:, None] * .2
    wav_bytes = audio_output.encode_wav(audio, rate)
    try:
        obj._new_token()
        # Leave render active until capture delivery, as live playback does.
        # Output here runs synchronously; its estimated finish is controlled.
        monkeypatch.setattr(path, '_finish_render', lambda serial, when:None)
        obj._play_wav(wav_bytes, threading.Event())
        assert path.submit(PCM, 100.)
        data, kw = received.get(timeout=2)
        assert data == np.full(2048, 500, dtype=np.int16).tobytes()
        assert kw['aec_trace_id'] is not None
    finally:
        path.close()
    summary, events = read_trace(trace)
    render_events = [e for e in events if e['kind'] == 'render']
    captures = [e for e in events if e['kind'] == 'capture']
    assert render_events and captures
    assert all(e['backend'] == engine for e in render_events + captures)
    assert all(e['rate'] == rate for e in render_events)
    recorded = np.fromfile(trace.folder / 'render.f32', dtype='<f4')
    assert np.array_equal(recorded, np.concatenate(writes)[:, 0])
    assert summary['trace_status'] == 'pcm_trace'
    assert summary['backends'][0]['backend'] == engine
    assert summary['capture_frames'] == 2048


def test_diagnostic_backend_scope_remains_stable_after_recording_timeout(tmp_path):
    trace = EchoTrace(tmp_path)
    path = EchoPath(trace=trace)
    trace.close()
    obj = speaker('silero', path)
    try:
        assert path.diagnostic_mode and obj._pcm_echo_path() is path
        obj._new_token()  # no new recording and no mid-session DSP mode switch
        assert trace.done.is_set()
    finally:
        path.close()
