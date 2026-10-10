"""Тесты jarvis.prosody — эмоции из голоса (эвристика)."""

import math
import numpy as np
import pytest

from jarvis import prosody


def _make_sine(freq: float, rms_target: float, duration: float = 0.5,
               sr: int = 16000) -> bytes:
    """Генерирует синусоиду заданной частоты и громкости (RMS)."""
    n = int(sr * duration)
    t = np.arange(n) / sr
    sig = np.sin(2 * np.pi * freq * t)
    # Нормируем под нужный RMS
    sig = sig / np.sqrt(np.mean(sig ** 2)) * rms_target
    sig = np.clip(sig, -32768, 32767).astype(np.int16)
    return sig.tobytes()


def test_prosody_empty():
    """Пустой ввод → None."""
    assert prosody.analyze_prosody(b"") is None


def test_prosody_too_short():
    """Слишком короткий чанк → None."""
    short = np.zeros(100, dtype=np.int16).tobytes()
    assert prosody.analyze_prosody(short) is None


def test_prosody_tired_quiet_low_pitch():
    """Тихо + низкий pitch → tired."""
    # 80 Гц, RMS ~50 (тихо)
    pcm = _make_sine(80, 50)
    result = prosody.analyze_prosody(pcm, 16000)
    assert result is not None
    assert result["emotion"] == "tired"
    assert result["arousal"] < 0.3


def test_prosody_excited_loud():
    """Громко + высокий pitch → excited."""
    # 300 Гц, RMS ~3000
    pcm = _make_sine(300, 3000)
    result = prosody.analyze_prosody(pcm, 16000)
    assert result is not None
    assert result["emotion"] in ("excited", "annoyed")
    assert result["arousal"] > 0.5


def test_prosody_result_keys():
    """Результат содержит все нужные ключи."""
    pcm = _make_sine(200, 1500)
    result = prosody.analyze_prosody(pcm, 16000)
    assert result is not None
    for key in ("emotion", "arousal", "valence", "rms", "pitch", "zcr"):
        assert key in result


def test_prosody_emotion_in_states():
    """Emotion — из набора mood.STATES."""
    from jarvis.mood import STATES
    pcm = _make_sine(200, 1500)
    result = prosody.analyze_prosody(pcm, 16000)
    assert result is not None
    assert result["emotion"] in STATES


def test_prosody_rms_reasonable():
    """RMS на нормальном сигнале > 0."""
    pcm = _make_sine(200, 1500)
    result = prosody.analyze_prosody(pcm, 16000)
    assert result is not None
    assert result["rms"] > 0