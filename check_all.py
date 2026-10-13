"""Единый прогон всех проверок Феникса — движок для check_all.bat.

Шаги (по порядку — от быстрого к медленному):
    1. check_syntax.py          — синтаксис всех .py
    2. pytest tests/            — юнит-тесты
    3. tests/test_intents.py    — интент-тесты (39 сценариев)
    4. tests/stress_intents.py  — стресс-тест (100 ситуаций)

Печатает компактную сводку: при успехе — одну итоговую строку «ВСЁ ОТЛИЧНО»,
при провале — какой именно шаг упал и что конкретно сломалось. Полные логи
складываются в logs/check_all/.

Запуск: python check_all.py   (или просто check_all.bat)
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

# UTF-8 для stdout/stderr — иначе на Windows (cp1251) падает печать
# русских букв и «ёлочек» в разборе ошибок.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parent
LOGS = BASE / "logs" / "check_all"
LOGS.mkdir(parents=True, exist_ok=True)

# Подпроцессы — тоже UTF-8: pytest/harness печатают русские буквы,
# а по умолчанию в pipe на Windows уезжает локальная кодировка.
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

# Защита от вечного зависания (LLM/сеть/железо).
TIMEOUT = 1800

_TS = re.compile(r"^\d{4}-\d{2}-\d{2} [\d:,]+ \w+ ")


def _lines(text: str) -> list[str]:
    return [_TS.sub("", line).rstrip() for line in text.splitlines()]


def summarize_syntax(text: str) -> list[str]:
    lines = _lines(text)
    bad = [l for l in lines if l.startswith("FAIL")]
    tail = [l for l in lines if l.startswith("Ошибок")]
    return (bad + tail)[:20]


def summarize_pytest(text: str) -> list[str]:
    lines = [l for l in _lines(text) if l.strip()]
    out = [l for l in lines if l.startswith(("FAILED", "ERROR"))][:20]
    tail = [l for l in lines[-3:] if re.search(r"\b(passed|failed|error)", l)]
    if tail:
        out.append("итог: " + tail[-1].strip())
    return out


def summarize_harness(text: str) -> list[str]:
    """Для test_intents.py / stress_intents.py: строка ИТОГ + блок ПРОВАЛЫ."""
    lines = _lines(text)
    out = [l.strip() for l in lines if "ИТОГ:" in l]
    start = next((i for i, l in enumerate(lines) if "ПРОВАЛЫ" in l), None)
    if start is not None:
        for line in lines[start:]:
            if "Полный лог" in line:
                break
            if line.strip() and "=====" not in line:
                out.append(line)
    return out[:40]


class Step:
    def __init__(self, key: str, title: str, argv: list[str], summarize):
        self.key = key
        self.title = title
        self.argv = argv
        self.summarize = summarize
        self.ok = False
        self.seconds = 0.0
        self.log_path = LOGS / f"{key}.log"
        self.details: list[str] = []


STEPS = [
    Step("syntax", "синтаксис .py", [sys.executable, "check_syntax.py"], summarize_syntax),
    Step("pytest", "юнит-тесты (pytest)", [sys.executable, "-m", "pytest", "tests/", "-q"], summarize_pytest),
    Step("intents", "интент-тесты (39)", [sys.executable, "tests/test_intents.py"], summarize_harness),
    Step("stress", "стресс-тест (100)", [sys.executable, "tests/stress_intents.py"], summarize_harness),
]


def run_step(step: Step, index: int, total: int) -> None:
    label = f"  [{index}/{total}] {step.title:<22}"
    print(f"{label} ... ", end="", flush=True)

    t0 = time.time()
    try:
        proc = subprocess.run(
            step.argv,
            cwd=BASE,
            env=ENV,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        step.ok = proc.returncode == 0
    except subprocess.TimeoutExpired as e:
        output = ((e.stdout or "") if isinstance(e.stdout, str) else "") + \
                 f"\n[таймаут] шаг не завершился за {TIMEOUT} с\n"
        step.ok = False
    except Exception as e:  # noqa: BLE001 — раннер не должен падать сам
        output = f"[ошибка запуска] {type(e).__name__}: {e}\n"
        step.ok = False

    step.seconds = time.time() - t0
    step.log_path.write_text(output, encoding="utf-8", errors="replace")
    if not step.ok:
        step.details = step.summarize(output)

    print(f"{'OK' if step.ok else 'ПРОВАЛ'}  ({step.seconds:.1f} с)")


def main() -> int:
    total = len(STEPS)
    print("=" * 62)
    print(f"  Проверка Феникса — шагов: {total}")
    print("=" * 62)

    for i, step in enumerate(STEPS, 1):
        run_step(step, i, total)

    failed = [s for s in STEPS if not s.ok]
    took = sum(s.seconds for s in STEPS)

    print()
    if failed:
        print("=" * 62)
        print(f"  ЕСТЬ ОШИБКИ — упало шагов: {len(failed)} из {total}")
        print("=" * 62)
        for step in failed:
            print()
            print(f"[{step.key}] {step.title} — что именно упало:")
            if step.details:
                for line in step.details:
                    print(f"    {line}")
            else:
                print("    (в логе нет опознавательных строк — смотри полный лог)")
            print(f"    Полный лог: {step.log_path}")
        print()
        print(f"Полные логи шагов: {LOGS}")
        return 1

    print("=" * 62)
    print(f"  ВСЁ ОТЛИЧНО — {total}/{total} проверок пройдено за {took:.1f} с")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
