"""Тесты jarvis.vad — Silero VAD ONNX.

Реальная модель в CI недоступна (нет onnxruntime).
Все тесты — с моками или проверкой fallback-поведения.
"""

import importlib.util
from unittest.mock import patch, MagicMock

import pytest

# Пропускаем весь модуль, если нет onnxruntime (CI).
if importlib.util.find_spec("onnxruntime") is None:
    pytest.skip("onnxruntime не установлен — VAD-тесты пропущены",
                allow_module_level=True)

from jarvis import vad


def test_vad_unavailable_without_model():
    """Без модели VAD.is_available() == False, is_speech → True (safe)."""
    with patch.object(vad, "_find_model", return_value=None):
        v = vad.VAD()
    assert v.is_available() is False
    # Fallback: без VAD всё считаем речью (старое поведение).
    assert v.is_speech(b"\x00" * 1024) is True


def test_vad_silence_returns_false():
    """Тишина (нули) → не речь."""
    import numpy as np
    v = vad.VAD()
    if not v.is_available():
        pytest.skip("модель VAD недоступна")
    silence = np.zeros(16000, dtype=np.int16).tobytes()
    assert v.is_speech(silence) is False


def test_vad_noise_returns_false():
    """Случайный шум не детектится как речь (обычно)."""
    import numpy as np
    v = vad.VAD()
    if not v.is_available():
        pytest.skip("модель VAD недоступна")
    np.random.seed(42)
    noise = (np.random.randn(16000) * 100).astype(np.int16).tobytes()
    assert v.is_speech(noise) is False


def test_vad_reset_does_not_crash():
    """reset() работает без ошибок, даже если модель есть."""
    v = vad.VAD()
    v.reset()


def test_vad_speech_probability_silence():
    """speech_probability на тишине → низкая."""
    import numpy as np
    v = vad.VAD()
    if not v.is_available():
        pytest.skip("модель VAD недоступна")
    silence = np.zeros(16000, dtype=np.int16).tobytes()
    prob = v.speech_probability(silence)
    assert prob < 0.1, f"prob={prob}"


def test_vad_short_chunk():
    """Чанк короче 512 сэмплов → False, без падения."""
    import numpy as np
    v = vad.VAD()
    short = np.zeros(100, dtype=np.int16).tobytes()
    assert v.is_speech(short) is False

def test_vad_adaptive_default_on():
    """VAD по умолчанию адаптивный."""
    from jarvis.vad import VAD
    v = VAD()
    assert v._adaptive is True


def test_vad_rms_baseline_grows():
    """RMS-база обновляется на тихих чанках."""
    import numpy as np
    from jarvis.vad import VAD
    v = VAD()
    if not v.is_available():
        pytest.skip("модель VAD недоступна")

    for _ in range(5):
        quiet = (np.random.randn(8000) * 100).astype(np.int16).tobytes()
        v.is_speech(quiet)

    assert v.rms_baseline() > 0


def test_vad_reset_keeps_rms_baseline():
    """reset() не сбрасывает RMS-базу."""
    import numpy as np
    from jarvis.vad import VAD
    v = VAD()
    if not v.is_available():
        pytest.skip("модель VAD недоступна")

    for _ in range(5):
        quiet = (np.random.randn(8000) * 100).astype(np.int16).tobytes()
        v.is_speech(quiet)

    before = v.rms_baseline()
    v.reset()
    after = v.rms_baseline()
    assert before == after


def test_vad_baseline_calibration_n():
    """Калибровка — 30 замеров до «заморозки» базы."""
    from jarvis.vad import VAD
    v = VAD()
    assert v._rms_calibration_n == 30