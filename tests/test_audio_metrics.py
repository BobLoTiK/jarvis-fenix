"""Метрики TTS-конвейера: чистая логика, без аудиоустройств и сети."""

import threading
import time

import pytest

from jarvis import audio_metrics


def test_marks_keep_first_value():
    audio_metrics.reset()
    tl = audio_metrics.Timeline()
    tl.mark("first_chunk")
    first = tl.durations()["first_chunk"]
    time.sleep(0.02)
    tl.mark("first_chunk")
    assert tl.durations()["first_chunk"] == first
    assert first >= 0


def test_finish_records_durations_without_text():
    audio_metrics.reset()
    tl = audio_metrics.Timeline()
    for name in audio_metrics.MARK_NAMES:
        tl.mark(name)
    tl.count_chunk()
    tl.count_chunk()
    record = tl.finish(cancelled=False, backend="piper")

    assert record["chunks"] == 2
    assert record["backend"] == "piper"
    assert record["cancelled"] is False
    assert record["total_ms"] >= 0
    for key in ("chunk_ms", "safe_ms", "pcm_ms", "audio_ms"):
        assert record[key] is not None
    # Никакого текста в метриках: ключи — только числа/флаги/имя движка.
    assert all("text" not in key for key in record)
    assert all(isinstance(value, (int, float, bool, str, type(None)))
               for value in record.values())


def test_summary_median_and_p95():
    audio_metrics.reset()
    for total in (1.0, 2.0, 3.0, 4.0):
        tl = audio_metrics.Timeline(t0=time.perf_counter() - total)
        tl.mark("first_chunk")
        tl.finish()
    summary = audio_metrics.summary()
    assert summary["turns"] == 4
    assert summary["chunk_ms"]["n"] == 4
    # p50 — медиана, p95 — ближайший ранг: 4 значения → последнее.
    assert summary["chunk_ms"]["p50"] == pytest.approx(2500.0, rel=0.2)
    assert summary["chunk_ms"]["p95"] >= summary["chunk_ms"]["p50"]


def test_disabled_timeline_is_noop():
    audio_metrics.reset()
    tl = audio_metrics.Timeline(enabled=False)
    tl.mark("first_chunk")
    tl.count_chunk()
    assert tl.durations() == {}
    assert tl.finish() == {}
    assert audio_metrics.summary()["turns"] == 0


def test_marks_from_threads_are_safe():
    audio_metrics.reset()
    tl = audio_metrics.Timeline()
    errors = []

    def worker():
        try:
            tl.mark("first_chunk")
            tl.count_chunk()
        except Exception as exc:  # pragma: no cover — сообщаем, а не глотаем
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert not errors
    assert set(tl.durations()) == {"first_chunk"}
    record = tl.finish()
    assert record["chunks"] == 16


def test_ring_is_capped():
    audio_metrics.reset()
    for _ in range(audio_metrics.MAX_TURNS + 5):
        audio_metrics.Timeline().finish()
    assert len(audio_metrics.recent()) == audio_metrics.MAX_TURNS


def test_p95_nearest_rank():
    assert audio_metrics._p95([5]) == 5.0
    assert audio_metrics._p95([1, 2, 3, 4]) == 4.0
    assert audio_metrics._p95([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) == 10.0
