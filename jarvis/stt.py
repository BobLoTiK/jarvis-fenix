"""Распознавание речи.

Гибридная схема: Vosk (стриминг, лёгкий) непрерывно слушает и ловит wake-слово,
а точную расшифровку команды делает Whisper (faster-whisper, int8, CPU) по
аудиобуферу той же фразы. Если Whisper выключен/не встал — работаем по Vosk.

Barge-in: во время речи Феникса микрофон НЕ глушится, а следит за громкостью.
Первые ECHO_WINDOW_SEC секунд — слепое окно (эхо не меряется).
Потом замеряется фоновое эхо от колонок и ставится порог = echo * barge_mult.
Если юзер громче — выставляется barge_flag.

Параметры barge-in читаются из config.json:
    barge_enabled       (bool)  — включён ли
    barge_mult          (float) — множитель эха (порог = echo * barge_mult)
    barge_min_threshold (int)   — минимальный порог (для наушников)
    barge_min_ms        (int)   — минимум мс речи юзера
"""

import json
import logging
import os
import queue
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
from vosk import KaldiRecognizer, Model, SetLogLevel

log = logging.getLogger("jarvis.stt")

TURBO_MODEL = "deepdml/faster-whisper-large-v3-turbo-ct2"

# Промпт для Whisper — держим его на русском
WHISPER_PROMPT = (
    "Это русская речь. Пожалуйста, транскрибируй текст на русском языке. "
    "Частые слова: Феникс, Джарвис, открой, закрой, найди, включи, выключи, "
    "сверни, разверни, продолжай, напечатай, расскажи, покажи, погода, "
    "напоминание, задача, голос, режим, паки."
)

# Barge-in — константы (дефолты, если не заданы в config.json)
ECHO_WINDOW_SEC = 0.5      # слепое окно — не меряем эхо
BARGE_LOG_INTERVAL = 0.5   # как часто логировать


def _enable_cuda_dlls() -> None:
    try:
        import nvidia
    except ImportError:
        return
    base = Path(nvidia.__path__[0])
    dirs = [str(p) for p in (base / "cublas" / "bin", base / "cudnn" / "bin") if p.exists()]
    if dirs:
        os.environ["PATH"] = os.pathsep.join(dirs) + os.pathsep + os.environ["PATH"]


class Listener:
    def __init__(self, model_dir: Path, sample_rate: int = 16000, device=None):
        SetLogLevel(-1)
        log.info("Загрузка модели Vosk из %s", model_dir)
        self._model = Model(str(model_dir))
        self._rec = KaldiRecognizer(self._model, sample_rate)
        self._sample_rate = sample_rate
        self._device = self.resolve_device(device)
        self.device_name = self._current_device_name()
        log.info("Микрофон: %s", self.device_name)
        self._audio: queue.Queue[bytes] = queue.Queue()
        self._utt_buf: list[bytes] = []
        self._utt_len = 0
        self.peak = 0
        self.utterances = 0

        try:
            cfg_path = Path(__file__).resolve().parent.parent / "config.json"
            _cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
        except Exception:
            log.exception("Не удалось прочитать config.json для barge-in, использую дефолты")
            _cfg = {}

        self.barge_enabled = bool(_cfg.get("barge_enabled", True))
        self._barge_mult = float(_cfg.get("barge_mult", 1.8))
        self._barge_min_threshold = int(_cfg.get("barge_min_threshold", 400))
        self._barge_min_ms = int(_cfg.get("barge_min_ms", 150))

        self.muted = False
        self.barge_flag = False
        self._barge_threshold = self._barge_min_threshold
        self._barge_echo = 0
        self._barge_echo_samples = []
        self._barge_echo_done = False
        self._barge_speech_ms = 0
        self._speech_active = False
        self._speech_started_at = 0.0
        self._last_barge_log = 0.0
        self._block_size = 8000

        log.info("Barge-in: enabled=%s, mult=%.1f, min_thr=%d, min_ms=%d",
                 self.barge_enabled, self._barge_mult,
                 self._barge_min_threshold, self._barge_min_ms)

    def barge_start(self) -> None:
        self.barge_flag = False
        self._barge_echo = 0
        self._barge_echo_samples = []
        self._barge_echo_done = False
        self._barge_speech_ms = 0
        self._speech_active = True
        self._speech_started_at = time.time()
        self._last_barge_log = 0.0
        self._barge_threshold = self._barge_min_threshold
        log.info("Barge-in: старт (порог %d)", self._barge_threshold)

    def barge_end(self) -> None:
        self._speech_active = False
        log.info("Barge-in: стоп (эхо=%d, порог=%d, речь=%d мс)",
                 self._barge_echo, self._barge_threshold, self._barge_speech_ms)

    def barge_reset(self) -> None:
        self.barge_flag = False
        self._barge_speech_ms = 0

    def _process_barge(self, rms: int) -> None:
        if not self._speech_active or not self.barge_enabled:
            return

        now = time.time()
        elapsed = now - self._speech_started_at

        if elapsed < ECHO_WINDOW_SEC:
            return

        if not self._barge_echo_done:
            self._barge_echo_samples.append(rms)
            if elapsed >= ECHO_WINDOW_SEC + 0.5:
                if self._barge_echo_samples:
                    arr = sorted(self._barge_echo_samples)
                    idx = int(len(arr) * 0.7)
                    self._barge_echo = arr[min(idx, len(arr) - 1)]
                self._barge_threshold = max(
                    int(self._barge_echo * self._barge_mult),
                    self._barge_min_threshold,
                )
                self._barge_echo_done = True
                log.info("Barge-in: эхо=%d, порог=%d",
                         self._barge_echo, self._barge_threshold)
            return

        if rms > self._barge_threshold:
            self._barge_speech_ms += int(self._block_size / 16)
            if self._barge_speech_ms >= self._barge_min_ms:
                self.barge_flag = True
        else:
            self._barge_speech_ms = 0

        if now - self._last_barge_log >= BARGE_LOG_INTERVAL:
            log.info("barge: peak=%d, echo=%d, thr=%d, speech_ms=%d, flag=%s",
                     rms, self._barge_echo, self._barge_threshold,
                     self._barge_speech_ms, self.barge_flag)
            self._last_barge_log = now

    @staticmethod
    def resolve_device(device):
        if device is None or device == "":
            return None
        if isinstance(device, int):
            return device
        name = str(device).lower()
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0 and name in d["name"].lower():
                log.info("Микрофон по имени %r -> [%d] %s", device, i, d["name"])
                return i
        log.warning("Микрофон по имени %r не найден, беру устройство по умолчанию", device)
        return None

    def _current_device_name(self) -> str:
        try:
            idx = self._device if self._device is not None else sd.default.device[0]
            return sd.query_devices(idx)["name"]
        except Exception:
            return "устройство по умолчанию"

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            log.warning("Аудиопоток: %s", status)
        arr = np.frombuffer(indata, dtype=np.int16)
        if arr.size:
            self.peak = max(self.peak, int(np.abs(arr).max()))
            rms = int(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
        else:
            rms = 0

        self._process_barge(rms)

        if not self.muted:
            self._audio.put(bytes(indata))

    def flush(self) -> None:
        while not self._audio.empty():
            try:
                self._audio.get_nowait()
            except queue.Empty:
                break
        self._utt_buf.clear()
        self._utt_len = 0
        self._rec.Reset()

    def phrases(self, stop_event):
        max_buf = self._sample_rate * 2 * 30
        with sd.RawInputStream(
            samplerate=self._sample_rate,
            blocksize=self._block_size,
            dtype="int16",
            channels=1,
            device=self._device,
            callback=self._callback,
        ):
            log.info("Микрофон открыт, слушаю...")
            while not stop_event.is_set():
                try:
                    data = self._audio.get(timeout=0.2)
                except queue.Empty:
                    continue
                self._utt_buf.append(data)
                self._utt_len += len(data)
                while self._utt_len > max_buf and len(self._utt_buf) > 1:
                    self._utt_len -= len(self._utt_buf.pop(0))
                if self._rec.AcceptWaveform(data):
                    text = json.loads(self._rec.Result()).get("text", "").strip()
                    audio = b"".join(self._utt_buf)
                    self._utt_buf.clear()
                    self._utt_len = 0
                    if text:
                        self.utterances += 1
                        log.info("Распознано (vosk): %s", text)
                        yield text, audio


class WhisperTranscriber:
    """Точная расшифровка короткого фрагмента аудио (faster-whisper)."""

    def __init__(self, model_name: str = "auto", device: str = "auto"):
        _enable_cuda_dlls()
        import ctranslate2
        from faster_whisper import WhisperModel

        if device == "auto":
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        if device == "cuda":
            name = TURBO_MODEL if model_name == "auto" else model_name
            try:
                log.info("Загрузка Whisper (%s) на GPU...", name)
                self._model = WhisperModel(name, device="cuda", compute_type="int8_float16")
                log.info("Whisper готов (GPU)")
                return
            except Exception:
                log.exception("GPU не завёлся, откатываюсь на CPU")
        name = "small" if model_name == "auto" else model_name
        log.info("Загрузка Whisper (%s) на CPU...", name)
        self._model = WhisperModel(name, device="cpu", compute_type="int8")
        log.info("Whisper готов (CPU)")

    def transcribe(self, pcm: bytes, sample_rate: int = 16000) -> str:
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if sample_rate != 16000 and len(audio) > 1:
            n = int(len(audio) * 16000 / sample_rate)
            audio = np.interp(
                np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio
            ).astype(np.float32)
        segments, _ = self._model.transcribe(
            audio,
            language="ru",
            beam_size=2,
            vad_filter=True,
            condition_on_previous_text=False,
            initial_prompt=WHISPER_PROMPT,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        log.info("Распознано (whisper): %s", text)
        return text