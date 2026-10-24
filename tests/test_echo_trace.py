"""Local diagnostic contracts: no devices or external services."""
import json
import queue
import threading
import wave
import zipfile
from types import SimpleNamespace as NS
from unittest.mock import Mock

import numpy as np
import pytest

from jarvis.echo import EchoPath, make_echo_path
from jarvis.echo_trace import EchoTrace
from tests.test_echo import listener, Processor, render, PCM


def read_trace(trace):
    assert trace.done.wait(3)
    summary = json.loads((trace.folder / 'summary.json').read_text())
    events = [json.loads(line) for line in (trace.folder / 'events.jsonl').read_text().splitlines()]
    assert trace.error is None
    with zipfile.ZipFile(trace.archive) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {
            'microphone.wav', 'reference.wav', 'cleaned.wav', 'render.f32',
            'events.jsonl', 'summary.json'}
    return summary, events


def test_three_aligned_channels_and_original_render_with_timestamps(tmp_path):
    t = EchoTrace(tmp_path)
    raw = np.arange(2560, dtype=np.int16)
    far = (raw // 2).astype(np.int16)
    clean = (raw // 4).astype(np.int16)
    audio = np.linspace(-.2, .2, 2205, dtype=np.float32)
    t.render(audio, 22050, 100., 4)
    one = t.capture(raw.tobytes(), far, clean.tobytes(), 100., epoch=1, gap=False)
    two = t.capture(raw.tobytes(), far, clean.tobytes(), 100.7, epoch=2, gap=True)
    t.note('decision', capture_id=two, triggered=False, reason='speaker_echo')
    t.note('render_end', serial=4, when=100.75)
    t.close()
    summary, events = read_trace(t)
    assert summary['capture_frames'] == 5120
    captures = [e for e in events if e['kind'] == 'capture']
    assert [e['frame_offset'] for e in captures] == [0, 2560]
    assert [e['when'] for e in captures] == [100., 100.7]  # gap is not hidden
    assert [e['seq'] for e in captures] == [one, two]
    assert [e for e in events if e['kind'] == 'decision'][0]['capture_id'] == two
    for name, expected in [('microphone', raw), ('reference', far), ('cleaned', clean)]:
        with wave.open(str(t.folder / (name + '.wav')), 'rb') as f:
            assert f.getparams()[:3] == (1, 2, 16000)
            assert np.array_equal(np.frombuffer(f.readframes(5120), dtype='<i2'),
                                  np.tile(expected, 2))
    assert np.array_equal(np.fromfile(t.folder / 'render.f32', dtype='<f4'), audio)


def test_timer_starts_at_first_audio_and_stops_without_more_audio(tmp_path):
    clock = NS(now=100.)
    t = EchoTrace(tmp_path, clock=lambda:clock.now, duration=.2)
    clock.now = 500.
    t.note('render_begin', serial=1)
    assert not t.done.wait(.1)  # idle startup is not the recording interval
    t.render(np.zeros(160, dtype=np.float32), 16000, 500., 1)
    clock.now = 501.
    summary, _ = read_trace(t)
    assert summary['stop_reason'] == 'time_limit'
    assert not t.active and t.capture(PCM, np.ones(2048, dtype=np.int16), PCM, 501.) is None


def test_first_trigger_auto_finishes_after_tail_without_app_shutdown(tmp_path):
    clock = NS(now=100.)
    t = EchoTrace(tmp_path, clock=lambda:clock.now, after_trigger=.2)
    t.capture(PCM, np.ones(2048, dtype=np.int16), PCM, 100.)
    t.note('decision', capture_id=1, triggered=True, reason='triggered')
    clock.now = 100.3
    summary, _ = read_trace(t)
    assert summary['stop_reason'] == 'after_first_trigger'


def test_audio_size_limit_and_no_late_writes(tmp_path):
    t = EchoTrace(tmp_path, byte_limit=13000)
    assert t.capture(PCM, np.ones(2048, dtype=np.int16), PCM, 100.) is not None
    assert t.capture(PCM, np.ones(2048, dtype=np.int16), PCM, 100.2) is None
    summary, _ = read_trace(t)
    assert summary['audio_bytes_reserved'] == 12288
    assert summary['stop_reason'] == 'size_limit'
    before = t.archive.read_bytes()
    t.note('decision', reason='late', triggered=False)
    t.close(); t.close()
    assert t.archive.read_bytes() == before


def test_queue_overflow_is_bounded_and_explicit_not_a_capture_wait(tmp_path):
    gate = threading.Event()
    class Paused(EchoTrace):
        def _run(self):
            assert gate.wait(2)
            super()._run()
    t = Paused(tmp_path, queue_size=2)
    try:
        for i in range(20):
            t.note('test', index=i)
        assert t._queue.qsize() == 2 and t._dropped == 18
    finally:
        gate.set(); t.close()
    summary, events = read_trace(t)
    assert summary['dropped_events'] == 18 and len(events) == 2


def test_disk_failure_disables_only_trace(tmp_path):
    blocked = tmp_path / 'not_a_directory'
    blocked.write_text('file')
    t = EchoTrace(blocked)
    assert t.done.wait(2) and t.error is not None
    assert t.note('anything') is None
    # The capture processor still delivers its normal output.
    received = queue.Queue(); p = EchoPath(factory=Processor, trace=t, clock=lambda:100.)
    p.start(lambda data, **kw:received.put(data)); assert p.ready.wait(1)
    try:
        render(p); assert p.submit(PCM, 100.)
        assert received.get(timeout=2) == np.full(2048, 500, dtype=np.int16).tobytes()
        assert p.state == 'ready'
    finally:
        p.close()


def test_normal_launch_does_not_create_trace_or_audio_files(monkeypatch, tmp_path):
    monkeypatch.delenv('FENIX_AEC_DIAGNOSTICS', raising=False)
    constructor = Mock(side_effect=AssertionError('normal launch must not construct recorder'))
    monkeypatch.setattr('jarvis.echo_trace.EchoTrace', constructor)
    p = make_echo_path({'aec_enabled':True})
    assert p._trace is None
    p.close()
    constructor.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_environment_does_not_enable_aec_or_rewrite_config(monkeypatch):
    monkeypatch.setenv('FENIX_AEC_DIAGNOSTICS', '1')
    constructor = Mock()
    monkeypatch.setattr('jarvis.echo_trace.EchoTrace', constructor)
    config = {'aec_enabled':False}
    assert make_echo_path(config) is None and config == {'aec_enabled':False}
    constructor.assert_not_called()


def test_opted_in_launch_uses_user_logs_folder(monkeypatch, tmp_path):
    monkeypatch.setenv('FENIX_AEC_DIAGNOSTICS', '1')
    monkeypatch.setattr('jarvis.paths.user_dir', lambda:tmp_path)
    p = make_echo_path({'aec_enabled':True})
    assert p._trace is not None
    p.close()
    read_trace(p._trace)
    assert p._trace.folder.parent == tmp_path / 'logs' / 'aec_diagnostics'


def test_echo_worker_capture_and_listener_decision_share_same_id(tmp_path):
    t = EchoTrace(tmp_path)
    x = listener(); x.vad = NS(is_speech=lambda b:True)
    p = EchoPath(factory=Processor, trace=t, clock=lambda:100.)
    x._echo_path = p
    received = queue.Queue()
    def deliver(data, **kw):
        x._accept_capture(data, **kw)
        received.put(kw)
    p.start(deliver); assert p.ready.wait(1)
    try:
        render(p); assert p.submit(PCM, 100.)
        kw = received.get(timeout=2)
        assert kw['aec_trace_id'] is not None
    finally:
        p.close()
    summary, events = read_trace(t)
    capture = [e for e in events if e['kind'] == 'capture'][0]
    decision = [e for e in events if e['kind'] == 'decision'][0]
    assert decision['capture_id'] == capture['seq'] == kw['aec_trace_id']
    assert decision['reason'] == 'warming' and not decision['triggered']
    assert summary['capture_frames'] == 2048


def test_recording_does_not_capture_idle_microphone(tmp_path):
    t = EchoTrace(tmp_path)
    p = EchoPath(factory=Processor, trace=t, clock=lambda:100.)
    received = queue.Queue()
    p.start(lambda data, **kw:received.put(data)); assert p.ready.wait(1)
    try:
        assert p.submit(PCM, 100.)
        assert received.get(timeout=2) == PCM
    finally:
        p.close()
    summary, events = read_trace(t)
    assert summary['capture_frames'] == 0 and not [e for e in events if e['kind'] == 'capture']


def test_trace_keeps_unrounded_trigger_and_native_reset_reason(tmp_path):
    t = EchoTrace(tmp_path, after_trigger=2.)
    x = listener(); x.vad = NS(is_speech=lambda b:True)
    x._echo_path = EchoPath(trace=t)
    try:
        clean = np.full(2560, 100, dtype=np.int16).tobytes()
        for seq in (17, 18):
            x._accept_capture(clean, aec_probability=.99, source_pcm=PCM,
                              aec_echo_similarity=.05, aec_verified=True,
                              aec_attenuation=.3, aec_best_attenuation=.01,
                              aec_trace_id=seq)
        x._echo_path._trace_note('native_reset', reason='acoustic_path_change', when=100.)
    finally:
        x._echo_path.close()
    _, events = read_trace(t)
    decisions = [e for e in events if e['kind'] == 'decision']
    assert decisions[-1]['triggered'] and decisions[-1]['reason'] == 'triggered'
    assert decisions[-1]['speech_ms'] == 320
    assert [e for e in events if e['kind'] == 'native_reset'][0]['reason'] == 'acoustic_path_change'


@pytest.mark.parametrize("similarity,probability", [(.05, .99), (.65, .99), (.05, .1)])
def test_trace_does_not_change_barge_decisions_or_asr_audio(tmp_path, similarity, probability):
    plain = listener(); traced = listener()
    trace = EchoTrace(tmp_path)
    traced._echo_path = EchoPath(trace=trace)
    plain.vad = traced.vad = NS(is_speech=lambda b:True)
    clean = np.full(2560, 100, dtype=np.int16).tobytes()
    try:
        for index in range(4):
            kwargs = dict(aec_probability=probability, source_pcm=PCM,
                          aec_echo_similarity=similarity, aec_verified=True,
                          aec_attenuation=.3, aec_best_attenuation=.01)
            plain._accept_capture(clean, **kwargs)
            traced._accept_capture(clean, **kwargs, aec_trace_id=index + 1)
            assert plain.barge_flag == traced.barge_flag
            assert plain._barge_speech_ms == traced._barge_speech_ms
            assert plain._aec_last_reason == traced._aec_last_reason
            assert plain._audio.get_nowait() == traced._audio.get_nowait() == clean
    finally:
        traced._echo_path.close()
    read_trace(trace)


def test_manual_launcher_keeps_recording_environment_local_to_process():
    from pathlib import Path
    batch = (Path(__file__).parents[1] / 'start_aec_diagnostics.bat').read_text()
    assert 'setlocal' in batch and 'choice /C YN' in batch
    assert 'set "FENIX_AEC_DIAGNOSTICS=1"' in batch
    assert '-m jarvis' in batch and 'setx' not in batch.lower()
    normal = (Path(__file__).parents[1] / 'start_fenix.bat').read_text()
    assert 'FENIX_AEC_DIAGNOSTICS' not in normal


def test_trigger_stop_deadline_survives_a_full_diagnostic_queue(tmp_path):
    clock = NS(now=100.)
    gate = threading.Event()
    class Paused(EchoTrace):
        def _run(self):
            assert gate.wait(2)
            super()._run()
    t = Paused(tmp_path, clock=lambda:clock.now, queue_size=1, after_trigger=.2)
    t.note('render_begin', serial=1)
    assert t.note('decision', capture_id=1, triggered=True) is None
    clock.now = 101.
    gate.set()
    summary, _ = read_trace(t)
    assert summary['stop_reason'] == 'after_first_trigger' and summary['dropped_events'] == 1
    assert not t.archive.with_suffix('.zip.partial').exists()
