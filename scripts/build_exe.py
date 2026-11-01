"""Сборка Феникс.exe (лёгкий лаунчер).

Собирает launcher.py в один exe с иконкой. Exe запускает pythonw -m jarvis
из папки проекта. Требует установленный Python на машине.

Запуск:
    python scripts/build_exe.py

Результат:
    dist/Феникс.exe       — исходник от PyInstaller
    Феникс.exe            — копия в корне проекта

Иконка jarvis/icon.ico обновляется из актуального фирменного PNG через make_icon.py.
"""

import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ICON = BASE / "jarvis" / "icon.ico"
EXE_NAME = "Феникс"
PYTHON_PACKAGE = "jarvis"


def load_version() -> str:
    """Версия приложения из jarvis/__init__.py (единственный источник правды)."""
    text = (BASE / PYTHON_PACKAGE / "__init__.py").read_text(encoding="utf-8")
    found = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not found:
        raise SystemExit("ОШИБКА: в jarvis/__init__.py не найден __version__")
    return found.group(1)


def version_tuple(version: str) -> tuple[int, int, int, int]:
    parts = [int(part) for part in re.findall(r"\d+", version)[:4]]
    parts += [0] * (4 - len(parts))
    return parts[0], parts[1], parts[2], parts[3]


def make_version_file(version: str) -> str:
    """Ресурс версии для PyInstaller (--version-file).

    Без него «Свойства → Подробно» у Феникс.exe пустые: нет ни версии, ни
    названия продукта. Пользователь видит безымянный exe, а эвристики
    антивирусов — файл без метаданных.
    """
    a, b, c, d = version_tuple(version)
    return f'''VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({a}, {b}, {c}, {d}),
    prodvers=({a}, {b}, {c}, {d}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'Феникс'),
        StringStruct('FileDescription', 'Феникс — голосовой ассистент'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', 'Феникс'),
        StringStruct('OriginalFilename', 'Феникс.exe'),
        StringStruct('ProductName', 'Феникс'),
        StringStruct('ProductVersion', '{version}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
'''


def ensure_icon() -> None:
    """Обновляет иконку через make_icon.py из актуального бренд-ресурса."""
    print("Обновляю иконку из фирменного master PNG...")
    make_icon = BASE / "scripts" / "make_icon.py"
    if not make_icon.exists():
        print("ОШИБКА: scripts/make_icon.py не найден.")
        sys.exit(1)

    subprocess.run([sys.executable, str(make_icon)], check=True)

    if not ICON.exists():
        print(f"ОШИБКА: иконка не создалась: {ICON}")
        sys.exit(1)


def check_bootstrap_ui() -> None:
    """PyInstaller's Tk hook bundles Tcl/Tk; verify the builder includes it."""
    try:
        import tkinter
        tkinter.Tcl().eval("info patchlevel")
    except Exception as exc:
        raise RuntimeError("Для сборки нужен Python с Tcl/Tk. В установщике Python включи Tcl/Tk and IDLE.") from exc


def build() -> None:
    check_bootstrap_ui()
    ensure_icon()

    version = load_version()
    version_file = BASE / "build" / "version_info.txt"
    version_file.parent.mkdir(parents=True, exist_ok=True)
    version_file.write_text(make_version_file(version), encoding="utf-8")
    print(f"Ресурс версии: {version} → {version_file}")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noconsole",
        "--clean",
        "--noconfirm",
        "--name", EXE_NAME,
        "--icon", str(ICON),
        "--version-file", str(version_file),
        "--distpath", str(BASE / "dist"),
        "--workpath", str(BASE / "build"),
        "--specpath", str(BASE / "build"),
        str(BASE / "launcher.py"),
    ]

    print("PyInstaller:", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=str(BASE))

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