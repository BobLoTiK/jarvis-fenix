"""Nonverbal policy/mixing: synthetic PCM and fake output, no TTS weights or speakers."""

import ast
import hashlib
import io
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
import wave

import numpy as np
import pytest

from jarvis import audio_output, paths
from jarvis.nonverbal import Nonverbal, Reaction, SAMPLES
from jarvis.reply import Reply
from jarvis.tts import Speaker


def wav(samples=None, rate=16000, channels=1, width=2):
    samples = np.full((1600, channels), 0.1) if samples is None else samples
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(width)
        wf.setframerate(rate)
        if width == 1:
            raw = (np.asarray(samples) * 128 + 128).astype("uint8").tobytes()
        elif width == 3:
            x = (np.asarray(samples) * 8388607).astype("int32").reshape(-1)
            raw = (
                np.stack([x & 255, (x >> 8) & 255, (x >> 16) & 255], axis=1)
                .astype("uint8")
                .tobytes()
            )
        else:
            raw = (
                (np.asarray(samples) * (2 ** (8 * width - 1) - 1))
                .astype("<i2" if width == 2 else "<i4")
                .tobytes()
            )
        wf.writeframes(raw)
    return buf.getvalue()


@pytest.fixture
def policy(tmp_path, monkeypatch):
    for name in SAMPLES.values():
        (tmp_path / name).write_bytes(wav())
    monkeypatch.setattr(paths, "nonverbal_dir", lambda: tmp_path)
    clock = Mock(return_value=100)
    cfg = {"nonverbal_enabled": True, "nonverbal_probability": 1.0}
    return Nonverbal(
        cfg,
        clock=clock,
        rng=NS(random=lambda: 0, choice=lambda x: x[0]),
        mood_getter=lambda: "happy",
    )


def take(p, allowed=True):
    token = threading.Event()
    p.begin(token, allowed)
    return p.take(token)


def test_disabled_means_no_profile_or_asset_access(policy):
    policy.config["nonverbal_enabled"] = False
    policy.mood_getter = Mock(side_effect=AssertionError("disabled"))
    assert take(policy) is None
    policy.mood_getter.assert_not_called()


def test_only_explicit_chat_eligible(policy):
    assert take(policy, False) is None
    assert take(policy) is not None
    assert not Reply(text="Пароль?").allow_nonverbal
    assert not Reply(text="Не расслышал").allow_nonverbal


def test_one_reaction_per_reply_not_per_sentence(policy):
    token = threading.Event()
    policy.begin(token, True)
    assert policy.take(token) is not None
    policy.clock.return_value += 100
    assert policy.take(token) is None


def test_cooldown_is_global_across_replies(policy):
    assert take(policy)
    policy.clock.return_value = 144
    assert take(policy) is None
    policy.clock.return_value = 145
    assert take(policy)


def test_cancelled_reply_never_takes_sample(policy):
    token = threading.Event()
    token.set()
    policy.begin(token, True)
    assert policy.take(token) is None


@pytest.mark.parametrize(
    "state,expected",
    [
        ("happy", "laugh"),
        ("excited", "laugh"),
        ("neutral", "hmm"),
        ("bored", "hmm"),
        ("tired", "sigh"),
        ("annoyed", None),
        ("unknown", None),
    ],
)
def test_mood_policy(policy, state, expected):
    policy.mood_getter = lambda: state
    r = take(policy)
    assert (r.path.stem if r else None) == expected


def test_default_probability_does_not_react_every_time(policy):
    policy.config.pop("nonverbal_probability")
    policy.rng = NS(random=lambda: 0.3, choice=lambda x: x[0])
    assert take(policy) is None


def test_missing_sample_is_silent_fallback(policy):
    policy.mood_getter = lambda: "happy"
    (paths.nonverbal_dir() / "laugh.wav").unlink()
    assert take(policy) is None


@pytest.mark.parametrize(
    "gain,expected",
    [(-100, -18), (100, -12), (-16, -16), ("bad", -15), (float("nan"), -15)],
)
def test_gain_bounds(policy, gain, expected):
    policy.config["nonverbal_gain_db"] = gain
    assert take(policy).gain_db == expected


def test_thread_race_cannot_schedule_two_reactions(policy):
    results = []

    def worker():
        results.append(take(policy))

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(r is not None for r in results) == 1


def test_live_disable_and_enable(policy):
    policy.config["nonverbal_enabled"] = False
    assert take(policy) is None
    policy.config["nonverbal_enabled"] = True
    assert take(policy)


@pytest.mark.parametrize("width", [1, 2, 3, 4])
@pytest.mark.parametrize("channels", [1, 2])
def test_pcm_decode(width, channels):
    audio, rate = audio_output.decode_wav(wav(channels=channels, width=width))
    assert audio.shape == (1600, channels) and rate == 16000
    assert np.allclose(audio, 0.1, atol=0.01)


def test_mix_uses_relative_db_and_preserves_both_channels(tmp_path):
    speech = np.full((1600, 2), 0.1, dtype="float32")
    p = tmp_path / "reaction.wav"
    p.write_bytes(wav())
    mixed = audio_output.mix_reaction(speech, 16000, Reaction(p, -15))
    assert np.allclose(mixed, 0.1 + 0.1 * 10 ** (-15 / 20), atol=1e-5)
    assert np.all(speech == 0.1)


def test_sample_resampling_tail_and_clipping(tmp_path):
    p = tmp_path / "reaction.wav"
    p.write_bytes(wav(rate=8000))
    speech = np.full((1000, 1), 0.99, dtype="float32")
    mixed = audio_output.mix_reaction(speech, 16000, Reaction(p, -12))
    assert mixed.shape == (3200, 1)
    assert abs(mixed).max() <= 0.981


@pytest.mark.parametrize(
    "data",
    [b"bad wav", b"", wav(samples=np.zeros((1600, 1)))],
    ids=["bad-wav", "empty", "silent-wav"],
)
def test_missing_or_bad_or_silent_sample_leaves_speech_intact(tmp_path, data):
    p = tmp_path / "reaction.wav"
    p.write_bytes(data)
    speech = np.full((1600, 1), 0.1, dtype="float32")
    assert audio_output.mix_reaction(speech, 16000, Reaction(p, -15)) is speech


def test_reaction_never_plays_without_speech(tmp_path):
    p = tmp_path / "reaction.wav"
    p.write_bytes(wav())
    speech = np.zeros((1600, 1), dtype="float32")
    assert audio_output.mix_reaction(speech, 16000, Reaction(p, -15)) is speech


def test_output_uses_single_stream_and_shared_stop_token():
    token = threading.Event()
    stream = Mock()
    stream.__enter__ = Mock(return_value=stream)
    stream.__exit__ = Mock(return_value=False)
    stream.write.side_effect = lambda _: token.set()
    sd = NS(OutputStream=Mock(return_value=stream))
    with patch.dict(sys.modules, {"sounddevice": sd}):
        audio_output.play_wav(wav(), token)
    sd.OutputStream.assert_called_once()
    stream.write.assert_called_once()
    assert sd.OutputStream.call_args.kwargs["dtype"] == "float32"


def test_cancel_before_play_does_not_open_device():
    token = threading.Event()
    token.set()
    sd = NS(OutputStream=Mock())
    with patch.dict(sys.modules, {"sounddevice": sd}):
        audio_output.play_wav(wav(), token)
    sd.OutputStream.assert_not_called()


def test_speaker_routes_sample_through_common_player(policy):
    speaker = Speaker.__new__(Speaker)
    speaker._nonverbal = policy
    token = threading.Event()
    policy.begin(token, True)
    with patch("jarvis.audio_output.play_wav") as play:
        speaker._play_wav(wav(), token)
    assert play.call_args.args[1] is token
    assert play.call_args.args[2].path.name == "laugh.wav"


@pytest.mark.parametrize(
    "module,cls,args",
    [
        ("piper", "PiperEngine", ("Привет.",)),
        ("silero", "SileroEngine", ("Привет.", "aidar", 1.0)),
    ],
)
def test_stream_engines_share_speakers_mixer(module, cls, args):
    import importlib

    engine_class = getattr(importlib.import_module("jarvis.tts_engines." + module), cls)
    engine = engine_class.__new__(engine_class)
    engine.synthesize = Mock(return_value=wav())
    output = Mock()
    engine.set_wav_player(output)
    token = threading.Event()
    engine._play(*args, token)
    output.assert_called_once_with(engine.synthesize.return_value, token)


def test_packaged_samples_have_provenance_and_valid_pcm():
    root = Path(__file__).resolve().parents[1] / "assets/nonverbal"
    rows = json.loads((root / "sources.json").read_text(encoding="utf-8"))["samples"]
    assert {r["file"] for r in rows} == set(SAMPLES.values())
    for r in rows:
        data = (root / r["file"]).read_bytes()
        assert r["license"] == "CC0-1.0" and r["source"].startswith(
            "https://freesound.org/"
        )
        assert hashlib.sha256(data).hexdigest() == r["sha256"]
        audio, rate = audio_output.decode_wav(data)
        assert 0 < len(audio) / rate <= 3 and abs(audio).max() > 0.01


def test_gui_checkbox_saves_setting_without_restart():
    source = Path(__file__).resolve().parents[1] / "jarvis/gui.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    cls = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "FenixGUI"
    )
    method = next(
        n
        for n in cls.body
        if isinstance(n, ast.FunctionDef) and n.name == "_on_nonverbal_enabled"
    )
    env = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), env)
    gui = NS(config=NS(set=Mock()))
    env["_on_nonverbal_enabled"](gui, NS(control=NS(value=True)))
    gui.config.set.assert_called_once_with("nonverbal_enabled", True)


def test_device_open_failure_falls_back_before_any_output():
    sd = NS(OutputStream=Mock(side_effect=OSError("no device")))
    token = threading.Event()
    with (
        patch.dict(sys.modules, {"sounddevice": sd}),
        patch("jarvis.audio_output._play_windows") as fallback,
    ):
        audio_output.play_wav(wav(), token)
    fallback.assert_called_once()
    assert fallback.call_args.args[-1] is token


def test_partial_write_failure_is_never_replayed():
    token = threading.Event()
    stream = Mock()
    stream.__enter__ = Mock(return_value=stream)
    stream.__exit__ = Mock(return_value=False)
    stream.write.side_effect = OSError("device lost")
    sd = NS(OutputStream=Mock(return_value=stream))
    with (
        patch.dict(sys.modules, {"sounddevice": sd}),
        patch("jarvis.audio_output._play_windows") as fallback,
    ):
        with pytest.raises(OSError):
            audio_output.play_wav(wav(), token)
    fallback.assert_not_called()


@pytest.mark.parametrize("chat", [False, True])
@pytest.mark.parametrize("stream", [False, True])
def test_handler_marks_only_chat_replies_eligible(chat, stream):
    from collections import deque
    from jarvis.intents.handler import IntentHandler

    h = IntentHandler.__new__(IntentHandler)
    h._pending_password = None
    h.mode = "combo"
    h._recent_phrases = deque()
    h.dialog = deque()

    def handle(_):
        h.last_was_chat = chat
        return iter(["Ответ."]) if stream else "Ответ."

    h._handle_single = handle
    with patch("jarvis.memory.append"), patch("jarvis.mood.apply_from_text"):
        reply = h.handle("Расскажи о космосе")
    assert reply.allow_nonverbal is chat


def test_installer_copies_all_nonverbal_resources():
    installer = Path(__file__).resolve().parents[1] / "installer.iss"
    text = installer.read_text(encoding="utf-8")
    assert 'Source: "{#PayloadDir}\\*"' in text
    from scripts.release_payload import collect_payload
    files = collect_payload(installer.parent, include_exe=False)
    for name in ("hmm.wav", "laugh.wav", "sigh.wav", "yawn.wav", "sources.json"):
        assert f"assets/nonverbal/{name}" in files


def test_token_sessions_are_not_retained_after_reply(policy):
    import gc

    token = threading.Event()
    policy.begin(token, True)
    assert len(policy._sessions) == 1
    del token
    gc.collect()
    assert not policy._sessions


def test_optional_policy_error_never_suppresses_speech():
    speaker = Speaker.__new__(Speaker)
    speaker._nonverbal = NS(take=Mock(side_effect=OSError("profile unavailable")))
    token = threading.Event()
    data = wav()
    with patch("jarvis.audio_output.play_wav") as play:
        speaker._play_wav(data, token)
    play.assert_called_once_with(data, token, None)


def test_windows_fallback_shares_stop_and_removes_temporary_wav(tmp_path, monkeypatch):
    import tempfile

    token = threading.Event()
    seen = []

    def play(name, flags):
        if name is not None:
            path = Path(name)
            assert path.is_file()
            seen.append(path)
            audio_output.decode_wav(path.read_bytes())
            token.set()

    winsound = NS(
        PlaySound=Mock(side_effect=play), SND_FILENAME=1, SND_ASYNC=2, SND_NODEFAULT=4
    )
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    with patch.dict(sys.modules, {"winsound": winsound}):
        audio_output._play_windows(
            np.full((1600, 1), 0.1, dtype="float32"), 16000, token
        )
    assert len(seen) == 1 and not seen[0].exists()
    assert winsound.PlaySound.call_args.args == (None, 0)
