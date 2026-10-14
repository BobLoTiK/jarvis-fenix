"""SAPI TTS — старый Windows-синтез через pyttsx3.

Fallback, если WinRT не завёлся. Качество ниже, но работает всегда.
"""

import logging
import re

log = logging.getLogger("jarvis.tts")

_SENTENCE_END = re.compile(r"[.!?…]+\s+")


class SAPIEngine:
    name = "sapi"

    voices = {
        "auto":   "Авто (системный SAPI)",
        "Pavel":  "Павел",
        "Irina":  "Ирина",
    }

    default_quality = "medium"
    default_rate = 1.15

    def __init__(self, voice: str = "auto", quality: str = "medium",
                 rate: float = 1.15):
        import pyttsx3
        self._engine = pyttsx3.init()
        self.voice = voice if voice in self.voices else "auto"
        self.quality = quality
        self.rate = float(rate)
        self._pick_voice()

    def _pick_voice(self):
        try:
            for v in self._engine.getProperty("voices"):
                ident = f"{v.id} {v.name}".lower()
                hint = self.voice.lower() if self.voice != "auto" else "ru"
                if hint in ident or "ru" in ident or "irina" in ident:
                    self._engine.setProperty("voice", v.id)
                    log.info("SAPI: голос %s", v.name)
                    break
        except Exception:
            log.exception("SAPI: не удалось выбрать голос")

    def is_available(self) -> bool:
        return self._engine is not None

    def set_voice(self, voice: str):
        if voice in self.voices:
            self.voice = voice
            self._pick_voice()

    def set_rate(self, rate: float):
        self.rate = float(rate)

    def synthesize(self, text: str, voice: str | None = None,
                   rate: float | None = None) -> bytes:
        """SAPI играет напрямую — байты не возвращаем."""
        raise NotImplementedError("SAPI не поддерживает synthesize()")

    def speak_stream(self, text_iter, voice: str, rate: float,
                     token) -> str:
        """SAPI воспроизводит напрямую, без WAV-обёртки."""
        from jarvis.text_utils import prepare_text

        buffer = ""
        full_parts = []

        def _flush(force: bool = False):
            nonlocal buffer
            while True:
                m = _SENTENCE_END.search(buffer)
                if not m:
                    break
                sent = buffer[:m.end()].strip()
                buffer = buffer[m.end():]
                if sent and not token.is_set():
                    self._say(sent, rate)
            if force and buffer.strip() and not token.is_set():
                self._say(buffer.strip(), rate)
                buffer = ""

        for chunk in text_iter:
            if chunk:
                full_parts.append(chunk)
                buffer += chunk
            if token.is_set():
                break
            _flush()
        if not token.is_set():
            _flush(force=True)
        return "".join(full_parts).strip()

    def _say(self, sentence: str, rate: float):
        from jarvis.text_utils import prepare_text

        text = prepare_text(sentence)
        if not text.strip().strip("\u200b\u200c\u200d\ufeff\u00ad"):
            return
        try:
            # pyttsx3/SAPI5 ждёт «слов в минуту» (база 200), а speaker
            # передаёт множитель 0.5–2.0. Прежняя формула int((rate-1)*100)
            # при rate≈1 давала 0 → math domain error внутри драйвера →
            # каждое предложение пропускалось молча.
            wpm = int(round(200 * max(0.3, min(3.0, float(rate)))))
            self._engine.setProperty("rate", wpm)
            self._engine.say(text)
            self._engine.runAndWait()
        except Exception:
            log.exception("SAPI: ошибка озвучки")

    def stop(self):
        try:
            self._engine.stop()
        except Exception:
            pass