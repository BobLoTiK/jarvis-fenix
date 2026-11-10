"""Метрики TTS-конвейера: только длительности и ресурсы, без текста.

Зачем: план R1 требует baseline «первый чанк LLM → безопасная фраза →
готовый PCM → начало звука», медиану/p95 и связь с отменой. Здесь нет ни
команды, ни ответа, ни ключей — только числа, поэтому запись в журнал
безопасна.

Точки конвейера (первое событие побеждает, повторы не считаются):

    first_chunk — первый чанк пришёл из LLM
    first_safe  — первый чанк прошёл постфильтр safety (можно озвучивать)
    first_pcm   — синтез дал первый готовый PCM
    first_audio — плеер начал писать в аудиовыход (звук пошёл)

Использование::

    tl = Timeline()
    tl.mark("first_chunk")
    ...
    tl.finish(cancelled=False, backend="silero")

Сводка по последним ходам: ``summary()`` — p50/p95 на метку. Один ход —
одна запись в кольцевом буфере (последние ``MAX_TURNS``); ничего не
хранится на диск.
"""

from __future__ import annotations

import logging
import statistics
import threading
import time
from collections import deque

log = logging.getLogger("jarvis.metrics")

#: Метки, по которым нужно baseline (порядок = порядок событий).
MARK_NAMES = ("first_chunk", "first_safe", "first_pcm", "first_audio")

#: Сколько ходов держим для p50/p95.
MAX_TURNS = 50

_ring: deque[dict] = deque(maxlen=MAX_TURNS)
_ring_lock = threading.Lock()

_proc = None
_proc_lock = threading.Lock()


def _process():
    """psutil.Process() ровно один раз; None — psutil недоступен."""
    global _proc
    with _proc_lock:
        if _proc is None:
            try:
                import psutil

                _proc = psutil.Process()
            except Exception:
                _proc = False
        return _proc or None


def _cpu_ms():
    proc = _process()
    if proc is None:
        return None
    try:
        times = proc.cpu_times()
        return round((times.user + times.system) * 1000.0, 1)
    except Exception:
        return None


def _rss_mb():
    proc = _process()
    if proc is None:
        return None
    try:
        return round(proc.memory_info().rss / (1024.0 * 1024.0), 1)
    except Exception:
        return None


class Timeline:
    """Метки одного хода. Потокобезопасен: mark() зовут из tee/энджина."""

    __slots__ = ("enabled", "t0", "_marks", "_lock", "_chunks", "_cpu", "_rss")

    def __init__(self, t0=None, *, enabled=True):
        self.enabled = bool(enabled)
        self.t0 = time.perf_counter() if t0 is None else float(t0)
        self._marks: dict[str, float] = {}
        self._lock = threading.Lock()
        self._chunks = 0
        self._cpu = _cpu_ms() if self.enabled else None
        self._rss = _rss_mb() if self.enabled else None

    def mark(self, name: str) -> None:
        """Первое срабатывание метки — остальные игнорируются."""
        if not self.enabled:
            return
        elapsed = round((time.perf_counter() - self.t0) * 1000.0, 1)
        with self._lock:
            self._marks.setdefault(name, elapsed)

    def count_chunk(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._chunks += 1

    def durations(self) -> dict:
        with self._lock:
            return dict(self._marks)

    def finish(self, *, cancelled=False, backend="") -> dict:
        """Закрывает ход: считает total/CPU/RSS, кладёт в кольцо и пишет журнал."""
        if not self.enabled:
            return {}
        elapsed = round((time.perf_counter() - self.t0) * 1000.0, 1)
        with self._lock:
            marks = dict(self._marks)
            chunks = self._chunks
        cpu = _cpu_ms()
        rss = _rss_mb()
        record = {
            "chunk_ms": marks.get("first_chunk"),
            "safe_ms": marks.get("first_safe"),
            "pcm_ms": marks.get("first_pcm"),
            "audio_ms": marks.get("first_audio"),
            "total_ms": elapsed,
            "chunks": chunks,
            "cancelled": bool(cancelled),
            "backend": backend or "",
            "cpu_ms": None if cpu is None or self._cpu is None
            else round(cpu - self._cpu, 1),
            "rss_delta_mb": None if rss is None or self._rss is None
            else round(rss - self._rss, 1),
        }
        with _ring_lock:
            _ring.append(record)
        log.info(
            "tts_metrics: chunk=%s safe=%s pcm=%s audio=%s total=%s ms | "
            "chunks=%d backend=%s | cpu_delta=%s ms rss_delta=%s MB | cancelled=%s",
            record["chunk_ms"], record["safe_ms"], record["pcm_ms"],
            record["audio_ms"], record["total_ms"], record["chunks"],
            record["backend"] or "-", record["cpu_ms"],
            record["rss_delta_mb"], record["cancelled"],
        )
        return record


def _p95(values: list[float]) -> float:
    """Ближайший ранг: 95-й перцентиль по отсортированной выборке."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 1)
    index = int(round(0.95 * (len(ordered) - 1)))
    return round(ordered[max(0, min(index, len(ordered) - 1))], 1)


def summary(limit: int = 0) -> dict:
    """Сводка по последним ходам: p50/p95 на каждую метку, число отмен."""
    with _ring_lock:
        items = list(_ring)
    if limit and limit > 0:
        items = items[-int(limit):]
    result: dict = {"turns": len(items)}
    for key in ("chunk_ms", "safe_ms", "pcm_ms", "audio_ms", "total_ms"):
        values = [float(item[key]) for item in items if item.get(key) is not None]
        if values:
            result[key] = {
                "n": len(values),
                "p50": round(statistics.median(values), 1),
                "p95": _p95(values),
            }
    result["cancelled"] = sum(1 for item in items if item.get("cancelled"))
    return result


def recent() -> list[dict]:
    """Копия кольца для тестов и диагностики (без текста — его тут нет)."""
    with _ring_lock:
        return [dict(item) for item in _ring]


def reset() -> None:
    """Очистить кольцо (тесты, ручной сброс baseline)."""
    with _ring_lock:
        _ring.clear()
