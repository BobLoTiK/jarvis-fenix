"""Распознавание речи.

Гибрид: Vosk (wake) + Whisper (точная расшифровка).
VAD: Silero ONNX отсекает тишину/шум ДО Vosk. После речи в Vosk уходит
ещё «хвост» тишины (vad_hangover_ms) — Vosk завершает фразу по тишине,
без хвоста он не отдал бы финальный текст.
Barge-in: адаптивная калибровка эха и фона при старте.
Ring buffer: последние 10 фраз (для «что ты слышал»).
"""

import json
import logging
import os
import queue
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np
import sounddevice as sd
from vosk import KaldiRecognizer, Model, SetLogLevel

from jarvis.vad import DEFAULT_HANGOVER_MS, SpeechHangover, VAD

log = logging.getLogger("jarvis.stt")

TURBO_MODEL = "deepdml/faster-whisper-large-v3-turbo-ct2"

WHISPER_PROMPT = (
    "Это русская речь. Пожалуйста, транскрибируй текст на русском языке. "
    "Имя ассистента — Феникс, второе имя — Джарвис. "
    "Частые слова: Феникс, Джарвис, открой, закрой, найди, погода, "
    "напоминание, задача, голос, режим, паки, Нижний Новгород, "
    "курс доллара."
)

ECHO_WINDOW_SEC = 0.5
BARGE_LOG_INTERVAL = 0.5

# Блок аудио из RawInputStream: 2048 сэмплов @16 кГц = 128 мс.
# Раньше было 8000 (500 мс), и это была главная «ступенька» задержки:
# VAD не мог отреагировать быстрее 500 мс, а датчик «хвоста» тишины
# (vad_hangover_ms) округлялся до 500 мс. Замер scripts/vadbench.py:
# с 500 мс VAD добавлял к ответу целый блок, с 128 мс — ~100 мс.
# 2048 кратно 512: Silero считает ровно 4 чанка, без остатка на полу
# (раньше из 8000 сэмплов 320 молча не доходили до модели).
DEFAULT_BLOCK_MS = 128
MIN_BLOCK_SAMPLES = 512

# Флаг, чтобы не добавлять пути CUDA в PATH повторно при каждом импорте stt.
_CUDA_DLLS_ADDED = False


def _enable_cuda_dlls():
    """Добавляет пути к CUDA-библиотекам (cuBLAS, cuDNN) в PATH.

    Идемпотентна: повторный вызов ничего не делает.
    """
    global _CUDA_DLLS_ADDED
    if _CUDA_DLLS_ADDED:
        return
    try:
        import nvidia
    except ImportError:
        return
    base = Path(nvidia.__path__[0])
    dirs = [str(p) for p in (base / "cublas" / "bin", base / "cudnn" / "bin") if p.exists()]
    if dirs:
        os.environ["PATH"] = os.pathsep.join(dirs) + os.pathsep + os.environ["PATH"]
        _CUDA_DLLS_ADDED = True


class Listener:
    def __init__(self, model_dir, sample_rate=16000, device=None, config=None):
        SetLogLevel(-1)
        self._model = Model(str(model_dir))
        self._rec = KaldiRecognizer(self._model, sample_rate)
        self._sample_rate = sample_rate
        self._config = config
        self._device = self.resolve_device(device)
        self.device_name = self._current_device_name()
        self._audio = queue.Queue()
        self._utt_buf = []
        self._utt_len = 0
        self.peak = 0
        self.utterances = 0
        self.current_rms = 0  # текущий уровень сигнала (для GUI)

        self.barge_enabled = True
        self.muted = False
        self.barge_flag = False
        # Блок аудио 128 мс (см. DEFAULT_BLOCK_MS) вместо старых 500 мс.
        self._block_size = max(
            MIN_BLOCK_SAMPLES,
            int(round(sample_rate * DEFAULT_BLOCK_MS / 1000.0)),
        )
        self._block_ms = max(
            1, int(round(self._block_size * 1000.0 / max(1, sample_rate)))
        )
        # Флаг «микрофон сменили на лету»: phrases() увидит его и
        # переоткроет RawInputStream на новом устройстве (см. set_input_device).
        self._device_reload = False

        # VAD: отсекает тишину/шум ДО Vosk. is_speech зовётся из
        # аудио-callback (PortAudio-поток), а не из listener-потока.
        # При этом ONNX-state защищён локом внутри VAD (callback vs reset).
        self.vad = None
        self.vad_enabled = True
        # «Хвост» после речи: Vosk завершает фразу по тишине
        # (AcceptWaveform -> True). Без хвоста VAD выкидывает всю тишину,
        # Vosk не видит паузу и не отдаёт финальный текст — ответ приходит
        # поздно или не приходит вовсе. См. vad.SpeechHangover.
        self._vad_gate = None
        if config is not None:
            try:
                self.vad_enabled = bool(config.get("vad_enabled", True))
            except Exception:
                pass
        if self.vad_enabled:
            try:
                threshold = 0.5
                adaptive = True
                if config is not None:
                    try:
                        threshold = float(config.get("vad_threshold", 0.5))
                    except Exception:
                        threshold = 0.5
                    try:
                        adaptive = bool(config.get("vad_adaptive", True))
                    except Exception:
                        adaptive = True
                self.vad = VAD(
                    sample_rate=sample_rate,
                    threshold=threshold,
                    adaptive=adaptive,
                    auto_download=self._vad_auto_download(),
                )
                # Debug VAD включается через config["vad_debug"]
                if config is not None:
                    try:
                        self.vad._debug = bool(config.get("vad_debug", False))
                    except Exception:
                        pass
                if not self.vad.is_available() and not self.vad.is_model_pending():
                    log.warning("VAD: модель недоступна — работаю без VAD")
                    self.vad = None
                else:
                    self._vad_gate = SpeechHangover(self._hangover_blocks())
                    if self.vad.is_model_pending():
                        # Модель качается в фоне (vad.py): сам объект уже
                        # живой и до появления файла просто пропускает всё.
                        log.info(
                            "VAD: модель качается в фоне — фильтр включится "
                            "сам (хвост=%d блоков)", self._vad_gate.max_blocks)
                    else:
                        log.info(
                            "VAD: adaptive=%s, threshold=%.2f, хвост=%d блоков",
                            adaptive, threshold, self._vad_gate.max_blocks,
                        )
            except Exception:
                log.exception("VAD: не удалось создать")
                self.vad = None
                self._vad_gate = None

        # Ring buffer последних фраз (для «что ты слышал»)
        self.recent_phrases: deque = deque(maxlen=10)

        # Адаптивный barge-in
        self._echo_window_samples = deque(maxlen=20)
        self._echo_baseline = 0
        self._barge_threshold = 150
        self._barge_speech_ms = 0
        self._speech_active = False
        self._speech_started_at = 0.0
        self._last_barge_log = 0.0
        self._echo_done = False

    def barge_start(self):
        self.barge_flag = False
        self._barge_speech_ms = 0
        self._speech_active = True
        self._speech_started_at = time.time()
        self._echo_done = False
        self._echo_window_samples.clear()
        self._barge_threshold = max(150, int(self._echo_baseline * 1.8))

    def barge_end(self):
        self._speech_active = False
        log.info("Barge-in: стоп (echo=%d, thr=%d, речь=%d мс)",
                 self._echo_baseline, self._barge_threshold, self._barge_speech_ms)

    def _process_barge(self, rms):
        if not self._speech_active or not self.barge_enabled:
            return
        now = time.time()
        elapsed = now - self._speech_started_at

        if elapsed < ECHO_WINDOW_SEC:
            return

        if not self._echo_done:
            self._echo_window_samples.append(rms)
            if elapsed >= ECHO_WINDOW_SEC + 0.5:
                if self._echo_window_samples:
                    arr = sorted(self._echo_window_samples)
                    self._echo_baseline = arr[int(len(arr) * 0.7)]
                self._barge_threshold = max(150, int(self._echo_baseline * 1.8))
                self._echo_done = True
                log.info("Barge-in: калибровка echo=%d, threshold=%d",
                         self._echo_baseline, self._barge_threshold)
            return

        self._echo_window_samples.append(rms)
        if len(self._echo_window_samples) >= 10:
            arr = sorted(self._echo_window_samples)
            new_echo = arr[int(len(arr) * 0.7)]
            self._echo_baseline = int(0.9 * self._echo_baseline + 0.1 * new_echo)
            self._barge_threshold = max(150, int(self._echo_baseline * 1.8))

        if rms > self._barge_threshold:
            self._barge_speech_ms += self._block_ms
            if self._barge_speech_ms >= 150:
                self.barge_flag = True
        else:
            self._barge_speech_ms = 0

        if now - self._last_barge_log >= BARGE_LOG_INTERVAL:
            log.info("barge: rms=%d, echo=%d, thr=%d, speech_ms=%d, flag=%s",
                     rms, self._echo_baseline, self._barge_threshold,
                     self._barge_speech_ms, self.barge_flag)
            self._last_barge_log = now

    @staticmethod
    def resolve_device(device):
        if device is None or device == "":
            return None
        if isinstance(device, int):
            return device
        name = str(device).lower()
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0 and name in d["name"].lower():
                return i
        log.warning("Микрофон %r не найден, беру по умолчанию", device)
        return None

    def _current_device_name(self):
        try:
            idx = self._device if self._device is not None else sd.default.device[0]
            return sd.query_devices(idx)["name"]
        except Exception:
            return "по умолчанию"

    def _hangover_blocks(self) -> int:
        """Сколько блоков тишины после речи отдавать в Vosk (см. vad.SpeechHangover)."""
        ms = DEFAULT_HANGOVER_MS
        if self._config is not None:
            try:
                ms = int(self._config.get("vad_hangover_ms", DEFAULT_HANGOVER_MS))
            except Exception:
                ms = DEFAULT_HANGOVER_MS
        block_ms = self._block_size * 1000.0 / max(1, self._sample_rate)
        return SpeechHangover.blocks_for_ms(ms, block_ms)

    def _vad_auto_download(self) -> bool:
        """Качать ли модель VAD, если её нет на диске (vad_auto_download).

        На чистой установке silero_vad.onnx отсутствует (в репозитории его
        нет), и VAD молча выключался. Теперь Феникс качает модель сам —
        флагом это можно запретить (например, на машине без интернета).
        """
        if self._config is None:
            return True
        try:
            return bool(self._config.get("vad_auto_download", True))
        except Exception:
            return True

    def _callback(self, indata, frames, time_info, status):
        if status:
            log.warning("Аудиопоток: %s", status)
        arr = np.frombuffer(indata, dtype=np.int16)
        if arr.size:
            self.peak = max(self.peak, int(np.abs(arr).max()))
            rms = int(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
            self.current_rms = rms
        else:
            rms = 0
            self.current_rms = 0
        self._process_barge(rms)

        if self.muted:
            return

        # VAD: пропускаем чанк в Vosk ТОЛЬКО если в нём есть речь.
        # Тишина и шум отсекаются — Vosk не крутит AcceptWaveform зря.
        # ВАЖНО: после речи отдаём ещё «хвост» тишины (vad_hangover_ms),
        # иначе Vosk не увидит паузу и не отдаст финальную фразу.
        raw = bytes(indata)
        if self.vad is not None:
            try:
                speech = self.vad.is_speech(raw)
            except Exception:
                log.exception("VAD.is_speech упал — пропускаю чанк как есть")
                speech = True
            if self._vad_gate is not None and not self._vad_gate.feed(speech):
                # Тишина дольше «хвоста» — в Vosk не пушим.
                # Barge/peak/current_rms уже обновлены.
                return

        self._audio.put(raw)

    def _drain_audio(self) -> None:
        """Чистит очередь аудио и накопленный буфер текущей фразы.

        Отдельный метод, потому что нужен минимум в двух местах:
        flush() (barge-in / wake / сброс) и переоткрытие потока при
        смене микрофона на лету (set_input_device).
        """
        while not self._audio.empty():
            try:
                self._audio.get_nowait()
            except queue.Empty:
                break
        self._utt_buf.clear()
        self._utt_len = 0

    def flush(self):
        """Сброс аудио-буфера.

        ВАЖНО: НЕ трогаем Vosk (Reset / AcceptWaveform) — только чистим
        очередь. Vosk не thread-safe: если дёргать его API из разных
        потоков, libvosk.dll падает с access violation (0xc0000015).

        Vosk-контекст сбрасывает сам listener в phrases() через Reset(),
        когда накапливается слишком много тишины.
        """
        self._drain_audio()
        # Сброс VAD state — после barge/wake/flush детекция должна начаться заново.
        if self.vad is not None:
            try:
                self.vad.reset()
            except Exception:
                pass
        # «Хвост» тоже сбрасываем — иначе после flush в Vosk утечёт
        # тишина из прошлой фразы.
        if self._vad_gate is not None:
            self._vad_gate.reset()

    def set_vad_enabled(self, enabled: bool) -> None:
        """Включить/выключить VAD на лету. Пересоздаёт инстанс."""
        self.vad_enabled = bool(enabled)

        if not self.vad_enabled:
            self.vad = None
            self._vad_gate = None
            log.info("VAD: выключен (динамически)")
            return

        # Включаем — пересоздаём VAD
        if self.vad is not None:
            log.info("VAD: уже включён")
            return

        try:
            threshold = 0.5
            adaptive = True
            if self._config is not None:
                try:
                    threshold = float(self._config.get("vad_threshold", 0.5))
                except Exception:
                    threshold = 0.5
                try:
                    adaptive = bool(self._config.get("vad_adaptive", True))
                except Exception:
                    adaptive = True

            from jarvis.vad import SpeechHangover, VAD
            self.vad = VAD(
                sample_rate=self._sample_rate,
                threshold=threshold,
                adaptive=adaptive,
                auto_download=self._vad_auto_download(),
            )
            if self._config is not None:
                try:
                    self.vad._debug = bool(self._config.get("vad_debug", False))
                except Exception:
                    pass
            if not self.vad.is_available() and not self.vad.is_model_pending():
                log.warning("VAD: модель недоступна — работаю без VAD")
                self.vad = None
                self._vad_gate = None
            else:
                self._vad_gate = SpeechHangover(self._hangover_blocks())
                if self.vad.is_model_pending():
                    log.info("VAD: включён (динамически), модель качается "
                             "в фоне — фильтр включится сам (хвост=%d блоков)",
                             self._vad_gate.max_blocks)
                else:
                    log.info(
                        "VAD: включён (динамически), adaptive=%s, "
                        "threshold=%.2f, хвост=%d блоков", adaptive, threshold,
                        self._vad_gate.max_blocks)
        except Exception:
            log.exception("VAD: не удалось создать динамически")
            self.vad = None
            self._vad_gate = None

    def reload_vad(self) -> None:
        """Перечитывает настройки VAD из config и пересоздаёт инстанс.

        Порог, адаптивность и «хвост» (vad_threshold / vad_adaptive /
        vad_hangover_ms) читаются ТОЛЬКО при создании VAD. Без этого
        метода слайдер «Порог VAD» в GUI двигался, но детекция
        продолжала работать со старым порогом до перезапуска.

        VAD выключен — ничего не делаем (включится по set_vad_enabled).
        """
        if not self.vad_enabled:
            log.info("VAD: reload пропущен — VAD выключен")
            return

        # Обнуляем, иначе set_vad_enabled(True) выйдет по «уже включён».
        self.vad = None
        self._vad_gate = None
        self.set_vad_enabled(True)

    def set_input_device(self, device) -> None:
        """Меняет микрофон на лету.

        Сам переоткрыть поток отсюда нельзя: RawInputStream живёт в
        phrases() (поток слушателя), и закрывать его из другого потока —
        гарантированный PortAudio-креш. Поэтому только помечаем
        `_device_reload`, а phrases() сам переоткроет поток.
        """
        new_device = self.resolve_device(device)
        if new_device == self._device:
            log.info("Микрофон не изменился (index=%s) — поток не трогаю",
                     new_device)
            return

        self._device = new_device
        self.device_name = self._current_device_name()
        self._device_reload = True
        log.info("Микрофон переключён на %r (index=%s) — переоткрываю поток",
                 self.device_name, new_device)

    def reset_stats(self):
        """Сбрасывает peak и utterances — для кнопки «Проверить микрофон»."""
        self.peak = 0
        self.utterances = 0
        log.info("Listener: статистика сброшена")

    def phrases(self, stop_event):
        max_buf = self._sample_rate * 2 * 30
        # Внешний while — смена микрофона на лету. set_input_device()
        # ставит _device_reload; здесь мы выходим из `with` (PortAudio
        # закрывает поток в своём же потоке — так безопасно) и
        # открываем новый уже на другом устройстве.
        backoff = 0.5
        while not stop_event.is_set():
            self._device_reload = False
            try:
                stream = sd.RawInputStream(
                    samplerate=self._sample_rate,
                    blocksize=self._block_size,
                    dtype="int16",
                    channels=1,
                    device=self._device,
                    callback=self._callback,
                )
                stream.start()
            except Exception:
                # Устройство занято/битое: раньше исключение вылетало из
                # phrases(), run_loop глотал его один раз — и слушатель
                # замолкал до перезапуска. Теперь повторяем с паузой.
                log.exception("Listener: не удалось открыть микрофон (%s) — "
                              "повторю через %.1f с", self.device_name, backoff)
                if stop_event.wait(backoff):
                    return
                backoff = min(backoff * 2, 10.0)
                continue
            backoff = 0.5
            try:
                log.info("Микрофон открыт (%s), слушаю...", self.device_name)
                while not stop_event.is_set() and not self._device_reload:
                    try:
                        data = self._audio.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    self._utt_buf.append(data)
                    self._utt_len += len(data)
                    while self._utt_len > max_buf and len(self._utt_buf) > 1:
                        self._utt_len -= len(self._utt_buf.pop(0))
                    if self._rec.AcceptWaveform(data):
                        text = json.loads(self._rec.Result()).get("text", "").strip()
                        audio = b"".join(self._utt_buf)
                        self._utt_buf.clear()
                        self._utt_len = 0
                        if text:
                            self.utterances += 1
                            self.recent_phrases.append(text)
                            log.info("Распознано (vosk): %s", text)
                            yield text, audio
            finally:
                # Закрываем поток в своём же потоке (PortAudio-безопасно).
                for closer in (stream.stop, stream.close):
                    try:
                        closer()
                    except Exception:
                        pass

            if self._device_reload and not stop_event.is_set():
                # Мы в потоке слушателя, поэтому Vosk дёргаем отсюда же:
                # фраза с прошлого микрофона не должна склеиться с новой.
                self._drain_audio()
                try:
                    self._rec.Reset()
                except Exception:
                    log.exception("Vosk: Reset при смене микрофона упал")
                if self.vad is not None:
                    try:
                        self.vad.reset()
                    except Exception:
                        pass
                if self._vad_gate is not None:
                    self._vad_gate.reset()
                log.info("Микрофон переоткрываю: %s", self.device_name)


class WhisperTranscriber:
    """faster-whisper с ленивой (фоновой) загрузкой модели.

    Раньше модель грузилась прямо в __init__ и блокировала старт
    Феникса: large-v3-turbo — ~5 с на GPU и десятки секунд на CPU,
    и всё это время окно GUI ещё не показывалось. При lazy=True
    загрузка идёт в фоновом потоке (preload_async), а первый
    transcribe() просто дожидается её окончания.
    """

    def __init__(self, model_name="auto", device="auto", lazy=False):
        self._model = None
        self._load_error: Exception | None = None
        self._loading = False
        self._load_lock = threading.Lock()
        self._loaded = threading.Event()
        self._model_name = model_name
        self._device = device

        if lazy:
            self.preload_async()
        else:
            self._load()
            self._loaded.set()

    # --- ленивая загрузка -------------------------------------------------

    def is_ready(self) -> bool:
        """Модель уже загружена?"""
        return self._model is not None

    def wait_ready(self, timeout: float | None = None) -> bool:
        """Ждёт окончания загрузки. True — модель готова."""
        return self._loaded.wait(timeout)

    def preload_async(self) -> None:
        """Грузит модель в фоновом потоке (не блокирует старт)."""
        with self._load_lock:
            if self._model is not None or self._loading:
                return
            self._loading = True
        threading.Thread(target=self._background_load, daemon=True,
                         name="whisper-load").start()

    def _background_load(self) -> None:
        try:
            self._load()
        except Exception as e:
            self._load_error = e
            log.exception("Whisper: фоновая загрузка не удалась")
        finally:
            with self._load_lock:
                self._loading = False
            self._loaded.set()

    def _ensure_loaded(self) -> None:
        """Гарантирует загруженную модель: ждёт фон, иначе грузит сам."""
        if self._model is not None:
            return
        if self._loading:
            self._loaded.wait()
        if self._model is None:
            self._load()
            self._loaded.set()

    def _load(self) -> None:
        """Загрузка модели. Работает и из фонового потока, и синхронно."""
        if self._model is not None:
            return

        model_name = self._model_name
        device = self._device

        # HF_HOME нужен ТОЛЬКО для Whisper: ctranslate2 ломается
        # на не-ASCII путях. Но Piper тоже использует huggingface_hub —
        # и если HF_HOME стоит, Piper качает модель в наш ASCII-кэш
        # в degraded-режиме (без symlinks).
        #
        # Решение: ставим HF_HOME временно — на время импорта faster_whisper
        # и загрузки модели. Потом восстанавливаем — чтобы Piper качал
        # в свой обычный кэш (~/.cache/huggingface).
        from jarvis import paths as _paths

        _old_hf_home = os.environ.get("HF_HOME")
        _old_hf_cache = os.environ.get("HUGGINGFACE_HUB_CACHE")

        os.environ["HF_HOME"] = str(_paths.program_whisper_cache_dir())
        os.environ["HUGGINGFACE_HUB_CACHE"] = str(_paths.program_whisper_cache_dir())

        try:
            _enable_cuda_dlls()
            import ctranslate2
            from faster_whisper import WhisperModel

            if device == "auto":
                device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"

            self._model = None

            if device == "cuda":
                name = TURBO_MODEL if model_name == "auto" else model_name
                try:
                    log.info("Загрузка Whisper (%s) на GPU...", name)
                    self._model = WhisperModel(
                        name, device="cuda", compute_type="int8_float16"
                    )
                    log.info("Whisper готов (GPU)")
                except Exception:
                    log.exception("GPU не завёлся, откатываюсь на CPU")

            if self._model is None:
                name = "small" if model_name == "auto" else model_name
                log.info("Загрузка Whisper (%s) на CPU...", name)
                self._model = WhisperModel(
                    name, device="cpu", compute_type="int8"
                )
                log.info("Whisper готов (CPU)")
        finally:
            # Восстанавливаем — чтобы Piper не качал в наш ASCII-кэш.
            if _old_hf_home is None:
                os.environ.pop("HF_HOME", None)
            else:
                os.environ["HF_HOME"] = _old_hf_home
            if _old_hf_cache is None:
                os.environ.pop("HUGGINGFACE_HUB_CACHE", None)
            else:
                os.environ["HUGGINGFACE_HUB_CACHE"] = _old_hf_cache

    def transcribe(self, pcm, sample_rate=16000):
        self._ensure_loaded()
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if sample_rate != 16000 and len(audio) > 1:
            n = int(len(audio) * 16000 / sample_rate)
            audio = np.interp(
                np.linspace(0, len(audio) - 1, n),
                np.arange(len(audio)), audio
            ).astype(np.float32)
        segments, _ = self._model.transcribe(
            audio, language="ru", beam_size=2, vad_filter=True,
            condition_on_previous_text=False, initial_prompt=WHISPER_PROMPT,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        log.info("Распознано (whisper): %s", text)
        return text