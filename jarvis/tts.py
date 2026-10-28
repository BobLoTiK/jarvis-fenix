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
        self._settings_lock = threading.RLock()
        self._settings_revision = 0
        self._desired_settings = (self._backend, self.voice, self.quality, self.rate)
        self._active_settings = None
        self._settings_pending = False
        self._settings_thread = None
        self._settings_error = ""

        # Глобальное состояние воспроизведения
        self._play_thread = None
        self._playing = False
        self._play_lock = threading.Lock()

        # Per-call stop-token
        self._current_token = threading.Event()
        self._stop_serial = 0
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
            with self._settings_lock:
                if not self._settings_pending:
                    self._engine_ready.set()

    def _ensure_engine(self, timeout: float = 1.0) -> bool:
        """Bounded readiness wait only; never re-enter native initialization.

        Slow first-use downloads stay on the existing tts-init thread. An
        unanswered loader must not trap a command behind _init_lock forever.
        This does not terminate a native loader thread or select another voice.
        """
        if self._engine is not None and not getattr(self, "_settings_pending", False):
            return True
        self._engine_ready.wait(max(0.0, min(float(timeout), 60.0)))
        if self._engine is None or getattr(self, "_settings_pending", False):
            log.warning("TTS: голос ещё не готов или недоступен; ответ остаётся текстовым")
            return False
        return True

    def _init_engine(self):
        with self._init_lock:
            if self._engine is not None:
                return
            self._init_engine_locked()

    def _init_engine_locked(self):
        with self._settings_lock:
            revision = self._settings_revision
            settings = self._desired_settings
        engine = self._load_settings(settings)
        with self._settings_lock:
            # A slow initial download must never overwrite a newer GUI request.
            if revision == self._settings_revision:
                if engine is not None:
                    self._publish_engine(engine, settings)
                    self._desired_settings = self._active_settings
                    active = self._active_settings
                else:
                    self._settings_error = "Движок не загрузился. Проверьте модель и журнал ошибок."
        if engine is not None and revision == self._settings_revision:
            self._rollback_config(settings, active)

    def _load_settings(self, settings):
        backend, voice, quality, rate = settings
        log.info("TTS: подготовка backend=%s, voice=%s, quality=%s", backend, voice, quality)
        engine = get_engine(backend, voice, quality, rate)
        if engine is not None:
            if hasattr(engine, "set_wav_player"):
                engine.set_wav_player(self._play_wav)
            engine.set_rate(rate)
        return engine

    def _publish_engine(self, engine, settings):
        backend, voice, quality, rate = settings
        self._engine = engine
        self._engine_name = engine.name
        self._backend, self.voice, self.quality, self.rate = settings
        # Engine constructors may normalize a voice from a different backend.
        self.voice = getattr(engine, "voice", voice)
        self._active_settings = (backend, self.voice, quality, rate)
        log.info("TTS: готов движок %s, голос %s, скорость %.2f",
                 self._engine_name, self.voice, self.rate)

    def configuration_status(self):
        """Read-only status; no downloads, engine calls, joins or native locks."""
        with self._settings_lock:
            return {"pending": self._settings_pending or not self._engine_ready.is_set(),
                    "error": self._settings_error, "backend": self._engine_name,
                    "voice": self.voice, "revision": self._settings_revision}

    def _request_settings(self, **changes):
        """Coalesce GUI edits into one loader. True means accepted, not ready."""
        keys = ("backend", "voice", "quality", "rate")
        with self._settings_lock:
            settings = dict(zip(keys, self._desired_settings))
            settings.update(changes)
            wanted = tuple(settings[k] for k in keys)
            if wanted == self._desired_settings and (self._settings_pending or self._engine is not None):
                return True
            self._desired_settings = wanted
            self._settings_revision += 1
            self._settings_pending = True
            self._settings_error = ""
            self._engine_ready.clear()
            # Cancels a preview immediately, even while a model is loading.
            self.stop()
            if self._settings_thread is None:
                worker = threading.Thread(target=self._settings_worker,
                                          daemon=True, name="tts-settings")
                self._settings_thread = worker
                try:
                    worker.start()
                except Exception:
                    self._settings_thread = None
                    self._settings_pending = False
                    self._settings_error = "Не удалось запустить подготовку голоса."
                    self._engine_ready.set()
                    if self._active_settings is not None:
                        self._desired_settings = self._active_settings
                        self._rollback_config(wanted, self._active_settings)
                    log.exception("TTS: не удалось запустить tts-settings")
                    return False
        return True

    def _settings_worker(self):
        # Waits for the initial loader here, never in a GUI/config callback.
        with self._init_lock:
            while True:
                with self._settings_lock:
                    revision = self._settings_revision
                    wanted = self._desired_settings
                engine = None
                error = ""
                try:
                    if not self.wait_end(timeout=2.0):
                        error = "Предыдущая озвучка ещё завершается. Повторите выбор после остановки."
                    else:
                        engine = self._load_settings(wanted)
                        if engine is None:
                            error = "Движок не загрузился. Проверьте модель и журнал ошибок."
                except Exception:
                    error = "Не удалось подготовить голос. Подробности в журнале."
                    log.exception("TTS: ошибка фоновой смены настроек")
                with self._settings_lock:
                    if revision != self._settings_revision:
                        continue  # superseded result must never become active
                    if engine is not None:
                        self._publish_engine(engine, wanted)
                    self._settings_error = error
                    self._settings_pending = False
                    self._engine_ready.set()
                    self._settings_thread = None
                    active = self._active_settings
                    # Retain last working runtime if replacement failed.
                    if active is not None:
                        self._desired_settings = active
                if active is not None:
                    self._rollback_config(wanted, active)
                return

    def _rollback_config(self, wanted, active):
        """CAS protects a newer user edit while rolling back a failed request."""
        keys = ("tts_backend", "tts_voice", "tts_voice_quality", "voice_rate")
        update = getattr(self._config, "update", None)
        if wanted == active:
            return
        if update is not None and not isinstance(self._config, dict):
            try:
                update(dict(zip(keys, active)), expected_values=dict(zip(keys, wanted)))
            except Exception:
                log.exception("TTS: не удалось вернуть настройки после отказа движка")

    def switch_backend(self, backend: str) -> bool:
        return self._request_settings(backend=normalize_backend(backend))

    def set_quality(self, quality: str) -> bool:
        return self._request_settings(quality=quality if quality in ("medium", "high") else "medium")

    def _recreate_engine(self) -> bool:
        # Compatibility for callers that explicitly request a reload.
        if not self._init_lock.acquire(blocking=False):
            return False
        self._init_lock.release()
        return self._request_settings()

    def set_voice(self, voice: str) -> None:
        self._request_settings(voice=voice)

    def set_rate(self, rate: float) -> None:
        self._request_settings(rate=float(rate))

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

    def _new_token(self, allow_nonverbal=False, *, cancel_event=None,
                   expected_serial=None) -> threading.Event | None:
        path = getattr(self, "_echo_path", None)
        if path is not None:
            if getattr(path, "diagnostic_mode", False) is True:
                path.set_trace_backend(self._engine_name, getattr(self, "voice", None))
            if self._pcm_echo_path() is None:
                path.suspend_render()
        with self._token_lock:
            if (expected_serial is not None and self._stop_serial != expected_serial):
                return None
            if cancel_event is not None and cancel_event.is_set():
                return None
            self._current_token = cancel_event if cancel_event is not None else threading.Event()
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
        """Synchronous facade using the same tracked, cancellable playback worker."""
        if self.play_async(text, allow_nonverbal=allow_nonverbal):
            if not self.wait_end(timeout=120.0):
                self.stop()
                self.wait_end(timeout=2.0)

    def play_async(self, text: str, *, allow_nonverbal=False, cancel_event=None) -> bool:
        """Асинхронная озвучка одного текста."""
        if not text:
            return False
        text = prepare_text(text)
        serial = getattr(self, "_stop_serial", None)
        if cancel_event is not None and cancel_event.is_set():
            return False
        if not self._ensure_engine():
            return False
        if serial is not None and serial != self._stop_serial:
            return False  # stop/change happened during readiness wait

        self.stop()
        expected = serial + 1 if serial is not None else None
        finished = self.wait_end(timeout=2.0)
        if not finished:
            log.warning(
                "TTS: старый поток не завершился за 2 сек — пропускаю новый "
                "(иначе наложение)"
            )
            return False

        token = self._new_token(allow_nonverbal, cancel_event=cancel_event,
                                expected_serial=expected)
        if token is None:
            return False
        engine, engine_name, voice, rate = self._engine, self._engine_name, self.voice, self.rate
        with self._play_lock:
            self._playing = True

        def _run():
            try:
                # SAPI играет сам, у него нет synthesize
                if token.is_set():
                    return
                if engine_name == "sapi":
                    list(engine.speak_stream(
                        iter([text]), voice, rate, token
                    ))
                else:
                    wav = engine.synthesize(text, voice, rate)
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
        serial = getattr(self, "_stop_serial", None)
        if not self._ensure_engine():
            # Просто вычитываем генератор, чтобы ничего не зависло
            return "".join(text_iter)
        if serial is not None and serial != self._stop_serial:
            return "".join(text_iter)

        self.stop()
        if not self.wait_end(timeout=1.0):
            return "".join(text_iter)

        token = self._new_token(allow_nonverbal,
                                expected_serial=serial + 1 if serial is not None else None)
        if token is None:
            return "".join(text_iter)
        engine, voice, rate = self._engine, self.voice, self.rate
        with self._play_lock:
            self._playing = True
            # Публикуем поток: иначе is_playing()/wait_end() во время
            # стрима отвечали «не играю» и напоминание могло озвучиться
            # поверх ответа.
            self._play_thread = threading.current_thread()

        try:
            return engine.speak_stream(
                text_iter, voice, rate, token
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
            self._stop_serial = getattr(self, "_stop_serial", 0) + 1
            token = self._current_token
            was_stopped = token.is_set()
            token.set()
        if not was_stopped:
            log.info("TTS: прерывание")
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
        if thread is threading.current_thread():
            return False
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