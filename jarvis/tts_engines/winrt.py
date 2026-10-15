"""WinRT TTS — системный синтез Windows, без внешних моделей.

Голос — системный (Pavel, Irina и т.д.). Качество зависит от установленных
пакетов русского языка в Windows.
"""

import asyncio
import logging

from jarvis.tts_engines.base import BaseEngine
import re

log = logging.getLogger("jarvis.tts")

_SENTENCE_END = re.compile(r"[.!?…]+\s+")


class WinRTEngine(BaseEngine):
    name = "winrt"

    voices = {
        "Pavel":  "Павел — мужской (системный)",
        "Irina":  "Ирина — женский (системный)",
        "auto":   "Авто (системный по языку)",
    }

    default_quality = "medium"
    default_rate = 1.15

    def __init__(self, voice: str = "Pavel", quality: str = "medium",
                 rate: float = 1.15):
        from winrt.windows.media.speechsynthesis import SpeechSynthesizer  # noqa

        if voice not in self.voices:
            voice = "auto"

        self.voice = voice
        self.quality = quality
        self.rate = float(rate)

    def is_available(self) -> bool:
        try:
            from winrt.windows.media.speechsynthesis import SpeechSynthesizer
            return bool(SpeechSynthesizer.all_voices)
        except Exception:
            return False

    def set_voice(self, voice: str):
        if voice in self.voices:
            self.voice = voice

    def set_rate(self, rate: float):
        self.rate = float(rate)

    async def _synthesize_async(self, text: str) -> bytes:
        from winrt.windows.media.speechsynthesis import SpeechSynthesizer
        from winrt.windows.storage.streams import DataReader

        synth = SpeechSynthesizer()
        voices = list(SpeechSynthesizer.all_voices)

        if self.voice != "auto":
            hint = self.voice.lower()
            voice = next(
                (v for v in voices if hint in v.display_name.lower()),
                None,
            )
        else:
            voice = next(
                (v for v in voices if v.language.lower().startswith("ru")),
                None,
            )

        if voice is not None:
            synth.voice = voice
        try:
            synth.options.speaking_rate = self.rate
        except Exception:
            pass

        stream = await synth.synthesize_text_to_stream_async(text)
        reader = DataReader(stream.get_input_stream_at(0))
        await reader.load_async(stream.size)
        return bytes(reader.read_buffer(stream.size))

    def synthesize(self, text: str, voice: str | None = None,
                   rate: float | None = None) -> bytes:
        if not text.strip():
            return b""
        if voice:
            self.set_voice(voice)
        if rate is not None:
            self.set_rate(rate)
        return asyncio.run(self._synthesize_async(text))

    def speak_stream(self, text_iter, voice: str, rate: float,
                     token) -> str:
        """WinRT стриминг (наивный — по предложениям)."""

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
                    self._play(sent, voice, rate, token)
            if force and buffer.strip() and not token.is_set():
                self._play(buffer.strip(), voice, rate, token)
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

    def _play(self, sentence: str, voice: str, rate: float, token):
        from jarvis.text_utils import prepare_text

        text = prepare_text(sentence)
        if not text.strip().strip("\u200b\u200c\u200d\ufeff\u00ad"):
            return
        wav = self.synthesize(text, voice, rate)
        if not wav or token.is_set():
            return
        self._output_wav(wav, token)
