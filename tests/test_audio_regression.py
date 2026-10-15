"""Fast contracts only: fake decoders are NOT an audio quality measurement."""

import json
import socket
import threading
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import Mock

import numpy as np
import pytest

from jarvis import stt
from jarvis.audio_output import encode_wav
from jarvis.matching import wake_score
from jarvis.recognition import Quality
from tests.audio import corpus, runner, runtime
from tests.audio.suite import Blocked, load_corpus, load_suite, safe_file
from tests.test_recognition_quality import method


class FakeRec:
    def __init__(self):
        self.accept = False
        self.calls = []
        self.resets = 0
        self.result = {"text": "феникс открой", "result": [{"conf": 0.99}]}

    def SetWords(self, enabled):
        self.words = enabled

    def AcceptWaveform(self, data):
        self.calls.append(data)
        return self.accept

    def Result(self):
        return json.dumps(self.result)

    def Reset(self):
        self.resets += 1

    def FinalResult(self):
        raise AssertionError("Forced endpoint is forbidden")


@pytest.fixture
def listener(monkeypatch):
    rec = FakeRec()
    monkeypatch.setattr(stt, "Model", lambda p: object())
    monkeypatch.setattr(stt, "KaldiRecognizer", lambda *a: rec)
    monkeypatch.setattr(stt, "SetLogLevel", lambda *a: None)
    # Any accidental microphone/device access fails, including device discovery.
    monkeypatch.setattr(stt, "sd", None)
    return stt.Listener("unused", config={"vad_enabled": False}, file_mode=True)


def test_file_feed_uses_callback_and_real_endpoint_path(listener):
    block = np.full(listener._block_size, 600, dtype="<i2").tobytes()
    assert listener.feed_pcm(block) == []
    assert listener.current_rms == 600
    assert listener._rec.words
    listener._rec.accept = True
    [(text, audio)] = listener.feed_pcm(block)
    assert text == "феникс открой"
    assert audio == block * 2
    assert listener.last_quality.accepted
    assert listener._utt_len == 0
    assert listener.utterances == 1


def test_reset_clears_audio_and_previous_quality(listener):
    listener.feed_pcm(b"\0\0" * 512)
    listener.last_quality = Quality(True, "old")
    listener.file_vad_errors = 1
    listener.reset_file_input()
    assert listener.last_quality is None
    assert listener.file_vad_errors == 0
    assert listener._rec.resets == 1
    assert not listener._utt_buf
    assert listener._audio.empty()


@pytest.mark.parametrize("pcm", [b"x", b"\0" * 4098], ids=["odd", "large"])
def test_invalid_pcm_blocks(listener, pcm):
    with pytest.raises(ValueError):
        listener.feed_pcm(pcm)
    assert not listener._rec.calls


def test_empty_and_silent_endpoint_dont_invent_phrase(listener):
    assert listener.feed_pcm(b"") == []
    listener._rec.accept = True
    listener._rec.result = {"text": ""}
    assert listener.feed_pcm(b"\0\0" * 512) == []
    assert not listener.last_quality.accepted


def test_file_mode_cannot_open_microphone(listener):
    with pytest.raises(RuntimeError):
        next(listener.phrases(threading.Event()))


def test_live_mode_cannot_be_fed_externally(listener):
    listener._file_mode = False
    with pytest.raises(RuntimeError):
        listener.feed_pcm(b"\0\0")
    with pytest.raises(RuntimeError):
        listener.reset_file_input()


def test_audio_buffer_is_bounded(listener):
    block = b"\0\0" * listener._block_size
    for _ in range(500):
        listener.feed_pcm(block)
    assert listener._utt_len <= 16000 * 2 * 30


def test_callback_vad_fault_is_visible_to_runner(listener):
    listener.vad = NS(is_speech=Mock(side_effect=RuntimeError("vad")))
    listener.feed_pcm(b"\0\0" * 512)
    assert listener.file_vad_errors == 1
    e = runtime.Engine.__new__(runtime.Engine)
    e.listener, e.no_vad = listener, True
    with pytest.raises(Blocked, match="callback"):
        e._require_vad()


class Synth:
    name = "Fake unit-test voice"

    def __init__(self, voice):
        pass

    def __call__(self, text):
        # Units test only corpus plumbing, never recognition.
        x = np.sin(np.arange(8000) * 0.13).astype(np.float32) * 0.1
        return encode_wav(x[:, None], 16000)


@pytest.fixture
def prepared(tmp_path):
    suite, sha = load_suite()
    data = corpus.prepare(suite, sha, tmp_path, synth_factory=Synth)
    return tmp_path, suite, sha, data


def test_default_corpus_counts_and_hashes(prepared):
    directory, suite, sha, data = prepared
    assert len(data["cases"]) == 27
    assert sum(len(c["turns"]) for c in data["cases"]) == 51
    assert load_corpus(directory, suite, sha) == data["cases"]
    assert all(c["source"] == "synthetic" for c in data["cases"])


@pytest.mark.parametrize("variant", ["clean", "quiet", "noise"])
def test_transforms_are_deterministic_and_do_not_mutate(variant):
    x = np.sin(np.arange(16000) * 0.1).astype(np.float32) * 0.1
    original = x.copy()
    y = corpus.transform(x, variant)
    np.testing.assert_array_equal(x, original)
    np.testing.assert_array_equal(y, corpus.transform(x, variant))
    if variant == "quiet":
        assert np.sqrt(np.mean(y**2)) / np.sqrt(np.mean(x**2)) == pytest.approx(
            10 ** (-12 / 20)
        )
    if variant == "noise":
        assert np.sqrt(np.mean((y - x) ** 2)) / np.sqrt(np.mean(x**2)) == pytest.approx(
            0.1, rel=0.001
        )


def test_stereo_resampled_and_framed():
    wav = encode_wav(np.full((24000, 2), 0.1, dtype=np.float32), 48000)
    x = corpus.mono16k(wav)
    assert len(x) == 8000
    assert np.mean(x) == pytest.approx(0.1, abs=0.001)
    pcm = corpus.framed_pcm(x)
    assert len(pcm) == (8000 + 8192 + 36864) * 2
    assert pcm == corpus.framed_pcm(x)


@pytest.mark.parametrize("path", ["../evil.wav", "/tmp/evil.wav", "a\\evil.wav"])
def test_paths_cannot_escape(tmp_path, path):
    with pytest.raises(Blocked):
        safe_file(tmp_path, path)


def test_symlink_escape(tmp_path):
    other = tmp_path.parent / (tmp_path.name + "-outside")
    other.mkdir(exist_ok=True)
    try:
        (tmp_path / "out").symlink_to(other, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks is not permitted on this Windows installation")
    with pytest.raises(Blocked):
        safe_file(tmp_path, "out/a.wav")


@pytest.mark.parametrize(
    "fault", ["hash", "empty", "duplicate", "suite", "missing", "turns"]
)
def test_invalid_corpus_is_blocked(prepared, fault):
    directory, suite, sha, data = prepared
    if fault == "hash":
        safe_file(directory, data["cases"][0]["turns"][0]["wav"]).write_bytes(b"bad")
    elif fault == "empty":
        data["cases"] = []
    elif fault == "duplicate":
        data["cases"].append(deepcopy(data["cases"][0]))
    elif fault == "suite":
        data["suite_sha256"] = "wrong"
    elif fault == "missing":
        data["cases"] = data["cases"][3:]
    else:
        data["cases"][0]["turns"] = []
    corpus.write_json(directory / "corpus.json", data)
    with pytest.raises(Blocked):
        load_corpus(directory, suite, sha)


@pytest.mark.parametrize(
    "fault", ["duplicate", "flag", "unknown", "two_sources", "empty"]
)
def test_invalid_suite_is_blocked(tmp_path, fault):
    suite, _ = load_suite()
    if fault == "duplicate":
        suite["scenarios"].append(deepcopy(suite["scenarios"][0]))
    elif fault == "flag":
        suite["scenarios"][0]["turns"][0]["expect"]["speech"] = "yes"
    elif fault == "unknown":
        suite["scenarios"][0]["turns"][0]["bogus"] = True
    elif fault == "two_sources":
        suite["scenarios"][0]["turns"][0]["signal"] = "noise"
    else:
        suite["scenarios"] = []
    corpus.write_json(tmp_path / "suite.json", suite)
    with pytest.raises(Blocked):
        load_suite(tmp_path / "suite.json")


def test_failed_prepare_keeps_previous_manifest(prepared):
    directory, suite, sha, _ = prepared
    before = (directory / "corpus.json").read_bytes()
    with pytest.raises(Blocked, match="Нет записи"):
        corpus.prepare(suite, sha, directory, recordings=directory / "missing")
    assert (directory / "corpus.json").read_bytes() == before
    load_corpus(directory, suite, sha)


def test_recordings_are_never_replaced_with_synthetic(tmp_path):
    suite, sha = load_suite()
    for scenario in suite["scenarios"]:
        for i, turn in enumerate(scenario["turns"], 1):
            if "text" in turn:
                p = tmp_path / "input" / scenario["id"] / f"{i:02d}.wav"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(Synth("")(turn["text"]))
    data = corpus.prepare(
        suite,
        sha,
        tmp_path / "out",
        recordings=tmp_path / "input",
        synth_factory=Mock(side_effect=AssertionError("no synthesis")),
    )
    assert all(c["source"] == "recorded" for c in data["cases"])


class App:
    # Existing AST helper allows real method bodies without importing Windows GUI.
    _process = method("jarvis/main.py", "Jarvis", "_process")
    _extract_command = method("jarvis/main.py", "Jarvis", "_extract_command")
    _is_wake = method("jarvis/main.py", "Jarvis", "_is_wake", wake_score=wake_score)
    _request_repeat = method("jarvis/main.py", "Jarvis", "_request_repeat")


def test_manifest_command_expectations_match_production_methods():
    suite, _ = load_suite()
    listener = NS(last_quality=Quality(True, "fixture"), recent_phrases=[])
    # No decoded text comes from this path in the REAL engine. This is a textual
    # contract test to catch wrong expected actions before expensive ASR runs.
    for case in suite["scenarios"]:
        with runtime.Sandbox(listener, app_class=App) as s:
            for turn in case["turns"]:
                before = getattr(s.handler, "_last_timings", None)
                ne, nr = len(s.events), len(s.replies)
                if "text" in turn:
                    s.process(turn["text"], b"")
                actual = s.snapshot(ne, nr, before)
                assert (
                    runtime.check_expected(actual, turn["expect"], int("text" in turn))
                    == []
                ), (case["id"], actual)


def test_sandbox_restores_side_effect_functions():
    from jarvis import timers

    add = timers.add
    with runtime.Sandbox(NS(), app_class=App):
        assert timers.add is not add
    assert timers.add is add


@pytest.mark.parametrize(
    "fault", ["endpoint", "noise_endpoint", "action", "pending", "routing", "reply"]
)
def test_expectations_cannot_silently_pass(fault):
    actual = {"actions": [], "pending": None, "handled": False, "replies": []}
    expect = {"actions": [], "pending": None}
    endpoints = 1
    if fault == "endpoint":
        endpoints = 0
    elif fault == "noise_endpoint":
        expect["speech"] = False
    elif fault == "action":
        actual["actions"] = [{"action": "open", "target": "unexpected"}]
    elif fault == "pending":
        actual["pending"] = "unit"
    elif fault == "routing":
        expect["handled"] = True
    else:
        expect["reply_contains"] = "question"
    assert runtime.check_expected(actual, expect, endpoints)


def test_missing_corpus_exits_blocked_not_pass(tmp_path):
    assert runner.main(["run", "--workdir", str(tmp_path)]) == 2
    data = json.loads((tmp_path / "reports/latest.json").read_text(encoding="utf-8"))
    assert data["status"] == "blocked"
    assert data["passed"] == 0


def test_network_guard_is_reversible():
    connect = socket.socket.connect
    with (
        runtime.patch.object(socket.socket, "connect", runtime.deny_network),
        socket.socket() as s,
        pytest.raises(Blocked),
    ):
        s.connect(("127.0.0.1", 80))
    assert socket.socket.connect is connect


def test_filter_cannot_produce_empty_pass(prepared):
    directory, suite, sha, _ = prepared
    with pytest.raises(Blocked, match="Фильтр"):
        runner.run(suite, sha, directory, selected="not-a-case")


def test_vad_fallback_never_counts_as_full_pass(listener):
    e = runtime.Engine.__new__(runtime.Engine)
    e.listener, e.no_vad = listener, False
    for v in [
        None,
        NS(is_available=lambda: False),
        NS(is_available=lambda: True, fault=True),
        NS(is_available=lambda: True, _auto_off=True),
    ]:
        listener.vad = v
        with pytest.raises(Blocked):
            e._require_vad()


class ResultEngine:
    """A runner-only fake: queued outputs, no claim of real ASR."""

    def __init__(self, models, **kwargs):
        self.values = iter(models)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def new_case(self):
        return self

    def replay(self, pcm, sandbox, **kwargs):
        assert isinstance(pcm, bytes) and pcm
        return next(self.values)


def expected_outputs(suite, *, mismatch=False):
    turns = suite["scenarios"][0]["turns"]
    outputs = []
    for t in turns:
        e = t["expect"]
        outputs.append(
            {
                "actions": e["actions"],
                "pending": e["pending"],
                "replies": [e.get("reply_contains", "private-test-reply")],
                "handled": True,
                "endpoints": [{"quality": "test"}],
                "wall_ms": 1,
                "audio_ms": 100,
                "whisper_calls": 0,
            }
        )
    if mismatch:
        outputs[0]["endpoints"] = []
    return outputs


@pytest.mark.parametrize("mismatch", [False, True], ids=["pass", "fail"])
def test_runner_reports_real_checks_and_redacts_speech(prepared, mismatch):
    directory, suite, sha, _ = prepared
    result = runner.run(
        suite,
        sha,
        directory,
        selected="open_app--auto--clean",
        models=expected_outputs(suite, mismatch=mismatch),
        engine_factory=ResultEngine,
        asr="vosk",
        no_vad=True,
    )
    assert result["status"] == ("fail" if mismatch else "pass")
    assert result["selected_cases"] == 1 and result["total_cases"] == 27
    assert result["coverage"]["vad"] is False
    assert result["coverage"]["whisper"] is False
    assert result["failed"] == int(mismatch)
    text = json.dumps(result)
    assert "private-test-reply" not in text
    if not mismatch:
        assert result["cases"][0]["turns"][1]["actions"] == [{"action": "open"}]


def test_transcripts_are_explicit_opt_in(prepared):
    directory, suite, sha, _ = prepared
    result = runner.run(
        suite,
        sha,
        directory,
        selected="open_app--auto--clean",
        models=expected_outputs(suite),
        engine_factory=ResultEngine,
        include_transcripts=True,
    )
    assert result["cases"][0]["turns"][1]["replies"] == ["private-test-reply"]
    assert result["cases"][0]["turns"][1]["actions"][0]["target"] == "блокнот"


def test_engine_failure_restores_network_patch(monkeypatch):
    connect = socket.socket.connect
    monkeypatch.setattr(stt, "Listener", Mock(side_effect=RuntimeError("load failed")))
    with pytest.raises(RuntimeError, match="load failed"):
        runtime.Engine({"vosk": "unused"}, asr="vosk", no_vad=True)
    assert socket.socket.connect is connect


def test_strict_vad_survives_reload_and_whisper_fault_is_blocked(monkeypatch, listener):
    from jarvis import vad

    base_vad = vad.VAD

    class FakeVAD:
        def __init__(self, *a, **kw):
            pass

        def is_available(self):
            return True

        def is_model_pending(self):
            return False

        def _max_prob(self, samples):
            raise RuntimeError("inference failed")

    class FakeWhisper:
        def __init__(self, *a, **kw):
            assert kw["local_files_only"] is True

        def transcribe(self, *a, **kw):
            raise RuntimeError("decode failed")

    monkeypatch.setattr(vad, "VAD", FakeVAD)
    monkeypatch.setattr(stt, "WhisperTranscriber", FakeWhisper)
    listener.vad_enabled = True
    listener.vad = FakeVAD()
    monkeypatch.setattr(stt, "Listener", lambda *a, **kw: listener)
    with runtime.Engine({"vosk": "unused", "whisper": "unused"}) as e:
        # Reload imports VAD inside set_vad_enabled, not from stt global.
        listener.reload_vad()
        with pytest.raises(RuntimeError):
            listener.vad._max_prob([])
        with pytest.raises(Blocked):
            e._require_vad()
        with pytest.raises(RuntimeError):
            e.whisper.transcribe(b"test")
        assert e.whisper.fault and e.whisper.calls == 1
    assert vad.VAD is FakeVAD
    monkeypatch.setattr(vad, "VAD", base_vad)


def test_audio_regression_ignored_by_snapshot():
    import snapshot

    assert {"audio-regression", ".audio-regression"} <= snapshot.EXCLUDE_DIRS


def test_cli_failure_code_one_and_blocked_two(prepared, monkeypatch):
    directory, _, _, _ = prepared
    monkeypatch.setattr(runner, "preflight", lambda *a, **kw: {})
    monkeypatch.setattr(
        runner,
        "run",
        lambda *a, **kw: {
            "status": "fail",
            "passed": 0,
            "failed": 1,
            "selected_cases": 1,
            "total_cases": 27,
            "cases": [],
        },
    )
    assert runner.main(["run", "--workdir", str(directory)]) == 1
    monkeypatch.setattr(runner, "preflight", Mock(side_effect=Blocked("missing model")))
    assert runner.main(["run", "--workdir", str(directory)]) == 2


@pytest.mark.parametrize(
    "local_only", [False, True], ids=["live-default", "replay-offline"]
)
def test_whisper_loader_forwards_offline_flag(monkeypatch, tmp_path, local_only):
    import sys

    from jarvis import paths

    calls = []

    def make_model(name, **kwargs):
        calls.append((name, kwargs))
        return object()

    monkeypatch.setitem(sys.modules, "ctranslate2", NS(get_cuda_device_count=lambda: 0))
    monkeypatch.setitem(sys.modules, "faster_whisper", NS(WhisperModel=make_model))
    monkeypatch.setattr(paths, "program_whisper_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(stt, "_enable_cuda_dlls", lambda: None)
    instance = stt.WhisperTranscriber(
        "local-test-model", device="cpu", local_files_only=local_only
    )
    assert instance.is_ready()
    assert calls == [
        (
            "local-test-model",
            {"device": "cpu", "compute_type": "int8", "local_files_only": local_only},
        )
    ]


def test_missing_vosk_fails_explicitly(monkeypatch):
    monkeypatch.setattr(stt, "Model", None)
    with pytest.raises(RuntimeError, match="Vosk"):
        stt.Listener("unused", file_mode=True)
