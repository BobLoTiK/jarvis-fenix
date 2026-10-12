"""Тесты jarvis.vad — Silero VAD ONNX.

Реальная модель в CI недоступна (нет onnxruntime).
Все тесты — с моками или проверкой fallback-поведения.

Проверяем:
- Fallback без модели (is_speech → True).
- Реальная модель (если есть): тишина/шум → False, голос → True.
- Нормализация: тихий сигнал усиливается.
- Адаптивный порог по SNR (_compute_threshold, без модели).
- Обучение фона: baseline растёт, reset его сохраняет.
- «Мёртвый» микрофон → auto-off + warning.
- Debug: логи пишутся.
"""

import importlib.util
import logging

from unittest.mock import patch

import pytest

# Пропускаем весь модуль, если нет onnxruntime (CI).
if importlib.util.find_spec("onnxruntime") is None:
    pytest.skip("onnxruntime не установлен — VAD-тесты пропущены",
                allow_module_level=True)

from jarvis import vad


@pytest.fixture(autouse=True)
def _no_vad_download(monkeypatch):
    """Запрещаем тестам качать модель Silero.

    VAD() без модели сам уходит качать silero_vad.onnx (2.3 МБ) в фоне.
    В тестах это лишнее: прогон лезет в сеть и пишет в PROGRAM_DIR/vad
    (оставался огрызок .part, который потом подменял рабочую модель).
    Тесты без модели должны пропускаться, а не качать её.
    """
    monkeypatch.setattr(vad, "ensure_model_async", lambda cb=None: None)


def _voiced(amp: int = 3000, n: int = 8000, sr: int = 16000):
    """Синтетический «голос»: гармоники 120/240/360 Гц (Silero видит речь)."""
    import numpy as np
    t = np.arange(n) / sr
    x = amp * (0.6 * np.sin(2 * np.pi * 120 * t)
               + 0.3 * np.sin(2 * np.pi * 240 * t)
               + 0.1 * np.sin(2 * np.pi * 360 * t))
    return x.astype(np.int16)


# =================================================================
# Fallback без модели
# =================================================================

def test_vad_unavailable_without_model():
    """Без модели VAD.is_available() == False, is_speech → True (safe).

    auto_download=False: иначе VAD ушёл бы качать модель в фоне прямо в
    тесте (сеть). Что бывает при авто-скачивании — в test_vad_model.py.
    """
    with patch.object(vad, "_find_model", return_value=None):
        v = vad.VAD(auto_download=False)
    assert v.is_available() is False
    assert v.is_model_pending() is False
    # Fallback: без VAD всё считаем речью (старое поведение).
    assert v.is_speech(b"\x00" * 1024) is True


# =================================================================
# Реальная модель (skip, если недоступна)
# =================================================================

def test_vad_silence_returns_false():
    """Тишина (нули) → не речь."""
    import numpy as np
    v = vad.VAD()
    if not v.is_available():
        pytest.skip("модель VAD недоступна")
    silence = np.zeros(16000, dtype=np.int16).tobytes()
    assert v.is_speech(silence) is False


def test_vad_noise_returns_false():
    """Случайный шум не детектится как речь."""
    import numpy as np
    v = vad.VAD()
    if not v.is_available():
        pytest.skip("модель VAD недоступна")
    np.random.seed(42)
    noise = (np.random.randn(16000) * 100).astype(np.int16).tobytes()
    assert v.is_speech(noise) is False


def test_vad_voiced_signal_is_speech():
    """Синтетический голос → речь (порог 0.3, без адаптива).

    Порог задаём явно: официальная silero_vad.onnx (2.3 МБ — Феникс
    качает её сам) на синтетических гармониках даёт prob ≈ 0.41: это
    заметно выше шума (≈0.02), но ниже дефолтного порога 0.5. Тест
    проверяет конвейер (нормализация → ONNX → порог), а не конкретную
    версию модели.
    """
    v = vad.VAD(threshold=0.3, adaptive=False, auto_download=False)
    if not v.is_available():
        pytest.skip("модель VAD недоступна")
    assert v.is_speech(_voiced(amp=3000).tobytes()) is True


def test_vad_quiet_voiced_signal_is_speech():
    """Нормализация позволяет ловить тихую речь (rms ~38)."""
    v = vad.VAD(threshold=0.3, adaptive=False, auto_download=False)
    if not v.is_available():
        pytest.skip("модель VAD недоступна")
    assert v.is_speech(_voiced(amp=80).tobytes()) is True


def test_vad_voiced_signal_is_above_noise():
    """Голос «речевее» шума и тишины — инвариант к версии модели."""
    import numpy as np
    v = vad.VAD(auto_download=False)
    if not v.is_available():
        pytest.skip("модель VAD недоступна")
    np.random.seed(42)
    noise = (np.random.randn(8000) * 100).astype(np.int16).tobytes()
    silence = np.zeros(8000, dtype=np.int16).tobytes()
    assert (v.speech_probability(_voiced(amp=3000).tobytes())
            > v.speech_probability(noise))
    assert (v.speech_probability(_voiced(amp=80).tobytes())
            > v.speech_probability(silence))


def test_vad_reset_does_not_crash():
    """reset() работает без ошибок, даже если модель есть."""
    v = vad.VAD(auto_download=False)
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
    v = vad.VAD(auto_download=False)
    if not v.is_available():
        pytest.skip("модель VAD недоступна")
    short = np.zeros(100, dtype=np.int16).tobytes()
    assert v.is_speech(short) is False


# =================================================================
# Нормализация
# =================================================================

def test_vad_normalization_amplifies_quiet_signal():
    """Тихий сигнал (пик 150) усиливается к целевой амплитуде."""
    import numpy as np
    v = vad.VAD()
    arr = (np.sin(np.linspace(0, 100, 8000)) * 150).astype(np.int16)
    out = v._normalize(arr)
    assert out.dtype == np.float32
    assert float(np.abs(out).max()) > 150 / 32768.0


# =================================================================
# Адаптивный порог (без модели — чистая логика)
# =================================================================

def test_vad_adaptive_default_on():
    """VAD по умолчанию адаптивный."""
    v = vad.VAD()
    assert v._adaptive is True


def test_vad_threshold_low_on_high_snr():
    """Сигнал явно выше фона (snr >= 6) → порог опускается до 0.30."""
    v = vad.VAD()
    v._rms_baseline = 100.0
    assert v._compute_threshold(1000.0) == pytest.approx(0.30)


def test_vad_threshold_high_near_noise():
    """Сигнал у уровня фона (snr <= 2) → порог поднимается до 0.70."""
    v = vad.VAD()
    v._rms_baseline = 100.0
    assert v._compute_threshold(150.0) == pytest.approx(0.70)


def test_vad_threshold_base_between():
    """Средний SNR → базовый порог без сдвига."""
    v = vad.VAD()
    v._rms_baseline = 100.0
    assert v._compute_threshold(300.0) == pytest.approx(0.50)


def test_vad_threshold_disabled_when_not_adaptive():
    """adaptive=False → порог всегда базовый."""
    v = vad.VAD(adaptive=False)
    v._rms_baseline = 100.0
    assert v._compute_threshold(1000.0) == pytest.approx(0.50)


def test_vad_threshold_default_without_baseline():
    """Фон ещё не измерен → базовый порог."""
    v = vad.VAD()
    assert v._compute_threshold(1000.0) == pytest.approx(0.50)


# =================================================================
# Обучение фона
# =================================================================

def test_vad_rms_baseline_grows():
    """RMS-база обновляется на чанках."""
    import numpy as np
    v = vad.VAD()
    if not v.is_available():
        pytest.skip("модель VAD недоступна")
    for _ in range(5):
        quiet = (np.random.randn(8000) * 100).astype(np.int16).tobytes()
        v.is_speech(quiet)
    assert v.rms_baseline() > 0


def test_vad_reset_keeps_rms_baseline():
    """reset() не сбрасывает RMS-базу."""
    import numpy as np
    v = vad.VAD()
    if not v.is_available():
        pytest.skip("модель VAD недоступна")
    for _ in range(5):
        quiet = (np.random.randn(8000) * 100).astype(np.int16).tobytes()
        v.is_speech(quiet)
    before = v.rms_baseline()
    v.reset()
    assert v.rms_baseline() == before


def test_vad_baseline_calibration_n():
    """Калибровка — 30 замеров до «заморозки» базы."""
    v = vad.VAD()
    assert v._rms_calibration_n == 30


# =================================================================
# «Мёртвый» микрофон (цифровая тишина)
# =================================================================

def test_vad_dead_microphone_auto_off():
    """Если фон ~0 (нет сигнала) — VAD сам себя отключает."""
    import numpy as np
    v = vad.VAD()
    if not v.is_available():
        pytest.skip("модель VAD недоступна")

    zeros = np.zeros(8000, dtype=np.int16).tobytes()
    for _ in range(35):
        v.is_speech(zeros)

    assert v._auto_off is True, "VAD не отключился на мёртвом микрофоне"
    # И теперь всё пропускает.
    assert v.is_speech(zeros) is True


def test_vad_dead_mic_warned_logged(caplog):
    """Auto-off пишет warning в лог."""
    import numpy as np
    v = vad.VAD()
    if not v.is_available():
        pytest.skip("модель VAD недоступна")

    zeros = np.zeros(8000, dtype=np.int16).tobytes()
    with caplog.at_level(logging.WARNING, logger="jarvis.vad"):
        for _ in range(35):
            v.is_speech(zeros)

    assert any("не даёт сигнала" in rec.message for rec in caplog.records), \
        "warning о мёртвом микрофоне не записан"


# =================================================================
# Debug-логи
# =================================================================

def test_vad_debug_flag_default_off():
    """Debug по умолчанию выключен."""
    v = vad.VAD()
    assert v._debug is False


def test_vad_debug_logs_when_enabled(caplog):
    """При _debug=True пишется лог про РЕЧЬ или ТИШИНУ."""
    import numpy as np
    v = vad.VAD()
    if not v.is_available():
        pytest.skip("модель VAD недоступна")

    v._debug = True
    v._auto_off = False
    # baseline принудительно ненулевой (калибровка завершена)
    v._rms_baseline = 100
    v._rms_samples = 30

    with caplog.at_level(logging.INFO, logger="jarvis.vad"):
        signal = (np.random.randn(8000) * 1000).astype(np.int16).tobytes()
        v.is_speech(signal)

    assert any(
        ("РЕЧЬ" in rec.message or "ТИШИНА" in rec.message)
        for rec in caplog.records
    ), "debug-лог VAD не записан"


# =================================================================
# Настройки конфига
# =================================================================

def test_vad_debug_from_config():
    """VAD поддерживает флаг _debug (ставится из config в stt.py)."""
    v = vad.VAD()
    v._debug = True
    assert v._debug is True

