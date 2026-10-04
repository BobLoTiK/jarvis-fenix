"""Проверяет синтаксис всех .py файлов в папке jarvis/."""
import ast
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
PKG = BASE / "jarvis"

if not PKG.exists():
    print(f"Папка {PKG} не найдена!")
    sys.exit(1)

files = sorted(PKG.glob("*.py"))
if not files:
    print("Нет .py файлов для проверки.")
    sys.exit(1)

failed = 0
for f in files:
    try:
        ast.parse(f.read_text(encoding="utf-8"))
        print(f"OK   {f.name}")
    except SyntaxError as e:
        failed += 1
        print(f"FAIL {f.name}: {e}")

print()
if failed:
    print(f"Ошибок: {failed}")
    sys.exit(1)
else:
    print(f"Все {len(files)} файлов в порядке.")