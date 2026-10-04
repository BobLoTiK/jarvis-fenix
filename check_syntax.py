"""Проверяет синтаксис всех .py файлов в проекте."""
import ast
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent

# Папки, где ищем .py
TARGETS = [
    BASE / "jarvis",
    BASE / "scripts",
    BASE,  # корень: launcher.py, check_syntax.py
]

# Исключения
SKIP_DIRS = {"__pycache__", ".venv", "venv", ".git", "models", "voices", "logs"}
SKIP_FILES = set()

files = []
for t in TARGETS:
    if not t.exists():
        continue
    if t == BASE:
        # В корне — только файлы верхнего уровня
        files.extend(f for f in t.glob("*.py") if f.name not in SKIP_FILES)
    else:
        for f in t.rglob("*.py"):
            if any(part in SKIP_DIRS for part in f.parts):
                continue
            if f.name in SKIP_FILES:
                continue
            files.append(f)

files = sorted(set(files))

failed = 0
for f in files:
    try:
        ast.parse(f.read_text(encoding="utf-8"))
        rel = f.relative_to(BASE)
        print(f"OK   {rel}")
    except SyntaxError as e:
        failed += 1
        rel = f.relative_to(BASE) if f.is_relative_to(BASE) else f
        print(f"FAIL {rel}: {e}")

print()
if failed:
    print(f"Ошибок: {failed}")
    sys.exit(1)
else:
    print(f"Все {len(files)} файлов в порядке.")