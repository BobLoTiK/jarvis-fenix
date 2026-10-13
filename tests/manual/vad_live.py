"""Живой тест VAD: пишет 5 сек с микрофона, показывает prob.

Ручной прогон (нужен микрофон): python tests/manual/vad_live.py
"""

import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

# Корень проекта: tests/manual/../.. — иначе `import jarvis` не найдётся.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from jarvis.vad import VAD  # noqa: E402

SR = 16000
BLOCK = 8000

vad = VAD(sample_rate=SR, threshold=0.5)
print("VAD available:", vad.is_available())

print("\nГовори ГРОМКО 5 секунд: 'Привет, раз, два, три'")
print(f"{'t':>5}  {'rms':>6}  {'prob':>5}  {'речь?':>5}")
print("-" * 35)

def callback(indata, frames, time_info, status):
    raw = bytes(indata)
    arr = np.frombuffer(raw, dtype=np.int16)
    rms = int(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
    prob = vad.speech_probability(raw)
    is_sp = vad.is_speech(raw)
    print(f"{time.time() % 100:>5.1f}  {rms:>6}  {prob:>5.2f}  "
          f"{'ДА' if is_sp else 'нет':>5}")

with sd.RawInputStream(samplerate=SR, blocksize=BLOCK, dtype='int16',
                       channels=1, callback=callback):
    time.sleep(5)

print("\nГотово.")