"""Loader/preview/stop races with controlled events; no network or audio devices."""
import threading
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from jarvis import tts
from jarvis.config import Config


class Engine:
    def __init__(self, name="piper", voice="ruslan"):
        self.name, self.voice = name, voice
        self.set_rate = Mock()
        self.set_wav_player = Mock()
        self.stop = Mock()
        self.synthesize = Mock(return_value=b"wav")


def ready(monkeypatch):
    monkeypatch.setattr(tts, "get_engine", lambda backend, voice, quality, rate: Engine(backend, voice))
    speaker = tts.Speaker({"tts_backend": "piper", "tts_voice": "ruslan"})
    speaker._play_wav = Mock()
    return speaker


def settle(speaker):
    assert speaker._engine_ready.wait(3)
    worker = speaker._settings_thread
    if worker is not None:
        worker.join(3)
        assert not worker.is_alive()
    assert not speaker.configuration_status()["pending"]


def wire(config, speaker):
    methods = {"tts_backend": speaker.switch_backend, "tts_voice": speaker.set_voice,
               "tts_voice_quality": speaker.set_quality, "voice_rate": speaker.set_rate}
    config.subscribe(lambda key, value: methods[key](value) if key in methods else None)


def test_switch_returns_before_model_finishes_and_does_not_mutate_active(monkeypatch):
    speaker = ready(monkeypatch)
    entered, release = threading.Event(), threading.Event()
    def load(backend, voice, quality, rate):
        entered.set()
        assert release.wait(3)
        return Engine(backend, "aidar")
    monkeypatch.setattr(tts, "get_engine", load)
    try:
        assert speaker.switch_backend("silero")
        assert entered.wait(1)
        assert speaker.configuration_status()["pending"]
        assert speaker._engine_name == "piper"
        assert speaker._ensure_engine(0) is False
    finally:
        release.set()
        settle(speaker)
    assert speaker._engine_name == "silero"
    assert speaker.voice == "aidar"


def test_initial_loader_cannot_overwrite_newer_voice_and_coalesces_edits(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def load(backend, voice, quality, rate):
        calls.append((backend, voice))
        if len(calls) == 1:
            entered.set()
            assert release.wait(3)
        return Engine(backend, voice)
    monkeypatch.setattr(tts, "get_engine", load)
    speaker = tts.Speaker({"tts_backend": "piper", "tts_voice": "ruslan"}, lazy=True)
    try:
        assert entered.wait(1)
        speaker.switch_backend("silero")
        speaker.set_voice("baya")
        speaker.set_rate(1.3)
        assert speaker._engine is None
        assert speaker._settings_thread.name == "tts-settings"
    finally:
        release.set()
        settle(speaker)
    assert calls == [("piper", "ruslan"), ("silero", "baya")]
    assert (speaker._engine_name, speaker.voice, speaker.rate) == ("silero", "baya", 1.3)


def test_superseded_download_is_discarded_and_latest_selection_wins(monkeypatch):
    speaker = ready(monkeypatch)
    entered, release = threading.Event(), threading.Event()
    calls = []
    def load(backend, voice, quality, rate):
        calls.append((backend, voice))
        if backend == "silero":
            entered.set()
            assert release.wait(3)
        return Engine(backend, voice)
    monkeypatch.setattr(tts, "get_engine", load)
    speaker.switch_backend("silero")
    try:
        assert entered.wait(1)
        speaker.switch_backend("piper")
        speaker.set_voice("dmitri")
        assert speaker._engine_name == "piper"
    finally:
        release.set()
        settle(speaker)
    assert calls == [("silero", "ruslan"), ("piper", "dmitri")]
    assert speaker._engine_name == "piper" and speaker.voice == "dmitri"


def test_failed_switch_rolls_config_back_to_actual_runtime(monkeypatch, tmp_path):
    config = Config(tmp_path / "config.json")
    config.update({"tts_backend": "piper", "tts_voice": "ruslan"})
    monkeypatch.setattr(tts, "get_engine", lambda *args: Engine())
    speaker = tts.Speaker(config)
    wire(config, speaker)
    monkeypatch.setattr(tts, "get_engine", lambda *args: None)
    assert config.set("tts_backend", "silero")
    settle(speaker)
    # Event is set before persisted rollback; join the captured worker if needed.
    for _ in range(100):
        if config.get("tts_backend") == "piper":
            break
        threading.Event().wait(.01)
    assert config.get("tts_backend") == speaker._backend == "piper"
    assert speaker._engine_name == "piper"
    assert speaker.configuration_status()["error"]


def test_rollback_cannot_overwrite_a_newer_user_edit(monkeypatch, tmp_path):
    config = Config(tmp_path / "config.json")
    config.update({"tts_backend": "piper", "tts_voice": "ruslan"})
    monkeypatch.setattr(tts, "get_engine", lambda *args: Engine())
    speaker = tts.Speaker(config)
    wanted = ("silero", "aidar", "medium", 1.15)
    active = ("piper", "ruslan", "medium", 1.15)
    config.update({"tts_backend": "piper", "tts_voice": "dmitri"})
    speaker._rollback_config(wanted, active)
    assert config.get("tts_voice") == "dmitri"


def test_slow_old_playback_prevents_engine_replacement(monkeypatch):
    speaker = ready(monkeypatch)
    old = speaker._engine
    speaker.wait_end = Mock(return_value=False)
    loader = Mock(side_effect=AssertionError("must not load over old playback"))
    monkeypatch.setattr(tts, "get_engine", loader)
    assert speaker.switch_backend("silero")
    settle(speaker)
    assert speaker._engine is old
    assert speaker._backend == "piper"
    assert speaker.configuration_status()["error"]
    loader.assert_not_called()


def test_stop_during_readiness_cancels_without_late_playback(monkeypatch):
    speaker = ready(monkeypatch)
    entered, release = threading.Event(), threading.Event()
    def ensure():
        entered.set()
        assert release.wait(3)
        return True
    speaker._ensure_engine = ensure
    result = []
    worker = threading.Thread(target=lambda: result.append(speaker.play_async("Проба")))
    worker.start()
    try:
        assert entered.wait(1)
        speaker.stop()
    finally:
        release.set()
        worker.join(2)
    assert result == [False]
    speaker._engine.synthesize.assert_not_called()


def test_cancelled_preview_is_not_queued_for_model_readiness(monkeypatch):
    speaker = ready(monkeypatch)
    cancel = threading.Event()
    cancel.set()
    assert speaker.play_async("Не говорить", cancel_event=cancel) is False
    speaker._engine.synthesize.assert_not_called()


def test_stop_during_synthesis_discards_wav_and_next_play_still_works(monkeypatch):
    speaker = ready(monkeypatch)
    entered, release = threading.Event(), threading.Event()
    def synthesize(*args):
        entered.set()
        assert release.wait(3)
        return b"wav"
    speaker._engine.synthesize.side_effect = synthesize
    assert speaker.play_async("Первая проба")
    try:
        assert entered.wait(1)
        speaker.stop()
    finally:
        release.set()
        assert speaker.wait_end(2)
    speaker._play_wav.assert_not_called()
    speaker._engine.synthesize.side_effect = None
    assert speaker.play_async("Следующая проба")
    assert speaker.wait_end(2)
    speaker._play_wav.assert_called_once()


def test_stream_does_not_overlap_a_stuck_worker(monkeypatch):
    speaker = ready(monkeypatch)
    speaker.wait_end = Mock(return_value=False)
    speaker._engine.speak_stream = Mock(side_effect=AssertionError("overlap"))
    assert speaker.speak_stream(iter(["Текст", " без звука"])) == "Текст без звука"
    speaker._engine.speak_stream.assert_not_called()


def test_quality_is_part_of_factory_cache_identity(monkeypatch):
    from jarvis.tts_engines import factory
    from jarvis.tts_engines import piper
    monkeypatch.setattr(factory, "_ENGINE_CACHE", {})
    create = Mock(side_effect=lambda *args: NS(args=args))
    monkeypatch.setattr(piper, "PiperEngine", create)
    a = factory._try_create("piper", "ruslan", "medium", 1.0)
    b = factory._try_create("piper", "ruslan", "high", 1.0)
    assert a is not b
    assert factory._try_create("piper", "ruslan", "medium", 1.0) is a
    assert create.call_count == 2


def test_silero_without_persisted_trust_never_prompts_or_downloads(monkeypatch, tmp_path):
    from jarvis.tts_engines.silero import SileroEngine
    engine = SileroEngine.__new__(SileroEngine)
    engine._lock, engine._model, engine._device = threading.Lock(), None, "cpu"
    load = Mock(side_effect=AssertionError("untrusted network/code execution"))
    engine._torch = NS(hub=NS(get_dir=lambda: str(tmp_path), load=load))
    with pytest.raises(RuntimeError, match="подтверждение доверия"):
        engine._load_model()
    load.assert_not_called()


def test_silero_uses_only_previously_approved_repo(monkeypatch, tmp_path):
    from jarvis.tts_engines.silero import SileroEngine
    (tmp_path / "trusted_list").write_text("snakers4_silero-models\n", encoding="utf-8")
    engine = SileroEngine.__new__(SileroEngine)
    engine._lock, engine._model, engine._device = threading.Lock(), None, "cpu"
    model = Mock()
    load = Mock(return_value=(model, None))
    engine._torch = NS(hub=NS(get_dir=lambda: str(tmp_path), load=load))
    engine._load_model()
    assert engine._model is model
    assert load.call_args.kwargs["trust_repo"] is True
    assert load.call_args.kwargs["repo_or_dir"] == "snakers4/silero-models"


def test_thread_start_failure_retains_runtime_and_does_not_leave_pending(monkeypatch):
    speaker = ready(monkeypatch)
    monkeypatch.setattr(tts.threading.Thread, "start", Mock(side_effect=RuntimeError("thread failure")))
    assert speaker.switch_backend("silero") is False
    assert speaker._engine_name == "piper"
    assert not speaker.configuration_status()["pending"]
    assert speaker.configuration_status()["error"]
    assert speaker._desired_settings[0] == "piper"


def test_failed_config_rollback_is_visible_in_log(monkeypatch, tmp_path, caplog):
    config = Config(tmp_path / "config.json")
    config.update({"tts_backend": "piper", "tts_voice": "ruslan"})
    monkeypatch.setattr(tts, "get_engine", lambda *args: Engine())
    speaker = tts.Speaker(config)
    active = speaker._active_settings
    wanted = ("silero", "aidar", "medium", 1.15)
    config.update({"tts_backend": "silero", "tts_voice": "aidar"})
    monkeypatch.setattr(config, "update", Mock(side_effect=OSError("disk")))
    speaker._rollback_config(wanted, active)
    assert "не удалось вернуть настройки" in caplog.text
