"""Native sound settings + real worker boundaries; no microphone or actual TTS."""
import queue
import sys
import threading
import time
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
ft = pytest.importorskip("flet")
from jarvis import gui as module, gui_audio as audio, mood, profile
from jarvis.config import Config


@pytest.fixture
def gui(tmp_path, monkeypatch):
    config = Config(tmp_path / "config.json")
    core = NS(listener=NS(device_name="USB microphone", current_rms=800, peak=1400,
        utterances=7, muted=False, level_updated_at=time.monotonic()),
        listening_enabled=True, speaker=NS(is_playing=Mock(return_value=False),
        stop=Mock(), _engine_name="piper"), cmd_lock=threading.Lock(),
        say=Mock(return_value=False), handler=NS(_pending_password=None, _pending_question=None))
    window = module.FenixGUI(core, config)
    monkeypatch.setattr(window, "_get_voice_options", lambda: [ft.dropdown.Option("ruslan", "Руслан")])
    # CI does not install PortAudio; device enumeration is an explicit transport fake.
    monkeypatch.setitem(sys.modules, "sounddevice", NS(query_devices=lambda: [
        {"name": "USB microphone", "max_input_channels": 1}]))
    window._build_main_tab()
    window._build_mic_tab()
    window._build_audio_tab()
    yield window
    sound = window._sound()
    if sound.thread:
        sound.thread.join(4)
    profile.unsubscribe(window._on_profile_switch)
    mood.unsubscribe(window._on_mood_change)
    module._apply_palette("dark")


def finish(gui):
    sound = gui._sound()
    sound.thread.join(4)
    assert not sound.thread.is_alive()
    while not gui._queue.empty():
        kind, value = gui._queue.get_nowait()
        if kind == "sound_result":
            sound.apply_result(*value)
    assert sound.busy is None
    assert sound.lock.acquire(blocking=False)
    sound.lock.release()


def sample_clock(gui, monkeypatch, rms=800, callback=None):
    clock = NS(now=time.monotonic() + .1)
    def sleep(seconds):
        clock.now += seconds
        gui.jarvis.listener.level_updated_at = clock.now
        gui.jarvis.listener.current_rms = rms
        if callback:
            callback()
    monkeypatch.setattr(audio, "time", NS(monotonic=lambda: clock.now, sleep=sleep))


def test_mic_controls_keep_full_name_and_refresh_without_saving(gui, monkeypatch):
    name = "USB microphone " + "long device name " * 5
    monkeypatch.setattr("sounddevice.query_devices", lambda: [{"name": name, "max_input_channels": 1}])
    before = gui.config.get("input_device")
    gui._sound().refresh_devices()
    assert name in [x.key for x in gui._mic_dropdown.options]
    assert gui.config.get("input_device") == before
    assert gui._mic_emotion_text is None


def test_missing_saved_device_is_visible_and_not_replaced(gui):
    gui.config.set("input_device", "Missing USB")
    gui._build_mic_tab()
    assert gui._mic_dropdown.value == "Missing USB"
    assert "не найдено" in gui._mic_dropdown.options[-1].text
    assert gui.config.get("input_device") == "Missing USB"


def test_live_level_uses_current_rms_not_historical_peak(gui):
    gui.jarvis.listener.current_rms = 0
    gui.jarvis.listener.peak = 32767
    gui._update_mic_level()
    assert gui._mic_level_bar.value == 0
    assert "ожидание" in gui._mic_status_text.value
    gui.jarvis.listener.current_rms = 900
    gui._update_mic_level()
    assert gui._mic_level_bar.value == .45
    assert "есть сигнал" in gui._mic_status_text.value


def test_stale_meter_and_paused_input_never_report_success(gui):
    gui.jarvis.listener.level_updated_at = 0
    gui._update_mic_level()
    assert "нет свежих" in gui._mic_status_text.value
    assert gui._mic_level_bar.value == 0
    gui.jarvis.listening_enabled = False
    gui._update_mic_level()
    assert "пауза" in gui._mic_status_text.value
    assert gui._on_mic_test(None) is False


@pytest.mark.parametrize("rms,needle", [(800, "заметен"), (250, "тихий"), (0, "заметного сигнала нет")])
def test_windowed_mic_test_preserves_listener_stats(gui, monkeypatch, rms, needle):
    sample_clock(gui, monkeypatch, rms)
    before = gui.jarvis.listener.peak, gui.jarvis.listener.utterances
    assert gui._on_mic_test(None)
    finish(gui)
    assert needle in gui._mic_test_result.value
    assert (gui.jarvis.listener.peak, gui.jarvis.listener.utterances) == before
    gui.jarvis.say.assert_not_called()


def test_mic_test_rejects_cached_samples(gui, monkeypatch):
    monkeypatch.setattr(audio, "time", NS(monotonic=time.monotonic, sleep=lambda s: None))
    assert gui._on_mic_test(None)
    finish(gui)
    assert "Нет свежих данных" in gui._mic_test_result.value


def test_changing_input_during_test_invalidates_result(gui, monkeypatch):
    sample_clock(gui, monkeypatch, callback=lambda: gui.config.set("input_device", "new input"))
    assert gui._on_mic_test(None)
    finish(gui)
    assert "Вход изменился" in gui._mic_test_result.value


def test_voice_test_uses_existing_say_without_handler_or_history(gui):
    before = list(gui._messages)
    assert gui._sound().test_voice()
    finish(gui)
    [(reply,), kwargs] = gui.jarvis.say.call_args
    assert reply.text == audio.TEST_PHRASE
    assert reply.allow_nonverbal is False
    assert gui._messages == before
    assert "Проба завершена" in gui._sound().voice_result.value
    assert gui.jarvis.cmd_lock.acquire(blocking=False)
    gui.jarvis.cmd_lock.release()
    assert gui._command_lock.acquire(blocking=False)
    gui._command_lock.release()


@pytest.mark.parametrize("pending", ["_pending_password", "_pending_question"])
def test_pending_command_blocks_voice_preview(gui, pending):
    setattr(gui.jarvis.handler, pending, {"action": "do-not-touch"})
    gui._sound().test_voice()
    finish(gui)
    gui.jarvis.say.assert_not_called()
    assert "Сначала завершите" in gui._sound().voice_result.value


def test_voice_does_not_queue_behind_core_or_gui_lock(gui):
    for lock in (gui.jarvis.cmd_lock, gui._command_lock):
        lock.acquire()
        try:
            gui._sound().test_voice()
            finish(gui)
            gui.jarvis.say.assert_not_called()
            assert "занят" in gui._sound().voice_result.value
        finally:
            lock.release()


def test_preview_failure_sanitized_and_locks_released(gui):
    gui.jarvis.say.side_effect = RuntimeError("private payload")
    gui._sound().test_voice()
    finish(gui)
    assert "private payload" not in gui._sound().voice_result.value
    assert "Не удалось" in gui._sound().voice_result.value
    assert gui.jarvis.cmd_lock.acquire(blocking=False)
    gui.jarvis.cmd_lock.release()


def test_duplicate_test_click_and_theme_rebuild(gui):
    entered, release = threading.Event(), threading.Event()
    def say(reply):
        entered.set()
        assert release.wait(3)
    gui.jarvis.say.side_effect = say
    sound = gui._sound()
    assert sound.test_voice()
    try:
        assert entered.wait(2)
        assert sound.test_voice() is False
        assert sound.test_mic() is False
        module._apply_palette("light")
        gui._build_mic_tab(); gui._build_audio_tab()
        assert sound.voice_test_button.disabled and sound.mic_test_button.disabled
        assert sound is gui._sound()
    finally:
        release.set()
        finish(gui)
    assert not sound.voice_test_button.disabled
    assert gui.jarvis.say.call_count == 1


def test_thread_start_failure_recovers(gui, monkeypatch):
    monkeypatch.setattr(audio.threading.Thread, "start", Mock(side_effect=RuntimeError("failed")))
    assert gui._sound().test_voice() is False
    assert gui._sound().busy is None
    assert not gui._sound().voice_test_button.disabled
    # A never-started Thread cannot be joined by the fixture.
    gui._sound().thread = None


def test_voice_picker_synced_to_chat_and_rate_saved(gui):
    gui._sound().change_voice(NS(control=NS(value="irina")))
    assert gui.config.get("tts_voice") == "irina"
    assert gui._main_voice_dropdown.value == "irina"
    assert gui._sound().voice_dropdown.value == "irina"
    gui._sound().change_rate(NS(control=NS(value=1.3)))
    assert gui.config.get("voice_rate") == 1.3
    assert "1.30" in gui._sound().rate_label.value


def test_stop_uses_existing_speaker(gui):
    gui._on_stop_speech()
    gui.jarvis.speaker.stop.assert_called_once()


def test_listener_level_heartbeat_updates_even_when_muted():
    import numpy as np
    from jarvis.stt import Listener
    listener = NS(peak=0, current_rms=0, level_updated_at=0,
                  muted=True, _process_barge=Mock())
    Listener._callback(listener, np.full(32, 600, dtype="<i2").tobytes(), 32, None, None)
    assert listener.current_rms == 600
    assert listener.level_updated_at > 0
    listener._process_barge.assert_called_once_with(600)


def test_voice_preview_does_not_interrupt_existing_speech(gui):
    gui.jarvis.speaker.is_playing.return_value = True
    gui._sound().test_voice()
    finish(gui)
    gui.jarvis.say.assert_not_called()
    gui.jarvis.speaker.stop.assert_not_called()
    assert "Дождитесь окончания" in gui._sound().voice_result.value


def test_disappeared_listener_clears_old_meter_metadata(gui):
    gui._update_mic_level()
    gui.jarvis.listener = None
    gui._update_mic_level()
    assert "слушатель не запущен" in gui._mic_device_text.value
    assert gui._mic_peak_text.value.endswith("—")
    assert gui._mic_utt_text.value.endswith("—")
