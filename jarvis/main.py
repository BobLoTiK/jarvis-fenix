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
from jarvis import timers
from jarvis.tts import Speaker
from jarvis.gui import FenixGUI

log = logging.getLogger("jarvis")

BASE_DIR = Path(__file__).resolve().parent.parent
_REJECT = object()


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
        self._barge_just_happened = False

        # Сериализация обработки команд: голосовой поток и GUI
        # не должны входить в handler.handle + say() одновременно.
        # Иначе два TTS накладываются, а stateful-поля IntentHandler
        # (pending_password, pending_question) портятся.
        self.cmd_lock = threading.Lock()

    def say(self, reply: Reply) -> bool:
        """Озвучивает Reply. Возвращает True, если сработал barge-in."""
        if reply is None:
            return False
        if not reply.is_stream and not reply.text:
            return False

        if self.gui is not None:
            self.gui.set_state("speaking")

        if self.barge_enabled and self.listener is not None:
            self.listener.barge_start()
        elif self.listener is not None:
            self.listener.muted = True

        barge_happened = False
        try:
            if reply.is_stream:
                self._say_stream(reply.stream)
            else:
                self._say_text(reply.text)
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

    def _say_text(self, text: str) -> None:
        self.speaker.play_async(text)
        while self.speaker.is_playing():
            if self.barge_enabled and self.listener is not None and self.listener.barge_flag:
                log.info("Barge-in сработал — прерываю TTS")
                self.speaker.stop()
                break
            time.sleep(0.05)
        self.speaker.wait_end(timeout=30.0)

    def _say_stream(self, gen) -> None:
        """Озвучивает стрим и показывает чанки в GUI.

        №73: end_stream вызывается ВСЕГДА (try/finally) — иначе при
        ошибке внутри потока стрим-пузырь в GUI зависает навсегда.

        Генератор оборачивается в tee: каждый чанк идёт и в speak_stream,
        и в GUI через add_stream_chunk.
        """
        result = {"text": ""}

        def _tee(iterator):
            """Пропускает чанки и в TTS, и в GUI."""
            for chunk in iterator:
                result["text"] += chunk
                if self.gui is not None:
                    self.gui.add_stream_chunk(chunk)
                yield chunk

        def _run():
            try:
                self.speaker.speak_stream(_tee(gen))
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

            # Финальный текст — в память
            if result["text"] and hasattr(self.handler, "finalize_stream"):
                self.handler.finalize_stream("", result["text"])

    def shutdown(self) -> None:
        self.stop_event.set()

    def mic_watchdog(self) -> None:
        """Проверяет микрофон ОДИН РАЗ через mic_check_sec.

        Больше не спамит: если микрофон молчит — предупреждает один раз
        за сессию. Дальше — тишина, пока пользователь сам не разберётся.

        self.say обёрнут в try/except: если TTS упадёт, watchdog-поток
        не умрёт молча.
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

        try:
            self.say(Reply(text="Я не слышу микрофон. Проверьте, включён ли он, "
                               "или выберите другое устройство в настройках."))
        except Exception:
            log.exception("mic_watchdog: не удалось озвучить предупреждение")

        if self.gui is not None:
            self.gui._queue.put(("open_mic_tab", None))

        log.info("mic_watchdog: предупреждение показано, больше не повторяем")

    def run_loop(self) -> None:
        try:
            for phrase, audio in self.listener.phrases(self.stop_event):
                if not self.listening_enabled:
                    continue
                try:
                    self._process(phrase, audio)
                except Exception:
                    log.exception("Ошибка обработки фразы %r", phrase)
        except Exception:
            log.exception("Аудиопоток упал")
            self.say(Reply(text="Проблема с микрофоном. Проверьте журнал."))

    def _process(self, phrase: str, audio: bytes) -> None:
        awaiting = time.time() < self._awaiting_until
        cmd = self._extract_command(normalize(phrase))
        pending = getattr(self.handler, "_pending_question", None)
        if pending and time.time() < pending.get("expires_at", 0):
            awaiting = True
        if cmd is None:
            return
        if cmd == "":
            self.say(Reply(text="Слушаю."))
            self._awaiting_until = time.time() + self.config["command_window_sec"]
            return
        if self.whisper is not None and audio:
            refined = self._refine(audio, awaiting)
            if refined is _REJECT:
                log.info("Whisper не подтвердил wake-слово — игнорирую (ложное срабатывание)")
                return
            if refined:
                cmd = refined

        if self.gui is not None:
            self.gui.add_message("user", cmd)
            self.gui.set_state("listening")

        # Сериализация с GUI: пока GUI не отдаст cmd_lock,
        # голосовой поток ждёт. И наоборот.
        with self.cmd_lock:
            reply = self.handler.handle(cmd)

            if self.gui is not None and not reply.is_stream:
                self.gui.add_message("assistant", reply.text or "")

            self._awaiting_until = time.time() + float(
                self.config.get("dialog_window_sec", 8))

            if getattr(self.handler, "_reset_requested", False):
                self.speaker.stop()
                self.speaker.wait_end(timeout=1.0)

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

    def _refine(self, audio: bytes, awaiting: bool):
        try:
            text = normalize(self.whisper.transcribe(audio))
        except Exception:
            log.exception("Whisper не справился, использую текст Vosk")
            return None
        if not text:
            return _REJECT
        tokens = text.split()
        for i, tok in enumerate(tokens):
            if self._is_wake(tok):
                return " ".join(tokens[i + 1:])
        if awaiting:
            return text
        if tokens and wake_score(tokens[0], self._wake_words[0]) >= 0.5:
            return " ".join(tokens[1:])
        return _REJECT

    def _extract_command(self, text: str) -> str | None:
        tokens = text.split()
        for i, tok in enumerate(tokens):
            if self._is_wake(tok):
                return " ".join(tokens[i + 1:])
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


def main() -> None:
    setup_logging()
    log.info("%s v%s запускается", APP_NAME, __version__)

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
    from jarvis import weather as _weather
    _profile.init()
    _weather.set_config(config)
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
            whisper = WhisperTranscriber(
                config.get("whisper_model", "auto"),
                config.get("whisper_device", "auto"),
            )
        except Exception:
            log.exception("Whisper не завёлся, работаю только на Vosk")

    brain = None
    if config.get("use_llm", True):
        from jarvis.brain import Brain
        brain = Brain(
            config.get("llm_model", "qwen2.5:7b-instruct"),
            config.get("ollama_url", "http://127.0.0.1:11434"),
            prompt_level=config.get("prompt_level", "auto"),
            temperature=config.get("llm_temperature", 0.7),
            config=config,
        )
        if not brain.available:
            brain = None

    speaker = Speaker(config)
    listener = Listener(model_dir, config["sample_rate"], config.get("input_device"))

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

    # Обратные ссылки для праздничных триггеров
    handler.jarvis = jarvis
    if gui is not None:
        gui.jarvis = jarvis

    # --- Подписки: изменения конфига применяются на лету ---
    def _on_config_change(key: str, value):
        if key == "tts_voice":
            speaker.set_voice(value)
        elif key == "voice_rate":
            speaker.set_rate(value)
        elif key == "mode":
            handler.mode = value
        elif key == "barge_enabled":
            jarvis.barge_enabled = bool(value)
            if listener is not None:
                listener.barge_enabled = bool(value)

    config.subscribe(_on_config_change)

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

    jarvis.say(Reply(text=f"{APP_NAME} запущен и готов к работе."))

    # =================================================================
    # ТРЕЙ ВРЕМЕННО ОТКЛЮЧЁН.
    #
    # Причина: pystray требует свой Windows message loop, а главный поток
    # занят flet'ом (ft.run блокирует). Попытка запустить pystray в фоне
    # приводит к зависанию GUI.
    # =================================================================
    if config.get("tray_enabled", False):
        log.warning(
            "tray_enabled=true, но трей временно отключён (в разработке). "
            "Феникс работает без трея. Выход — Ctrl+C или диспетчер задач."
        )

    # === Режим запуска (№84) ===
    launch_mode = str(config.get("launch_mode", "gui") or "gui").lower()
    if launch_mode not in ("gui", "tray"):
        launch_mode = "gui"

    if launch_mode == "tray":
        log.warning(
            "launch_mode=tray, но трей отключён — переключаюсь на gui"
        )
        launch_mode = "gui"

    if gui is not None:
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

    jarvis.shutdown()
    log.info("Завершение работы")


if __name__ == "__main__":
    main()