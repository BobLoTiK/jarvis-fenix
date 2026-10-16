"""Полная сборка Феникса: Феникс.exe + Феникс_Setup.exe — одной командой.

Шаги:
    1. scripts\\make_icon.py             — jarvis\\icon.ico (из актуального PNG)
    2. scripts\\make_installer_images.py — BMP-баннеры для Inno Setup
    3. scripts\\build_exe.py             — Феникс.exe (PyInstaller)
    4. release_payload.py                — чистая поставка + manifest
    5. ISCC.exe installer.iss            — dist\\Феникс_Setup.exe

Запуск:
    python scripts\\build_setup.py
    python scripts\\build_setup.py --check             (проверить ресурсы без сборки)
    python scripts\\build_setup.py --run               (сразу запустить установщик)
    python scripts\\build_setup.py --version 1.0.2    (версия установщика)

Требуется:
    - PyInstaller в текущем Python (pip install -r requirements-dev.txt)
    - Pillow — для баннеров установщика
    - Inno Setup 6: https://jrsoftware.org/isdl.php
      ISCC.exe ищется в PATH, затем в стандартных папках установки.

Версия:
    --version переопределяет MyAppVersion в installer.iss (в ISCC уходит
    /DMyAppVersion). CI берёт версию из тега: релиз v1.0.2 → «1.0.2».
    Без флага используется значение из installer.iss.

Результат:
    dist\\Феникс_Setup.exe — установщик (ставит в C:\\ProgramData\\Phoenix)
"""

import re
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Direct execution from any cwd, without importing the runtime/audio stack.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = Path(__file__).resolve().parent.parent
SCRIPTS = BASE / "scripts"
ICON = BASE / "jarvis" / "icon.ico"
PAYLOAD = BASE / "build" / "release-payload"
ISS = BASE / "installer.iss"
SETUP_EXE = BASE / "dist" / "Феникс_Setup.exe"

# Где искать ISCC.exe, если его нет в PATH
ISCC_SEARCH_PATHS = [
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]

TOTAL_STEPS = 5


def step(num: int, text: str) -> None:
    print()
    print("=" * 60)
    print(f"[{num}/{TOTAL_STEPS}] {text}")
    print("=" * 60)


def run(cmd: list[str]) -> None:
    """Запускает команду, падая с понятной ошибкой."""
    print(">", " ".join(str(c) for c in cmd))
    try:
        result = subprocess.run(cmd, cwd=str(BASE))
    except FileNotFoundError as exc:
        print(f"ОШИБКА: не найдена команда {cmd[0]!r}: {exc}")
        sys.exit(1)

    if result.returncode != 0:
        print(f"ОШИБКА: команда завершилась с кодом {result.returncode}")
        sys.exit(1)


def include_script(name: str) -> None:
    """Запускает scripts/<name> текущим интерпретатором из корня проекта."""
    path = SCRIPTS / name
    if not path.exists():
        print(f"ОШИБКА: не найден скрипт {path}")
        sys.exit(1)
    run([sys.executable, str(path)])


def find_iscc() -> str:
    """Ищет ISCC.exe: INNO_SETUP → PATH → стандартные папки."""
    override = os.environ.get("INNO_SETUP")
    if override:
        candidate = Path(override)
        if candidate.is_dir():
            candidate /= "ISCC.exe"
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("ISCC")
    if found:
        return found

    for path in ISCC_SEARCH_PATHS:
        if Path(path).exists():
            return path

    print("ОШИБКА: не найден ISCC.exe (компилятор Inno Setup 6).")
    print()
    print("Что делать:")
    print("  1. Скачай Inno Setup: https://jrsoftware.org/isdl.php")
    print("  2. Установи (по умолчанию — C:\\Program Files (x86)\\Inno Setup 6)")
    print("  3. Запусти этот скрипт снова")
    sys.exit(1)


def parse_version(argv: list[str]) -> str | None:
    """Версия из `--version X` / `--version=X` (уходит в ISCC как /DMyAppVersion)."""
    for i, arg in enumerate(argv):
        if arg == "--version" and i + 1 < len(argv):
            return argv[i + 1].strip()
        if arg.startswith("--version="):
            return arg.split("=", 1)[1].strip()
    return None


def validate_version(version):
    if version is not None and not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?",version):
        raise ValueError("Версия должна выглядеть как 1.0.2 или 1.0.2-ci.1")
    return version


def main() -> int:
    try:
        version = validate_version(parse_version(sys.argv))
        if any(arg in ('--version','--version=') for arg in sys.argv) and not version:
            raise ValueError("После --version требуется значение")
        from scripts.release_payload import collect_payload, stage_payload
        files = collect_payload(BASE, include_exe=False)
        if not ISS.is_file():
            raise ValueError(f"Missing installer script: {ISS}")
    except (ValueError, OSError) as exc:
        print(f"ОШИБКА preflight: {exc}")
        return 1
    if '--check' in sys.argv:
        print(f"Preflight OK: {len(files)} public files; launcher not compiled, Inno not run.")
        return 0
    if sys.platform != 'win32':
        print("Сборка EXE/Setup требует Windows. Для проверки: --check")
        return 1

    print("Феникс — сборка установщика")
    print(f"Корень проекта: {BASE}")
    if version:
        print(f"Версия (--version): {version}")

    if not ISS.exists():
        print(f"ОШИБКА: не найден {ISS}")
        return 1

    # 1. Иконка
    step(1, "Иконка jarvis\\icon.ico")
    include_script("make_icon.py")

    # Version shown on the banner must match the requested release version.
    step(2, "Баннеры установщика")
    banner_cmd = [sys.executable, str(SCRIPTS / "make_installer_images.py")]
    if version:
        banner_cmd.extend(["--version", version])
    run(banner_cmd)

    step(3, "Сборка Феникс.exe (PyInstaller)")
    include_script("build_exe.py")

    step(4, "Чистый payload и SHA-256 manifest (без данных машины сборщика)")
    staged = stage_payload(BASE, PAYLOAD)
    print(f"Подготовлено {len(staged)} файлов: {PAYLOAD}")

    # 5. Установщик (Inno Setup)
    step(5, "Компиляция установщика (Inno Setup)")
    iscc = find_iscc()
    print(f"ISCC: {iscc}")
    cmd: list[str] = [iscc, f"/DPayloadDir={PAYLOAD}"]
    if version:
        print(f"Версия установщика: {version} (/DMyAppVersion)")
        cmd.append(f"/DMyAppVersion={version}")
    cmd.append(str(ISS))
    SETUP_EXE.unlink(missing_ok=True)
    run(cmd)

    if not SETUP_EXE.exists():
        print(f"ОШИБКА: ISCC не создал {SETUP_EXE}")
        return 1

    print()
    print("=" * 60)
    print("ГОТОВО")
    print("=" * 60)
    print(f"Установщик: {SETUP_EXE}")
    print(f"Размер:     {SETUP_EXE.stat().st_size / 1024 / 1024:.1f} МБ")
    if version:
        print(f"Версия:     {version}")
    print()
    print("Запусти его — Феникс встанет в C:\\ProgramData\\Phoenix.")
    print("Первый запуск ярлыка скачает зависимости и Vosk-модель.")

    if "--run" in sys.argv:
        print()
        print("Запускаю установщик...")
        subprocess.Popen([str(SETUP_EXE)])

    return 0


if __name__ == "__main__":
    sys.exit(main())
