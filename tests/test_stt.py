"""stt.Listener: живое применение настроек (то, что раньше не работало).

Проверяем то, из-за чего настройки в GUI «ничего не делали»:
    - reload_vad()  — пересоздаёт VAD с новым порогом/адаптивностью и
      новым «хвостом» (vad_hangover_ms), не требуя перезапуска;
    - set_input_device() — помечает смену микрофона, и phrases()
      переоткрывает RawInputStream на новом устройстве;
    - _drain_audio() — чистит очередь и буфер фразы.

Микрофон не открывается и модели не грузятся: RawInputStream,
KaldiRecognizer, Model, VAD и SpeechHangover подменены заглушками.
"""

import importlib.util
import queue
import time
from threading import Event, Thread

import pytest

missing = [m for m in ("sounddevice", "vosk", "numpy")
           if importlib.util.find_spec(m) is None]
if missing:
    pytest.skip(f"нет {', '.join(missing)} — тесты stt пропущены",
                allow_module_level=True)

from jarvis import stt  # noqa: E402
from jarvis import vad as vad_mod  # noqa: E402


class FakeRec:
    """Заглушка KaldiRecognizer (Vosk): фраз не отдаёт."""

    def __init__(self):
        self.reset_calls = 0
        self.accepted = 0

    def AcceptWaveform(self, data):
        self.accepted += 1
        return False

    def Result(self):
        return '{"text": ""}'

    def FinalResult(self):
        return '{"text": ""}'

    def Reset(self):
        self.reset_calls += 1


class FakeVAD:
    """Заглушка Silero VAD: помнит параметры и счётчик reset()."""

    def __init__(self, sample_rate=16000, threshold=0.5, adaptive=True):
        self.sample_rate = sample_rate
        self.threshold = threshold
        self.adaptive = adaptive
        self._debug = False
        self.resets = 0

    def is_available(self):
        return True

    def is_speech(self, pcm):
        return True

    def reset(self):
        self.resets += 1


class FakeGate:
    """Заглушка SpeechHangover: считает блоки как настоящая."""

    def __init__(self, blocks=3):
        self.max_blocks = max(0, int(blocks))

    @staticmethod
    def blocks_for_ms(ms, block_ms):
        if block_ms <= 0:
            return 0
        return int(round(max(0.0, float(ms)) / block_ms))

    def feed(self, is_speech):
        return bool(is_speech)

    def reset(self):
        pass


class FakeStream:
    """Заглушка sd.RawInputStream: пишет, на каком устройстве открылись."""

    opened: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        FakeStream.opened.append(kwargs.get("device"))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Cfg(dict):
    """Мини-Config: обработчикам нужен только get()."""

    def get(self, key, default=None):
        return dict.get(self, key, default)


def _query_devices(index=None):
    devices = [
        {"name": "Микрофон (Realtek)", "max_input_channels": 2},
        {"name": "USB Headset", "max_input_channels": 1},
        {"name": "Динамики", "max_input_channels": 0},
    ]
    if isinstance(index, int):
        return devices[index]
    return devices


@pytest.fixture()
def cfg():
    return Cfg(vad_enabled=True, vad_threshold=0.5, vad_adaptive=True,
               vad_hangover_ms=1500)


@pytest.fixture()
def devices(monkeypatch):
    monkeypatch.setattr(stt.sd, "query_devices", _query_devices)
    monkeypatch.setattr(stt.sd, "default",
                        type("D", (), {"device": (0, 1)})())


@pytest.fixture()
def listener(monkeypatch, cfg, devices):
    monkeypatch.setattr(stt, "Model", lambda path: object())
    monkeypatch.setattr(stt, "KaldiRecognizer", lambda model, sr: FakeRec())
    # stt.py импортирует VAD/SpeechHangover к себе на уровень модуля —
    # их надо подменить там же (в set_vad_enabled импорт локальный).
    monkeypatch.setattr(stt, "VAD", FakeVAD)
    monkeypatch.setattr(stt, "SpeechHangover", FakeGate)
    monkeypatch.setattr(vad_mod, "VAD", FakeVAD)
    monkeypatch.setattr(vad_mod, "SpeechHangover", FakeGate)
    monkeypatch.setattr(FakeStream, "opened", [])
    return stt.Listener("C:/fake-model", 16000, None, config=cfg)


# =================================================================
# reload_vad
# =================================================================

def test_listener_starts_with_vad(listener):
    assert isinstance(listener.vad, FakeVAD)
    assert isinstance(listener._vad_gate, FakeGate)


def test_reload_vad_applies_new_threshold(listener, cfg):
    """Порог, сдвинутый в GUI, должен дойти до работающего VAD."""
    cfg["vad_threshold"] = 0.2
    listener.reload_vad()
    assert listener.vad.threshold == 0.2


def test_reload_vad_applies_adaptive(listener, cfg):
    cfg["vad_adaptive"] = False
    listener.reload_vad()
    assert listener.vad.adaptive is False


def test_reload_vad_rebuilds_hangover(listener, cfg):
    """«Хвост» 500 мс при блоке 500 мс = 1 блок."""
    cfg["vad_hangover_ms"] = 500
    listener.reload_vad()
    assert listener._vad_gate.max_blocks == 1


def test_hangover_blocks_from_config(listener, cfg):
    """1500 мс при блоке 500 мс = 3 блока (как в config по умолчанию)."""
    assert listener._vad_gate.max_blocks == 3


def test_reload_vad_skipped_when_disabled(listener, cfg):
    """VAD выключен — reload его не включает обратно."""
    listener.vad = None
    listener._vad_gate = None
    listener.vad_enabled = False
    listener.reload_vad()
    assert listener.vad is None


def test_vad_disabled_in_config(monkeypatch):
    """vad_enabled=false — VAD не создаётся вовсе."""
    monkeypatch.setattr(stt, "Model", lambda path: object())
    monkeypatch.setattr(stt, "KaldiRecognizer", lambda model, sr: FakeRec())
    monkeypatch.setattr(stt, "VAD", FakeVAD)
    monkeypatch.setattr(stt, "SpeechHangover", FakeGate)

    listener = stt.Listener("C:/fake-model", 16000, None,
                            config=Cfg(vad_enabled=False))

    assert listener.vad is None
    assert listener._vad_gate is None


# =================================================================
# set_input_device + _drain_audio
# =================================================================

def test_set_input_device_finds_index_by_name(listener):
    listener.set_input_device("usb")
    assert listener._device == 1
    assert listener._device_reload is True
    assert "USB Headset" in listener.device_name


def test_set_input_device_same_device_is_noop(listener):
    """Тот же микрофон — поток не трогаем (лишний рестарт не нужен)."""
    listener._device = 1
    listener.set_input_device("usb")
    assert listener._device_reload is False


def test_set_input_device_unknown_falls_back(listener):
    listener._device = 1
    listener.set_input_device("нет такого микрофона")
    assert listener._device is None
    assert listener._device_reload is True


def test_set_input_device_back_to_default(listener):
    listener._device = 1
    listener.set_input_device(None)
    assert listener._device is None
    assert listener._device_reload is True


def test_drain_audio_clears_queue_and_buffer(listener):
    listener._audio.put(b"chunk")
    listener._utt_buf.append(b"chunk")
    listener._utt_len = 5

    listener._drain_audio()

    assert listener._audio.empty()
    assert listener._utt_buf == []
    assert listener._utt_len == 0


def test_flush_clears_queue(listener):
    listener._audio.put(b"chunk")
    listener._utt_buf.append(b"chunk")
    listener._utt_len = 5

    listener.flush()

    assert listener._audio.empty()
    assert listener._utt_buf == []


# =================================================================
# phrases(): переоткрытие потока при смене микрофона
# =================================================================

def test_phrases_reopens_stream_on_device_change(monkeypatch, listener):
    """Смена микрофона на лету: поток закрывается и открывается заново."""
    monkeypatch.setattr(stt.sd, "RawInputStream", FakeStream)
    stop = Event()

    def _consume():
        for _ in listener.phrases(stop):
            break

    thread = Thread(target=_consume, daemon=True, name="test-listener")
    thread.start()

    # Ждём, пока поток откроется на «по умолчанию».
    for _ in range(100):
        if FakeStream.opened:
            break
        time.sleep(0.01)
    assert FakeStream.opened == [None], "поток не открылся"

    listener.set_input_device("usb")

    for _ in range(200):
        if len(FakeStream.opened) >= 2:
            break
        time.sleep(0.01)

    stop.set()
    thread.join(timeout=3.0)

    assert FakeStream.opened == [None, 1], "поток не переоткрылся"
    assert listener._rec.reset_calls >= 1, "Vosk не сброшен при смене микрофона"


def test_phrases_keeps_stream_without_device_change(monkeypatch, listener):
    """Без смены микрофона поток открывается ровно один раз."""
    monkeypatch.setattr(stt.sd, "RawInputStream", FakeStream)
    stop = Event()

    def _consume():
        for _ in listener.phrases(stop):
            break

    thread = Thread(target=_consume, daemon=True, name="test-listener")
    thread.start()
    for _ in range(100):
        if FakeStream.opened:
            break
        time.sleep(0.01)
    time.sleep(0.2)
    stop.set()
    thread.join(timeout=3.0)

    assert FakeStream.opened == [None]
