"""Точка входа: связывает распознавание, интенты, синтез речи и трей.

Barge-in: во время речи Феникса микрофон НЕ глушится, а следит за громкостью.
Если юзер заговорил — TTS прерывается через speaker.stop().
После barge-in окно диалога открывается заново — можно продолжать без wake-слова.

Стриминг: генератор оборачивается в tee — чанки идут и в TTS, и в GUI.
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
from jarvis.intents import IntentHandler, normalize
from jarvis.model import ensure_model
from jarvis.reply import Reply
from jarvis.stt import Listener
from jarvis.tray import build_tray
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

    def say(self, reply: Reply) -> bool:
        """Озвучивает Reply. Возвращает True, если сработал barge-in.

        reply — всегда Reply (из handler.handle или собранный вручную).
        """
        if reply is None:
            return False
        if not reply.is_stream and not reply.text:
            return False

        if self.gui is not None:
            self.gui.set_state("speaking")

        if self.barge_enabled and self.listener is not None:
            self.listener.barge_start()
        else:
            self.listener.muted = True

        barge_happened = False
        try:
            if reply.is_stream:
                self._say_stream(reply.stream)
            else:
                self._say_text(reply.text)
            barge_happened = self.barge_enabled and self.listener.barge_flag
        finally:
            if self.barge_enabled and self.listener is not None:
                self.listener.barge_end()
            self.listener.flush()
            self.listener.muted = False
            if self.gui is not None:
                self.gui.set_state("idle")
        return barge_happened

    def _say_text(self, text: str) -> None:
        self.speaker.play_async(text)
        while self.speaker.is_playing():
            if self.barge_enabled and self.listener.barge_flag:
                log.info("Barge-in сработал — прерываю TTS")
                self.speaker.stop()
                break
            time.sleep(0.05)
        self.speaker.wait_end(timeout=30.0)

    def _say_stream(self, gen) -> None:
        """Озвучивает стрим и показывает чанки в GUI.

        Генератор оборачивается в tee: каждый чанк идёт
        и в speak_stream, и в GUI через add_stream_chunk.
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

        while t.is_alive():
            if self.barge_enabled and self.listener.barge_flag:
                log.info("Barge-in сработал — прерываю стриминг")
                self.speaker.stop()
                t.join(timeout=1.0)
                break
            time.sleep(0.05)
        t.join(timeout=5.0)

        # Закрываем стрим-пузырь в GUI
        if self.gui is not None:
            self.gui.end_stream()

        # Финальный текст — в память
        if result["text"] and hasattr(self.handler, "finalize_stream"):
            self.handler.finalize_stream("", result["text"])

    def shutdown(self) -> None:
        self.stop_event.set()

    def mic_watchdog(self) -> None:
        delay = float(self.config.get("mic_check_sec", 20))
        if self.stop_event.wait(delay):
            return
        if self.listener.utterances == 0 and self.listener.peak < 200:
            log.warning("Микрофон молчит (пик %d за %.0f с): %s — проверьте устройство",
                        self.listener.peak, delay, self.listener.device_name)
            self.say(Reply(text="Я не слышу микрофон. Проверьте, включён ли он, "
                               "или укажите нужный в настройках."))

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

        # Сообщаем GUI о команде
        if self.gui is not None:
            self.gui.add_message("user", cmd)
            self.gui.set_state("listening")

        reply = self.handler.handle(cmd)

        # Текстовый ответ — сразу в GUI.
        # Стрим — добавится в _say_stream через tee.
        if self.gui is not None and not reply.is_stream:
            self.gui.add_message("assistant", reply.text or "")

        barge_happened = self.say(reply)

        if getattr(self.handler, "_reset_requested", False):
            self._awaiting_until = 0.0
            self.handler._reset_requested = False
            log.info("Сброс: жду wake-слово")
            return

        if barge_happened:
            log.info("Barge-in: открываю окно диалога (без wake-слова)")
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
    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    LOGS_DIR = BASE_DIR / "logs"
    LOGS_DIR.mkdir(exist_ok=True)

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


def main() -> None:
    setup_logging()
    log.info("%s v%s запускается", APP_NAME, __version__)

    # Порядок импортов критичен для Windows:
    #   faster_whisper → ctranslate2 → winrt.
    try:
        import faster_whisper  # noqa: F401
        import ctranslate2  # noqa: F401
    except ImportError:
        pass

    config: Config = load_config(BASE_DIR)
    from jarvis import profile as _profile
    _profile.init()
    model_dir = ensure_model(BASE_DIR / "models")

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
        )
        if not brain.available:
            brain = None

    speaker = Speaker(config)
    listener = Listener(model_dir, config["sample_rate"], config.get("input_device"))
    handler = IntentHandler(config, build_apps(config), brain)

    gui = None
    if config.get("gui_enabled", True):
        try:
            gui = FenixGUI(None, config)
        except Exception:
            log.exception("GUI не завёлся")

    jarvis = Jarvis(config, listener, speaker, handler, BASE_DIR, whisper, gui=gui)

    if gui is not None:
        gui.jarvis = jarvis
        # НЕ запускаем здесь — запустим в конце main() в главном потоке

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

    # Трей — в отдельном потоке (может не работать на некоторых системах)
    if config.get("tray_enabled", True):
        try:
            tray = build_tray(jarvis)
            threading.Thread(target=tray.run, daemon=True, name="tray").start()
        except Exception:
            log.exception("Трей не завёлся — работаю без него")

    # Flet — в ГЛАВНОМ потоке (блокирует до закрытия окна)
    if gui is not None:
        log.info("Запускаю Flet в главном потоке")
        gui.run_main()
    else:
        log.info("GUI выключен — жду завершения")
        jarvis.stop_event.wait()

    jarvis.shutdown()
    log.info("Завершение работы")


if __name__ == "__main__":
    main()