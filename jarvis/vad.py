"""Silero VAD — детекция речи в аудио-потоке с адаптивным порогом.

Обёртка над ONNX-моделью Silero VAD (~1 МБ) через onnxruntime (без PyTorch).

Зачем:
    - Отсекает тишину/шум перед Vosk — распознаватель не крутит
      AcceptWaveform зря.
    - Экономит CPU: в тихой комнате в Vosk почти ничего не уходит.

Как работает (адаптивно):
    0. Silero v5 получает на вход «context(64) + chunk(512)» и переносит
       state, как в официальной обёртке. Без контекста модель «проседает»
       на непрерывной речи — особенно тихой.
    1. Нормализация по пику (gain до x20). После неё вероятность Silero
       почти не зависит от абсолютного уровня микрофона: речь даёт
       prob ~0.9, шум ~0.1. Поэтому тихая речь НЕ режется «абсолютным
       порогом RMS» (раньше был хардкод 80 — он ломал тихие микрофоны).
    2. Фоновый шум (RMS тишины) обучается на лету «min-tracker»:
       вниз быстро (0.30), вверх медленно (0.02), чтобы всплески речи
       не задирали оценку фона. Первые `_rms_calibration_n` чанков —
       фаза калибровки (подъём чуть быстрее, 0.05).
    3. Порог речи подстраивается по SNR (rms / фон):
         - сигнал явно выше фона (snr >= _CLEAR_SNR) -> порог ниже;
         - сигнал у уровня фона (snr <= _NEAR_NOISE_SNR) -> порог выше;
         - фон ещё не измерен -> базовый порог (threshold).
    4. «Мёртвый» микрофон (фон почти 0, цифровая тишина) — VAD отключается
       сам: лучше пропускать всё, чем резать всё.

Решение:  речь = (max_prob по чанкам) >= adaptive_threshold.

Debug:
    `vad._debug = True` (или config["vad_debug"]=True) -> лог каждый чанк:
        VAD: РЕЧЬ (rms=180 snr=15.0 prob=0.87 thr=0.30)
        VAD: ТИШИНА (rms=20 snr=1.3 prob=0.05 thr=0.70)

ВАЖНО: Vosk работает как раньше. Wake-слово по-прежнему обязательно
(если wake_word_required=True). VAD только фильтрует вход.

API:
    VAD(sample_rate=16000, threshold=0.5, adaptive=True)
    .is_speech(pcm_int16)      — детекция речи в чанке (bool)
    .speech_probability(pcm)   — макс prob для отладки (float)
    .rms_baseline()            — текущий RMS фона (для отладки/GUI)
    .reset()                   — сброс ONNX-state между фразами

    SpeechHangover(blocks=3)
    .feed(is_speech) -> bool   — отдавать ли блок в Vosk (хвост после речи)
    .reset()                   — сбросить хвост

Потокобезопасность: is_speech зовётся из аудио-callback, а reset() —
из основного потока (flush). ONNX-state защищён `_lock`.
"""

import logging
import threading
from pathlib import Path

log = logging.getLogger("jarvis.vad")

# Размер чанка для ONNX: 512 сэмплов при 16 кГц (32 мс).
_CHUNK_SAMPLES = 512

# Silero v5 требует подавать 512 новых сэмплов + 64 контекстных
# (последние 64 сэмпла предыдущего чанка). Без контекста модель «проседает»
# на непрерывной речи — особенно тихой. См. OnnxWrapper в silero-vad.
_CONTEXT_SAMPLES = 64

# Порог речи по умолчанию (макс. вероятность Silero на чанк).
_DEFAULT_THRESHOLD = 0.5

# Цифровая тишина: ниже этого RMS модель не гоняем (экономия CPU).
_HARD_SILENCE_RMS = 3.0

# Нормализация: тянем пик к _TARGET_PEAK, не сильнее _MAX_GAIN.
_TARGET_PEAK = 3000.0
_MAX_GAIN = 20.0

# SNR-границы адаптивного порога.
_NEAR_NOISE_SNR = 2.0    # rms <= фон*2   -> сигнал «в шуме», строже
_CLEAR_SNR = 6.0         # rms >= фон*6   -> сигнал явно выше фона
_SNR_STEP = 0.2          # шаг сдвига порога
_MIN_THRESHOLD = 0.30    # нижняя граница адаптивного порога
_MAX_THRESHOLD = 0.80    # верхняя граница адаптивного порога

# «Мёртвый» микрофон: фон ниже — сигнала нет вовсе.
_DEAD_MIC_RMS = 1.0

# «Хвост» после речи (мс). Vosk завершает фразу по ТИШИНЕ
# (KaldiRecognizer.AcceptWaveform -> True). Если VAD выкинет всю тишину,
# Vosk не увидит паузу, не отдаст финальный текст — и Феникс ответит
# поздно или не ответит вовсе. Поэтому после речи пропускаем в Vosk ещё
# столько тишины. 1500 мс = столько же, сколько видит Vosk без VAD.
DEFAULT_HANGOVER_MS = 1500


def _find_model() -> Path | None:
    """Ищет silero_vad.onnx: PROGRAM_DIR/vad -> рядом с пакетом -> fallback."""
    candidates = []
    try:
        from jarvis import paths
        candidates.append(paths.program_dir() / "vad" / "silero_vad.onnx")
    except Exception:
        log.debug("VAD: paths недоступен, ищу модель рядом с пакетом",
                  exc_info=True)
    candidates.append(Path(__file__).resolve().parent / "silero_vad.onnx")
    # Исторический путь установщика — как последний шанс.
    candidates.append(Path(r"C:\ProgramData\Phoenix\vad\silero_vad.onnx"))
    for path in candidates:
        try:
            if path.exists():
                return path
        except OSError:
            continue
    return None


class VAD:
    """Silero VAD — детектор речи с адаптивным порогом.

    Работает на CPU через onnxruntime. ONNX-state защищён локом:
    is_speech (аудио-поток) и reset (основной поток) не мешают друг другу.
    """

    def __init__(self, sample_rate: int = 16000,
                 threshold: float = _DEFAULT_THRESHOLD,
                 adaptive: bool = True):
        self._sample_rate = sample_rate
        self._threshold = float(threshold)
        self._available = False

        # Адаптивный порог.
        self._adaptive = bool(adaptive)
        self._rms_baseline = 0.0        # RMS фона (обучается)
        self._rms_samples = 0           # сколько калибровочных замеров набрано
        self._rms_calibration_n = 30    # ~15 сек при block 8000/16k = 500 мс
        self._quiet_warned = False      # уже предупредили про мёртвый микрофон
        self._auto_off = False          # VAD сам себя отключил
        self._debug = False             # True -> логировать каждый чанк

        self._session = None
        self._state = None
        self._context = None
        self._lock = threading.Lock()   # ONNX-state: callback vs reset()

        try:
            import numpy as np  # noqa: F401
            import onnxruntime as ort
        except ImportError as e:
            log.warning("VAD: нет onnxruntime/numpy (%s) — работаю без VAD", e)
            return

        model_path = _find_model()
        if model_path is None:
            log.warning(
                "VAD: модель silero_vad.onnx не найдена — работаю без VAD. "
                "Положи её в %s (или выключи vad_enabled).",
                Path(r"C:\ProgramData\Phoenix\vad\silero_vad.onnx"),
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

    # --- служебное -------------------------------------------------------

    def _reset_state(self):
        """Сброс ONNX state и контекста.

        Silero v5: state формы (2, 1, 128) + контекст (1, 64) float32.
        """
        import numpy as np
        with self._lock:
            self._state = np.zeros((2, 1, 128), dtype=np.float32)
            self._context = np.zeros((1, _CONTEXT_SAMPLES), dtype=np.float32)

    def is_available(self) -> bool:
        return self._available

    def reset(self):
        """Сбросить ONNX-state между фразами (для barge-in, wake).

        Флаги auto_off / quiet_warned и оценку фона НЕ сбрасываем — если VAD
        один раз решил, что микрофон мёртв, не перепроверяем.
        """
        if self._available:
            self._reset_state()

    def rms_baseline(self) -> float:
        """Текущая оценка RMS фона (для отладки/GUI)."""
        return self._rms_baseline

    # --- адаптация -------------------------------------------------------

    def _update_noise_floor(self, rms: float) -> None:
        """Обновляет оценку фона: вниз быстро, вверх медленно.

        «Min-tracker»: громкие всплески (речь, кашель) не задирают фон,
        а понижение уровня (стало тише) отслеживается быстро.
        """
        if self._rms_samples < self._rms_calibration_n:
            self._rms_samples += 1

        if self._rms_baseline <= 0.0:
            # Первый замер — стартовая оценка фона.
            self._rms_baseline = rms
        elif rms < self._rms_baseline:
            self._rms_baseline += 0.30 * (rms - self._rms_baseline)
        elif self._rms_samples < self._rms_calibration_n:
            self._rms_baseline += 0.05 * (rms - self._rms_baseline)
        else:
            self._rms_baseline += 0.02 * (rms - self._rms_baseline)

        if self._debug:
            log.info("VAD: ФОН (rms=%.0f baseline=%.0f n=%d/%d)",
                     rms, self._rms_baseline,
                     self._rms_samples, self._rms_calibration_n)

    def _compute_threshold(self, rms: float) -> float:
        """Адаптивный порог по SNR. Без фона/адаптива — базовый threshold."""
        thr = self._threshold
        if not self._adaptive or self._rms_baseline <= 0.0 or rms <= 0.0:
            return thr
        snr = rms / self._rms_baseline
        if snr <= _NEAR_NOISE_SNR:
            thr = min(_MAX_THRESHOLD, thr + _SNR_STEP)
        elif snr >= _CLEAR_SNR:
            thr = max(_MIN_THRESHOLD, thr - _SNR_STEP)
        return thr

    # --- инференс --------------------------------------------------------

    def _normalize(self, arr):
        """Тянет пик к _TARGET_PEAK (не сильнее _MAX_GAIN) -> float32 [-1, 1]."""
        import numpy as np
        peak = float(np.abs(arr).max())
        if peak > 0 and peak < _TARGET_PEAK:
            gain = min(_TARGET_PEAK / peak, _MAX_GAIN)
            if gain > 1.0:
                arr = (arr.astype(np.float32) * gain).clip(
                    -32768, 32767).astype(np.int16)
        return arr.astype(np.float32) / 32768.0

    def _run_chunk(self, chunk) -> float:
        """Прогон одного 512-сэмплового чанка -> вероятность речи.

        Silero v5: на вход идёт `context(64) + chunk(512)` = 576 сэмплов,
        state переносится между чанками, context обновляется. Без этого
        вероятность «проседает» на непрерывной (особенно тихой) речи.
        """
        import numpy as np

        seg = chunk.reshape(1, -1).astype(np.float32)
        sr = np.array(self._sample_rate, dtype=np.int64)

        with self._lock:
            inp = np.concatenate([self._context, seg], axis=1)
            outputs = self._session.run(
                None,
                {"input": inp, "state": self._state, "sr": sr},
            )
            # outputs = [output, new_state]
            prob = float(outputs[0][0][0])
            self._state = outputs[1]
            self._context = seg[:, -_CONTEXT_SAMPLES:]
        return prob

    def _max_prob(self, samples) -> float:
        """Макс. вероятность речи по всем чанкам сигнала."""
        if len(samples) < _CHUNK_SAMPLES:
            return 0.0
        max_prob = 0.0
        for i in range(0, len(samples) - _CHUNK_SAMPLES + 1, _CHUNK_SAMPLES):
            prob = self._run_chunk(samples[i:i + _CHUNK_SAMPLES])
            if prob > max_prob:
                max_prob = prob
        return max_prob

    # --- публичный API ---------------------------------------------------

    def is_speech(self, pcm_int16: bytes) -> bool:
        """Есть ли речь в чанке PCM int16 (16 кГц, mono).

        Fallback: без модели или при ошибке инференса -> True (старое
        поведение — ничего не режем).
        """
        if not self._available:
            return True
        if self._auto_off:
            return True

        import numpy as np

        arr = np.frombuffer(pcm_int16, dtype=np.int16)
        if arr.size == 0:
            return False

        # 1. RMS по оригиналу — до усиления (для адаптации фона/SNR).
        rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))

        # 2. Оценка фона + проверка «мёртвого» микрофона.
        self._update_noise_floor(rms)
        if (self._rms_samples >= self._rms_calibration_n
                and self._rms_baseline < _DEAD_MIC_RMS):
            if not self._quiet_warned:
                log.warning(
                    "VAD: микрофон не даёт сигнала (RMS фона=%.1f < %.1f). "
                    "VAD отключается сам — пропускаю всё. Проверьте микрофон "
                    "(Windows → Звук) или выключите vad_enabled.",
                    self._rms_baseline, _DEAD_MIC_RMS,
                )
                self._quiet_warned = True
            self._auto_off = True
            return True

        # 3. Цифровая тишина — модель не гоняем.
        if rms < _HARD_SILENCE_RMS:
            if self._debug:
                log.info("VAD: ТИШИНА-АБС (rms=%.1f < %.1f)",
                         rms, _HARD_SILENCE_RMS)
            return False

        # 4. Нормализация + инференс.
        samples = self._normalize(arr)
        try:
            max_prob = self._max_prob(samples)
        except Exception:
            log.exception("VAD: ошибка инференса — пропускаю чанк как речь")
            return True

        # 5. Адаптивный порог + решение.
        threshold = self._compute_threshold(rms)
        speech = max_prob >= threshold

        if self._debug:
            snr = rms / self._rms_baseline if self._rms_baseline > 0 else 0.0
            log.info(
                "VAD: %s (rms=%.0f snr=%.2f prob=%.3f thr=%.2f)",
                "РЕЧЬ" if speech else "ТИШИНА",
                rms, snr, max_prob, threshold,
            )
        return speech

    def speech_probability(self, pcm_int16: bytes) -> float:
        """Максимальная вероятность речи в чанке (для отладки).

        Та же нормализация, что и в is_speech. Чистая вероятность модели —
        без учёта фона/порога.
        """
        if not self._available or self._auto_off:
            return 1.0

        import numpy as np

        arr = np.frombuffer(pcm_int16, dtype=np.int16)
        if arr.size == 0:
            return 0.0

        samples = self._normalize(arr)
        try:
            return self._max_prob(samples)
        except Exception:
            return 1.0


class SpeechHangover:
    """Решает, отдавать ли блок в распознаватель, с «хвостом» после речи.

    Зачем: Vosk режет фразу по тишине (`AcceptWaveform` -> True). VAD без
    «хвоста» выкидывает тишину целиком, поэтому Vosk не видит паузу и
    НИКОГДА не отдаёт финальный текст — ответ приходит поздно (или не
    приходит). С «хвостом» Vosk видит ровно те же 1.5 с тишины, что и при
    выключенном VAD, но длинную тишину мы по-прежнему не гоняем зря.

    Класс намеренно без зависимостей (numpy/onnxruntime/sounddevice) —
    чтобы тестировался в CI.

    API:
        gate.feed(is_speech) -> bool   # True => блок идёт в Vosk
        gate.reset()                   # сброс хвоста (flush/barge)
    """

    def __init__(self, blocks: int = 3):
        self._max_blocks = max(0, int(blocks))
        self._left = 0

    @property
    def max_blocks(self) -> int:
        return self._max_blocks

    def feed(self, is_speech: bool) -> bool:
        if is_speech:
            self._left = self._max_blocks
            return True
        if self._left > 0:
            self._left -= 1
            return True
        return False

    def reset(self) -> None:
        self._left = 0

    @staticmethod
    def blocks_for_ms(ms: float, block_ms: float) -> int:
        """Сколько блоков «хвоста» соответствует ms миллисекунд."""
        if block_ms <= 0:
            return 0
        return int(round(max(0.0, float(ms)) / block_ms))
