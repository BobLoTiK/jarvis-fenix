"""Синтез речи.

Бэкенды: xtts / piper / winrt / sapi.
Смена голоса на лету: через Config.subscribe — main.py вызывает speaker.set_voice().
Streaming: speak_stream(iterator) — озвучивает по предложениям.
Barge-in: play_async() + stop() — играет в потоке, можно прервать.
Предобработка текста: _prepare_text() — CJK, единицы, числа.
"""

import asyncio
import io
import logging
import os
import re
import threading
import time
import wave
import winsound
from pathlib import Path

log = logging.getLogger("jarvis.tts")

PIPER_REPO = "rhasspy/piper-voices"
BASE_DIR = Path(__file__).resolve().parent.parent

_SENTENCE_END = re.compile(r"[.!?…]+\s+")


# ---------------------------------------------------------------
# Предобработка текста
# ---------------------------------------------------------------

_REPLACEMENTS = [
    # единицы измерения
    (r"\bм/с\b", " метров в секунду"),
    (r"\bкм/ч\b", " километров в час"),
    (r"\bкм/с\b", " километров в секунду"),
    (r"\bм/c\b", " метров в секунду"),
    (r"\bкм/ч\.", " километров в час"),
    # температура
    (r"([+-]?\d+)\s*°\s*[CFЦ]?\b", r"\1 градусов"),
    (r"°\s*[CFЦ]?\b", " градусов"),
    # проценты
    (r"(\d+)\s*%", r"\1 процентов"),
    # сокращения
    (r"\bт\.\s*д\.", " так далее"),
    (r"\bт\.\s*е\.", " то есть"),
    (r"\bт\.\s*к\.", " так как"),
    (r"\bт\.\s*п\.", " тому подобное"),
    (r"\bдр\.", " другие"),
    (r"\bг\.", " год"),
    (r"\bгг\.", " годы"),
    (r"\bруб\.", " рублей"),
    (r"\bкоп\.", " копеек"),
    (r"\bтыс\.", " тысяч"),
    (r"\bмлн\.", " миллионов"),
    (r"\bмлрд\.", " миллиардов"),
    # единицы после цифры
    (r"\b(\d+)\s*см\b", r"\1 сантиметров"),
    (r"\b(\d+)\s*мм\b", r"\1 миллиметров"),
    (r"\b(\d+)\s*км\b", r"\1 километров"),
    (r"\b(\d+)\s*кг\b", r"\1 килограммов"),
    (r"\b(\d+)\s*мг\b", r"\1 миллиграммов"),
    (r"\b(\d+)\s*МБ\b", r"\1 мегабайт"),
    (r"\b(\d+)\s*ГБ\b", r"\1 гигабайт"),
    (r"\b(\d+)\s*КБ\b", r"\1 килобайт"),
    (r"\b(\d+)\s*м\b", r"\1 метров"),
    (r"\b(\d+)\s*г\b", r"\1 граммов"),
    # символы
    (r"→", " стремится к "),
    (r"←", " из "),
    (r"≈", " примерно "),
    (r"≥", " больше или равно "),
    (r"≤", " меньше или равно "),
    (r"≠", " не равно "),
    (r"&", " и "),
    (r"\+", " плюс "),
    (r"(?<!\w)-(?!\w)", " минус "),
    # markdown-мусор
    (r"\*+", ""),
    (r"_+", ""),
    (r"#+\s*", ""),
    (r"`+", ""),
    (r"^\s*[-•]\s+", ""),
]

_RE_COMPILED = [(re.compile(pat), repl) for pat, repl in _REPLACEMENTS]

_CJK_RE = re.compile(
    r"[\u4e00-\u9fff"
    r"\u3040-\u309f"
    r"\u30a0-\u30ff"
    r"\uac00-\ud7af"
    r"\u3000-\u303f"
    r"\uff00-\uffef]+"
)


def _prepare_text(text: str) -> str:
    """Чистит текст: CJK, сокращения, markdown."""
    if not text:
        return text
    text = _CJK_RE.sub(" ", text)
    for pattern, repl in _RE_COMPILED:
        text = pattern.sub(repl, text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    return text


class Speaker:
    def __init__(self, config):
        # config — объект Config или dict. Работает и так, и так.
        cfg = config if hasattr(config, "get") else {}
        self.rate = float(cfg.get("voice_rate", 1.15))
        self.voice = cfg.get("tts_voice", "ruslan")
        self._voice_hint = cfg.get("voice", "Pavel")
        self._mode = None
        self._engine = None
        self._piper = None
        self._piper_cfg = None

        self._play_thread = None
        self._stop_flag = threading.Event()
        self._playing = False
        self._play_lock = threading.Lock()

        backend = cfg.get("tts_backend", "auto")
        ref = BASE_DIR / cfg.get("xtts_ref", "voices/jarvis.wav")
        if backend in ("auto", "xtts"):
            if ref.exists():
                try:
                    self._init_xtts(ref)
                except Exception:
                    log.exception("XTTS не завёлся, переключаюсь на piper")
            elif backend == "xtts":
                log.warning("Референс голоса не найден: %s", ref)
        if self._mode is None and backend in ("auto", "xtts", "piper"):
            try:
                self._init_piper(self.voice)
            except Exception:
                log.exception("Piper не завёлся, переключаюсь на WinRT")
        if self._mode is None:
            try:
                from winrt.windows.media.speechsynthesis import SpeechSynthesizer  # noqa: F401
                self._mode = "winrt"
                log.info("TTS: WinRT, голос %r, скорость %.2f", self._voice_hint, self.rate)
            except Exception:
                log.exception("WinRT недоступен, переключаюсь на SAPI")
                self._init_sapi()

    # --- сеттеры для Config.subscribe ------------------------------------

    def set_voice(self, voice: str) -> None:
        if voice == self.voice:
            return
        log.info("Голос изменился: %s → %s", self.voice, voice)
        self.voice = voice
        if self._mode == "piper":
            try:
                self._init_piper(voice)
            except Exception:
                log.exception("Не удалось переключить Piper на %s", voice)

    def set_rate(self, rate: float) -> None:
        self.rate = float(rate)
        if self._piper_cfg is not None:
            try:
                from piper import SynthesisConfig
                self._piper_cfg = SynthesisConfig(length_scale=round(1.0 / self.rate, 2))
            except Exception:
                pass

    # --- xtts / piper / sapi / winrt --------------------------------------

    def _init_xtts(self, ref: Path) -> None:
        os.environ.setdefault("COQUI_TOS_AGREED", "1")
        import torch
        from TTS.api import TTS as CoquiTTS

        device = "cuda" if torch.cuda.is_available() else "cpu"
        log.info("Загрузка XTTS-v2 на %s...", device)
        self._xtts = CoquiTTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
        self._xtts_ref = str(ref)
        self._mode = "xtts"
        log.info("TTS: XTTS-v2, клон голоса из %s", ref.name)

    def _speak_xtts(self, text: str) -> None:
        import numpy as np
        samples = self._xtts.tts(text=text, speaker_wav=self._xtts_ref,
                                 language="ru", speed=self.rate)
        pcm = (np.clip(np.asarray(samples), -1, 1) * 32767).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(pcm.tobytes())
        winsound.PlaySound(buf.getvalue(), winsound.SND_MEMORY)

    def _init_piper(self, voice: str) -> None:
        from huggingface_hub import hf_hub_download
        from piper import PiperVoice, SynthesisConfig

        rel = f"ru/ru_RU/{voice}/medium/ru_RU-{voice}-medium.onnx"
        onnx = hf_hub_download(PIPER_REPO, rel)
        hf_hub_download(PIPER_REPO, rel + ".json")
        self._piper = PiperVoice.load(onnx)
        self._piper_cfg = SynthesisConfig(length_scale=round(1.0 / self.rate, 2))
        self._mode = "piper"
        log.info("TTS: piper, голос %s, скорость %.2f", voice, self.rate)

    def _speak_piper(self, text: str) -> None:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            self._piper.synthesize_wav(text, wf, self._piper_cfg)
        winsound.PlaySound(buf.getvalue(), winsound.SND_MEMORY)

    def _init_sapi(self) -> None:
        import pyttsx3
        self._engine = pyttsx3.init()
        for v in self._engine.getProperty("voices"):
            ident = f"{v.id} {v.name}".lower()
            if self._voice_hint.lower() in ident or "ru" in ident or "irina" in ident:
                self._engine.setProperty("voice", v.id)
                log.info("TTS: SAPI, голос %s", v.name)
                break
        self._mode = "sapi"

    async def _synthesize(self, text: str) -> bytes:
        from winrt.windows.media.speechsynthesis import SpeechSynthesizer
        from winrt.windows.storage.streams import DataReader

        synth = SpeechSynthesizer()
        voices = list(SpeechSynthesizer.all_voices)
        voice = next(
            (v for v in voices if self._voice_hint.lower() in v.display_name.lower()),
            None,
        ) or next((v for v in voices if v.language.lower().startswith("ru")), None)
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

    def _speak_one(self, text: str) -> None:
        text = _prepare_text(text)
        if not text or self._stop_flag.is_set():
            return
        log.info("Говорю: %s", text)
        try:
            if self._mode == "xtts":
                self._speak_xtts(text)
            elif self._mode == "piper":
                self._speak_piper(text)
            elif self._mode == "winrt":
                wav = asyncio.run(self._synthesize(text))
                if not self._stop_flag.is_set():
                    winsound.PlaySound(wav, winsound.SND_MEMORY)
            else:
                self._engine.say(text)
                self._engine.runAndWait()
        except Exception:
            log.exception("Ошибка синтеза речи")

    def speak(self, text: str) -> None:
        if not text:
            return
        self._speak_one(text)

    def play_async(self, text: str) -> None:
        self._stop_flag.clear()
        self._playing = True

        def _run():
            try:
                self._speak_one(text)
            finally:
                with self._play_lock:
                    self._playing = False

        self._play_thread = threading.Thread(target=_run, daemon=True, name="tts-play")
        self._play_thread.start()

    def stop(self) -> None:
        log.info("TTS: прерывание (barge-in)")
        self._stop_flag.set()
        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass

    def is_playing(self) -> bool:
        return self._playing and self._play_thread is not None and self._play_thread.is_alive()

    def wait_end(self, timeout: float = 30.0) -> None:
        if self._play_thread is not None:
            self._play_thread.join(timeout=timeout)
        self._playing = False

    def speak_stream(self, text_iter, timeout: float = 30.0) -> str:
        self._stop_flag.clear()
        self._playing = True

        buffer = ""
        full_text_parts = []
        pending = []

        def _flush_sentences(force: bool = False):
            nonlocal buffer
            while True:
                m = _SENTENCE_END.search(buffer)
                if not m:
                    break
                sentence = buffer[:m.end()].strip()
                buffer = buffer[m.end():]
                if sentence:
                    pending.append(sentence)
            if force and buffer.strip():
                pending.append(buffer.strip())
                buffer = ""

        try:
            for chunk in text_iter:
                if self._stop_flag.is_set():
                    log.info("TTS: стриминг прерван")
                    break
                buffer += chunk
                full_text_parts.append(chunk)
                _flush_sentences()
                while pending and not self._stop_flag.is_set():
                    sentence = pending.pop(0)
                    self._speak_one(sentence)
            if not self._stop_flag.is_set():
                _flush_sentences(force=True)
                while pending and not self._stop_flag.is_set():
                    sentence = pending.pop(0)
                    self._speak_one(sentence)
        except Exception:
            log.exception("Ошибка в speak_stream")
        finally:
            self._playing = False

        return "".join(full_text_parts).strip()