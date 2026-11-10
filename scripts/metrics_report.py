"""Сводка `tts_metrics` из журнала: p50/p95 без запуска приложения.

Зачем: baseline R1 снимается на живом прогоне, а сравнивать прогоны удобно по
одной команде. Скрипт читает строки, которые пишет `jarvis.audio_metrics`
(текст команд и ответов там не появляется), и печатает медианы и p95 по
ступеням конвейера плюс производные задержки: постфильтр, синтез, старт плеера.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from pathlib import Path

FIELDS = ("chunk", "safe", "pcm", "audio", "total")

_LINE_RE = re.compile(
    r"tts_metrics: chunk=(?P<chunk>[0-9.]+|None) safe=(?P<safe>[0-9.]+|None) "
    r"pcm=(?P<pcm>[0-9.]+|None) audio=(?P<audio>[0-9.]+|None) "
    r"total=(?P<total>[0-9.]+|None) ms \| chunks=(?P<chunks>\d+) "
    r"backend=(?P<backend>\S*)"
)


def _number(value: str):
    return None if value == "None" else float(value)


def parse_line(line: str) -> dict | None:
    """Одна строка журнала → запись или None, если это не tts_metrics."""
    match = _LINE_RE.search(line)
    if match is None:
        return None
    record = {field: _number(match.group(field)) for field in FIELDS}
    record["chunks"] = int(match.group("chunks"))
    record["backend"] = match.group("backend")
    return record


def parse_lines(text: str) -> list[dict]:
    records = []
    for line in text.splitlines():
        record = parse_line(line)
        if record is not None:
            records.append(record)
    return records


def percentile(values: list[float], share: float) -> float:
    """Ближайший ранг, как в audio_metrics._p95: без интерполяции."""
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(share * len(ordered)) - 1))
    return ordered[index]


def summarize(records: list[dict]) -> dict:
    result: dict[str, dict] = {}
    for field in FIELDS:
        values = [record[field] for record in records if record[field] is not None]
        if not values:
            result[field] = {"n": 0}
            continue
        result[field] = {
            "n": len(values),
            "p50": round(percentile(values, 0.50), 1),
            "p95": round(percentile(values, 0.95), 1),
            "max": round(max(values), 1),
        }
    for name, left, right in (
        ("guard", "chunk", "safe"),
        ("synth", "safe", "pcm"),
        ("player", "pcm", "audio"),
    ):
        deltas = [
            record[right] - record[left]
            for record in records
            if record[left] is not None and record[right] is not None
        ]
        if not deltas:
            result[name] = {"n": 0}
            continue
        result[name] = {
            "n": len(deltas),
            "p50": round(percentile(deltas, 0.50), 1),
            "p95": round(percentile(deltas, 0.95), 1),
            "max": round(max(deltas), 1),
        }
    return result


def _format_table(title: str, summary: dict) -> list[str]:
    lines = [title]
    for name, stats in summary.items():
        if not stats.get("n"):
            lines.append(f"  {name:<8} нет данных")
            continue
        lines.append(
            "  {name:<8} n={n:<3} p50={p50:>8.1f} p95={p95:>8.1f} max={max:>8.1f}".format(
                name=name, **stats
            )
        )
    return lines


def default_log() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidate = Path(appdata) / "Phoenix" / "logs" / "jarvis.log"
        if candidate.exists():
            return candidate
    return Path("logs") / "jarvis.log"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--log", type=Path, default=None, help="путь к jarvis.log")
    parser.add_argument("--last", type=int, default=0, help="последние N записей (0 — все)")
    parser.add_argument("--json", action="store_true", help="вывести JSON")
    args = parser.parse_args(argv)

    path = args.log or default_log()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        print(f"не читается журнал {path}: {error}", file=sys.stderr)
        return 1

    records = parse_lines(text)
    if args.last > 0:
        records = records[-args.last:]
    if not records:
        print(f"в {path} нет строк tts_metrics (метрики включены? metrics_enabled)")
        return 1

    streaming = [record for record in records if record["chunks"] > 1]
    single = [record for record in records if record["chunks"] <= 1]
    summary = summarize(records)

    if args.json:
        print(json.dumps(
            {
                "log": str(path),
                "turns": len(records),
                "all": summary,
                "streaming": summarize(streaming),
                "single": summarize(single),
            },
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    print(f"журнал: {path}")
    print(f"записей: {len(records)} (стрим: {len(streaming)}, одна реплика: {len(single)})")
    for line in _format_table("все записи, мс:", summary):
        print(line)
    if streaming:
        for line in _format_table("только стрим (chunks>1), мс:", summarize(streaming)):
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
