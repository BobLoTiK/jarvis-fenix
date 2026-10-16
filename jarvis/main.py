"""Точка входа: связывает распознавание, интенты, синтез речи и GUI.

Barge-in: во время речи Феникса микрофон НЕ глушится, а следит за громкостью.
Если юзер заговорил — TTS прерывается через speaker.stop().
После barge-in окно диалога открывается заново — можно продолжать без wake-слова.

Стриминг: генератор оборачивается в tee — чанки идут и в TTS, и в GUI.

launch_mode:
    "gui"  — окно Flet + трей + голос (по умолчанию).
    "tray" — только трей + голос, без окна.
"""

import logging
import logging.handlers
import threading
import time
from pathlib import Path

from jarvis.matching import wake_score

from jarvis import APP_NAME, __version__
from jarvis.apps import build_apps
from jarvis.config import Config, load_config
from jarvis.intents import IntentHandler
from jarvis.text_utils import normalize
from jarvis.model import ensure_model
from jarvis.reply import Reply
from jarvis.stt import Listener
from jarvis import safety
from jarvis import timers
from jarvis.tts import Speaker
from jarvis.gui import FenixGUI

log = logging.getLogger("jarvis")

BASE_DIR = Path(__file__).resolve().parent.parent
_REJECT = object()
_UNCERTAIN = object()


class Jarvis:
    def __init__(self, config, listener, speaker, handler, base_dir: Path,
                 whisper=None, gui=None):
        self.config = config
        self.listener = listener
        self.speaker = speaker
        self.handler = handler
        self.base_dir = base_dir
        self.whisper = whisper
        self.gui = gui
        self.listening_enabled = True
        self.stop_event = threading.Event()
        self._awaiting_until = 0.0
        self._wake_words = [normalize(w) for w in config["wake_words"]]
        self.barge_enabled = bool(config.get("barge_enabled", True))
        if self.listener is not None:
            self.listener.barge_enabled = self.barge_enabled
            self.listener.sensitive_input = lambda: bool(
                getattr(self.handler, "_pending_password", None)
            )
        self._barge_just_happened = False

        # Wake-слово обязательно по умолчанию.
        # Если wake_word_required=False — VAD уже отфильтровал тишину/шум,
        # и любая распознанная фраза идёт в обработку.
        self._wake_word_required = bool(
            config.get("wake_word_required", True)
        )
        log.info(
            "Wake-слово: %s",
            "обязательно" if self._wake_word_required else "отключено (VAD-режим)"
        )

        # Сериализация обработки команд: голосовой поток и GUI
        # не должны входить в handler.handle + say() одновременно.
        # Иначе два TTS накладываются, а stateful-поля IntentHandler
        # (pending_password, pending_question) портятся.
        self.cmd_lock = threading.Lock()

        # Отдельный лок для say(). cmd_lock сериализует только handle(),
        # а say() зовут ещё таймеры (timers._fire), mic_watchdog и
        # celebrations — раньше они входили без лока, и speaker.stop()
        # обрывал текущую фразу (или сам таймер молча съедался
        # по wait_end-таймауту). RLock — на случай вложенного вызова.
        self._say_lock = threading.RLock()

    def say(self, reply: Reply) -> bool:
        """Озвучивает Reply. Возвращает True, если сработал barge-in."""
        if reply is None:
            return False
        if not reply.is_stream and not reply.text:
            return False

        with self._say_lock:
            return self._say_locked(reply)

    def _say_locked(self, reply: Reply) -> bool:
        """Тело say() — вызывать ТОЛЬКО через say(), под _say_lock."""
        if self.gui is not None:
            self.gui.set_state("speaking")

        if self.barge_enabled and self.listener is not None:
            self.listener.barge_start()
        elif self.listener is not None:
            self.listener.muted = True

        barge_happened = False
        try:
            if reply.is_stream:
                self._say_stream(reply.stream, allow_nonverbal=reply.allow_nonverbal)
            else:
                self._say_text(reply.text, allow_nonverbal=reply.allow_nonverbal)
            barge_happened = (
                self.barge_enabled
                and self.listener is not None
                and self.listener.barge_flag
            )
        finally:
            if self.barge_enabled and self.listener is not None:
                self.listener.barge_end()
            if self.listener is not None:
                # flush() теперь чистит только очередь — Vosk не трогает.
                self.listener.flush()
                self.listener.muted = False
            if self.gui is not None:
                self.gui.set_state("idle")
        return barge_happened

    def _say_text(self, text: str, *, allow_nonverbal=False) -> None:
        # Постфильтр «красной черты»: промпт в brain.py её только просит.
        ok, reason = safety.check_response(text)
        if not ok:
            log.error(
                "Safety: ответ заблокирован (категория=%s) — озвучиваю заглушку",
                reason,
            )
            text = safety.SAFE_REPLY
        self.speaker.play_async(text, allow_nonverbal=allow_nonverbal and ok)
        while self.speaker.is_playing():
            if self.barge_enabled and self.listener is not None and self.listener.barge_flag:
                log.info("Barge-in сработал — прерываю TTS")
                self.speaker.stop()
                break
            time.sleep(0.05)
        self.speaker.wait_end(timeout=30.0)

    def _say_stream(self, gen, *, allow_nonverbal=False) -> None:
        """Озвучивает стрим и показывает чанки в GUI.

        №73: end_stream вызывается ВСЕГДА (try/finally) — иначе при
        ошибке внутри потока стрим-пузырь в GUI зависает навсегда.

        Генератор оборачивается в tee: каждый чанк идёт и в speak_stream,
        и в GUI через add_stream_chunk.
        """
        result = {"text": ""}
        # Состояние постфильтра: safety кладёт сюда весь текст и факт блокировки.
        guard: dict = {}

        def _tee(iterator):
            """Пропускает чанки и в TTS, и в GUI."""
            for chunk in iterator:
                result["text"] += chunk
                if self.gui is not None:
                    self.gui.add_stream_chunk(chunk)
                yield chunk

        def _run():
            try:
                # Постфильтр: начало стрима придерживается до проверки.
                self.speaker.speak_stream(
                    _tee(safety.guard_stream(gen, guard)),
                    allow_nonverbal=allow_nonverbal,
                )
            except Exception:
                log.exception("Ошибка в speak_stream")

        t = threading.Thread(target=_run, daemon=True, name="tts-stream")
        t.start()

        try:
            while t.is_alive():
                if self.barge_enabled and self.listener is not None and self.listener.barge_flag:
                    log.info("Barge-in сработал — прерываю стриминг")
                    self.speaker.stop()
                    t.join(timeout=1.0)
                    break
                time.sleep(0.05)
            t.join(timeout=5.0)
        finally:
            # №73: закрываем стрим-пузырь ВСЕГДА
            if self.gui is not None:
                self.gui.end_stream()

            if guard.get("blocked"):
                log.error(
                    "Safety: ответ заблокирован (категория=%s) — стрим прерван",
                    guard.get("reason"),
                )

            # Финальный текст — в память. Заблокированный ответ в память
            # не пишем: он не прозвучал.
            if (result["text"] and not guard.get("blocked")
                    and hasattr(self.handler, "finalize_stream")):
                self.handler.finalize_stream(result["text"])

    def shutdown(self) -> None:
        self.stop_event.set()

    def mic_watchdog(self) -> None:
        """One passive startup diagnostic in the log; never speak or steal a tab.

        Silence alone is not proof of a faulty microphone. Explicit level testing
        stays available in GUI; real audio-stream errors are handled separately.
        """
        if not self.config.get("mic_watchdog_enabled", True):
            log.info("mic_watchdog выключен в config")
            return

        delay = float(self.config.get("mic_check_sec", 20))
        if self.stop_event.wait(delay):
            return

        if self.listener.peak >= 50:
            log.info("mic_watchdog: пик %d — микрофон живой", self.listener.peak)
            return

        log.warning("Микрофон молчит (пик %d за %.0f с): %s",
                    self.listener.peak, delay, self.listener.device_name)

        log.info("mic_watchdog: результат только в журнале, без озвучки и переключения GUI")

    def run_loop(self) -> None:
        try:
            for phrase, audio in self.listener.phrases(self.stop_event):
                if not self.listening_enabled:
                    continue
                try:
                    self._process(phrase, audio)
                except Exception:
                    log.exception("Ошибка обработки голосовой команды")
        except Exception:
            log.exception("Аудиопоток упал")
            self.say(Reply(text="Проблема с микрофоном. Проверьте журнал."))

    def _process(self, phrase: str, audio: bytes) -> None:
        awaiting = time.time() < self._awaiting_until
        sensitive = bool(getattr(self.handler, "_pending_password", None))
        pending = getattr(self.handler, "_pending_question", None)
        from jarvis.intents.clarification import pending_alive
        if pending_alive(pending):
            awaiting = True
            self._awaiting_until = max(self._awaiting_until, pending["expires_at"])
        if sensitive:
            # Ввод пароля не зависит от окна wake и сохраняет исходный текст.
            tokens = phrase.strip().split(maxsplit=1)
            cmd = phrase.strip()
            if tokens and self._is_wake(normalize(tokens[0])):
                cmd = tokens[1] if len(tokens) > 1 else ""
        else:
            cmd = self._extract_command(phrase)
        if cmd is None:
            return
        if audio:
            if self.gui is not None:
                self.gui.set_state("recognizing")
            from jarvis.recognition import assess_pcm, transcripts_agree
            quality = assess_pcm(audio, self.config.get("sample_rate", 16000))
            if not quality.accepted:
                self._request_repeat()
                return
            primary = getattr(getattr(self, "listener", None), "last_quality", None)
            if self.whisper is not None and not sensitive:
                refined = self._refine(audio, awaiting)
                if refined is _REJECT:
                    if self.gui is not None:
                        self.gui.set_state("idle")
                    return  # Не подтвердилось обращение к ассистенту.
                if refined is _UNCERTAIN:
                    self._request_repeat()
                    return
                if refined is not None:
                    if primary is not None and primary.accepted and not transcripts_agree(cmd, refined):
                        self._request_repeat()
                        return
                    cmd = refined
                elif primary is None or not primary.accepted:
                    # Ошибка Whisper — не повод безусловно доверять Vosk.
                    self._request_repeat()
                    return
            elif primary is None or not primary.accepted:
                self._request_repeat()
                return
        if cmd == "":
            self.say(Reply(text="Слушаю."))
            self._awaiting_until = time.time() + self.config["command_window_sec"]
            return

        if self.gui is not None:
            self.gui.set_state("listening")

        # Prosody: эмоция из тона голоса ДО обработки текста.
        # Если включена и уверена — ставит mood из audio.
        if audio and self.config.get("prosody_enabled", True):
            try:
                from jarvis import mood as _mood
                _mood.apply_from_prosody(
                    audio,
                    self.config.get("sample_rate", 16000),
                    config=self.config,
                )
            except Exception:
                log.exception("Prosody: ошибка анализа")

        # Проверяем чувствительный ввод под тем же локом, что и handle().
        with self.cmd_lock:
            sensitive = sensitive or bool(getattr(self.handler, "_pending_password", None))
            if self.gui is not None:
                self.gui.add_message("user", "[Ввод пароля скрыт]" if sensitive else cmd)
            if not sensitive:
                recent = getattr(getattr(self, "listener", None), "recent_phrases", None)
                if recent is not None:
                    recent.append(cmd)
            # Короткий ответ на слот — не постоянный факт о пользователе.
            answering_slot = pending_alive(getattr(self.handler, "_pending_question", None))
            if not sensitive and not answering_slot and getattr(self, "observer", None) is not None:
                try:
                    self.observer.observe("user", cmd)
                except Exception:
                    log.exception("Observer.observe (user) упал")

            if self.gui is not None:
                self.gui.set_state("thinking")
            reply = self.handler.handle(cmd)

            if self.gui is not None and not reply.is_stream:
                self.gui.add_message("assistant", reply.text or "")

            self._awaiting_until = time.time() + float(
                self.config.get("dialog_window_sec", 8))

            if getattr(self.handler, "_reset_requested", False):
                self.speaker.stop()
                self.speaker.wait_end(timeout=1.0)

            # Observer: запоминаем ответ Феникса.
            if getattr(self, "observer", None) is not None and not reply.is_stream:
                try:
                    self.observer.observe("assistant", reply.text or "")
                except Exception:
                    log.exception("Observer.observe (assistant) упал")

            barge_happened = self.say(reply)

            if getattr(self.handler, "_reset_requested", False):
                self._awaiting_until = 0.0
                self.handler._reset_requested = False
                log.info("Сброс: жду wake-слово")
                return

            if barge_happened:
                log.info("Barge-in: окно диалога уже открыто (без wake-слова)")
                self._awaiting_until = time.time() + float(
                    self.config.get("dialog_window_sec", 8))

    def _request_repeat(self):
        """Уточнение без записи сомнительной расшифровки в историю/память."""
        now = time.monotonic()
        if now - getattr(self, "_last_repeat_at", float("-inf")) < 3.0:
            return
        self._last_repeat_at = now
        reply = Reply(text="Не расслышал. Повтори, пожалуйста.")
        if self.gui is not None:
            self.gui.add_message("assistant", reply.text)
        self.say(reply)
        self._awaiting_until = time.time() + float(self.config.get("command_window_sec", 6))

    def _refine(self, audio: bytes, awaiting: bool):
        try:
            text = self.whisper.transcribe(
                audio, sample_rate=self.config.get("sample_rate", 16000)
            ).strip()
        except Exception:
            log.exception("Whisper не справился; Vosk допустим только при достаточной уверенности")
            return None
        quality = getattr(self.whisper, "last_quality", None)
        if quality is None or not quality.accepted:
            return _UNCERTAIN
        if not text:
            return _UNCERTAIN
        import re
        tokens = list(re.finditer(r"\S+", text))
        for token in tokens:
            if self._is_wake(normalize(token.group())):
                return text[token.end():].lstrip(" ,.!?:;—")
        if awaiting or not self._wake_word_required:
            return text
        return _REJECT

    def _extract_command(self, text: str) -> str | None:
        """Извлекает команду из текста.

        Режимы:
            wake_word_required=True (default):
                Ищем wake-слово. Если нашли — берём текст после него.
                Если фраза в окне диалога — берём как есть.
                Иначе — None (игнорируем).
            wake_word_required=False:
                Wake-слово НЕ нужно. VAD уже отфильтровал тишину/шум,
                поэтому любой распознанный текст — это речь юзера.
                Возвращаем как есть.
        """
        # Режим без wake: VAD уже отфильтровал, любой текст — команда.
        if not self._wake_word_required:
            return text.strip() or None

        import re
        tokens = list(re.finditer(r"\S+", text))
        for token in tokens:
            if self._is_wake(normalize(token.group())):
                return text[token.end():].lstrip(" ,.!?:;—")
        if time.time() < self._awaiting_until:
            return text
        return None

    def _is_wake(self, token: str) -> bool:
        return token in self._wake_words or any(
            wake_score(token, w) >= 0.8 for w in self._wake_words
        )


def setup_logging() -> None:
    from jarvis import paths as _paths

    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    LOGS_DIR = _paths.logs_dir()

    fmt = "%(asctime)s %(name)s %(levelname)s %(message)s"
    formatter = logging.Formatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(logging.INFO)
    root.addHandler(console)

    jarvis_handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / "jarvis.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    jarvis_handler.setFormatter(formatter)
    jarvis_handler.setLevel(logging.INFO)
    root.addHandler(jarvis_handler)

    errors_handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / "errors.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    errors_handler.setFormatter(formatter)
    errors_handler.setLevel(logging.WARNING)
    root.addHandler(errors_handler)

    actions_logger = logging.getLogger("jarvis.actions")
    actions_logger.setLevel(logging.INFO)
    actions_logger.propagate = False
    actions_handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / "actions.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    actions_handler.setFormatter(formatter)
    actions_logger.addHandler(actions_handler)

    # Observer: отдельный файл. Это данные пользователя («что из диалога
    # вытащили»), поэтому держим их отдельно от общего jarvis.log —
    # propagate=False, чтобы факты не дублировались в общий лог.
    observer_logger = logging.getLogger("jarvis.observer")
    observer_logger.setLevel(logging.INFO)
    observer_logger.propagate = False
    observer_handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / "observer.log",
        maxBytes=1024 * 1024,
        backupCount=2,
        encoding="utf-8",
    )
    observer_handler.setFormatter(formatter)
    observer_logger.addHandler(observer_handler)

    # Глобальный перехват исключений в потоках
    def _thread_excepthook(args):
        thread_name = args.thread.name if args.thread else "?"
        log.critical(
            "Необработанное исключение в потоке %r:",
            thread_name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = _thread_excepthook

    # Глобальный перехват для ГЛАВНОГО потока
    import sys

    def _sys_excepthook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            return
        log.critical(
            "Необработанное исключение в главном потоке:",
            exc_info=(exc_type, exc_value, exc_tb),
        )

    sys.excepthook = _sys_excepthook


def make_config_listener(jarvis, config, listener, speaker, handler,
                        apply_tray=None):
    """Собирает подписчик config → живые компоненты (для Config.subscribe).

    Почему отдельной функцией: раньше это жило внутри main() и
    проверялось только руками. Из-за этого часть настроек из GUI
    «терялась» — например, ползунок порога VAD писал config.json,
    но работающий VAD о нём не узнавал (порог читается только при
    создании VAD), а смена микрофона требовала перезапуска.

    apply_tray(enabled) — необязательный обработчик ключа tray_enabled
    (иконку нельзя поднять из тестов: нужен pystray и живой рабочий стол).

    Возвращает callback(key, value).
    """
    def _on_config_change(key: str, value):
        if key == "tts_voice":
            speaker.set_voice(value)
        elif key == "voice_rate":
            speaker.set_rate(value)
        elif key == "mode":
            handler.mode = value
        elif key == "tray_enabled":
            if apply_tray is not None:
                apply_tray(bool(value))
        elif key == "barge_enabled":
            jarvis.barge_enabled = bool(value)
            if listener is not None:
                listener.barge_enabled = bool(value)
        elif key == "wake_word_required":
            jarvis._wake_word_required = bool(value)
            log.info("Wake-слово: %s",
                     "обязательно" if value else "отключено")
        elif key == "tts_backend":
            # Смена backend TTS на лету
            try:
                speaker.switch_backend(str(value))
            except Exception:
                log.exception("Не удалось переключить TTS backend")
        elif key == "tts_voice_quality":
            # Качество читается только при создании движка — пересоздаём.
            try:
                speaker.set_quality(str(value))
            except Exception:
                log.exception("Не удалось переключить качество голоса")
        elif key == "vad_enabled":
            if listener is not None:
                listener.set_vad_enabled(bool(value))
        elif key in ("vad_threshold", "vad_adaptive", "vad_hangover_ms",
                     "vad_auto_download"):
            # Порог / адаптивность / «хвост» / авто-скачивание модели
            # читаются ТОЛЬКО при создании VAD — без пересоздания
            # слайдеры и чекбокс в GUI ни на что не влияли.
            if listener is not None:
                listener.reload_vad()
        elif key == "input_device":
            # Смена микрофона на лету: listener сам переоткроет
            # RawInputStream на новом устройстве (без перезапуска).
            if listener is not None:
                listener.set_input_device(value)
        elif key in ("memory_rag_enabled", "memory_rag_model",
                     "ollama_url", "memory_rag_top_k"):
            # Векторная память читает конфиг на каждый вызов, поэтому
            # достаточно разбудить индексацию и сбросить кэши.
            from jarvis import vectormem
            vectormem.on_config_change(key, value)

    return _on_config_change


# Handle мьютекса держим на уровне модуля: соберёт GC — мьютекс
# освободится, и второй экземпляр сможет стартовать.
_MUTEX_HANDLE = None


def _single_instance() -> bool:
    """Именованный мьютекс на всё время работы процесса.

    Старый скомпилированный launcher держит то же имя до выхода после Popen:
    ожидаем его краткую передачу. Новый launcher имеет отдельный setup-mutex.
    Настоящий guard живёт здесь всё время работы ядра (AppMutex инсталлятора).
    """
    global _MUTEX_HANDLE
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    # Older Phoenix.exe holds the SAME mutex until it exits after Popen.
    # Give that short-lived parent time to exit; a real running core keeps it.
    deadline = time.monotonic() + 3.0
    while True:
        handle = kernel32.CreateMutexW(None, False,
                                      "Local\\JarvisPhoenixSingleInstance")
        exists = kernel32.GetLastError() == 183
        if not handle:
            raise ctypes.WinError()
        if not exists:
            _MUTEX_HANDLE = handle
            return True
        kernel32.CloseHandle(handle)
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def main() -> None:
    setup_logging()
    log.info("%s v%s запускается", APP_NAME, __version__)

    if not _single_instance():
        log.warning("Феникс уже запущен — второй экземпляр не стартую")
        return

    # Порядок импортов критичен для Windows:
    #   faster_whisper → ctranslate2 → winrt.
    # Если faster_whisper нет — ctranslate2 нет — winrt может дать
    # access violation. Поэтому логируем явно, что отсутствует.
    for _mod in ("faster_whisper", "ctranslate2"):
        try:
            __import__(_mod)
        except ImportError:
            log.warning(
                "Модуль %s не установлен. Whisper будет недоступен, "
                "работаю только на Vosk. Установи: pip install %s",
                _mod, _mod.replace("_", "-"),
            )

    config: Config = load_config(BASE_DIR)
    from jarvis import profile as _profile
    from jarvis import vectormem
    from jarvis import weather as _weather
    _profile.init()
    _weather.set_config(config)
    vectormem.set_config(config)
    # ensure_model сам найдёт/скопирует/скачает модель в ASCII-путь.
    # Передаём локальную папку models (может быть в C:\jarvis\models),
    # если она есть — модель скопируется оттуда, иначе скачается.
    local_models = BASE_DIR / "models"
    if not local_models.exists():
        local_models = None
    model_dir = ensure_model(local_models)

    whisper = None
    if config.get("use_whisper", True):
        try:
            from jarvis.stt import WhisperTranscriber
            # lazy=True: large-v3-turbo грузится в фоне (~5 с на GPU,
            # десятки секунд на CPU). Раньше старт Феникса ждал эту
            # загрузку и окно GUI появлялось поздно.
            whisper = WhisperTranscriber(
                config.get("whisper_model", "auto"),
                config.get("whisper_device", "auto"),
                lazy=True,
                config=config,
            )
            whisper.preload_async()
        except Exception:
            log.exception("Whisper не завёлся, работаю только на Vosk")

    brain = None
    if config.get("use_llm", True):
        try:
            from jarvis.brain import Brain
            brain = Brain(
                config.get("llm_model", "qwen2.5:7b-instruct"),
                config.get("ollama_url", "http://127.0.0.1:11434"),
                prompt_level=config.get("prompt_level", "auto"),
                temperature=config.get("llm_temperature", 0.7),
                config=config,
            )
        except Exception:
            # Битый ollama_url и прочие неожиданности не должны ронять
            # старт: Феникс живёт и без LLM.
            log.exception("Brain не завёлся — работаю без LLM")
            brain = None
        if brain is not None and not brain.available:
            brain = None

    # Векторная память: индексация фактов в фоне. Модель эмбеддингов
    # подтянется только когда фича включена (см. vectormem.warmup_async).
    vectormem.warmup_async()

    # Speaker с lazy=True: движок (PiperVoice.load ~2.3 с, Silero — до
    # минуты) грузится в фоне, окно Феникса появляется сразу.
    speaker = Speaker(config, lazy=True)
    listener = Listener(
        model_dir,
        config["sample_rate"],
        config.get("input_device"),
        config=config,
    )

    gui = None
    if config.get("gui_enabled", True):
        try:
            gui = FenixGUI(None, config)
        except Exception:
            log.exception("GUI не завёлся")

    handler = IntentHandler(
        config, build_apps(config), brain,
        listener=listener, gui=gui,
    )

    jarvis = Jarvis(config, listener, speaker, handler, BASE_DIR, whisper, gui=gui)

    # Прогрев тяжёлых API — brightness через WMI (~0.5 сек).
    # Иначе первый голосовой запрос «какая яркость» виснет.
    try:
        from jarvis import actions
        actions.get_brightness()
    except Exception:
        log.debug("Прогрев brightness не удался — не критично")

    # Обратные ссылки для праздничных триггеров
    handler.jarvis = jarvis
    if gui is not None:
        gui.jarvis = jarvis


    # Observer — фоновое извлечение фактов из диалога.
    try:
        from jarvis import profile as _profile_mod
        from jarvis import learning as _learning_mod
        from jarvis.observer import DialogObserver
        observer = DialogObserver(
            config=config,
            brain=brain,
            profile_module=_profile_mod,
            learning_module=_learning_mod,
        )
        observer.start()
        jarvis.observer = observer
        handler.observer = observer
    except Exception:
        log.exception("Observer не завёлся")
        observer = None

    # =================================================================
    # Трей (pystray).
    #
    # Состояние держим в словаре: иконку можно поднять/снять на лету
    # (ключ tray_enabled). Иконка поднимается ДО ft.run() — pystray
    # держит собственный Windows message loop, а главный поток вот-вот
    # заберёт Flet. Ошибки трея НИКОГДА не роняют Феникса: нет
    # pystray/PIL — значит просто нет трея.
    # =================================================================
    tray_holder = {"icon": None}
    tray_lock = threading.RLock()

    def _tray_failed(failed_icon=None) -> None:
        """Restore an accessible window when the active tray loop dies."""
        with tray_lock:
            if failed_icon is not None and tray_holder["icon"] is not failed_icon:
                return
            tray_holder["icon"] = None
            if jarvis.stop_event.is_set():
                return
            if gui is not None:
                gui.start_hidden = False
                gui.set_tray_active(False)
                gui.show_window()  # queued, also safe before the Flet session exists

    def _apply_tray(enabled: bool) -> None:
        """Включает/выключает иконку трея и режим «крестик сворачивает»."""
        with tray_lock:
            if enabled and tray_holder["icon"] is None:
                try:
                    from jarvis.tray import start_tray
                    tray_holder["icon"] = start_tray(jarvis, on_fail=_tray_failed)
                except Exception:
                    log.exception("Трей: запуск упал — работаю без трея")
            elif not enabled and tray_holder["icon"] is not None:
                old_icon = tray_holder["icon"]
                tray_holder["icon"] = None
                try:
                    old_icon.stop()
                except Exception:
                    log.debug("Трей: иконка уже снята", exc_info=True)
                if gui is not None:
                    gui.start_hidden = False
                    gui.show_window()

            if gui is not None:
                # Трей есть -> крестик прячет окно, нет -> окно закрывается.
                gui.set_tray_active(tray_holder["icon"] is not None)

    # --- Подписки: изменения конфига применяются на лету ---
    config.subscribe(make_config_listener(jarvis, config, listener,
                                          speaker, handler,
                                          apply_tray=_apply_tray))

    def _on_timer_fire(timer: dict):
        text = timer.get("text") or "время вышло"
        msg = f"Напоминание: {text}."
        log.info("Таймер сработал: %s", msg)
        jarvis.say(Reply(text=msg))

    timers.set_on_fire(_on_timer_fire)
    restored = timers.restore_all()
    if restored:
        log.info("Восстановлено напоминаний: %d", restored)

    # Jarvis — в фоновом потоке
    worker = threading.Thread(target=jarvis.run_loop, daemon=True, name="jarvis-listener")
    worker.start()
    threading.Thread(target=jarvis.mic_watchdog, daemon=True, name="mic-watchdog").start()

    # Mood: раз в 60 сек проверяем, не «устарело» ли состояние.
    # Возврат к neutral через 5 мин (см. mood.decay).
    def _mood_decay_loop():
        while not jarvis.stop_event.is_set():
            if jarvis.stop_event.wait(60.0):
                return
            try:
                from jarvis import mood
                mood.decay()
            except Exception:
                log.exception("mood.decay упал в фоновом потоке")

    threading.Thread(target=_mood_decay_loop, daemon=True,
                     name="mood-decay").start()

    def _greet() -> None:
        """Приветствие в фоне.

        Раньше jarvis.say() вызывался прямо здесь, в главном потоке:
        TTS (с загрузкой движка) + ожидание конца фразы держали старт,
        и окно Flet появлялось только после приветствия. Теперь
        приветствие идёт параллельно с показом окна.
        """
        try:
            from jarvis import first_run
            if first_run.is_first_run():
                log.info("Первый запуск: приветствие через задачу")
                jarvis.say(Reply(text=first_run.greeting()))
            else:
                jarvis.say(Reply(text=f"{APP_NAME} запущен и готов к работе."))
        except Exception:
            log.exception("Ошибка приветствия")
            try:
                jarvis.say(Reply(text=f"{APP_NAME} запущен и готов к работе."))
            except Exception:
                log.exception("Повторное приветствие тоже упало")

    threading.Thread(target=_greet, daemon=True, name="greeting").start()

    # Иконка трея поднимается ЗДЕСЬ — до ft.run (см. _apply_tray выше).
    _apply_tray(bool(config.get("tray_enabled", True)))

    # === Режим запуска (№84) ===
    launch_mode = str(config.get("launch_mode", "gui") or "gui").lower()
    if launch_mode not in ("gui", "tray"):
        launch_mode = "gui"

    # launch_mode=tray без иконки — окно осталось бы скрытым навсегда.
    if launch_mode == "tray" and tray_holder["icon"] is None:
        log.warning(
            "launch_mode=tray, но трей не поднялся — переключаюсь на gui"
        )
        launch_mode = "gui"

    if gui is not None:
        gui.start_hidden = launch_mode == "tray"
        if launch_mode == "tray":
            log.info("launch_mode=tray — GUI запущен, но окно скрыто")
            gui.start_hidden = True
        else:
            log.info("Запускаю Flet в главном потоке (launch_mode=gui)")

        # Flet ВСЕГДА в главном потоке (signal.signal)
        gui.run_main()
    else:
        log.info("GUI выключен — жду завершения")
        jarvis.stop_event.wait()

    if tray_holder["icon"] is not None:
        stopping_icon = tray_holder["icon"]
        tray_holder["icon"] = None
        try:
            stopping_icon.stop()
        except Exception:
            log.debug("Трей: иконка уже снята", exc_info=True)

    jarvis.shutdown()
    log.info("Завершение работы")


if __name__ == "__main__":
    main()