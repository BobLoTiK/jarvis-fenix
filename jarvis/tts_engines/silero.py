"""Silero TTS v5_5 — русский голос, ~150 МБ, требует PyTorch.

Голоса v5_5: aidar, baya, kseniya, xenia, eugene.
Качество: UTMOS 3.04 (лучшее среди опенсорса RU).
Скорость CPU: ~1–2 сек на фразу.

ВАЖНО: torch и silero ломаются на кириллице в пути (C:\\Users\\Максим\\...).
Поэтому TORCH_HOME ставим программно в ASCII-путь ДО импорта torch.
"""

import io
import logging
import os
import re
import threading
import time
import wave
from pathlib import Path

# numpy нужен только в рантайме (синтез). Импортируем лениво —
# чтобы модуль можно было импортировать для проверки контракта
# (list_engines, интерфейс) без numpy.
try:
    import numpy as np
except ImportError:
    np = None

log = logging.getLogger("jarvis.tts")


def _setup_torch_home() -> None:
    """Переносит кэш torch в ASCII-путь. ДО import torch."""
    if os.environ.get("TORCH_HOME"):
        return
    try:
        from jarvis import paths as _paths
        torch_home = _paths.program_dir() / "torch"
        torch_home.mkdir(parents=True, exist_ok=True)
        os.environ["TORCH_HOME"] = str(torch_home)
        log.info("TORCH_HOME=%s", torch_home)
    except Exception:
        log.exception("Не удалось установить TORCH_HOME — silero может упасть")


_setup_torch_home()


_SAMPLE_RATE = 48000
_VERSION = "v5_5_ru"
_SENTENCE_END = re.compile(r"[.!?…]+\s+")


class SileroEngine:
    name = "silero"

    voices = {
        "aidar":   "Айдар — мужской",
        "baya":    "Бая — женский",
        "kseniya": "Ксения — женский",
        "xenia":   "Ксения (v5) — женский",
        "eugene":  "Евгений — мужской",
    }

    default_quality = "medium"
    default_rate = 1.15

    def __init__(self, voice: str = "aidar", quality: str = "medium",
                 rate: float = 1.15):
        import torch
        self._torch = torch
        torch.set_num_threads(4)

        if voice not in self.voices:
            # Не спамим — voice="" это служебный вызов из factory.
            if voice:
                log.warning("Silero: голос %r не знаю, беру aidar", voice)
            voice = "aidar"

        self.voice = voice
        self.quality = quality
        self.rate = float(rate)

        self._model = None
        self._device = torch.device("cpu")
        self._lock = threading.RLock()
        self._load_model()

    def _load_model(self):
        with self._lock:
            if self._model is not None:
                return
            log.info("Silero: загружаю %s (первый раз ~30 сек)...", _VERSION)
            t0 = time.time()
            model, _ = self._torch.hub.load(
                repo_or_dir="snakers4/silero-models",
                model="silero_tts",
                language="ru",
                speaker=_VERSION,
            )
            model.to(self._device)
            self._model = model
            log.info("Silero: модель готова за %.1f сек", time.time() - t0)

    def is_available(self) -> bool:
        return self._model is not None

    def set_voice(self, voice: str):
        if voice in self.voices:
            self.voice = voice

    def set_rate(self, rate: float):
        self.rate = float(rate)

    def synthesize(self, text: str, voice: str | None = None,
                   rate: float | None = None) -> bytes:
        if np is None:
            raise RuntimeError("numpy не установлен — Silero недоступен")
        if not text.strip():
            return b""
        voice = voice or self.voice
        rate = rate if rate is not None else self.rate
        if voice not in self.voices:
            voice = "aidar"

        with self._lock:
            self._load_model()
            audio = self._model.apply_tts(
                text=text,
                speaker=voice,
                sample_rate=_SAMPLE_RATE,
            )

        samples = (audio.numpy() * 32767).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(_SAMPLE_RATE)
            wf.writeframes(samples.tobytes())
        return buf.getvalue()

    def speak_stream(self, text_iter, voice: str, rate: float,
                     token) -> str:
        """Стриминг Silero через sounddevice."""
        from jarvis.text_utils import prepare_text

        buffer = ""
        full_parts = []

        def _flush(force: bool = False):
            nonlocal buffer
            while True:
                m = _SENTENCE_END.search(buffer)
                if not m:
                    break
                sent = buffer[:m.end()].strip()
                buffer = buffer[m.end():]
                if sent and not token.is_set():
                    self._play(sent, voice, rate, token)
            if force and buffer.strip() and not token.is_set():
                self._play(buffer.strip(), voice, rate, token)
                buffer = ""

        for chunk in text_iter:
            if chunk:
                full_parts.append(chunk)
                buffer += chunk
            if token.is_set():
                break
            _flush()
        if not token.is_set():
            _flush(force=True)
        return "".join(full_parts).strip()

    def _play(self, sentence: str, voice: str, rate: float, token):
        if np is None:
            return
        from jarvis.text_utils import prepare_text

        text = prepare_text(sentence)
        if not text.strip().strip("\u200b\u200c\u200d\ufeff\u00ad"):
            return
        if token.is_set():
            return

        wav = self.synthesize(text, voice, rate)
        if not wav or token.is_set():
            return

        try:
            import sounddevice as sd
            with wave.open(io.BytesIO(wav)) as wf:
                rate_hz = wf.getframerate()
                frames = wf.readframes(wf.getnframes())
            audio = np.frombuffer(frames, dtype=np.int16)
            chunk = int(rate_hz * 0.05)
            with sd.OutputStream(samplerate=rate_hz, channels=1,
                                 dtype="int16") as stream:
                for i in range(0, len(audio), chunk):
                    if token.is_set():
                        break
                    stream.write(audio[i:i + chunk])
        except Exception:
            log.exception("Silero: ошибка воспроизведения")