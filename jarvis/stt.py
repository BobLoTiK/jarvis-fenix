"""Распознавание речи.

Гибрид: Vosk (wake) + Whisper (точная расшифровка).
Barge-in: адаптивная калибровка эха и фона при старте.
Ring buffer: последние 10 фраз (для «что ты слышал»).
"""

import json
import logging
import os
import queue
import time
from collections import deque
from pathlib import Path

import numpy as np
import sounddevice as sd
from vosk import KaldiRecognizer, Model, SetLogLevel

log = logging.getLogger("jarvis.stt")

TURBO_MODEL = "deepdml/faster-whisper-large-v3-turbo-ct2"

WHISPER_PROMPT = (
    "Это русская речь. Пожалуйста, транскрибируй текст на русском языке. "
    "Частые слова: Феникс, открой, закрой, найди, погода, напоминание, "
    "задача, голос, режим, паки, Нижний Новгород, курс доллара."
)

ECHO_WINDOW_SEC = 0.5
BARGE_LOG_INTERVAL = 0.5

# Флаг, чтобы не добавлять пути CUDA в PATH повторно при каждом импорте stt.
_CUDA_DLLS_ADDED = False


def _enable_cuda_dlls():
    """Добавляет пути к CUDA-библиотекам (cuBLAS, cuDNN) в PATH.

    Идемпотентна: повторный вызов ничего не делает.
    """
    global _CUDA_DLLS_ADDED
    if _CUDA_DLLS_ADDED:
        return
    try:
        import nvidia
    except ImportError:
        return
    base = Path(nvidia.__path__[0])
    dirs = [str(p) for p in (base / "cublas" / "bin", base / "cudnn" / "bin") if p.exists()]
    if dirs:
        os.environ["PATH"] = os.pathsep.join(dirs) + os.pathsep + os.environ["PATH"]
        _CUDA_DLLS_ADDED = True


class Listener:
    def __init__(self, model_dir, sample_rate=16000, device=None):
        SetLogLevel(-1)
        self._model = Model(str(model_dir))
        self._rec = KaldiRecognizer(self._model, sample_rate)
        self._sample_rate = sample_rate
        self._device = self.resolve_device(device)
        self.device_name = self._current_device_name()
        self._audio = queue.Queue()
        self._utt_buf = []
        self._utt_len = 0
        self.peak = 0
        self.utterances = 0
        self.current_rms = 0  # текущий уровень сигнала (для GUI)
        
        self.barge_enabled = True
        self.muted = False
        self.barge_flag = False
        self._block_size = 8000

        # Ring buffer последних фраз (для «что ты слышал»)
        self.recent_phrases: deque = deque(maxlen=10)

        # Адаптивный barge-in
        self._echo_window_samples = deque(maxlen=20)
        self._echo_baseline = 0
        self._barge_threshold = 150
        self._barge_speech_ms = 0
        self._speech_active = False
        self._speech_started_at = 0.0
        self._last_barge_log = 0.0
        self._echo_done = False

    def barge_start(self):
        self.barge_flag = False
        self._barge_speech_ms = 0
        self._speech_active = True
        self._speech_started_at = time.time()
        self._echo_done = False
        self._echo_window_samples.clear()
        self._barge_threshold = max(150, int(self._echo_baseline * 1.8))

    def barge_end(self):
        self._speech_active = False
        log.info("Barge-in: стоп (echo=%d, thr=%d, речь=%d мс)",
                 self._echo_baseline, self._barge_threshold, self._barge_speech_ms)

    def _process_barge(self, rms):
        if not self._speech_active or not self.barge_enabled:
            return
        now = time.time()
        elapsed = now - self._speech_started_at

        if elapsed < ECHO_WINDOW_SEC:
            return

        if not self._echo_done:
            self._echo_window_samples.append(rms)
            if elapsed >= ECHO_WINDOW_SEC + 0.5:
                if self._echo_window_samples:
                    arr = sorted(self._echo_window_samples)
                    self._echo_baseline = arr[int(len(arr) * 0.7)]
                self._barge_threshold = max(150, int(self._echo_baseline * 1.8))
                self._echo_done = True
                log.info("Barge-in: калибровка echo=%d, threshold=%d",
                         self._echo_baseline, self._barge_threshold)
            return

        self._echo_window_samples.append(rms)
        if len(self._echo_window_samples) >= 10:
            arr = sorted(self._echo_window_samples)
            new_echo = arr[int(len(arr) * 0.7)]
            self._echo_baseline = int(0.9 * self._echo_baseline + 0.1 * new_echo)
            self._barge_threshold = max(150, int(self._echo_baseline * 1.8))

        if rms > self._barge_threshold:
            self._barge_speech_ms += int(self._block_size / 16)
            if self._barge_speech_ms >= 150:
                self.barge_flag = True
        else:
            self._barge_speech_ms = 0

        if now - self._last_barge_log >= BARGE_LOG_INTERVAL:
            log.info("barge: rms=%d, echo=%d, thr=%d, speech_ms=%d, flag=%s",
                     rms, self._echo_baseline, self._barge_threshold,
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
                return i
        log.warning("Микрофон %r не найден, беру по умолчанию", device)
        return None

    def _current_device_name(self):
        try:
            idx = self._device if self._device is not None else sd.default.device[0]
            return sd.query_devices(idx)["name"]
        except Exception:
            return "по умолчанию"

    def _callback(self, indata, frames, time_info, status):
        if status:
            log.warning("Аудиопоток: %s", status)
        arr = np.frombuffer(indata, dtype=np.int16)
        if arr.size:
            self.peak = max(self.peak, int(np.abs(arr).max()))
            rms = int(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
            self.current_rms = rms
        else:
            rms = 0
            self.current_rms = 0
        self._process_barge(rms)
        if not self.muted:
            self._audio.put(bytes(indata))

    def flush(self):
        while not self._audio.empty():
            try:
                self._audio.get_nowait()
            except queue.Empty:
                break
        self._utt_buf.clear()
        self._utt_len = 0
        self._rec.Reset()
        
    def reset_stats(self):
        """Сбрасывает peak и utterances — для кнопки «Проверить микрофон»."""
        self.peak = 0
        self.utterances = 0
        log.info("Listener: статистика сброшена")

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
                        self.recent_phrases.append(text)
                        log.info("Распознано (vosk): %s", text)
                        yield text, audio


class WhisperTranscriber:
    def __init__(self, model_name="auto", device="auto"):
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

    def transcribe(self, pcm, sample_rate=16000):
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if sample_rate != 16000 and len(audio) > 1:
            n = int(len(audio) * 16000 / sample_rate)
            audio = np.interp(
                np.linspace(0, len(audio) - 1, n),
                np.arange(len(audio)), audio
            ).astype(np.float32)
        segments, _ = self._model.transcribe(
            audio, language="ru", beam_size=2, vad_filter=True,
            condition_on_previous_text=False, initial_prompt=WHISPER_PROMPT,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        log.info("Распознано (whisper): %s", text)
        return text