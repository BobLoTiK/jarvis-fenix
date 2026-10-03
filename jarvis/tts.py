"""Синтез речи.

Бэкенды: xtts / piper / winrt / sapi.
Смена голоса на лету: при каждом speak() перечитываем config.json.
Streaming: speak_stream(iterator) — озвучивает по предложениям.
Barge-in: play_async() + stop() — играет в потоке, можно прервать.
"""

import asyncio
import io
import json
import logging
import os
import re
import threading
import time
import wave
import winsound
from pathlib import Path

log = logging.getLogger("jarvis.tts")

PIPER_REPO = "rhasspy/piper-voices"
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"

_SENTENCE_END = re.compile(r"[.!?…]+\s+")


class Speaker:
    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.rate = float(cfg.get("voice_rate", 1.15))
        self.voice = cfg.get("tts_voice", "ruslan")
        self._voice_hint = cfg.get("voice", "Pavel")
        self._mode = None
        self._engine = None
        self._piper = None
        self._piper_cfg = None

        # barge-in: поток воспроизведения и флаг прерывания
        self._play_thread = None
        self._stop_flag = threading.Event()
        self._playing = False
        self._play_lock = threading.Lock()

        backend = cfg.get("tts_backend", "auto")
        ref = BASE_DIR / cfg.get("xtts_ref", "voices/jarvis.wav")
        if backend in ("auto", "xtts"):
            if ref.exists():
                try:
                    self._init_xtts(ref)
                except Exception:
                    log.exception("XTTS не завёлся, переключаюсь на piper")
            elif backend == "xtts":
                log.warning("Референс голоса не найден: %s — переключаюсь на piper", ref)
        if self._mode is None and backend in ("auto", "xtts", "piper"):
            try:
                self._init_piper(self.voice)
            except Exception:
                log.exception("Piper не завёлся, переключаюсь на WinRT")
        if self._mode is None:
            try:
                from winrt.windows.media.speechsynthesis import SpeechSynthesizer  # noqa: F401

                self._mode = "winrt"
                log.info("TTS: WinRT, голос с подсказкой %r, скорость %.2f",
                         self._voice_hint, self.rate)
            except Exception:
                log.exception("WinRT недоступен, переключаюсь на SAPI (pyttsx3)")
                self._init_sapi()

    # --- перечитывание конфига при каждом speak() ------------------------

    def _reload_config(self) -> None:
        try:
            if not CONFIG_PATH.exists():
                return
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            log.exception("Не удалось перечитать config.json")
            return

        new_rate = float(cfg.get("voice_rate", self.rate))
        self.rate = new_rate
        if self._piper_cfg is not None:
            try:
                from piper import SynthesisConfig
                self._piper_cfg = SynthesisConfig(length_scale=round(1.0 / self.rate, 2))
            except Exception:
                pass

        new_voice = cfg.get("tts_voice", self.voice)
        if new_voice != self.voice:
            log.info("Голос изменился: %s → %s", self.voice, new_voice)
            self.voice = new_voice
            if self._mode == "piper":
                try:
                    self._init_piper(new_voice)
                except Exception:
                    log.exception("Не удалось переключить Piper на %s", new_voice)

    # --- xtts ------------------------------------------------------------

    def _init_xtts(self, ref: Path) -> None:
        os.environ.setdefault("COQUI_TOS_AGREED", "1")
        import torch
        from TTS.api import TTS as CoquiTTS

        device = "cuda" if torch.cuda.is_available() else "cpu"
        log.info("Загрузка XTTS-v2 на %s...", device)
        self._xtts = CoquiTTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
        self._xtts_ref = str(ref)
        self._mode = "xtts"
        log.info("TTS: XTTS-v2, клон голоса из %s", ref.name)

    def _speak_xtts(self, text: str) -> None:
        import numpy as np

        samples = self._xtts.tts(text=text, speaker_wav=self._xtts_ref,
                                 language="ru", speed=self.rate)
        pcm = (np.clip(np.asarray(samples), -1, 1) * 32767).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(pcm.tobytes())
        winsound.PlaySound(buf.getvalue(), winsound.SND_MEMORY)

    # --- piper -----------------------------------------------------------

    def _init_piper(self, voice: str) -> None:
        from huggingface_hub import hf_hub_download
        from piper import PiperVoice, SynthesisConfig

        rel = f"ru/ru_RU/{voice}/medium/ru_RU-{voice}-medium.onnx"
        onnx = hf_hub_download(PIPER_REPO, rel)
        hf_hub_download(PIPER_REPO, rel + ".json")
        self._piper = PiperVoice.load(onnx)
        self._piper_cfg = SynthesisConfig(length_scale=round(1.0 / self.rate, 2))
        self._mode = "piper"
        log.info("TTS: piper, голос %s, скорость %.2f", voice, self.rate)

    def _speak_piper(self, text: str) -> None:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            self._piper.synthesize_wav(text, wf, self._piper_cfg)
        winsound.PlaySound(buf.getvalue(), winsound.SND_MEMORY)

    # --- winrt / sapi ----------------------------------------------------

    def _init_sapi(self) -> None:
        import pyttsx3

        self._engine = pyttsx3.init()
        for v in self._engine.getProperty("voices"):
            ident = f"{v.id} {v.name}".lower()
            if self._voice_hint.lower() in ident or "ru" in ident or "irina" in ident:
                self._engine.setProperty("voice", v.id)
                log.info("TTS: SAPI, голос %s", v.name)
                break
        self._mode = "sapi"

    async def _synthesize(self, text: str) -> bytes:
        from winrt.windows.media.speechsynthesis import SpeechSynthesizer
        from winrt.windows.storage.streams import DataReader

        synth = SpeechSynthesizer()
        voices = list(SpeechSynthesizer.all_voices)
        voice = next(
            (v for v in voices if self._voice_hint.lower() in v.display_name.lower()),
            None,
        ) or next((v for v in voices if v.language.lower().startswith("ru")), None)
        if voice is not None:
            synth.voice = voice
        try:
            synth.options.speaking_rate = self.rate
        except Exception:
            pass
        stream = await synth.synthesize_text_to_stream_async(text)
        reader = DataReader(stream.get_input_stream_at(0))
        await reader.load_async(stream.size)
        return bytes(reader.read_buffer(stream.size))

    # --- общий вход ------------------------------------------------------

    def _speak_one(self, text: str) -> None:
        """Синтез и воспроизведение одного куска. Блокирующий."""
        text = text.strip()
        if not text or self._stop_flag.is_set():
            return
        log.info("Говорю: %s", text)
        try:
            if self._mode == "xtts":
                self._speak_xtts(text)
            elif self._mode == "piper":
                self._speak_piper(text)
            elif self._mode == "winrt":
                wav = asyncio.run(self._synthesize(text))
                if not self._stop_flag.is_set():
                    winsound.PlaySound(wav, winsound.SND_MEMORY)
            else:
                self._engine.say(text)
                self._engine.runAndWait()
        except Exception:
            log.exception("Ошибка синтеза речи")

    def speak(self, text: str) -> None:
        """Блокирующий синтез (для старых вызовов)."""
        if not text:
            return
        self._reload_config()
        self._speak_one(text)

    # --- barge-in API ----------------------------------------------------

    def play_async(self, text: str) -> None:
        """Играет в отдельном потоке. Можно прервать через stop()."""
        self._reload_config()
        self._stop_flag.clear()
        self._playing = True

        def _run():
            try:
                self._speak_one(text)
            finally:
                with self._play_lock:
                    self._playing = False

        self._play_thread = threading.Thread(target=_run, daemon=True, name="tts-play")
        self._play_thread.start()

    def stop(self) -> None:
        """Прерывает текущее воспроизведение."""
        log.info("TTS: прерывание (barge-in)")
        self._stop_flag.set()
        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass

    def is_playing(self) -> bool:
        return self._playing and self._play_thread is not None and self._play_thread.is_alive()

    def wait_end(self, timeout: float = 30.0) -> None:
        """Ждёт окончания потока воспроизведения."""
        if self._play_thread is not None:
            self._play_thread.join(timeout=timeout)
        self._playing = False

    def speak_stream(self, text_iter, timeout: float = 30.0) -> str:
        """Streaming TTS. Буферизует куски по предложениям и играет по мере готовности.

        Прерывается через stop() (barge-in работает).
        Возвращает полный текст ответа.
        """
        self._reload_config()
        self._stop_flag.clear()
        self._playing = True

        buffer = ""
        full_text_parts = []
        pending = []

        def _flush_sentences(force: bool = False):
            nonlocal buffer
            while True:
                m = _SENTENCE_END.search(buffer)
                if not m:
                    break
                sentence = buffer[:m.end()].strip()
                buffer = buffer[m.end():]
                if sentence:
                    pending.append(sentence)
            if force and buffer.strip():
                pending.append(buffer.strip())
                buffer = ""

        try:
            for chunk in text_iter:
                if self._stop_flag.is_set():
                    log.info("TTS: стриминг прерван")
                    break
                buffer += chunk
                full_text_parts.append(chunk)
                _flush_sentences()
                while pending and not self._stop_flag.is_set():
                    sentence = pending.pop(0)
                    self._speak_one(sentence)
            if not self._stop_flag.is_set():
                _flush_sentences(force=True)
                while pending and not self._stop_flag.is_set():
                    sentence = pending.pop(0)
                    self._speak_one(sentence)
        except Exception:
            log.exception("Ошибка в speak_stream")
        finally:
            self._playing = False

        return "".join(full_text_parts).strip()