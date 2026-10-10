"""Silero VAD — детекция речи в аудио-потоке с адаптивным порогом.

Обёртка над ONNX-моделью Silero VAD (~1 МБ).
Работает через onnxruntime, без PyTorch.

Зачем:
    - Отсекает тишину перед Vosk — Vosk не крутит AcceptWaveform зря.
    - Отсекает шум (кашель, клацанье) — не уходит в Vosk.
    - Экономит CPU: ~90% времени в комнате тихо.

Адаптивность:
    Порог подстраивается под уровень микрофона автоматически.
    - Первые N чанков идут в калибровку RMS-фона.
    - Речь = (RMS > baseline × 2) И (VAD prob > adaptive_threshold).
    - Чем тише сигнал — тем ниже порог VAD.
    Решает проблему тихих микрофонов, когда absolute threshold 0.5
    не пропускает речь с prob 0.15.

ВАЖНО: Vosk работает как раньше. Wake-слово по-прежнему обязательно
(если wake_word_required=True). VAD только фильтрует вход.

API:
    VAD(sample_rate=16000, threshold=0.5, adaptive=True)
    .is_speech(pcm_int16)      — детекция речи в чанке (bool)
    .speech_probability(pcm)   — макс prob для отладки
    .rms_baseline()            — текущий RMS фона (для отладки/GUI)
    .reset()                   — сброс ONNX-state между фразами
"""

import logging
from pathlib import Path

log = logging.getLogger("jarvis.vad")

# Где искать модель. Сначала PROGRAM_DIR (ASCII), потом рядом с jarvis/.
_MODEL_CANDIDATES = [
    Path(r"C:\ProgramData\Phoenix\vad\silero_vad.onnx"),
    Path(__file__).resolve().parent / "silero_vad.onnx",
]

# Размер чанка для ONNX: 512 сэмплов при 16 кГц (32 мс).
_CHUNK_SAMPLES = 512

# Порог речи по умолчанию.
_DEFAULT_THRESHOLD = 0.5


def _find_model() -> Path | None:
    """Ищет silero_vad.onnx в стандартных местах."""
    for p in _MODEL_CANDIDATES:
        if p.exists():
            return p
    return None


class VAD:
    """Silero VAD — детектор речи с адаптивным порогом.

    Работает на CPU через onnxruntime. Один инстанс = один поток
    (не thread-safe). В listener-потоке один VAD — ок.
    """

    def __init__(self, sample_rate: int = 16000,
                 threshold: float = _DEFAULT_THRESHOLD,
                 adaptive: bool = True):
        self._sample_rate = sample_rate
        self._threshold = float(threshold)
        self._available = False

        # Адаптивный порог: если микрофон тихий — VAD-порог опускается
        # автоматически. Опирается на RMS фонового шума.
        self._adaptive = bool(adaptive)
        self._rms_baseline = 0.0       # RMS «тишины» — калибруется сам
        self._rms_samples = 0          # сколько калибровочных замеров набрано
        self._rms_calibration_n = 30   # ~15 сек при block 8000/16k = 500 мс

        self._session = None
        self._state = None  # state тензоры ONNX между вызовами

        try:
            import numpy as np  # noqa: F401
            import onnxruntime as ort
        except ImportError as e:
            log.warning("VAD: не установлен onnxruntime или numpy (%s) — "
                        "работаю без VAD", e)
            return

        model_path = _find_model()
        if model_path is None:
            log.warning(
                "VAD: модель silero_vad.onnx не найдена. Положи её в "
                "C:\\ProgramData\\Phoenix\\vad\\silero_vad.onnx"
            )
            return

        try:
            opts = ort.SessionOptions()
            opts.inter_op_num_threads = 1
            opts.intra_op_num_threads = 1
            opts.log_severity_level = 3  # только ошибки

            self._session = ort.InferenceSession(
                str(model_path), sess_options=opts,
                providers=["CPUExecutionProvider"],
            )
            self._reset_state()
            self._available = True
            log.info("VAD: Silero ONNX загружен (%s)", model_path)
        except Exception:
            log.exception("VAD: не удалось загрузить модель")

    def _reset_state(self):
        """Сброс ONNX state (между фразами)."""
        import numpy as np
        # Silero VAD v5: state формы (2, 1, 128) float32
        self._state = np.zeros((2, 1, 128), dtype=np.float32)

    def is_available(self) -> bool:
        return self._available

    def reset(self):
        """Сбросить ONNX state между фразами (для barge-in, wake).

        RMS-база НЕ сбрасывается — она про микрофон, а не про фразу.
        """
        if self._available:
            self._reset_state()

    def rms_baseline(self) -> float:
        """Текущий RMS фона (для отладки/GUI)."""
        return self._rms_baseline

    def is_speech(self, pcm_int16: bytes) -> bool:
        """Есть ли речь в чанке PCM int16 (16 кГц, mono).

        Адаптивный режим:
            1. Обновляем RMS-базу (фон) по первым N чанкам.
            2. Речь = (RMS > baseline × 2) И (VAD prob > adaptive_threshold).
            3. adaptive_threshold зависит от уровня RMS:
               - тихий сигнал  → порог ниже (0.15)
               - средний       → стандартный (self._threshold)
               - тише фона     → порог выше (0.5)
        """
        if not self._available:
            # Без VAD всё считаем речью — старое поведение.
            return True

        import numpy as np

        arr = np.frombuffer(pcm_int16, dtype=np.int16)
        if arr.size == 0:
            return False

        # --- RMS для адаптивности ---
        rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))

        # Калибровка: пока не набрали N замеров — считаем это фоном.
        # (Обычно при старте Феникса пользователь молчит.)
        if self._rms_samples < self._rms_calibration_n:
            self._rms_baseline = (
                (self._rms_baseline * self._rms_samples + rms)
                / (self._rms_samples + 1)
            )
            self._rms_samples += 1

        # Если очень громко — точно речь, не гоняем VAD зря.
        if self._adaptive and self._rms_baseline > 0:
            if rms > self._rms_baseline * 3.0:
                return True

        # --- VAD-инференс ---
        samples = arr.astype(np.float32) / 32768.0
        if len(samples) < _CHUNK_SAMPLES:
            return False

        # --- Адаптивный порог VAD ---
        threshold = self._threshold
        if self._adaptive:
            if rms > 0 and self._rms_baseline > 0:
                ratio = rms / max(self._rms_baseline, 1.0)
                if ratio < 1.5:
                    # Скорее фон — требуем высокий prob.
                    threshold = max(self._threshold, 0.5)
                elif ratio < 3.0:
                    # Средне — обычный порог.
                    threshold = self._threshold
                else:
                    # Заметно громче фона — снижаем порог.
                    threshold = min(self._threshold, 0.15)
            else:
                # Ещё не откалибровано — низкий порог.
                threshold = min(self._threshold, 0.15)

        max_prob = 0.0
        for i in range(0, len(samples) - _CHUNK_SAMPLES + 1, _CHUNK_SAMPLES):
            chunk = samples[i:i + _CHUNK_SAMPLES]
            try:
                prob = self._run_chunk(chunk)
            except Exception:
                log.exception("VAD: ошибка инференса")
                return True  # безопасный fallback
            if prob > max_prob:
                max_prob = prob
            if prob >= threshold:
                return True

        return False

    def _run_chunk(self, chunk) -> float:
        """Прогон одного 512-сэмплового чанка → вероятность речи."""
        import numpy as np

        inp = chunk.reshape(1, -1).astype(np.float32)
        sr = np.array(self._sample_rate, dtype=np.int64)

        outputs = self._session.run(
            None,
            {
                "input": inp,
                "state": self._state,
                "sr": sr,
            },
        )
        # outputs = [output, new_state]
        prob = float(outputs[0][0][0])
        self._state = outputs[1]
        return prob

    def speech_probability(self, pcm_int16: bytes) -> float:
        """Максимальная вероятность речи в чанке (для отладки)."""
        if not self._available:
            return 1.0

        import numpy as np

        samples = np.frombuffer(pcm_int16, dtype=np.int16).astype(np.float32)
        samples /= 32768.0

        if len(samples) < _CHUNK_SAMPLES:
            return 0.0

        max_prob = 0.0
        for i in range(0, len(samples) - _CHUNK_SAMPLES + 1, _CHUNK_SAMPLES):
            chunk = samples[i:i + _CHUNK_SAMPLES]
            try:
                prob = self._run_chunk(chunk)
                if prob > max_prob:
                    max_prob = prob
            except Exception:
                return 1.0
        return max_prob