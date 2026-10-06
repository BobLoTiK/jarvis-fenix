"""Сборка Феникс.exe (лёгкий лаунчер).

Собирает launcher.py в один exe с иконкой. Exe запускает pythonw -m jarvis
из папки проекта. Требует установленный Python на машине.

Запуск:
    python scripts/build_exe.py

Результат:
    dist/Феникс.exe       — исходник от PyInstaller
    Феникс.exe            — копия в корне проекта

ВАЖНО: иконка должна существовать: jarvis/icon.ico.
Если её нет — сначала запусти: python scripts/make_icon.py
"""

import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ICON = BASE / "jarvis" / "icon.ico"
EXE_NAME = "Феникс"


def ensure_icon() -> None:
    """Если иконки нет — генерирует её через make_icon.py."""
    if ICON.exists():
        print(f"Иконка: {ICON}")
        return

    print("Иконка не найдена — генерирую...")
    make_icon = BASE / "scripts" / "make_icon.py"
    if not make_icon.exists():
        print("ОШИБКА: scripts/make_icon.py не найден.")
        sys.exit(1)

    subprocess.run([sys.executable, str(make_icon)], check=True)

    if not ICON.exists():
        print(f"ОШИБКА: иконка не создалась: {ICON}")
        sys.exit(1)


def build() -> None:
    ensure_icon()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noconsole",
        "--clean",
        "--noconfirm",
        "--name", EXE_NAME,
        "--icon", str(ICON),
        "--distpath", str(BASE / "dist"),
        "--workpath", str(BASE / "build"),
        "--specpath", str(BASE / "build"),
        str(BASE / "launcher.py"),
    ]

    print("PyInstaller:", " ".join(cmd))
    subprocess.run(cmd, check=True)

    src = BASE / "dist" / f"{EXE_NAME}.exe"
    dst = BASE / f"{EXE_NAME}.exe"

    if not src.exists():
        print(f"ОШИБКА: PyInstaller не собрал {src}")
        sys.exit(1)

    dst.write_bytes(src.read_bytes())
    print(f"Готово: {dst}")
    print(f"Размер: {dst.stat().st_size / 1024 / 1024:.1f} МБ")


if __name__ == "__main__":
    build()