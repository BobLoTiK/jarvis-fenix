"""Самопроверка без микрофона: TTS -> Vosk -> разбор команды.

Запуск: python scripts/selftest.py
"""

import asyncio
import io
import json
import sys
import wave
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from vosk import KaldiRecognizer, Model, SetLogLevel  # noqa: E402

from jarvis.apps import build_apps, find_app  # noqa: E402
from jarvis.installed import find_installed, scan_start_menu  # noqa: E402
from jarvis.intents import IntentHandler, normalize  # noqa: E402
from jarvis.matching import match_score, wake_score  # noqa: E402
from jarvis.actions import find_process, spoken_domain, guess_site  # noqa: E402
from jarvis.tts import Speaker  # noqa: E402

PHRASES = [
    "феникс открой стим",
    "феникс закрой дискорд",
    "феникс сколько времени",
    "феникс открой ютуб",
]


def recognize(model: Model, wav_bytes: bytes) -> str:
    wf = wave.open(io.BytesIO(wav_bytes))
    rec = KaldiRecognizer(model, wf.getframerate())
    while True:
        chunk = wf.readframes(4000)
        if not chunk:
            break
        rec.AcceptWaveform(chunk)
    return json.loads(rec.FinalResult()).get("text", "")


def main() -> None:
    SetLogLevel(-1)
    # Whisper — строго до первого использования WinRT (иначе access violation)
    from jarvis.stt import WhisperTranscriber
    whisper = WhisperTranscriber("auto", "auto")
    # для прогона TTS->STT нужен WinRT-бэкенд