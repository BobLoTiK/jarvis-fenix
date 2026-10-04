"""Точка входа: связывает распознавание, интенты, синтез речи и трей.

Barge-in: во время речи Феникса микрофон НЕ глушится, а следит за громкостью.
Если юзер заговорил — TTS прерывается через speaker.stop().
После barge-in окно диалога открывается заново — можно продолжать без wake-слова.
"""

import logging
import logging.handlers
import threading
import time
from pathlib import Path

from jarvis.matching import wake_score

from jarvis import APP_NAME, __version__
from jarvis.apps import build_apps
from jarvis.config import load_config
from jarvis.intents import IntentHandler, normalize
from jarvis.model import ensure_model
from jarvis.stt import Listener
from jarvis.tray import build_tray
from jarvis import timers
from jarvis.tts import Speaker

log = logging.getLogger("jarvis")

BASE_DIR = Path(__file__).resolve().parent.parent
_REJECT = object()


class Jarvis:
    def __init__(self, config: dict, listener: Listener, speaker: Speaker,
                 handler: IntentHandler, base_dir: Path, whisper=None):
        self.config = config
        self.listener = listener
        self.speaker = speaker
        self.handler = handler
        self.base_dir = base_dir
        self.whisper = whisper
        self.listening_enabled = True
        self.stop_event = threading.Event()
        self._awaiting_until = 0.0
        self._wake_words = [normalize(w) for w in config["wake_words"]]
        # barge-in — из конфига
        self.barge_enabled = bool(config.get("barge_enabled", True))
        if self.listener is not None:
            self.listener.barge_enabled = self.barge_enabled
        # флаг: был ли barge-in в последнем say()
        self._barge_just_happened = False

    # --- barge-in-совместимый say() --------------------------------------

    def say(self, text) -> bool:
        """Озвучивает строку или генератор. Возвращает True, если был barge-in."""
        if not text:
            return False

        is_stream = hasattr(text, "__iter__") and not isinstance(text, str)

        if self.barge_enabled and self.listener is not None:
            self.listener.barge_start()
        else:
            self.listener.muted = True

        barge_happened = False
        try:
            if is_stream:
                self._say_stream(text)
            else:
                self._say_text(text)
            # проверяем флаг после завершения речи
            barge_happened = self.barge_enabled and self.listener.barge_flag
        finally:
            if self.barge_enabled and self.listener is not None:
                self.listener.barge_end()
            # при barge-in НЕ flush'им буфер — там может быть фраза юзера
            # (но в простой версии она всё равно потеряется — это ок)
            self.listener.flush()
            self.listener.muted = False
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
        result = {"text": ""}

        def _run():
            try:
                result["text"] = self.speaker.speak_stream(gen)
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

        if result["text"] and hasattr(self.handler, "finalize_stream"):
            self.handler.finalize_stream("", result["text"])

    # --- служебное -------------------------------------------------------

    def shutdown(self) -> None:
        self.stop_event.set()

    def mic_watchdog(self) -> None:
        delay = float(self.config.get("mic_check_sec", 20))
        if self.stop_event.wait(delay):
            return
        if self.listener.utterances == 0 and self.listener.peak < 200:
            log.warning("Микрофон молчит (пик %d за %.0f с): %s — проверьте устройство",
                        self.listener.peak, delay, self.listener.device_name)
            self.say("Я не слышу микрофон. Проверьте, включён ли он, "
                     "или укажите нужный в настройках.")

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
            self.say("Проблема с микрофоном. Проверьте журнал.")

    def _process(self, phrase: str, audio: bytes) -> None:
        awaiting = time.time() < self._awaiting_until
        cmd = self._extract_command(normalize(phrase))
        if cmd is None:
            return
        if cmd == "":
            self.say("Слушаю.")
            self._awaiting_until = time.time() + self.config["command_window_sec"]
            return
        if self.whisper is not None and audio:
            refined = self._refine(audio, awaiting)
            if refined is _REJECT:
                log.info("Whisper не подтвердил wake-слово — игнорирую (ложное срабатывание)")
                return
            if refined:
                cmd = refined
        reply = self.handler.handle(cmd)
        barge_happened = self.say(reply)

        # сброс «стой»
        if getattr(self.handler, "_reset_requested", False):
            self._awaiting_until = 0.0
            self.handler._reset_requested = False
            log.info("Сброс: жду wake-слово")
            return

        # после ЛЮБОГО ответа — окно на продолжение диалога без wake-слова.
        # После barge-in — тоже (и особенно полезно).
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
    # Заглушаем болтливые библиотеки
    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    """Настраивает логирование: общий лог, лог действий, лог ошибок."""
    LOGS_DIR = BASE_DIR / "logs"
    LOGS_DIR.mkdir(exist_ok=True)

    fmt = "%(asctime)s %(name)s %(levelname)s %(message)s"
    formatter = logging.Formatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)

    # 1) Консоль
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(logging.INFO)
    root.addHandler(console)

    # 2) Общий лог jarvis.log
    jarvis_handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / "jarvis.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    jarvis_handler.setFormatter(formatter)
    jarvis_handler.setLevel(logging.INFO)
    root.addHandler(jarvis_handler)

    # 3) Лог ошибок errors.log
    errors_handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / "errors.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    errors_handler.setFormatter(formatter)
    errors_handler.setLevel(logging.WARNING)
    root.addHandler(errors_handler)

    # 4) Лог действий actions.log
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

    config = load_config(BASE_DIR)
    model_dir = ensure_model(BASE_DIR / "models")

    whisper = None
    if config.get("use_whisper", True):
        try:
            from jarvis.stt import WhisperTranscriber

            whisper = WhisperTranscriber(
                config.get("whisper_model", "auto"), config.get("whisper_device", "auto")
            )
        except Exception:
            log.exception("Whisper не завёлся, работаю только на Vosk")

    brain = None
    if config.get("use_llm", True):
        from jarvis.brain import Brain

        brain = Brain(config.get("llm_model", "qwen2.5:1.5b-instruct"),
                      config.get("ollama_url", "http://127.0.0.1:11434"))
        if not brain.available:
            brain = None

    speaker = Speaker(config)
    listener = Listener(model_dir, config["sample_rate"], config.get("input_device"))
    handler = IntentHandler(config, build_apps(config), brain)
    jarvis = Jarvis(config, listener, speaker, handler, BASE_DIR, whisper)
    
    # таймеры: callback + восстановление сохранённых
    def _on_timer_fire(timer: dict):
        text = timer.get("text") or "время вышло"
        msg = f"Напоминание: {text}."
        log.info("Таймер сработал: %s", msg)
        jarvis.say(msg)

    timers.set_on_fire(_on_timer_fire)
    restored = timers.restore_all()
    if restored:
        log.info("Восстановлено напоминаний: %d", restored)

    worker = threading.Thread(target=jarvis.run_loop, daemon=True, name="jarvis-listener")
    worker.start()
    jarvis.say(f"{APP_NAME} запущен и готов к работе.")
    threading.Thread(target=jarvis.mic_watchdog, daemon=True, name="mic-watchdog").start()

    tray = build_tray(jarvis)
    tray.run()
    jarvis.shutdown()
    log.info("Завершение работы")


if __name__ == "__main__":
    main()