"""Windows SAPI: all pyttsx3/COM calls belong to one dedicated thread."""
import logging
import queue
import re
import sys
import threading
import time

log = logging.getLogger("jarvis.tts")
_SENTENCE_END = re.compile(r"[.!?…]+\s+")


class SAPIEngine:
    name = "sapi"
    voices = {"auto": "Авто (системный SAPI)", "Pavel": "Павел", "Irina": "Ирина"}
    default_quality = "medium"
    default_rate = 1.15

    def __init__(self, voice="auto", quality="medium", rate=1.15):
        self.voice = voice if voice in self.voices else "auto"
        self.quality, self.rate = quality, float(rate)
        self._requests = queue.Queue()
        self._ready = threading.Event()
        self._cancel_lock = threading.Lock()
        self._cancel = threading.Event()
        self._error = None
        self._engine = None
        self._thread = threading.Thread(target=self._owner, daemon=True, name="sapi-owner")
        self._thread.start()
        if not self._ready.wait(10):
            raise RuntimeError("SAPI: инициализация не завершилась за 10 секунд")
        if self._error is not None:
            raise RuntimeError("SAPI: не удалось создать системный голос") from self._error

    def _owner(self):
        com = None
        try:
            if sys.platform == "win32":
                import comtypes
                com = comtypes
                com.CoInitialize()
            import pyttsx3
            self._engine = pyttsx3.Engine()  # never share pyttsx3.init()'s global cache
            self._pick_voice(self.voice)
            self._ready.set()
            while True:
                request = self._requests.get()
                if request is None:
                    return
                text, voice, rate, token, cancelled, done, errors = request
                try:
                    if token.is_set() or cancelled.is_set():
                        continue
                    self._pick_voice(voice)
                    wpm = int(round(200 * max(0.3, min(3.0, float(rate)))))
                    self._engine.setProperty("rate", wpm)
                    self._engine.say(text)
                    loop_started = False
                    try:
                        self._engine.startLoop(False)
                        loop_started = True
                        deadline = time.monotonic() + 120.0
                        while True:
                            if token.is_set() or cancelled.is_set():
                                self._engine.stop()
                                break
                            self._engine.iterate()  # pumps SAPI events on its COM owner
                            if not self._engine.isBusy():
                                break
                            if time.monotonic() >= deadline:
                                self._engine.stop()
                                raise TimeoutError("SAPI: превышено время одной фразы")
                            time.sleep(.01)
                    finally:
                        if loop_started:
                            self._engine.endLoop()
                except Exception as exc:
                    errors.append(exc)
                    try:
                        self._engine.stop()
                    except Exception:
                        pass
                    log.exception("SAPI: ошибка озвучки")
                finally:
                    done.set()
        except Exception as exc:
            self._error = exc
            self._ready.set()
            log.exception("SAPI: ошибка потока-владельца")
        finally:
            if self._engine is not None:
                try:
                    self._engine.stop()
                except Exception:
                    pass
            if com is not None:
                com.CoUninitialize()

    def _pick_voice(self, voice):
        """Called only from sapi-owner, never from GUI or the speaking caller."""
        available = self._engine.getProperty("voices")
        hint = voice.lower() if voice != "auto" else "ru"
        preferred = [v for v in available if hint in f"{v.id} {v.name}".lower()]
        fallback = [v for v in available if any(
            part in f"{v.id} {v.name}".lower() for part in ("ru", "irina"))]
        for v in (preferred or fallback)[:1]:
            self._engine.setProperty("voice", v.id)
            log.info("SAPI: голос %s", v.name)

    def is_available(self):
        return self._ready.is_set() and self._error is None and self._thread.is_alive()

    def set_voice(self, voice):
        if voice in self.voices:
            self.voice = voice

    def set_rate(self, rate):
        self.rate = float(rate)

    def synthesize(self, text, voice=None, rate=None):
        raise NotImplementedError("SAPI не поддерживает synthesize()")

    def speak_stream(self, text_iter, voice, rate, token):
        buffer, full_parts = "", []
        def flush(force=False):
            nonlocal buffer
            while True:
                match = _SENTENCE_END.search(buffer)
                if not match:
                    break
                sentence = buffer[:match.end()].strip()
                buffer = buffer[match.end():]
                if sentence and not token.is_set():
                    self._say(sentence, rate, token, voice)
            if force and buffer.strip() and not token.is_set():
                self._say(buffer.strip(), rate, token, voice)
                buffer = ""
        for chunk in text_iter:
            if token.is_set():
                break
            if chunk:
                full_parts.append(chunk)
                buffer += chunk
            flush()
        if not token.is_set():
            flush(True)
        return "".join(full_parts).strip()

    def _say(self, sentence, rate, token=None, voice=None):
        from jarvis.text_utils import prepare_text
        text = prepare_text(sentence)
        if not text.strip().strip("\u200b\u200c\u200d\ufeff\u00ad"):
            return
        token = token if token is not None else threading.Event()
        done, cancelled, errors = threading.Event(), threading.Event(), []
        with self._cancel_lock:
            self._cancel = cancelled
            if token.is_set():
                return
            self._requests.put((text, voice or self.voice, rate, token, cancelled, done, errors))
        # Do not report completion while the COM owner still has active audio.
        deadline = time.monotonic() + 125.0
        while not done.wait(.05):
            if self._error is not None or not self._thread.is_alive():
                raise RuntimeError("SAPI: поток-владелец завершился")
            if time.monotonic() >= deadline:
                cancelled.set()
                token.set()
                # Cancellation is not proof that native audio has ended. Keep
                # this worker alive until owner acknowledgement, so Speaker will
                # reject overlapping playback/replacement rather than fake success.
                log.error("SAPI: нет подтверждения остановки; новая озвучка заблокирована")
                deadline = float("inf")
        if errors:
            raise RuntimeError("SAPI: системная озвучка завершилась с ошибкой") from errors[0]

    def stop(self):
        # No cross-thread COM/pyttsx3 calls and no joins on the GUI thread.
        with self._cancel_lock:
            self._cancel.set()
