"""Синтез речи.

Бэкенды: xtts / piper / winrt / sapi.
Смена голоса на лету: через Config.subscribe — main.py вызывает speaker.set_voice().
Streaming: speak_stream(iterator) — озвучивает по предложениям.
Barge-in: воспроизведение через sounddevice с проверкой per-call токена —
реально прерывает звук.
Предобработка текста: prepare_text() из text_utils — CJK, единицы, числа.

Фикс гонки: вместо одного _stop_flag — per-call stop-token. Каждый
play_async / speak_stream создаёт свой threading.Event, stop() взводит
ТОЛЬКО текущий. Старый поток проверяет свой токен, который новый
поток не сбрасывает. Иначе 2-3 голоса одновременно.

wait_end: возвращает bool (успел ли поток завершиться). play_async
проверяет результат — если старый поток не завершился, новый не
запускается (иначе наложение TTS).
"""

import asyncio
import io
import logging
import os
import re
import threading
import time
import wave
from pathlib import Path

import numpy as np

from jarvis.text_utils import prepare_text

log = logging.getLogger("jarvis.tts")

PIPER_REPO = "rhasspy/piper-voices"
BASE_DIR = Path(__file__).resolve().parent.parent

_SENTENCE_END = re.compile(r"[.!?…]+\s+")


class Speaker:
    def __init__(self, config):
        self._config = config
        cfg = config if hasattr(config, "get") else {}
        self.rate = float(cfg.get("voice_rate", 1.15))
        self.voice = cfg.get("tts_voice", "ruslan")
        self._voice_hint = cfg.get("voice", "Pavel")
        self._mode = None
        self._engine = None
        self._piper = None
        self._piper_cfg = None
        self._piper_quality = "medium"

        # Глобальное состояние воспроизведения
        self._play_thread = None
        self._playing = False
        self._play_lock = threading.Lock()

        # Per-call stop-token
        self._current_token: threading.Event = threading.Event()
        self._token_lock = threading.Lock()

        backend = cfg.get("tts_backend", "auto")
        ref = BASE_DIR / cfg.get("xtts_ref", "voices/jarvis.wav")
        if backend in ("auto", "xtts"):
            if ref.exists():
                try:
                    self._init_xtts(ref)
                except Exception:
                    log.exception("XTTS не завёлся, переключаюсь на piper")
            elif backend == "xtts":
                log.warning("Референс голоса не найден: %s", ref)
        if self._mode is None and backend in ("auto", "xtts", "piper"):
            try:
                self._init_piper(self.voice)
            except Exception:
                log.exception("Piper не завёлся, переключаюсь на WinRT")
        if self._mode is None:
            try:
                from winrt.windows.media.speechsynthesis import SpeechSynthesizer  # noqa: F401
                self._mode = "winrt"
                log.info("TTS: WinRT, голос %r, скорость %.2f", self._voice_hint, self.rate)
            except Exception:
                log.exception("WinRT недоступен, переключаюсь на SAPI")
                self._init_sapi()

    # --- сеттеры для Config.subscribe ------------------------------------

    def set_voice(self, voice: str) -> None:
        if voice == self.voice:
            return
        log.info("Голос изменился: %s → %s", self.voice, voice)
        self.voice = voice
        if self._mode == "piper":
            try:
                self._init_piper(voice)
            except Exception:
                log.exception("Не удалось переключить Piper на %s", voice)

    def set_rate(self, rate: float) -> None:
        self.rate = float(rate)
        if self._piper_cfg is not None:
            try:
                from piper import SynthesisConfig
                self._piper_cfg = SynthesisConfig(length_scale=round(1.0 / self.rate, 2))
            except Exception:
                pass

    # --- per-call stop-token ---------------------------------------------

    def _new_token(self) -> threading.Event:
        """Создаёт новый stop-token и делает его текущим.

        ВАЖНО: старый токен НЕ сбрасывается — старый поток продолжит
        видеть его взведённым и завершится корректно.
        """
        with self._token_lock:
            self._current_token = threading.Event()
            return self._current_token

    def _current_stop(self) -> threading.Event:
        with self._token_lock:
            return self._current_token

    # --- воспроизведение через sounddevice (для barge-in) ----------------

    def _play_wav(self, wav_bytes: bytes, token: threading.Event) -> None:
        """Играет WAV-байты чанками, проверяя per-call token."""
        try:
            import sounddevice as sd
        except ImportError:
            log.warning(
                "sounddevice недоступен — играю через winsound. "
                "Barge-in НЕ БУДЕТ РАБОТАТЬ. Установи: pip install sounddevice"
            )
            import winsound
            winsound.PlaySound(wav_bytes, winsound.SND_MEMORY)
            return

        with wave.open(io.BytesIO(wav_bytes)) as wf:
            rate = wf.getframerate()
            channels = wf.getnchannels()
            width = wf.getsampwidth()

        dtype = {1: "int8", 2: "int16", 4: "int32"}.get(width)
        if dtype is None:
            log.warning("Неподдерживаемая ширина сэмпла: %d", width)
            return

        with wave.open(io.BytesIO(wav_bytes)) as wf:
            frames = wf.readframes(wf.getnframes())
        audio = np.frombuffer(frames, dtype=dtype)
        if channels > 1:
            audio = audio.reshape(-1, channels)

        chunk = int(rate * 0.05)
        try:
            with sd.OutputStream(samplerate=rate, channels=channels, dtype=dtype) as stream:
                for i in range(0, len(audio), chunk):
                    if token.is_set():
                        log.info("TTS: воспроизведение прервано (token)")
                        break
                    stream.write(audio[i:i + chunk])
        except Exception:
            log.exception("sounddevice.OutputStream не завёлся — падаю на winsound")
            import winsound
            winsound.PlaySound(wav_bytes, winsound.SND_MEMORY)

    # --- xtts / piper / sapi / winrt --------------------------------------

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

    def _speak_xtts(self, text: str, token: threading.Event) -> None:
        if token.is_set():
            return
        samples = self._xtts.tts(text=text, speaker_wav=self._xtts_ref,
                                 language="ru", speed=self.rate)
        if token.is_set():
            return
        pcm = (np.clip(np.asarray(samples), -1, 1) * 32767).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(pcm.tobytes())
        self._play_wav(buf.getvalue(), token)

    def _init_piper(self, voice: str) -> None:
        from huggingface_hub import hf_hub_download
        from piper import PiperVoice, SynthesisConfig

        cfg = self._config if hasattr(self, "_config") else {}
        quality = "medium"
        if hasattr(cfg, "get"):
            quality = cfg.get("tts_voice_quality", "medium")
        if quality not in ("medium", "high"):
            quality = "medium"

        rel = f"ru/ru_RU/{voice}/{quality}/ru_RU-{voice}-{quality}.onnx"

        try:
            onnx = hf_hub_download(PIPER_REPO, rel)
            hf_hub_download(PIPER_REPO, rel + ".json")
            log.info("TTS: piper, голос %s/%s", voice, quality)
        except Exception:
            log.warning("Голос %s/%s не найден, откат на medium", voice, quality)
            quality = "medium"
            rel = f"ru/ru_RU/{voice}/medium/ru_RU-{voice}-medium.onnx"
            onnx = hf_hub_download(PIPER_REPO, rel)
            hf_hub_download(PIPER_REPO, rel + ".json")

        self._piper = PiperVoice.load(onnx)
        self._piper_cfg = SynthesisConfig(length_scale=round(1.0 / self.rate, 2))
        self._mode = "piper"
        self._piper_quality = quality
        log.info("TTS: piper, голос %s/%s, скорость %.2f", voice, quality, self.rate)

    def _speak_piper(self, text: str, token: threading.Event) -> None:
        if token.is_set():
            return
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            self._piper.synthesize_wav(text, wf, self._piper_cfg)
        if token.is_set():
            return
        self._play_wav(buf.getvalue(), token)

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

    def _speak_one(self, text: str, token: threading.Event) -> None:
        text = prepare_text(text)
        if not text or token.is_set():
            return
        # Пропускаем, если в тексте только невидимые символы
        # (zero-width space, BOM, soft hyphen). Иначе Piper падает
        # с wave.Error('# channels not specified').
        if not text.strip().strip("\u200b\u200c\u200d\ufeff\u00ad"):
            log.debug("TTS: пропускаю невидимый текст %r", text)
            return
        log.info("Говорю: %s", text)
        try:
            if self._mode == "xtts":
                self._speak_xtts(text, token)
            elif self._mode == "piper":
                self._speak_piper(text, token)
            elif self._mode == "winrt":
                wav = asyncio.run(self._synthesize(text))
                if token.is_set():
                    return
                self._play_wav(wav, token)
            else:
                if token.is_set():
                    return
                self._engine.say(text)
                self._engine.runAndWait()
        except Exception:
            log.exception("Ошибка синтеза речи")

    def speak(self, text: str) -> None:
        """Синхронная озвучка (для тестов)."""
        if not text:
            return
        token = self._new_token()
        self._speak_one(text, token)

    def play_async(self, text: str) -> None:
        """Асинхронная озвучка одного текста.

        №74: если старый поток не завершился за timeout — НЕ запускаем
        новый (иначе наложение TTS). Логируем и выходим.
        """
        self.stop()

        # Ждём завершения старого потока. Если не успел — не запускаем новый.
        finished = self.wait_end(timeout=2.0)
        if not finished:
            log.warning(
                "TTS: старый поток не завершился за 2 сек — пропускаю новый вызов "
                "(иначе наложение)"
            )
            return

        token = self._new_token()

        with self._play_lock:
            self._playing = True

        def _run():
            try:
                self._speak_one(text, token)
            finally:
                with self._play_lock:
                    self._playing = False

        self._play_thread = threading.Thread(target=_run, daemon=True, name="tts-play")
        self._play_thread.start()

    def stop(self) -> None:
        """Взводит ТЕКУЩИЙ токен. Старые токены не трогает."""
        with self._token_lock:
            token = self._current_token
        if not token.is_set():
            log.info("TTS: прерывание (stop)")
        token.set()

    def is_playing(self) -> bool:
        with self._play_lock:
            return self._playing and self._play_thread is not None and self._play_thread.is_alive()

    def wait_end(self, timeout: float = 30.0) -> bool:
        """Ждёт завершения текущего TTS-потока.

        №72: возвращает bool — успел ли поток завершиться.
        _playing = False ставится ТОЛЬКО если поток реально завершился.
        Иначе is_playing() начнёт врать.

        Защита: thread.join() на НЕзапущенном потоке бросает RuntimeError
        («cannot join thread before it is started»). Проверяем is_alive()
        перед join — если поток уже мёртв или ещё не стартовал, join не нужен.
        """
        with self._play_lock:
            thread = self._play_thread
        if thread is None:
            return True

        # Защита от join() на незапущенном/уже завершённом потоке.
        if not thread.is_alive():
            with self._play_lock:
                self._playing = False
            return True

        thread.join(timeout=timeout)
        finished = not thread.is_alive()
        if finished:
            with self._play_lock:
                self._playing = False
        else:
            log.warning("TTS: поток не завершился за %.1f сек (timeout)", timeout)
        return finished

    def speak_stream(self, text_iter, timeout: float = 30.0) -> str:
        """Streaming TTS. Разбивает текст по предложениям и озвучивает по мере поступления.

        №93: append чанка в full_text_parts ДО проверки токена —
        иначе последний прочитанный чанк теряется.
        """
        self.stop()
        self.wait_end(timeout=1.0)

        token = self._new_token()

        with self._play_lock:
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
                # №93: append ДО проверки токена — иначе при barge-in
                # последний чанк теряется.
                if chunk:
                    full_text_parts.append(chunk)
                    buffer += chunk
                if token.is_set():
                    log.info("TTS: стриминг прерван")
                    break
                _flush_sentences()
                while pending and not token.is_set():
                    sentence = pending.pop(0)
                    self._speak_one(sentence, token)
            if not token.is_set():
                _flush_sentences(force=True)
                while pending and not token.is_set():
                    sentence = pending.pop(0)
                    self._speak_one(sentence, token)
        except Exception:
            log.exception("Ошибка в speak_stream")
        finally:
            with self._play_lock:
                self._playing = False

        return "".join(full_text_parts).strip()