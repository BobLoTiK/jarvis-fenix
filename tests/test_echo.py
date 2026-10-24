"""AEC contracts: bounded synthetic PCM and controlled native transport; no devices."""
from collections import deque
import queue
import sys
import threading
from types import SimpleNamespace as NS
from unittest.mock import Mock

import numpy as np
import pytest

from jarvis.echo import EchoPath, make_echo_path
from jarvis import audio_output, stt
from jarvis.tts import Speaker
from tests.test_nonverbal import wav

PCM = np.full(2048, 1000, dtype=np.int16).tobytes()

class Processor:
    speech_probability = .8
    def __init__(self):
        self.calls = []
        self.reset = Mock()
    def process(self, near, far):
        self.calls.append((threading.get_ident(),near.copy(),far.copy()))
        return (near // 2).astype(np.int16)


@pytest.fixture
def path():
    proc=Processor();received=queue.Queue()
    p=EchoPath(factory=lambda:proc,clock=lambda:100.0)
    p.start(lambda data,**kw:received.put((data,kw)))
    assert p.ready.wait(1) and p._healthy
    yield p,proc,received
    p.close();assert not p.thread.is_alive()


def render(p,at=100,rate=16000,n=3200):
    tap=p.begin_render();assert tap is not None
    tap.feed(np.full((n,1),.25,dtype=np.float32),rate,at)
    return tap


def test_disabled_means_no_path_or_native_import():
    cfg={};assert make_echo_path(cfg) is None;assert cfg=={}


@pytest.mark.parametrize('rate',[8000,22050,48000,'16000'])
def test_unsupported_capture_rate_keeps_old_path(rate):
    assert make_echo_path({'aec_enabled':True,'sample_rate':rate}) is None


@pytest.mark.parametrize('delay,expected',[(float('nan'),40),(float('inf'),40),('bad',40),(-1,0),(900,500),(75,75)])
def test_delay_is_validated_without_config_writes(delay,expected):
    cfg={'aec_enabled':True,'aec_stream_delay_ms':delay}
    p=make_echo_path(cfg);assert p.delay_ms==expected
    assert len(cfg)==2 and cfg['aec_stream_delay_ms'] is delay
    p.close()


@pytest.mark.parametrize('error',[ImportError('missing optional package'),OSError('native DLL unavailable')])
def test_missing_native_package_does_not_block_or_receive_pcm(error):
    factory=Mock(side_effect=error);p=EchoPath(factory=factory,clock=lambda:100)
    p.start(Mock());assert p.ready.wait(1);p.thread.join(1)
    assert p.state=='unavailable' and not p.submit(PCM,100)
    tap=p.begin_render();assert tap is not None and p.render_guard_active()
    tap.finish(100);assert p.render_guard_active()  # 400 ms acoustic tail
    p.clock=lambda:101;assert not p.render_guard_active()
    factory.assert_called_once();p.close()


def test_cleaned_capture_uses_reference_and_one_worker(path):
    p,proc,received=path;render(p)
    assert p.submit(PCM,100)
    data,kw=received.get(timeout=1)
    assert data==np.full(2048,500,dtype=np.int16).tobytes()
    assert kw['source_pcm']==PCM and kw['aec_probability']==.8
    owner,near,far=proc.calls[0]
    assert owner!=threading.get_ident() and near.dtype==far.dtype==np.int16
    assert near.shape==far.shape==(2048,)
    assert np.all(np.abs(far.astype(int)-8192)<=1)


def test_idle_keeps_original_pcm_without_calling_processor(path):
    p,proc,received=path
    assert p.submit(PCM,100)
    data,kw=received.get(timeout=1)
    assert data==PCM and kw['aec_probability'] is None
    assert not proc.calls


def test_non_piper_suspends_previous_reference(path):
    p,proc,received=path;render(p);p.suspend_render()
    assert p.submit(PCM,100)
    data,kw=received.get(timeout=1)
    assert data==PCM and kw['aec_probability'] is None
    assert not proc.calls;proc.reset.assert_called_once()


def test_reference_resamples_and_mixes_channels(path):
    p,_,_=path;tap=p.begin_render()
    stereo=np.column_stack([np.full(4410,.2),np.full(4410,.4)])
    tap.feed(stereo,22050,100)
    far=p._reference(100,1600)
    assert far.shape==(1600,) and np.max(np.abs(far.astype(int)-9830))<=1


def test_future_reference_not_used_early_and_cancel_trims_it(path):
    p,_,_=path;tap=render(p,100.1)
    assert not p._reference(100,800).any()
    tap.finish(100.15)
    assert p._reference(100.12,160).any()
    assert not p._reference(100.2,160).any()
    assert p._reference(101,160) is None


def test_old_render_end_cannot_close_new_render(path):
    p,_,_=path;old=render(p);new=render(p,100.1)
    old.finish(100.05)
    assert p._rendering
    new.finish(100.2);assert not p._rendering


@pytest.mark.parametrize('bad',[np.array([np.nan]),np.zeros((2,2,2)),np.zeros(5000)])
def test_bad_or_oversized_reference_rejected(path,bad):
    p,_,_=path;tap=p.begin_render()
    with pytest.raises(ValueError):tap.feed(bad,16000,100)


def test_reference_is_bounded_and_purges_old_audio(path):
    p,_,_=path;tap=p.begin_render()
    for _ in range(200):tap.feed(np.zeros(800),16000,100)
    assert len(p._references)==80
    p.clock=lambda:104
    tap.feed(np.zeros(800),16000,104)
    assert len(p._references)==1


@pytest.mark.parametrize('raw,when',[(b'x',100),(b'x'*16002,100),(PCM,float('nan'))])
def test_invalid_capture_not_queued(path,raw,when):
    p,_,_=path;assert p.submit(raw,when) is False


def test_queue_full_drops_instead_of_growing_or_injecting_raw():
    p=EchoPath();p._healthy=True
    for _ in range(20):assert p.submit(PCM,100)
    assert p._queue.qsize()==4 and p.dropped==16
    p.close()


def test_stale_capture_not_delivered(path):
    p,proc,received=path;render(p)
    # Put a deliberately old block followed by a fresh synchronization marker.
    p._queue.put_nowait((p._epoch,PCM,100,99))
    p.submit(PCM,100)
    received.get(timeout=1)
    assert p.dropped==1 and received.empty() and len(proc.calls)==1


def test_flush_invalidates_inflight_capture_without_native_calls_on_caller():
    entered=threading.Event();release=threading.Event();outputs=queue.Queue()
    class Slow(Processor):
        def process(self,near,far):
            entered.set();assert release.wait(2);return near
    proc=Slow();p=EchoPath(factory=lambda:proc,clock=lambda:100)
    p.start(lambda data,**kw:outputs.put(data));assert p.ready.wait(1)
    try:
        render(p);p.submit(PCM,100);assert entered.wait(1)
        p.flush();release.set()
        marker=np.full(2048,2000,dtype=np.int16).tobytes();p.submit(marker,100)
        assert outputs.get(timeout=1)==marker
        assert outputs.empty()
    finally:release.set();p.close()


def test_native_error_falls_back_next_block_without_replaying_old_audio():
    proc=Processor();proc.process=Mock(side_effect=RuntimeError('native failed'))
    delivered=Mock();p=EchoPath(factory=lambda:proc,clock=lambda:100)
    p.start(delivered);assert p.ready.wait(1)
    render(p);p.submit(PCM,100);p.thread.join(1)
    assert not p.thread.is_alive() and p.state=='failed'
    delivered.assert_not_called();assert not p.submit(PCM,100);p.close()


def test_close_is_idempotent_and_disables_capture(path):
    p,_,_=path;p.close();p.close()
    assert not p.submit(PCM,100) and p.begin_render() is None


def listener():
    x=stt.Listener.__new__(stt.Listener)
    x._echo_path=None;x._sample_rate=16000;x.peak=x.current_rms=0
    x.muted=False;x._speech_active=True;x.barge_enabled=True;x.barge_flag=False
    x._echo_baseline=0;x._barge_threshold=150
    x._barge_speech_ms=0;x._audio=queue.Queue();x.vad=None;x._vad_gate=None
    x._process_barge=Mock()
    return x


def test_callback_only_queues_when_aec_ready():
    x=listener();x._echo_path=NS(submit=Mock(return_value=True))
    x._accept_capture=Mock()
    x._callback(PCM,2048,NS(currentTime=10.,inputBufferAdcTime=9.9),None)
    x._accept_capture.assert_not_called();x._process_barge.assert_not_called()
    x._echo_path.submit.assert_called_once()
    assert x._echo_path.submit.call_args.args[0]==PCM


def test_callback_missing_native_is_guarded_during_piper_render():
    x=listener();x._echo_path=NS(submit=Mock(return_value=False),take_gap=lambda:False,
                                 render_guard_active=lambda:True)
    x._callback(PCM,2048,None,None)
    x._process_barge.assert_not_called()
    assert x._audio.empty() and x.current_rms==1000


def test_callback_missing_native_keeps_original_path_when_piper_is_idle():
    x=listener();x._echo_path=NS(submit=Mock(return_value=False),take_gap=lambda:False,
                                 render_guard_active=lambda:False)
    x._callback(PCM,2048,None,None)
    x._process_barge.assert_called_once_with(1000)
    assert x._audio.get_nowait()==PCM


@pytest.mark.parametrize('prob,rms,vad,expected',[(.8,1000,True,True),(.2,1000,True,False),(.8,0,True,False),(.8,1000,False,False)])
def test_aec_barge_requires_clean_energy_and_speech(prob,rms,vad,expected):
    x=listener();x.vad=NS(is_speech=lambda b:vad)
    cleaned=np.full(2048,rms,dtype=np.int16).tobytes()
    for _ in range(3):
        x._accept_capture(cleaned,aec_probability=prob,source_pcm=PCM,
                          aec_echo_similarity=.05,aec_verified=True)
    assert x.barge_flag is expected
    x._process_barge.assert_not_called()
    assert x.current_rms==1000  # meter/watchdog reports physical mic, not cleaned silence


def test_aec_barge_rejects_unverified_or_correlated_render_residual():
    x=listener();x.vad=NS(is_speech=lambda b:True)
    cleaned=np.full(2560,1000,dtype=np.int16).tobytes()
    for verified,similarity in [(False,.01),(True,.35)]:
        for _ in range(4):
            x._accept_capture(cleaned,aec_probability=.95,source_pcm=cleaned,
                              aec_echo_similarity=similarity,aec_verified=verified)
        assert not x.barge_flag
    assert x._aec_last_reason=='speaker_echo'


def test_aec_barge_adapts_to_quiet_microphone_without_learning_user_as_noise():
    x=listener();x.vad=NS(is_speech=lambda b:True)
    x._aec_residual_levels=deque(maxlen=24);x._aec_level_threshold=20
    residual=np.full(2560,4,dtype=np.int16).tobytes()
    for _ in range(4):
        x._accept_capture(residual,aec_probability=.2,source_pcm=PCM,
                          aec_echo_similarity=.05,aec_verified=True,
                          aec_attenuation=.01,aec_best_attenuation=.01)
    assert x._aec_level_threshold==15 and not x.barge_flag
    quiet_user=np.full(2560,37,dtype=np.int16).tobytes()
    for _ in range(2):
        x._accept_capture(quiet_user,aec_probability=.8,source_pcm=PCM,
                          aec_echo_similarity=.12,aec_verified=True,
                          aec_attenuation=.5,aec_best_attenuation=.01)
    assert x.barge_flag and x._aec_last_reason=='triggered'
    assert x._aec_trigger_metrics['rms']==37


def test_aec_barge_rejects_low_attenuation_echo_above_adaptive_level():
    x=listener();x.vad=NS(is_speech=lambda b:True)
    echo=np.full(2560,80,dtype=np.int16).tobytes()
    for _ in range(3):
        x._accept_capture(echo,aec_probability=.9,source_pcm=PCM,
                          aec_echo_similarity=.2,aec_verified=True,
                          aec_attenuation=.03,aec_best_attenuation=.02)
    assert not x.barge_flag and x._aec_last_reason=='attenuation'


def test_aec_barge_rejects_close_speaker_acoustic_path_change():
    x=listener();x.vad=NS(is_speech=lambda b:True)
    close_echo=np.full(2560,400,dtype=np.int16).tobytes()
    for _ in range(3):
        x._accept_capture(close_echo,aec_probability=.95,source_pcm=PCM,
                          aec_echo_similarity=.25,aec_raw_similarity=.7,
                          aec_verified=True,aec_attenuation=.5,
                          aec_best_attenuation=.01)
    assert not x.barge_flag
    assert x._aec_last_reason=='acoustic_path_change'


def test_verified_render_is_revoked_when_acoustic_path_changes():
    rng=np.random.default_rng(81)
    signal=rng.integers(-6000,6000,size=2560,dtype=np.int16)
    class Changing(Processor):
        speech_probability=.9
        def __init__(self):self.count=0;self.reset=Mock()
        def process(self,near,far):
            self.count+=1
            return (near//(100 if self.count<=2 else 2)).astype(np.int16)
    proc=Changing();received=queue.Queue()
    p=EchoPath(factory=lambda:proc,clock=lambda:100)
    p.start(lambda data,**kw:received.put(kw));assert p.ready.wait(1)
    tap=p.begin_render();tap.feed(signal.astype(np.float32)/32767,16000,100)
    try:
        states=[]
        for _ in range(4):
            assert p.submit(signal.tobytes(),100)
            states.append(received.get(timeout=2)['aec_verified'])
        assert states==[False,True,True,False]
        assert proc.reset.call_count==1
        assert p.diagnostics()['readaptations']==1
    finally:p.close()


def test_clean_pcm_reaches_vad_and_asr_not_raw_echo():
    x=listener();x.vad=NS(is_speech=Mock(return_value=True))
    cleaned=np.full(2048,500,dtype=np.int16).tobytes()
    x._accept_capture(cleaned,aec_probability=.8,source_pcm=PCM)
    x.vad.is_speech.assert_called_once_with(cleaned)
    assert x._audio.get_nowait()==cleaned


def test_muted_aec_does_not_enqueue_recognition():
    x=listener();x.muted=True
    x._accept_capture(PCM,aec_probability=.8,source_pcm=PCM)
    assert x._audio.empty()


def test_wav_replay_cannot_accidentally_use_live_aec():
    x=listener();x._file_mode=True
    with pytest.raises(RuntimeError):x.set_echo_path(Mock())


@pytest.mark.parametrize('engine,has_echo',[('piper',True),('silero',False),('winrt',False)])
def test_normal_session_only_piper_registers_reference_with_common_output(monkeypatch,engine,has_echo):
    p=Mock();s=Speaker.__new__(Speaker);s._engine_name=engine;s._echo_path=p;s._nonverbal=None
    play=Mock();monkeypatch.setattr(audio_output,'play_wav',play)
    token=threading.Event();s._play_wav(b'wav',token)
    assert ('echo' in play.call_args.kwargs) is has_echo
    if has_echo:assert play.call_args.kwargs['echo'] is p


def test_reference_matches_actual_mixed_blocks_and_stop_token(monkeypatch):
    records=[];tap=NS(feed=lambda data,rate,when:records.append(('ref',data.copy(),rate,when)),finish=Mock())
    echo=NS(begin_render=lambda:tap,suspend_render=Mock())
    token=threading.Event()
    class Output:
        latency=.02
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def write(self,data):records.append(('write',data.copy()));token.set()
    constructor=Mock(return_value=Output())
    monkeypatch.setitem(sys.modules,'sounddevice',NS(OutputStream=constructor))
    monkeypatch.setattr(audio_output.time,'monotonic',lambda:100.)
    audio_output.play_wav(wav(),token,echo=echo)
    assert constructor.call_count==1
    assert [r[0] for r in records]==['ref','write']
    assert np.array_equal(records[0][1],records[1][1])
    assert len(records[0][1])==800 and records[0][3]==100.02
    tap.finish.assert_called_once()


def test_bad_optional_reference_does_not_break_playback(monkeypatch):
    tap=NS(feed=Mock(side_effect=RuntimeError('ref')),finish=Mock())
    echo=NS(begin_render=lambda:tap,suspend_render=Mock())
    writes=[]
    class Output:
        latency=.01
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def write(self,data):writes.append(data)
    monkeypatch.setitem(sys.modules,'sounddevice',NS(OutputStream=lambda **k:Output()))
    audio_output.play_wav(wav(),threading.Event(),echo=echo)
    assert writes;echo.suspend_render.assert_called_once()


def test_native_linux_api_smoke_without_devices():
    native=pytest.importorskip('pywebrtc_audio')
    p=native.AudioProcessor(sample_rate=16000,echo_cancellation=True,
        noise_suppression=False,auto_gain_control=False,stream_delay_ms=40)
    rng=np.random.default_rng(7)
    for _ in range(8):
        far=rng.integers(-2000,2000,size=2560,dtype=np.int16)
        out=p.process((far//2).astype(np.int16),far)
        assert out.shape==far.shape and out.dtype==np.int16
        assert 0<=p.speech_probability<=1
    p.reset()


def test_asr_gap_resets_recognizer_only_when_consumed():
    x=listener();x._rec=NS(Reset=Mock(),AcceptWaveform=Mock())
    x._utt_buf=[PCM];x._utt_len=len(PCM);x.last_quality=object()
    x._accept_capture(PCM,aec_probability=.8,source_pcm=PCM,aec_reset=True)
    x._rec.Reset.assert_not_called()
    assert x._audio.get_nowait() is None
    x._consume_audio(None)
    x._rec.Reset.assert_called_once();x._rec.AcceptWaveform.assert_not_called()
    assert x._utt_buf==[] and x._utt_len==0 and x.last_quality is None


def test_aec_barge_preserves_cleaned_onset_across_stop_flush():
    from collections import deque
    x=listener();x._aec_preroll=deque(maxlen=4);x._aec_barge=False
    x._utt_buf=[];x._utt_len=0;x._vad_gate=None
    x._echo_path=NS(flush=Mock(),take_gap=Mock())
    clean=np.full(2048,600,dtype=np.int16).tobytes()
    for _ in range(3):
        x._accept_capture(clean,aec_probability=.8,source_pcm=PCM,
                          aec_echo_similarity=.05,aec_verified=True)
    assert x.barge_flag and x._aec_barge
    x.barge_end();x.flush()
    assert x._audio.get_nowait() is None
    assert [x._audio.get_nowait() for _ in range(3)]==[clean,clean,clean]
    assert x._audio.empty() and not x._aec_preroll
    x._echo_path.take_gap.assert_called_once()


def test_preroll_is_bounded_and_not_replayed_without_barge():
    from collections import deque
    x=listener();x._aec_preroll=deque(maxlen=4);x._aec_barge=False
    x._utt_buf=[];x._utt_len=0
    for _ in range(12):x._accept_capture(PCM,aec_probability=.1,source_pcm=PCM)
    assert len(x._aec_preroll)==4 and not x.barge_flag
    x.barge_end();x.flush()
    assert x._audio.empty() and not x._aec_preroll


def test_live_aec_blocks_match_both_webrtc_and_silero_frame_sizes():
    x=listener();x._file_mode=False;path=NS(start=Mock())
    x.set_echo_path(path)
    assert x._block_size==2560 and x._block_size%160==x._block_size%512==0
    assert x._block_ms==160 and x._aec_preroll.maxlen==3
    path.start.assert_called_once_with(x._accept_capture)


def test_discontinuity_keeps_current_render_but_invalidates_capture(path):
    p,proc,received=path;render(p)
    before=p._epoch;p.discontinuity()
    assert p._epoch>before and p._rendering and p._references
    assert p.submit(PCM,100)
    _,kw=received.get(timeout=1)
    assert kw['aec_reset'] is True
    proc.reset.assert_called_once()


def test_real_native_synthetic_echo_through_timestamped_reference():
    # A deterministic DSP sanity check, NOT a room/Windows audio benchmark.
    native=pytest.importorskip('pywebrtc_audio')
    rng=np.random.default_rng(12);n=2560;blocks=45;delay=640
    far=rng.integers(-5000,5000,size=n*blocks,dtype=np.int16)
    near=np.concatenate([np.zeros(delay,dtype=np.int16),far[:-delay]//2])
    clock=NS(now=100.)
    received=queue.Queue()
    path=EchoPath(factory=lambda:native.AudioProcessor(sample_rate=16000,
        echo_cancellation=True,stream_delay_ms=40),clock=lambda:clock.now)
    path.start(lambda data,**kw:received.put(data));assert path.ready.wait(2)
    tap=path.begin_render();assert tap is not None
    outputs=[]
    try:
        for i in range(blocks):
            clock.now=100+i*n/16000
            chunk=far[i*n:(i+1)*n]
            tap.feed(chunk.astype(np.float32)/32767,16000,clock.now)
            assert path.submit(near[i*n:(i+1)*n].tobytes(),clock.now)
            outputs.append(np.frombuffer(received.get(timeout=2),dtype=np.int16).copy())
        original=near[-n*10:].astype(np.float64)
        cleaned=np.concatenate(outputs[-10:]).astype(np.float64)
        assert np.mean(cleaned**2)<np.mean(original**2)*.8
    finally:path.close()


def reference_history(p, samples, at=100., rate=16000):
    tap = p.begin_render()
    for offset in range(0, len(samples), rate // 10):
        tap.feed(samples[offset:offset + rate // 10], rate, at + offset / rate)
    return tap


@pytest.mark.parametrize('delay_samples', [0, 1, 117, 597, 641, 1599, 7999, -1599])
def test_waveform_echo_match_checks_between_old_20ms_grid_points(delay_samples):
    rng = np.random.default_rng(502)
    far = rng.uniform(-.4, .4, 16000).astype(np.float32)
    p = EchoPath(clock=lambda:100.6)
    reference_history(p, far)
    offset = 9600 - delay_samples
    near = np.round(far[offset:offset + 2560] * 32767 * .07).astype(np.int16)
    before = near.copy()
    assert p._echo_similarity(near, 100.6) > .999
    assert np.array_equal(near, before)
    p.close()


@pytest.mark.parametrize('rate', [22050, 48000])
def test_echo_match_resamples_reference_before_sample_lag_search(rate):
    rng = np.random.default_rng(115)
    far = rng.uniform(-.4, .4, rate).astype(np.float32)
    p = EchoPath(clock=lambda:100.6)
    reference_history(p, far, rate=rate)
    times = .6 - 597 / 16000 + np.arange(2560) / 16000
    near = np.round(np.interp(times * rate, np.arange(len(far)), far) * 10000).astype(np.int16)
    assert p._echo_similarity(near, 100.6) > .999
    p.close()


def test_echo_match_missing_reference_and_dc_cannot_create_false_match():
    p = EchoPath(clock=lambda:100.6)
    assert p._echo_similarity(np.ones(2560), 100.6) is None
    reference_history(p, np.ones(16000, dtype=np.float32) * .2)
    assert p._echo_similarity(np.ones(2560), 100.6) is None
    p.close()


def test_echo_match_does_not_use_uncovered_zero_padded_windows():
    rng = np.random.default_rng(33)
    p = EchoPath(clock=lambda:100.6)
    # A tiny reference fragment is not a full correlation observation.
    reference_history(p, rng.uniform(-.4, .4, 100).astype(np.float32), at=100.6)
    assert p._echo_similarity(rng.normal(size=2560), 100.6) is None
    p.close()


def test_sample_aligned_echo_rejects_residual_but_allows_double_talk():
    rng = np.random.default_rng(803)
    p = EchoPath(clock=lambda:100.6)
    far = rng.uniform(-.4, .4, 16000).astype(np.float32)
    reference_history(p, far)
    echo = far[9600 - 597:9600 - 597 + 2560]
    # Short multipath response: not simply a byte-identical render block.
    room_echo = np.convolve(echo, [.65, .20, -.08], mode='full')[:2560]
    residual = np.round(room_echo * 300).astype(np.int16)
    # Near-end speech dominates the residual after successful cancellation,
    # while the physical microphone is still dominated by loud speaker echo.
    user = rng.normal(0, 280, 2560)
    mixed = np.round(residual + user).astype(np.int16)
    source = np.round(room_echo * 10000 + user).astype(np.int16)
    echo_similarity, mixed_similarity, raw_similarity = p._echo_similarities(
        (residual, mixed, source), 100.6
    )
    assert echo_similarity > .8 and raw_similarity > .8
    assert mixed_similarity < .22
    for signal, similarity, expected in [(residual, echo_similarity, False),
                                          (mixed, mixed_similarity, True)]:
        x = listener(); x.vad = NS(is_speech=lambda b:True)
        for _ in range(2):
            x._accept_capture(signal.tobytes(), aec_probability=.99,
                              source_pcm=source.tobytes(),
                              aec_echo_similarity=similarity,
                              aec_raw_similarity=raw_similarity,
                              aec_verified=True,
                              aec_attenuation=float(np.linalg.norm(signal.astype(float))
                                                    / np.linalg.norm(source.astype(float))),
                              aec_best_attenuation=.01)
        assert x.barge_flag is expected
    p.close()


def test_capture_attenuation_is_current_even_below_calibration_energy():
    class Quiet(Processor):
        def process(self, near, far):
            return (near // 5).astype(np.int16)
    proc = Quiet(); received = queue.Queue()
    p = EchoPath(factory=lambda:proc, clock=lambda:100.)
    p.start(lambda data, **kw:received.put(kw)); assert p.ready.wait(1)
    render(p)
    try:
        p._last_attenuation = .01
        quiet = np.full(2560, 60, dtype=np.int16).tobytes()
        assert p.submit(quiet, 100.)
        assert received.get(timeout=1)['aec_attenuation'] == pytest.approx(.2)
        assert p.submit(bytes(5120), 100.)
        assert received.get(timeout=1)['aec_attenuation'] is None
    finally:
        p.close()


def test_reference_chunk_boundaries_do_not_create_one_sample_holes():
    p = EchoPath(clock=lambda:100.6)
    reference_history(p, np.full(16000, .25, dtype=np.float32))
    far = p._reference(100.5, 5120)
    assert np.all(np.abs(far.astype(int) - 8192) <= 1)
    p.close()
