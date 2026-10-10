"""Синтез речи — фасад над tts_engines.

Speaker не знает о Piper/Silero/WinRT/SAPI напрямую — работает через
BaseEngine из jarvis.tts_engines.

Возможности:
    play_async(text)     — асинхронная озвучка одного текста
    speak_stream(gen)    — стриминг: озвучивает по предложениям
    speak(text)          — синхронная озвучка (для тестов)
    stop()               — прервать текущее воспроизведение
    wait_end(timeout)    — дождаться завершения (bool — успел ли)
    is_playing()         — идёт ли воспроизведение
    set_voice(voice)     — сменить голос на лету
    set_rate(rate)       — сменить скорость на лету

Per-call stop-token: каждый play_async / speak_stream создаёт свой
threading.Event. stop() взводит ТОЛЬКО текущий — старый поток видит
свой токен взведённым и завершается сам. Иначе 2-3 голоса накладываются.
"""

import logging
import threading
import time
from typing import Iterator

from jarvis.tts_engines import get_engine, list_engines

log = logging.getLogger("jarvis.tts")


class Speaker:
    def __init__(self, config):
        self._config = config
        cfg = config if hasattr(config, "get") else {}

        self.voice = cfg.get("tts_voice", "ruslan")
        self.rate = float(cfg.get("voice_rate", 1.15))
        self.quality = cfg.get("tts_voice_quality", "medium")
        self._backend = cfg.get("tts_backend", "auto")

        self._engine = None
        self._engine_name = "none"

        # Глобальное состояние воспроизведения
        self._play_thread = None
        self._playing = False
        self._play_lock = threading.Lock()

        # Per-call stop-token
        self._current_token = threading.Event()
        self._token_lock = threading.Lock()

        # Грузим движок
        self._init_engine()

    # ------------------------------------------------------------------
    # Инициализация
    # ------------------------------------------------------------------

    def _init_engine(self):
        log.info("TTS: выбираю движок (backend=%s)", self._backend)
        engine = get_engine(self._backend, self.voice, self.quality,
                            self.rate)
        if engine is None:
            log.error("TTS: ни один движок не доступен")
            return
        self._engine = engine
        self._engine_name = engine.name
        log.info("TTS: движок %s, голос %s, скорость %.2f",
                 self._engine_name, self.voice, self.rate)

    def switch_backend(self, backend: str) -> bool:
        """Переключить движок на лету."""
        if backend == self._backend and self._engine is not None:
            return True

        # Сброс кэша голосов — при смене backend голоса другие.
        try:
            from jarvis import voices as _voices
            _voices._VOICES_CACHE.clear()
        except Exception:
            pass

        old = self._engine_name
        self._backend = backend
        self.stop()
        self.wait_end(timeout=2.0)
        engine = get_engine(backend, self.voice, self.quality, self.rate)
        if engine is None:
            log.warning("TTS: не удалось переключиться на %s", backend)
            self._backend = old
            return False
        self._engine = engine
        self._engine_name = engine.name
        log.info("TTS: движок переключён %s → %s", old, self._engine_name)
        return True

    # ------------------------------------------------------------------
    # Сеттеры (для Config.subscribe)
    # ------------------------------------------------------------------

    def set_voice(self, voice: str) -> None:
        if voice == self.voice:
            return
        log.info("TTS: голос %s → %s", self.voice, voice)
        self.voice = voice
        if self._engine is not None:
            try:
                self._engine.set_voice(voice)
            except Exception:
                log.exception("TTS: не удалось сменить голос на %s", voice)

    def set_rate(self, rate: float) -> None:
        self.rate = float(rate)
        if self._engine is not None:
            try:
                self._engine.set_rate(self.rate)
            except Exception:
                log.exception("TTS: не удалось сменить скорость")

    # ------------------------------------------------------------------
    # Stop-token
    # ------------------------------------------------------------------

    def _new_token(self) -> threading.Event:
        with self._token_lock:
            self._current_token = threading.Event()
            return self._current_token

    def _current_stop(self) -> threading.Event:
        with self._token_lock:
            return self._current_token

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def speak(self, text: str) -> None:
        """Синхронная озвучка (для тестов)."""
        if not text or self._engine is None:
            return
        token = self._new_token()
        try:
            if hasattr(self._engine, "synthesize"):
                self._engine.synthesize(text, self.voice, self.rate)
            # Для SAPI (без synthesize) — через стриминг с одним куском
            if self._engine_name == "sapi":
                list(self._engine.speak_stream(iter([text]),
                                               self.voice, self.rate, token))
        except Exception:
            log.exception("TTS: ошибка в speak()")

    def play_async(self, text: str) -> None:
        """Асинхронная озвучка одного текста."""
        if not text or self._engine is None:
            return

        self.stop()
        finished = self.wait_end(timeout=2.0)
        if not finished:
            log.warning(
                "TTS: старый поток не завершился за 2 сек — пропускаю новый "
                "(иначе наложение)"
            )
            return

        token = self._new_token()
        with self._play_lock:
            self._playing = True

        def _run():
            try:
                # SAPI играет сам, у него нет synthesize
                if self._engine_name == "sapi":
                    list(self._engine.speak_stream(
                        iter([text]), self.voice, self.rate, token
                    ))
                else:
                    wav = self._engine.synthesize(text, self.voice, self.rate)
                    if wav and not token.is_set():
                        self._play_wav(wav, token)
            except Exception:
                log.exception("TTS: ошибка в play_async")
            finally:
                with self._play_lock:
                    self._playing = False

        self._play_thread = threading.Thread(target=_run, daemon=True,
                                             name="tts-play")
        self._play_thread.start()

    def speak_stream(self, text_iter: Iterator[str],
                     timeout: float = 30.0) -> str:
        """Стриминг: озвучивает по предложениям.

        Возвращает полный озвученный текст.
        """
        if self._engine is None:
            # Просто вычитываем генератор, чтобы ничего не зависло
            return "".join(text_iter)

        self.stop()
        self.wait_end(timeout=1.0)

        token = self._new_token()
        with self._play_lock:
            self._playing = True

        try:
            return self._engine.speak_stream(
                text_iter, self.voice, self.rate, token
            )
        except Exception:
            log.exception("TTS: ошибка в speak_stream")
            return ""
        finally:
            with self._play_lock:
                self._playing = False

    def stop(self) -> None:
        """Взводит текущий токен. Старые — не трогает."""
        with self._token_lock:
            token = self._current_token
        if not token.is_set():
            log.info("TTS: прерывание")
        token.set()
        if self._engine is not None:
            try:
                self._engine.stop()
            except Exception:
                pass

    def is_playing(self) -> bool:
        with self._play_lock:
            return (self._playing and self._play_thread is not None
                    and self._play_thread.is_alive())

    def wait_end(self, timeout: float = 30.0) -> bool:
        """Ждёт завершения текущего TTS-потока. True — успел."""
        with self._play_lock:
            thread = self._play_thread
        if thread is None:
            return True
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
            log.warning("TTS: поток не завершился за %.1f сек", timeout)
        return finished

    # ------------------------------------------------------------------
    # Воспроизведение WAV (для engine.synthesize())
    # ------------------------------------------------------------------

    def _play_wav(self, wav_bytes: bytes, token: threading.Event) -> None:
        """Играет WAV-байты через sounddevice с проверкой токена."""
        import io
        import wave

        import numpy as np

        try:
            import sounddevice as sd
        except ImportError:
            log.warning("TTS: sounddevice недоступен, играю через winsound")
            import winsound
            winsound.PlaySound(wav_bytes, winsound.SND_MEMORY)
            return

        with wave.open(io.BytesIO(wav_bytes)) as wf:
            rate = wf.getframerate()
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            frames = wf.readframes(wf.getnframes())

        dtype = {1: "int8", 2: "int16", 4: "int32"}.get(width, "int16")
        audio = np.frombuffer(frames, dtype=dtype)
        if channels > 1:
            audio = audio.reshape(-1, channels)

        chunk = int(rate * 0.05)
        try:
            with sd.OutputStream(samplerate=rate, channels=channels,
                                 dtype=dtype) as stream:
                for i in range(0, len(audio), chunk):
                    if token.is_set():
                        log.info("TTS: воспроизведение прервано")
                        break
                    stream.write(audio[i:i + chunk])
        except Exception:
            log.exception("TTS: sounddevice упал, fallback winsound")
            import winsound
            winsound.PlaySound(wav_bytes, winsound.SND_MEMORY)


# Список доступных движков — для GUI/CLI
def available_backends() -> list[str]:
    return list_engines()


def engine_voices(backend: str) -> dict:
    """Голоса конкретного движка. Для валидации в config."""
    eng = get_engine(backend, "", "medium", 1.15)
    if eng is None:
        return {}
    return dict(eng.voices)