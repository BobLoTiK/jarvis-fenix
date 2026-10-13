"""Отладка Silero VAD — прогон на синтетике.

Ручной прогон (нужна модель в C:\\ProgramData\\Phoenix\\vad):
    python tests/manual/vad_debug.py
"""

import numpy as np
import onnxruntime as ort

MODEL = r"C:\ProgramData\Phoenix\vad\silero_vad.onnx"
SR = 16000
CHUNK = 512

sess = ort.InferenceSession(MODEL)

# --- Синусоида 150 Гц (похоже на голос) ---
print("Прогон синусоиды 150 Гц:")
state = np.zeros((2, 1, 128), dtype=np.float32)
sr = np.array(SR, dtype=np.int64)

t = np.arange(SR * 2) / SR
sig = (0.5 * np.sin(2 * np.pi * 150 * t)).astype(np.float32)

probs = []
for i in range(0, len(sig) - CHUNK + 1, CHUNK):
    chunk = sig[i:i + CHUNK].reshape(1, -1)
    out = sess.run(None, {"input": chunk, "state": state, "sr": sr})
    state = out[1]
    probs.append(float(out[0][0][0]))

print("  первые 10 prob:", [f"{p:.3f}" for p in probs[:10]])
print("  макс prob:", max(probs))

# --- Тишина ---
print("\nПрогон тишины:")
state = np.zeros((2, 1, 128), dtype=np.float32)
silence = np.zeros(CHUNK, dtype=np.float32)
probs_silence = []
for i in range(10):
    chunk = silence.reshape(1, -1)
    out = sess.run(None, {"input": chunk, "state": state, "sr": sr})
    state = out[1]
    probs_silence.append(float(out[0][0][0]))

print("  первые 10 prob:", [f"{p:.3f}" for p in probs_silence[:10]])
print("  макс prob:", max(probs_silence))

# --- Белый шум ---
print("\nПрогон белого шума (громкий):")
state = np.zeros((2, 1, 128), dtype=np.float32)
np.random.seed(42)
noise = (np.random.randn(CHUNK) * 0.3).astype(np.float32)
probs_noise = []
for i in range(10):
    chunk = noise.reshape(1, -1)
    out = sess.run(None, {"input": chunk, "state": state, "sr": sr})
    state = out[1]
    probs_noise.append(float(out[0][0][0]))

print("  первые 10 prob:", [f"{p:.3f}" for p in probs_noise[:10]])
print("  макс prob:", max(probs_noise))