"""Эталон для AEC: проба loopback, буфер задержки и выбор источника."""
from array import array

from jarvis.echo_loopback import (LoopbackProbe, ReferenceDelay, choose_reference,
                                  open_loopback_stream, probe_loopback)


class FakeSettings:
    def __init__(self, loopback=False, fail=False):
        if fail:
            raise RuntimeError("нет такого режима")
        self.loopback = loopback


class FakeSD:
    WasapiSettings = FakeSettings

    def __init__(self, devices, hostapis=None):
        self._devices = devices
        self._hostapis = hostapis if hostapis is not None else [
            {"name": "MME"}, {"name": "Windows WASAPI"}]

    def query_hostapis(self):
        return self._hostapis

    def query_devices(self):
        return self._devices


def test_probe_without_sounddevice_is_honest(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sounddevice":
            raise ImportError("нет пакета")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    probe = probe_loopback()
    assert probe.available is False and "sounddevice" in probe.reason


def test_probe_without_wasapi_settings():
    probe = probe_loopback(sd_module=type("SD", (), {})())
    assert probe.available is False and "WasapiSettings" in probe.reason


def test_probe_with_settings_that_reject_loopback():
    sd = FakeSD([{"name": "Колонки", "hostapi": 1, "max_output_channels": 2,
                  "default_samplerate": 48000}])
    sd.WasapiSettings = lambda **kwargs: FakeSettings(fail=True)
    probe = probe_loopback(sd_module=sd)
    assert probe.available is False and "loopback=True" in probe.reason


def test_probe_without_wasapi_hostapi():
    sd = FakeSD([{"name": "Колонки", "hostapi": 0, "max_output_channels": 2,
                  "default_samplerate": 48000}], hostapis=[{"name": "MME"}])
    probe = probe_loopback(sd_module=sd)
    assert probe.available is False and "WASAPI" in probe.reason


def test_probe_finds_wasapi_output_device():
    sd = FakeSD([
        {"name": "Микрофон", "hostapi": 1, "max_output_channels": 0,
         "max_input_channels": 2, "default_samplerate": 48000},
        {"name": "Динамики (Realtek)", "hostapi": 1, "max_output_channels": 2,
         "default_samplerate": 44100},
    ])
    probe = probe_loopback(sd_module=sd)
    assert probe.available is True
    assert probe.device == 1 and "Realtek" in probe.device_name
    assert probe.sample_rate == 44100


def test_open_stream_refuses_without_probe():
    try:
        open_loopback_stream(LoopbackProbe(False, "WASAPI нет"), lambda *a: None)
    except RuntimeError as exc:
        assert "WASAPI нет" in str(exc)
    else:
        raise AssertionError("должен был отказать")


def test_reference_choice_prefers_our_own_pcm():
    assert choose_reference(local_active=True, loopback_active=True).source == "local"
    assert choose_reference(local_active=False, loopback_active=True).source == "loopback"
    assert choose_reference(local_active=False, loopback_active=False).source == "none"


def test_reference_delay_aligns_signal_with_delay():
    delay = ReferenceDelay(delay_ms=40, rate=16000)
    assert delay.delay_frames == 640
    samples = array("h", [i % 30000 for i in range(2000)])
    delay.push(samples.tobytes())
    head = array("h")
    head.frombytes(delay.take(640))
    assert head.tolist() == [0] * 640  # первые 40 мс — сигнал ещё «в пути»
    rest = array("h")
    rest.frombytes(delay.take(160))
    assert rest.tolist() == samples[:160].tolist()


def test_reference_delay_returns_silence_when_not_ready():
    delay = ReferenceDelay(delay_ms=100, rate=8000)
    delay.push(b"\x01\x00" * 10)
    assert delay.take(5) == b"\x00\x00" * 5
    assert len(delay) == 10


def test_reference_delay_pads_missing_frames_with_zeros():
    delay = ReferenceDelay(delay_ms=0, rate=8000)
    delay.push(b"\x05\x00\x06\x00")
    chunk = array("h")
    chunk.frombytes(delay.take(4))
    assert chunk.tolist() == [5, 6, 0, 0]


def test_reference_delay_handles_odd_bytes_and_reset():
    delay = ReferenceDelay(delay_ms=0, rate=8000)
    delay.push(b"\x01\x00\x02")  # непарный байт отбрасывается
    assert len(delay) == 1
    delay.reset()
    assert len(delay) == 0 and delay.take(2) == b"\x00\x00" * 2


def test_reference_delay_keeps_buffer_bounded():
    delay = ReferenceDelay(delay_ms=0, rate=1000)
    delay.push(b"\x00\x00" * 5000)
    assert delay.max_frames == 2000 and len(delay) == 2000


def test_reference_delay_survives_trim():
    delay = ReferenceDelay(delay_ms=100, rate=100)  # 10 отсчётов задержки
    delay.push(b"\x01\x00" * 500)
    assert len(delay) <= delay.max_frames
    out = array("h")
    out.frombytes(delay.take(320))
    assert len(out) == 320
