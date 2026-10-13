"""Полная сборка Феникса: Феникс.exe + Феникс_Setup.exe — одной командой.

Шаги:
    1. scripts\\make_icon.py             — jarvis\\icon.ico (если ещё нет)
    2. scripts\\make_installer_images.py — BMP-баннеры для Inno Setup
    3. scripts\\check_caps.py            — system_caps.json (если ещё нет)
    4. scripts\\build_exe.py             — Феникс.exe (PyInstaller)
    5. ISCC.exe installer.iss            — dist\\Феникс_Setup.exe

Запуск:
    python scripts\\build_setup.py
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

import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SCRIPTS = BASE / "scripts"
ICON = BASE / "jarvis" / "icon.ico"
CAPS = BASE / "system_caps.json"
ISS = BASE / "installer.iss"
SETUP_EXE = BASE / "dist" / "Феникс_Setup.exe"

# Где искать ISCC.exe, если его нет в PATH
ISCC_SEARCH_PATHS = [
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
    r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
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
    """Ищет ISCC.exe: PATH → INNO_SETUP → стандартные папки."""
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


def caps_available() -> bool:
    """Есть ли модули, нужные scripts/check_caps.py (pycaw + sbc).

    В CI их нет — тогда шаг с system_caps.json просто пропускается.
    Файл необязателен: в installer.iss он с skipifsourcedoesntexist,
    а код без него считает громкость/яркость недоступными.
    """
    import importlib.util

    return all(
        importlib.util.find_spec(name)
        for name in ("pycaw", "screen_brightness_control")
    )


def main() -> int:
    version = parse_version(sys.argv)

    print("Феникс — сборка установщика")
    print(f"Корень проекта: {BASE}")
    if version:
        print(f"Версия (--version): {version}")

    if not ISS.exists():
        print(f"ОШИБКА: не найден {ISS}")
        return 1

    # 1. Иконка
    step(1, "Иконка jarvis\\icon.ico")
    if ICON.exists():
        print(f"OK: уже есть ({ICON.stat().st_size / 1024:.1f} КБ)")
    else:
        include_script("make_icon.py")

    # 2. Картинки для Inno Setup
    step(2, "Баннеры установщика (installer_banner.bmp, installer_small.bmp)")
    include_script("make_installer_images.py")

    # 3. Возможности системы — system_caps.json читают actions.py и gui.py
    step(3, "Возможности системы (system_caps.json)")
    if CAPS.exists():
        print(f"OK: уже есть ({CAPS})")
    elif not caps_available():
        print("ПРОПУСК: нет pycaw / screen-brightness-control (обычно это CI).")
        print("Файл необязателен: в installer.iss он с skipifsourcedoesntexist,")
        print("а код без него считает громкость/яркость недоступными.")
    else:
        print("Нет файла — генерирую...")
        try:
            include_script("check_caps.py")
        except SystemExit as exc:
            # Не критично: в installer.iss у файла skipifsourcedoesntexist
            print(f"ВНИМАНИЕ: check_caps.py завершился с кодом {exc.code}")
            print("Установщик соберётся и без system_caps.json")
        if not CAPS.exists():
            print("ВНИМАНИЕ: system_caps.json не создан — собираю без него")

    # 4. Феникс.exe (PyInstaller)
    step(4, "Сборка Феникс.exe (PyInstaller)")
    include_script("build_exe.py")

    # 5. Установщик (Inno Setup)
    step(5, "Компиляция установщика (Inno Setup)")
    iscc = find_iscc()
    print(f"ISCC: {iscc}")
    cmd: list[str] = [iscc]
    if version:
        print(f"Версия установщика: {version} (/DMyAppVersion)")
        cmd.append(f"/DMyAppVersion={version}")
    cmd.append(str(ISS))
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
