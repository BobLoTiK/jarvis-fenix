"""Сводка tts_metrics: разбор строк и проценты, без запуска приложения."""

import pytest

from scripts import metrics_report as report

LINE = (
    "2026-11-11 02:28:27,411 jarvis.metrics INFO tts_metrics: chunk=1374.9 "
    "safe=2090.7 pcm=2209.2 audio=2227.1 total=8938.1 ms | chunks=40 "
    "backend=piper | cpu_delta=2750.0 ms rss_delta=39.1 MB | cancelled=False"
)
SINGLE = (
    "2026-11-11 02:21:24,432 jarvis.metrics INFO tts_metrics: chunk=None "
    "safe=None pcm=143.5 audio=220.1 total=2474.6 ms | chunks=0 backend=piper "
    "| cpu_delta=765.6 ms rss_delta=59.2 MB | cancelled=False"
)


def test_parse_line_extracts_numbers_and_none():
    record = report.parse_line(LINE)
    assert record["chunk"] == 1374.9
    assert record["total"] == 8938.1
    assert record["chunks"] == 40
    assert record["backend"] == "piper"

    empty = report.parse_line(SINGLE)
    assert empty["chunk"] is None
    assert empty["pcm"] == 143.5
    assert empty["chunks"] == 0


def test_parse_line_ignores_other_log_lines():
    assert report.parse_line("2026-11-11 jarvis.stt INFO barge: rms=0") is None


def test_summary_percentiles_and_derived():
    records = report.parse_lines("\n".join([LINE, SINGLE]))
    summary = report.summarize(records)

    assert summary["pcm"]["n"] == 2
    # Ближайший ранг: для двух значений p50 — нижнее, p95 — верхнее.
    assert summary["pcm"]["p50"] == pytest.approx(143.5, abs=0.2)
    assert summary["pcm"]["p95"] == pytest.approx(2209.2, abs=0.2)
    # Производные считаются только по записям, где обе метки есть.
    assert summary["guard"] == {"n": 1, "p50": 715.8, "p95": 715.8, "max": 715.8}
    assert summary["synth"]["n"] == 1
    assert summary["player"]["n"] == 2


def test_percentile_nearest_rank():
    assert report.percentile([5], 0.95) == 5
    assert report.percentile([1, 2, 3, 4], 0.5) == 2
    assert report.percentile([1, 2, 3, 4], 0.95) == 4


def test_cli_prints_table(tmp_path, capsys):
    log = tmp_path / "jarvis.log"
    log.write_text(
        LINE + "\n" + SINGLE + "\n",
        encoding="utf-8",
    )
    assert report.main(["--log", str(log)]) == 0
    out = capsys.readouterr().out
    assert "записей: 2" in out
    assert "стрим: 1" in out
    assert "p50" in out


def test_cli_json(tmp_path, capsys):
    log = tmp_path / "jarvis.log"
    log.write_text(LINE + "\n", encoding="utf-8")
    assert report.main(["--log", str(log), "--json"]) == 0
    import json

    data = json.loads(capsys.readouterr().out)
    assert data["turns"] == 1
    assert data["streaming"]["chunk"]["n"] == 1


def test_cli_missing_metrics(tmp_path, capsys):
    log = tmp_path / "jarvis.log"
    log.write_text("ничего полезного\n", encoding="utf-8")
    assert report.main(["--log", str(log)]) == 1
    assert "нет строк tts_metrics" in capsys.readouterr().out
