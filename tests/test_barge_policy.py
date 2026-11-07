"""Правило очерёдности разговора: таблица вердиктов и один хук в Listener."""
import time

from jarvis.barge import BargePolicy
from jarvis.config import Config
from jarvis.stt import Listener


class FakeConfig:
    def __init__(self, **data):
        self.data = data

    def get(self, key, default=None):
        return self.data.get(key, default)


def test_defaults_match_previous_behaviour():
    policy = BargePolicy()
    assert policy.min_after_tts_sec == 0.35
    assert policy.min_speech_ms == 150
    assert policy.evaluate(rms=200, threshold=100, speech_ms=200, tts_elapsed=1.0) == "barge"


def test_quiet_echo_does_not_barge():
    policy = BargePolicy()
    assert policy.evaluate(rms=110, threshold=100, speech_ms=300, tts_elapsed=1.0) == "quiet"
    assert policy.evaluate(rms=100, threshold=100, speech_ms=300, tts_elapsed=1.0) == "quiet"


def test_own_tail_right_after_tts_start_does_not_barge():
    policy = BargePolicy()
    assert policy.evaluate(rms=500, threshold=100, speech_ms=300, tts_elapsed=0.1) == "too_soon"
    assert policy.evaluate(rms=500, threshold=100, speech_ms=300, tts_elapsed=0.34) == "too_soon"


def test_short_click_does_not_barge():
    policy = BargePolicy()
    assert policy.evaluate(rms=500, threshold=100, speech_ms=120, tts_elapsed=1.0) == "short"


def test_config_overrides_and_invalid_values_fall_back():
    policy = BargePolicy.from_config(FakeConfig(barge_min_after_tts_sec=0.6,
                                                barge_min_speech_ms=200,
                                                barge_level_margin=1.5))
    assert policy.min_after_tts_sec == 0.6
    assert policy.min_speech_ms == 200
    assert policy.level_margin == 1.5
    fallback = BargePolicy.from_config(FakeConfig(barge_min_after_tts_sec="мусор",
                                                  barge_min_speech_ms=None,
                                                  barge_level_margin=float("nan")))
    assert fallback == BargePolicy()


def listener_stub(tmp_path, *, enabled: bool):
    listener = object.__new__(Listener)
    listener._config = Config(tmp_path / "config.json")
    listener._config._data["barge_policy_enabled"] = enabled
    listener._barge_policy = None
    listener.barge_enabled = True
    listener.barge_flag = False
    listener._speech_active = True
    listener._speech_started_at = time.time() - 2.0
    listener._echo_done = True
    listener._echo_baseline = 100
    listener._barge_threshold = 100
    listener._barge_speech_ms = 0
    listener._block_ms = 128
    listener._echo_window_samples = []
    listener._last_barge_log = 0.0
    return listener


def test_policy_off_keeps_previous_barge_behaviour(tmp_path):
    listener = listener_stub(tmp_path, enabled=False)
    listener._barge_speech_ms = 150
    listener._process_barge(1000)
    assert listener.barge_flag is True


def test_policy_on_ignores_quiet_echo(tmp_path):
    listener = listener_stub(tmp_path, enabled=True)
    listener._barge_speech_ms = 150
    listener._process_barge(105)  # выше порога, но без запаса
    assert listener.barge_flag is False


def test_policy_on_accepts_loud_long_speech(tmp_path):
    listener = listener_stub(tmp_path, enabled=True)
    listener._barge_speech_ms = 150
    listener._process_barge(400)
    assert listener.barge_flag is True


def test_policy_on_ignores_own_tail_in_first_ms(tmp_path):
    listener = listener_stub(tmp_path, enabled=True)
    listener._speech_started_at = time.time()  # TTS только начался
    listener._barge_speech_ms = 150
    listener._process_barge(1000)
    assert listener.barge_flag is False
