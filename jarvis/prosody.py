"""Prosody — эмоции из голоса (RMS + pitch + ZCR).

Быстрая эвристика БЕЗ ML-моделей. Работает на CPU мгновенно.

Вход: сырое аудио (PCM int16, 16 кГц, mono).
Выход: {emotion, arousal, valence} где:
    - emotion  — одна из "happy" / "excited" / "annoyed" / "tired" / "neutral"
    - arousal  — 0..1 (спокойствие → возбуждение)
    - valence  — -1..+1 (негатив → позитив)

Эмоции совпадают с mood.STATES:
    neutral  — ровный тон
    happy    — умеренный тон, тёплый
    excited  — громко, высоко
    annoyed  — громко, резко (высокий ZCR)
    tired    — тихо, низкий pitch

ВАЖНО: это быстрая эвристика. Точность ~60-70%.
ML-модель (audeering/wav2vec2) — отдельный этап.

Использование:
    from jarvis.prosody import analyze_prosody
    result = analyze_prosody(pcm_bytes, sample_rate=16000)
    if result:
        mood.set_mood(result["emotion"], reason="prosody")
"""

import logging
import math

log = logging.getLogger("jarvis.prosody")


# --- Пороги (эмпирические, калибруются под нормальный микрофон) ---

# RMS в int16. Тихая речь 100-500, нормальная 1000-3000, крик 5000+.
_RMS_TIRED_MAX = 200       # ниже — усталость
_RMS_LOUD_MIN = 2500       # выше — возбуждение

# Pitch (Гц). Мужской голос 80-180, женский 150-300.
# Низкий pitch → усталость, высокий → возбуждение.
_PITCH_TIRED_MAX = 95
_PITCH_EXCITED_MIN = 220

# ZCR (0..1). Высокий → шипящие/резкие звуки → раздражение.
_ZCR_ANNOYED_MIN = 0.18


def _rms(samples) -> float:
    """RMS (громкость) сырого аудио int16."""
    if not samples:
        return 0.0
    n = len(samples)
    s = sum(int(x) * int(x) for x in samples)
    return math.sqrt(s / n)


def _zero_crossing_rate(samples) -> float:
    """ZCR — доля переходов через ноль. Высокий на шумных/шипящих."""
    if len(samples) < 2:
        return 0.0
    crossings = 0
    prev = samples[0]
    for x in samples[1:]:
        if (prev >= 0) != (x >= 0):
            crossings += 1
        prev = x
    return crossings / len(samples)


def _estimate_pitch(samples, sample_rate: int) -> float:
    """Очень грубая оценка pitch через autocorrelation.

    Возвращает частоту в Гц (0, если не удалось).
    Точность ±20%, но для эмоций хватает.

    ВАЖНО: samples кастится в float64 ДО умножения.
    Иначе int16 * int16 переполняется (32767² ≈ 10⁹ >> int16 max).
    """
    if len(samples) < 512:
        return 0.0

    # Автокорреляция для лагов 40..400 сэмплов (50..400 Гц при 16 кГц)
    # Считаем на окне 1024 сэмпла.
    n = min(1024, len(samples))
    a = samples[:n].astype("float64")

    max_lag = min(400, n // 2)
    min_lag = 40

    best_lag = 0
    best_val = 0.0
    for lag in range(min_lag, max_lag):
        val = 0.0
        for i in range(0, n - lag, 4):  # шаг 4 — быстрее
            val += a[i] * a[i + lag]
        if val > best_val:
            best_val = val
            best_lag = lag

    if best_lag == 0:
        return 0.0
    return sample_rate / best_lag


def analyze_prosody(pcm_int16: bytes, sample_rate: int = 16000,
                    min_samples: int = 3200) -> dict | None:
    """Анализ просодии.

    pcm_int16 — сырое аудио PCM int16 (16 кГц, mono).
    min_samples — минимальный размер (по умолчанию 200 мс).

    Возвращает dict с emotion/arousal/valence, или None если слишком
    короткий чанк.
    """
    if not pcm_int16:
        return None

    try:
        import numpy as np
    except ImportError:
        log.warning("prosody: numpy не установлен")
        return None

    arr = np.frombuffer(pcm_int16, dtype=np.int16)
    if arr.size < min_samples:
        return None

    # --- Признаки ---
    rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
    zcr = float(np.mean(np.abs(np.diff(np.sign(arr))) > 0))
    pitch = _estimate_pitch(arr, sample_rate)

    # --- Классификация (по приоритету) ---
    emotion = "neutral"
    arousal = 0.5  # 0=спокойствие, 1=возбуждение
    valence = 0.0  # -1=негатив, +1=позитив

    # Усталость: тихо + низкий pitch
    if rms < _RMS_TIRED_MAX and (pitch == 0 or pitch < _PITCH_TIRED_MAX):
        emotion = "tired"
        arousal = 0.15
        valence = -0.2

    # Раздражение: громко + высокий ZCR (резкие звуки)
    elif rms > _RMS_LOUD_MIN and zcr > _ZCR_ANNOYED_MIN:
        emotion = "annoyed"
        arousal = 0.8
        valence = -0.6

    # Возбуждение: громко + высокий pitch
    elif rms > _RMS_LOUD_MIN or pitch > _PITCH_EXCITED_MIN:
        emotion = "excited"
        arousal = 0.9
        valence = 0.7

    # Радость: умеренно громко, без раздражения
    elif rms > _RMS_TIRED_MAX and zcr < _ZCR_ANNOYED_MIN:
        # Мягкая эвристика: если pitch в среднем диапазоне — happy
        if pitch and _PITCH_TIRED_MAX < pitch < _PITCH_EXCITED_MIN:
            emotion = "happy"
            arousal = 0.6
            valence = 0.5

    result = {
        "emotion": emotion,
        "arousal": round(arousal, 2),
        "valence": round(valence, 2),
        "rms": round(rms, 1),
        "pitch": round(pitch, 1) if pitch else 0.0,
        "zcr": round(zcr, 3),
    }
    log.debug("prosody: %s (rms=%.0f pitch=%.0f zcr=%.2f)",
              emotion, rms, pitch, zcr)
    return result