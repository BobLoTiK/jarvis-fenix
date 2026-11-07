"""Эталонный сигнал для AEC, когда звук идёт не через наш PCM (этап 4).

Наш плеер отдаёт PCM в `RenderTap` (`jarvis/echo.py`) — это лучший эталон.
Но SAPI, системные звуки и чужие приложения идут мимо него; тогда эталон нужно
взять из системы: WASAPI loopback в PortAudio отдаёт то, что уходит в динамики.

Здесь только:

- проба: умеет ли установленный `sounddevice`/PortAudio отдавать loopback
  (без установки драйверов и виртуальных кабелей — это решение человека);
- буфер эталона с задержкой: сигнал, который сейчас выйдет в динамики, уже
  слышен микрофону на несколько десятков миллисекунд позже;
- выбор источника: наш PCM, когда играем мы, иначе loopback.

По умолчанию ничего не включается (`aec_enabled=false` как и раньше).
"""

import logging
from array import array
from dataclasses import dataclass

log = logging.getLogger("jarvis.echo_loopback")


@dataclass(frozen=True)
class LoopbackProbe:
    """Результат пробы. `available=False` — это факт, а не ошибка."""

    available: bool
    reason: str
    device: int | None = None
    device_name: str = ""
    sample_rate: int = 48000


def _wasapi_hostapi(sd):
    try:
        hostapis = sd.query_hostapis()
    except Exception:
        return None
    for index, api in enumerate(hostapis):
        if "wasapi" in str(api.get("name", "")).lower():
            return index
    return None


def probe_loopback(*, sd_module=None) -> LoopbackProbe:
    """Проверить, даёт ли эта машина loopback-захват без установки чего-либо."""
    if sd_module is None:
        try:
            import sounddevice as sd_module
        except Exception:
            return LoopbackProbe(False, "sounddevice не установлен")
    settings_cls = getattr(sd_module, "WasapiSettings", None)
    if settings_cls is None:
        return LoopbackProbe(False, "в этой сборке PortAudio нет WasapiSettings")
    try:
        settings_cls(loopback=True)
    except Exception:
        return LoopbackProbe(False, "PortAudio не поддерживает loopback=True")
    hostapi = _wasapi_hostapi(sd_module)
    if hostapi is None:
        return LoopbackProbe(False, "WASAPI не найден среди hostapi")
    try:
        devices = sd_module.query_devices()
    except Exception:
        return LoopbackProbe(False, "список устройств недоступен")
    for index, device in enumerate(devices):
        if device.get("hostapi") != hostapi:
            continue
        if device.get("max_output_channels", 0) <= 0:
            continue
        try:
            rate = int(device.get("default_samplerate") or 48000)
        except (TypeError, ValueError):
            rate = 48000
        return LoopbackProbe(True, "loopback доступен", index,
                             str(device.get("name", "")), rate)
    return LoopbackProbe(False, "нет выходного устройства WASAPI")


def open_loopback_stream(probe: LoopbackProbe, callback, *, blocksize: int = 1024):
    """Открыть поток loopback. Исключение — честный отказ, а не тишина."""
    if not probe.available:
        raise RuntimeError(probe.reason)
    import sounddevice as sd

    try:
        settings = sd.WasapiSettings(loopback=True)
    except Exception as exc:
        raise RuntimeError(f"loopback недоступен: {exc}") from None
    stream = sd.InputStream(device=probe.device, channels=2,
                            samplerate=probe.sample_rate, blocksize=blocksize,
                            dtype="int16", extra_settings=settings,
                            callback=callback)
    stream.start()
    return stream


@dataclass(frozen=True)
class ReferenceChoice:
    """Чей сигнал считать эталоном прямо сейчас."""

    source: str          # "local" | "loopback" | "none"
    reason: str


def choose_reference(*, local_active: bool, loopback_active: bool) -> ReferenceChoice:
    """Наш PCM важнее: если играем мы, loopback не нужен (это тот же звук)."""
    if local_active:
        return ReferenceChoice("local", "звук идёт через наш плеер")
    if loopback_active:
        return ReferenceChoice("loopback", "звук идёт мимо плеера (SAPI/система)")
    return ReferenceChoice("none", "тишина")


class ReferenceDelay:
    """Буфер эталона: то, что выйдет в динамики, микрофон услышит позже.

    Простое кольцо в отсчётах: `push` — что уходит в динамики, `take` — что
    должно было звучать `delay_ms` назад. Так эталон и микрофон совпадают по
    времени без отдельной точной синхронизации.
    """

    def __init__(self, delay_ms: float = 40.0, rate: int = 16000):
        self.rate = max(1, int(rate))
        try:
            delay = float(delay_ms)
        except (TypeError, ValueError):
            delay = 40.0
        self.delay_ms = max(0.0, min(500.0, delay))
        self._delay_frames = int(self.rate * self.delay_ms / 1000.0)
        self._buffer = array("h")
        self._offset = 0      # абсолютный номер первого отсчёта в буфере
        self._read = 0        # сколько отсчётов эталона уже выдано
        self.max_frames = self.rate * 2

    @property
    def delay_frames(self) -> int:
        return self._delay_frames

    def push(self, pcm: bytes) -> None:
        if not pcm:
            return
        if len(pcm) % 2:
            pcm = pcm[:-1]
        self._buffer.frombytes(pcm)
        if len(self._buffer) > self.max_frames:
            drop = len(self._buffer) - self.max_frames
            del self._buffer[:drop]
            self._offset += drop

    def take(self, frames: int) -> bytes:
        """Эталон на `frames` отсчётов: сдвинут на задержку, недобор — нулями."""
        frames = max(0, int(frames))
        if frames == 0:
            return b""
        result = array("h", bytes(2 * frames))
        start = self._read - self._delay_frames
        for index in range(frames):
            source = start + index
            position = source - self._offset
            if 0 <= position < len(self._buffer):
                result[index] = self._buffer[position]
        self._read += frames
        return result.tobytes()

    def reset(self) -> None:
        self._buffer = array("h")
        self._offset = 0
        self._read = 0

    def __len__(self) -> int:
        return len(self._buffer)

    def __repr__(self) -> str:
        return (f"ReferenceDelay(delay={self.delay_ms:.0f} мс, "
                f"буфер={len(self._buffer)} отсчётов)")
