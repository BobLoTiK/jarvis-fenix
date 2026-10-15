"""Piper TTS — быстрый, ~60 МБ, 4 голоса для русского.

Голоса: ruslan, dmitri, irina, denis.
"""

import io
import logging

from jarvis.tts_engines.base import BaseEngine
import re
import wave

log = logging.getLogger("jarvis.tts")

PIPER_REPO = "rhasspy/piper-voices"

_SENTENCE_END = re.compile(r"[.!?…]+\s+")


class PiperEngine(BaseEngine):
    name = "piper"

    voices = {
        "ruslan": "Руслан — мужской, спокойный",
        "dmitri": "Дмитрий — мужской, ниже",
        "irina":  "Ирина — женский",
        "denis":  "Денис — мужской, дикторский",
    }

    default_quality = "medium"
    default_rate = 1.15

    def __init__(self, voice: str = "ruslan", quality: str = "medium",
                 rate: float = 1.15):
        from piper import PiperVoice, SynthesisConfig  # noqa: F401

        if voice not in self.voices:
            if voice:
                log.warning("Piper: голос %r не знаю, беру ruslan", voice)
            voice = "ruslan"

        self.voice = voice
        self.quality = quality if quality in ("medium", "high") else "medium"
        self.rate = float(rate)
        self._piper = None
        self._piper_cfg = None
        self._load_model()

    def _load_model(self):
        from piper import PiperVoice, SynthesisConfig

        rel = (f"ru/ru_RU/{self.voice}/{self.quality}/"
               f"ru_RU-{self.voice}-{self.quality}.onnx")

        onnx = self._resolve_model(rel)
        if onnx is None:
            log.warning("Piper: голос %s/%s не найден, откат на medium",
                        self.voice, self.quality)
            self.quality = "medium"
            rel = f"ru/ru_RU/{self.voice}/medium/ru_RU-{self.voice}-medium.onnx"
            onnx = self._resolve_model(rel)
        if onnx is None:
            raise RuntimeError(f"Piper: модель {rel} недоступна")

        self._piper = PiperVoice.load(onnx)
        self._piper_cfg = SynthesisConfig(
            length_scale=round(1.0 / self.rate, 2)
        )
        log.info("Piper: голос %s/%s, скорость %.2f",
                 self.voice, self.quality, self.rate)

    @staticmethod
    def _resolve_model(rel: str) -> str | None:
        """Путь к модели: сначала локальный кэш, потом сеть.

        Зачем: try_to_load_from_cache отвечает мгновенно и БЕЗ сети
        (0.000 с), а hf_hub_download лезет на HF Hub даже за уже
        скачанным файлом (0.16 с на файл, 0.36 с на отсутствующий).
        Из-за этого каждый запуск Феникса ждал сеть, а
        «ruslan/high» (которого нет) ещё и каждый раз искался заново.

        Возвращает путь к .onnx или None, если модели нет.
        """
        try:
            from huggingface_hub import try_to_load_from_cache

            cached = try_to_load_from_cache(PIPER_REPO, rel)
            if isinstance(cached, str):
                cfg_cached = try_to_load_from_cache(PIPER_REPO, rel + ".json")
                if isinstance(cfg_cached, str):
                    log.info("Piper: модель %s взята из кэша", rel)
                    return cached
            elif cached is not None:
                # HF уже знает, что файла нет (маркер .no_exist) — в сеть
                # не идём, сразу откатываемся на medium.
                log.debug("Piper: %s помечен как отсутствующий в кэше HF", rel)
                return None
        except Exception:
            log.debug("Piper: локальный кэш HF недоступен — пробую сеть")

        try:
            from huggingface_hub import hf_hub_download

            path = hf_hub_download(PIPER_REPO, rel)
            hf_hub_download(PIPER_REPO, rel + ".json")
            return path
        except Exception as e:
            log.debug("Piper: %s не скачался (%s)", rel, e)
            return None

    def is_available(self) -> bool:
        return self._piper is not None

    def set_voice(self, voice: str):
        if voice == self.voice or voice not in self.voices:
            return
        self.voice = voice
        try:
            self._load_model()
        except Exception:
            log.exception("Piper: не удалось переключить голос на %s", voice)

    def set_rate(self, rate: float):
        from piper import SynthesisConfig
        self.rate = float(rate)
        if self._piper_cfg is not None:
            self._piper_cfg = SynthesisConfig(
                length_scale=round(1.0 / self.rate, 2)
            )

    def synthesize(self, text: str, voice: str | None = None,
                   rate: float | None = None) -> bytes:
        """Piper → WAV-байты."""
        if not text.strip():
            return b""

        cfg = self._piper_cfg
        if rate is not None and rate != self.rate:
            try:
                from piper import SynthesisConfig
                cfg = SynthesisConfig(length_scale=round(1.0 / rate, 2))
            except Exception:
                cfg = self._piper_cfg

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            self._piper.synthesize_wav(text, wf, cfg)
        return buf.getvalue()

    def speak_stream(self, text_iter, voice: str, rate: float,
                     token) -> str:
        """Стриминг Piper через sounddevice."""
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
                    self._play(sent, token)
            if force and buffer.strip() and not token.is_set():
                self._play(buffer.strip(), token)
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

    def _play(self, sentence: str, token):
        from jarvis.text_utils import prepare_text

        text = prepare_text(sentence)
        if not text.strip().strip("\u200b\u200c\u200d\ufeff\u00ad"):
            return
        wav = self.synthesize(text)
        if not wav or token.is_set():
            return
        self._output_wav(wav, token)
