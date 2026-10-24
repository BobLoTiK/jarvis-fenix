"""Синтез речи — фасад над tts_engines.

Speaker не знает о Piper/Silero/SAPI напрямую — работает через
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
from typing import Iterator

from jarvis.tts_engines import get_engine, list_engines
from jarvis.tts_engines.factory import normalize_backend
from jarvis.text_utils import prepare_text

log = logging.getLogger("jarvis.tts")


class Speaker:
    def __init__(self, config, lazy: bool = False):
        from jarvis.nonverbal import Nonverbal
        self._nonverbal = Nonverbal(config if hasattr(config, "get") else {})
        self._config = config
        cfg = config if hasattr(config, "get") else {}

        self.voice = cfg.get("tts_voice") or "ruslan"
        self.rate = float(cfg.get("voice_rate", 1.15))
        self.quality = cfg.get("tts_voice_quality", "medium")
        self._backend = normalize_backend(cfg.get("tts_backend", "auto"))

        self._echo_path = None
        self._engine = None
        self._engine_name = "none"
        # Инициализация движка — под локом: ленивая загрузка в фоне и
        # switch_backend из GUI не должны создавать движок одновременно.
        self._init_lock = threading.RLock()
        self._engine_ready = threading.Event()

        # Глобальное состояние воспроизведения
        self._play_thread = None
        self._playing = False
        self._play_lock = threading.Lock()

        # Per-call stop-token
        self._current_token = threading.Event()
        self._token_lock = threading.Lock()

        # Грузим движок
        if lazy:
            # lazy=True: движок грузится в фоне. PiperVoice.load — ~2.3 с,
            # Silero — до минуты, и раньше эти секунды «висело» окно.
            log.info("TTS: движок грузится в фоне (окно появится раньше)")
            threading.Thread(target=self._init_engine_bg, daemon=True,
                             name="tts-init").start()
        else:
            self._init_engine()
            self._engine_ready.set()

    # ------------------------------------------------------------------
    # Инициализация
    # ------------------------------------------------------------------

    def _init_engine_bg(self) -> None:
        """Фоновая инициализация движка (lazy=True)."""
        try:
            self._init_engine()
        except Exception:
            log.exception("TTS: фоновая инициализация движка упала")
        finally:
            self._engine_ready.set()

    def _ensure_engine(self, timeout: float = 1.0) -> bool:
        """Bounded readiness wait only; never re-enter native initialization.

        Slow first-use downloads stay on the existing tts-init thread. An
        unanswered loader must not trap a command behind _init_lock forever.
        This does not terminate a native loader thread or select another voice.
        """
        if self._engine is not None:
            return True
        self._engine_ready.wait(max(0.0, min(float(timeout), 60.0)))
        if self._engine is None:
            log.warning("TTS: голос ещё не готов или недоступен; ответ остаётся текстовым")
            return False
        return True

    def _init_engine(self):
        with self._init_lock:
            if self._engine is not None:
                return
            self._init_engine_locked()

    def _init_engine_locked(self):
        log.info("TTS: выбираю движок (backend=%s)", self._backend)
        if self._backend == "silero":
            log.info("TTS: Silero — первая загрузка может занять 1–3 минуты")
        elif self._backend == "auto":
            log.info("TTS: auto — пробую silero → piper → sapi")
        engine = get_engine(self._backend, self.voice, self.quality,
                            self.rate)
        if engine is None:
            log.error("TTS: ни один движок не доступен")
            return
        if hasattr(engine, "set_wav_player"):
            engine.set_wav_player(self._play_wav)
        self._engine = engine
        self._engine_name = engine.name
        log.info("TTS: движок %s, голос %s, скорость %.2f",
                 self._engine_name, self.voice, self.rate)

    def switch_backend(self, backend: str) -> bool:
        """Переключить движок на лету."""
        backend = normalize_backend(backend)
        if backend == self._backend and self._engine is not None:
            return True

        # Сброс кэша голосов — при смене backend голоса другие.
        try:
            from jarvis import voices as _voices
            _voices._VOICES_CACHE.clear()
        except Exception:
            pass

        old_backend = self._backend
        self._backend = backend
        if not self._recreate_engine():
            # Возвращаем прежнее имя backend, а не имя загруженного
            # движка: иначе из «auto» в настройках оседало «silero».
            self._backend = old_backend
            return False
        return True

    def set_quality(self, quality: str) -> bool:
        """Смена качества голоса: читается только при создании движка.

        Прежний GUI-путь звал switch_backend(текущий) — ранний выход
        возвращал True, и настройка не применялась до перезапуска.
        """
        quality = quality if quality in ("medium", "high") else "medium"
        if quality == self.quality and self._engine is not None:
            return True
        self.quality = quality
        if self._engine is None:
            return True  # подхватится при ленивом создании
        return self._recreate_engine()

    def _recreate_engine(self) -> bool:
        """Serialize engine replacement; never block GUI behind pending init."""
        if not self._init_lock.acquire(blocking=False):
            log.warning("TTS: текущий движок ещё готовится; смена в этом запуске не выполнена")
            return False
        try:
            old_name = self._engine_name
            self.stop()
            if not self.wait_end(timeout=2.0):
                log.warning("TTS: предыдущая озвучка не завершилась; движок не заменён")
                return False
            engine = get_engine(self._backend, self.voice, self.quality, self.rate)
            if engine is None:
                log.warning("TTS: не удалось пересоздать движок %s", self._backend)
                return False
            if hasattr(engine, "set_wav_player"):
                engine.set_wav_player(self._play_wav)
            self._engine = engine
            self._engine_name = engine.name
            self._engine_ready.set()
            log.info("TTS: движок пересоздан %s → %s (quality=%s)",
                     old_name, self._engine_name, self.quality)
            return True
        finally:
            self._init_lock.release()

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

    def set_echo_path(self, path):
        self._echo_path = path

    def _pcm_echo_path(self):
        """Normal AEC remains Piper-only; diagnostic sessions accept WAV engines."""
        path = getattr(self, "_echo_path", None)
        if path is None:
            return None
        if self._engine_name == "piper":
            return path
        if (getattr(path, "diagnostic_mode", False) is True
                and self._engine_name == "silero"):
            return path
        return None

    def _new_token(self, allow_nonverbal=False) -> threading.Event:
        path = getattr(self, "_echo_path", None)
        if path is not None:
            if getattr(path, "diagnostic_mode", False) is True:
                path.set_trace_backend(self._engine_name, getattr(self, "voice", None))
            if self._pcm_echo_path() is None:
                path.suspend_render()
        with self._token_lock:
            self._current_token = threading.Event()
            policy = getattr(self, "_nonverbal", None)
            if policy is not None:
                policy.begin(self._current_token, allow_nonverbal)
            return self._current_token

    def _current_stop(self) -> threading.Event:
        with self._token_lock:
            return self._current_token

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def speak(self, text: str, *, allow_nonverbal=False) -> None:
        """Синхронная озвучка (для тестов и скриптов)."""
        if not text:
            return
        text = prepare_text(text)
        if not self._ensure_engine():
            return
        token = self._new_token(allow_nonverbal)
        try:
            if self._engine_name == "sapi":
                # SAPI играет сам, через стриминг с одним куском.
                list(self._engine.speak_stream(iter([text]),
                                               self.voice, self.rate, token))
                return
            wav = self._engine.synthesize(text, self.voice, self.rate)
            # Раньше байты просто выбрасывались — speak() не играл звук
            # ни на одном движке (SAPI-ветка была недостижима: hasattr
            # ловил его NotImplementedError раньше проверки имени).
            if wav:
                self._play_wav(wav, token)
        except Exception:
            log.exception("TTS: ошибка в speak()")

    def play_async(self, text: str, *, allow_nonverbal=False) -> bool:
        """Асинхронная озвучка одного текста."""
        if not text:
            return False
        text = prepare_text(text)
        if not self._ensure_engine():
            return False

        self.stop()
        finished = self.wait_end(timeout=2.0)
        if not finished:
            log.warning(
                "TTS: старый поток не завершился за 2 сек — пропускаю новый "
                "(иначе наложение)"
            )
            return False

        token = self._new_token(allow_nonverbal)
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

        return True

    def speak_stream(self, text_iter: Iterator[str],
                     timeout: float = 30.0, *, allow_nonverbal=False) -> str:
        """Стриминг: озвучивает по предложениям.

        Возвращает полный озвученный текст.
        """
        if not self._ensure_engine():
            # Просто вычитываем генератор, чтобы ничего не зависло
            return "".join(text_iter)

        self.stop()
        self.wait_end(timeout=1.0)

        token = self._new_token(allow_nonverbal)
        with self._play_lock:
            self._playing = True
            # Публикуем поток: иначе is_playing()/wait_end() во время
            # стрима отвечали «не играю» и напоминание могло озвучиться
            # поверх ответа.
            self._play_thread = threading.current_thread()

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

    def stop_requested(self) -> bool:
        """Cancellation of the current call, not completion of a native worker."""
        return self._current_stop().is_set()

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
        """Единый микшер для прямой и потоковой PCM-озвучки."""
        from jarvis.audio_output import play_wav
        policy = getattr(self, "_nonverbal", None)
        reaction = None
        if policy is not None:
            try:
                reaction = policy.take(token)
            except Exception:
                log.exception("Non-verbal: ошибка необязательной реакции; продолжаю речь")
        path = self._pcm_echo_path()
        if path is not None:
            if getattr(path, "diagnostic_mode", False) is True:
                path.set_trace_backend(self._engine_name, getattr(self, "voice", None))
            play_wav(wav_bytes, token, reaction, echo=path)
        else:
            play_wav(wav_bytes, token, reaction)


# Список доступных движков — для GUI/CLI
def available_backends() -> list[str]:
    return list_engines()


def engine_voices(backend: str) -> dict:
    """Голоса конкретного движка. Для валидации в config."""
    eng = get_engine(backend, "", "medium", 1.15)
    if eng is None:
        return {}
    return dict(eng.voices)