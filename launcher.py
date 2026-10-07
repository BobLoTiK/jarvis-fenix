"""Лаунчер Феникса — полный автозапуск.

Что делает при запуске:
    1. Ищет Python 3.10-3.12 (py -3.X, where python, типичные пути).
    2. Если не нашёл — MessageBox: [Скачать Python 3.11] [Отмена].
       Скачивает python-3.11.9-amd64.exe, запускает installer.
    3. Проверяет .venv311. Если нет — создаёт.
    4. Проверяет зависимости (flet, vosk, piper). Если нет — pip install.
    5. Проверяет Vosk-модель. Если нет — скачивает.
    6. Проверяет Ollama (URL + поиск на дисках). Если нет — MessageBox.
    7. Запускает Феникс через .venv311\\Scripts\\pythonw.exe -m jarvis.

Собирается в exe (PyInstaller). Защищён от повторного запуска.
Логи — в logs/launcher.log рядом с exe.
"""

import ctypes
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

# ============================================================
# Константы
# ============================================================

# Local\ вместо Global\ — работает без прав администратора
# (Global\ требует SeCreateGlobalPrivilege).
MUTEX_NAME = "Local\\JarvisPhoenixSingleInstance"
_MUTEX_HANDLE = None

PYTHON_INSTALLER_URL = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
PYTHON_INSTALLER_FILE = "python-3.11.9-amd64.exe"

VOSK_MODEL_NAME = "vosk-model-small-ru-0.22"
VOSK_MODEL_URL = f"https://alphacephei.com/vosk/models/{VOSK_MODEL_NAME}.zip"

OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_DOWNLOAD_PAGE = "https://ollama.com/download"

# Где искать Python, если py launcher не работает
PYTHON_SEARCH_PATHS = [
    r"C:\Python312\python.exe",
    r"C:\Python311\python.exe",
    r"C:\Python310\python.exe",
    r"C:\Program Files\Python312\python.exe",
    r"C:\Program Files\Python311\python.exe",
    r"C:\Program Files\Python310\python.exe",
]

# Где искать Ollama
OLLAMA_SEARCH_PATHS = [
    r"C:\Program Files\Ollama\ollama.exe",
    r"C:\Program Files (x86)\Ollama\ollama.exe",
]

# Какие версии Python подходят
REQUIRED_PY_VERSIONS = ("3.12", "3.11", "3.10")

# MessageBox флаги
MB_OK = 0x00
MB_OKCANCEL = 0x01
MB_YESNO = 0x04
MB_ICONERROR = 0x10
MB_ICONWARNING = 0x30
MB_ICONINFORMATION = 0x40
MB_ICONQUESTION = 0x20

IDYES = 6
IDNO = 7
IDOK = 1
IDCANCEL = 2

# Флаги subprocess
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008


# ============================================================
# MessageBox
# ============================================================

def msg_box(text: str, title: str = "Феникс", flags: int = MB_OK) -> int:
    """Показывает Windows MessageBox. Возвращает ID нажатой кнопки."""
    try:
        return ctypes.windll.user32.MessageBoxW(0, text, title, flags)
    except Exception:
        return 0


def info(text: str, title: str = "Феникс") -> None:
    msg_box(text, title, MB_OK | MB_ICONINFORMATION)


def warn(text: str, title: str = "Феникс") -> None:
    msg_box(text, title, MB_OK | MB_ICONWARNING)


def error(text: str, title: str = "Феникс — ошибка") -> None:
    msg_box(text, title, MB_OK | MB_ICONERROR)


def ask_yes_no(text: str, title: str = "Феникс") -> bool:
    return msg_box(text, title, MB_YESNO | MB_ICONQUESTION) == IDYES


# ============================================================
# Логирование
# ============================================================

def _setup_logging(base_dir: Path) -> Path:
    logs_dir = base_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "launcher.log"

    logger = logging.getLogger("launcher")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    fh.setFormatter(logging.Formatter(
        "%(asctime)s launcher %(levelname)s %(message)s"
    ))
    logger.addHandler(fh)

    return log_file


# ============================================================
# Мьютекс
# ============================================================

def already_running(logger) -> bool:
    global _MUTEX_HANDLE

    if _MUTEX_HANDLE is not None:
        return False

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    last_error = kernel32.GetLastError()

    if last_error == 183:
        if handle:
            kernel32.CloseHandle(handle)
        logger.info("Феникс уже запущен")
        return True

    _MUTEX_HANDLE = handle
    return False


# ============================================================
# Поиск папки проекта
# ============================================================

def find_project_dir(logger) -> Path:
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
    else:
        exe_dir = Path(__file__).resolve().parent

    candidates = [exe_dir, exe_dir.parent, Path.cwd()]
    for cand in candidates:
        if (cand / "jarvis" / "__init__.py").exists():
            logger.info("Проект найден: %s", cand)
            return cand

    logger.error("Не найдена папка с jarvis/ (проверены: %s)",
                 ", ".join(str(c) for c in candidates))
    return exe_dir


# ============================================================
# Python: поиск, скачивание installer
# ============================================================

def _check_python_version(python_exe: str, logger) -> str | None:
    """Возвращает версию ('3.11.9') или None, если не подходит."""
    try:
        result = subprocess.run(
            [python_exe, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            return None
        out = result.stdout.strip() or result.stderr.strip()
        if out.startswith("Python "):
            version = out[7:].strip()
            for req in REQUIRED_PY_VERSIONS:
                if version.startswith(req):
                    return version
        return None
    except Exception:
        return None


def find_python(logger) -> str | None:
    """Ищет Python 3.10-3.12. Возвращает путь к python.exe или None."""
    # 1. py launcher
    for ver in REQUIRED_PY_VERSIONS:
        try:
            result = subprocess.run(
                ["py", f"-{ver}", "-c", "import sys; print(sys.executable)"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=CREATE_NO_WINDOW,
            )
            if result.returncode == 0:
                exe = result.stdout.strip()
                if exe and Path(exe).exists():
                    logger.info("Python %s найден через py: %s", ver, exe)
                    return exe
        except Exception:
            pass

    # 2. where python
    for name in ("python.exe", "python"):
        found = shutil.which(name)
        if found:
            version = _check_python_version(found, logger)
            if version:
                logger.info("Python %s найден в PATH: %s", version, found)
                return found

    # 3. Типичные пути
    for path_str in PYTHON_SEARCH_PATHS:
        p = Path(path_str)
        if p.exists():
            version = _check_python_version(str(p), logger)
            if version:
                logger.info("Python %s найден: %s", version, p)
                return str(p)

    # 4. %LOCALAPPDATA%\Programs\Python\PythonXY
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        for ver in ("312", "311", "310"):
            cand = Path(local_appdata) / "Programs" / "Python" / f"Python{ver}" / "python.exe"
            if cand.exists():
                version = _check_python_version(str(cand), logger)
                if version:
                    logger.info("Python %s найден: %s", version, cand)
                    return str(cand)

    logger.info("Python 3.10-3.12 не найден")
    return None


def download_python_installer(logger) -> Path | None:
    """Скачивает официальный installer Python в temp."""
    temp_dir = Path(os.environ.get("TEMP", "."))
    installer = temp_dir / PYTHON_INSTALLER_FILE

    if installer.exists():
        logger.info("Installer уже есть: %s", installer)
        return installer

    info(
        "Сейчас будет скачан установщик Python 3.11 (~25 МБ).\n\n"
        "После скачивания откроется окно установки — "
        "нажми «Install Now» и дождись завершения.\n\n"
        "Нажми ОК, чтобы начать скачивание.",
        "Феникс — установка Python",
    )

    logger.info("Скачиваю installer: %s", PYTHON_INSTALLER_URL)
    try:
        urllib.request.urlretrieve(PYTHON_INSTALLER_URL, installer)
        logger.info("Installer скачан: %s", installer)
        return installer
    except Exception:
        logger.exception("Не удалось скачать installer Python")
        error(
            "Не удалось скачать Python.\n\n"
            "Проверь интернет или скачай вручную:\n"
            "https://www.python.org/downloads/release/python-3119/\n\n"
            "Логи: logs\\launcher.log",
        )
        return None


def run_python_installer(installer: Path, logger) -> bool:
    """Запускает installer Python. Ждёт завершения."""
    logger.info("Запускаю installer: %s", installer)
    try:
        subprocess.run([str(installer)], check=False)
    except Exception:
        logger.exception("Ошибка запуска installer")
        return False

    logger.info("Installer завершён, ищу Python заново")
    time.sleep(2)
    python = find_python(logger)
    return python is not None


# ============================================================
# Venv: создание
# ============================================================

def find_venv_pythonw(project_dir: Path, logger) -> Path | None:
    candidates = [
        project_dir / ".venv311" / "Scripts" / "pythonw.exe",
        project_dir / ".venv" / "Scripts" / "pythonw.exe",
    ]
    for cand in candidates:
        if cand.exists():
            logger.info("venv найден: %s", cand)
            return cand
    return None


def create_venv(project_dir: Path, python_exe: str, logger) -> bool:
    """Создаёт .venv311 через указанный Python."""
    venv_dir = project_dir / ".venv311"

    if venv_dir.exists():
        logger.info("venv уже существует: %s", venv_dir)
        return True

    info(
        "Создаю виртуальное окружение...\n\n"
        "Это займёт несколько секунд.",
        "Феникс — окружение",
    )

    logger.info("Создаю venv: %s", venv_dir)
    try:
        result = subprocess.run(
            [python_exe, "-m", "venv", str(venv_dir)],
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            logger.error("venv не создан: %s", result.stderr)
            error(
                "Не удалось создать виртуальное окружение.\n\n"
                f"{result.stderr[:500]}\n\n"
                "Логи: logs\\launcher.log",
            )
            return False
        logger.info("venv создан: %s", venv_dir)
        return True
    except Exception:
        logger.exception("Ошибка создания venv")
        error("Не удалось создать окружение. Логи: logs\\launcher.log")
        return False


# ============================================================
# Зависимости: установка
# ============================================================

def check_dependencies(project_dir: Path, logger) -> bool:
    """Проверяет, установлены ли ключевые зависимости в venv."""
    python = project_dir / ".venv311" / "Scripts" / "python.exe"
    if not python.exists():
        return False
    try:
        result = subprocess.run(
            [str(python), "-c", "import flet, vosk; print('ok')"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=CREATE_NO_WINDOW,
        )
        return result.returncode == 0
    except Exception:
        return False


def install_dependencies(project_dir: Path, logger) -> bool:
    """Устанавливает зависимости из requirements.txt."""
    python = project_dir / ".venv311" / "Scripts" / "python.exe"
    req = project_dir / "requirements.txt"

    if not req.exists():
        logger.error("requirements.txt не найден: %s", req)
        error("requirements.txt не найден. Феникс установлен неправильно.")
        return False

    info(
        "Устанавливаю зависимости.\n\n"
        "Это займёт 5–10 минут (flet, vosk, piper, faster-whisper).\n\n"
        "Нажми ОК, чтобы начать. После завершения появится ещё одно окно.",
        "Феникс — установка",
    )

    logger.info("pip install -r requirements.txt")
    try:
        result = subprocess.run(
            [str(python), "-m", "pip", "install", "-r", str(req)],
            cwd=str(project_dir),
        )
        if result.returncode != 0:
            logger.error("pip install упал: returncode=%d", result.returncode)
            error(
                "Не удалось установить зависимости.\n\n"
                "Возможные причины:\n"
                "  - Нет интернета\n"
                "  - Нет Visual C++ Redistributable\n\n"
                "Смотри: logs\\launcher.log",
            )
            return False
        logger.info("Зависимости установлены")
        info("Зависимости установлены. OK", "Феникс")
        return True
    except Exception:
        logger.exception("Ошибка pip install")
        error("Ошибка установки зависимостей. Логи: logs\\launcher.log")
        return False


# ============================================================
# Vosk-модель: проверка, скачивание
# ============================================================

def check_vosk_model(project_dir: Path, logger) -> bool:
    """Проверяет Vosk-модель в ASCII-пути (C:\\ProgramData\\Phoenix\\models)."""
    program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    model_dir = Path(program_data) / "Phoenix" / "models" / VOSK_MODEL_NAME
    ok = model_dir.exists() and (model_dir / "am").exists()
    logger.info("Vosk-модель в %s: %s", model_dir, "есть" if ok else "нет")
    return ok


def download_vosk_model(project_dir: Path, logger) -> bool:
    """Скачивает и распаковывает Vosk-модель в ASCII-путь."""
    program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    safe_models = Path(program_data) / "Phoenix" / "models"

    try:
        safe_models.mkdir(parents=True, exist_ok=True)
    except Exception:
        safe_models = Path(r"C:\Phoenix\models")
        safe_models.mkdir(parents=True, exist_ok=True)

    logger.info("Vosk-модель будет в: %s", safe_models)

    zip_path = safe_models / f"{VOSK_MODEL_NAME}.zip"
    target_dir = safe_models / VOSK_MODEL_NAME

    if target_dir.exists() and (target_dir / "am").exists():
        logger.info("Vosk-модель уже есть: %s", target_dir)
        return True

    info(
        "Скачиваю модель Vosk (~45 МБ) в C:\\ProgramData\\Phoenix\\models.\n\n"
        "Это займёт 1–2 минуты.",
        "Феникс — модель Vosk",
    )

    logger.info("Скачиваю Vosk: %s", VOSK_MODEL_URL)
    try:
        urllib.request.urlretrieve(VOSK_MODEL_URL, zip_path)
        logger.info("Vosk скачан: %s", zip_path)
    except Exception:
        logger.exception("Не удалось скачать Vosk")
        error("Не удалось скачать модель Vosk. Проверь интернет. Смотри logs\\launcher.log")
        return False

    info("Распаковываю модель Vosk...", "Феникс")
    logger.info("Распаковываю Vosk")
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.namelist():
                parts = member.split("/", 1)
                if len(parts) < 2 or not parts[1]:
                    continue
                target = target_dir / parts[1]
                # Защита от Zip Slip: путь должен оставаться внутри target_dir.
                try:
                    resolved = target.resolve()
                    base = target_dir.resolve()
                    if base not in resolved.parents and resolved != base:
                        logger.warning("Zip Slip попытка: %r", member)
                        continue
                except Exception:
                    logger.warning("Не удалось проверить путь: %r", member)
                    continue

                if member.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, open(target, "wb") as dst:
                        dst.write(src.read())
        zip_path.unlink(missing_ok=True)
        logger.info("Vosk распакован: %s", target_dir)
        info("Модель Vosk готова. OK", "Феникс")
        return True
    except Exception:
        logger.exception("Ошибка распаковки Vosk")
        error("Не удалось распаковать модель. Логи: logs\\launcher.log")
        return False


# ============================================================
# Ollama: проверка, поиск
# ============================================================

def check_ollama_running(logger) -> bool:
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/version", timeout=2):
            logger.info("Ollama сервер отвечает")
            return True
    except Exception:
        return False


def find_ollama_exe(logger) -> Path | None:
    found = shutil.which("ollama") or shutil.which("ollama.exe")
    if found:
        logger.info("Ollama в PATH: %s", found)
        return Path(found)

    candidates = [Path(p) for p in OLLAMA_SEARCH_PATHS]
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(Path(local_appdata) / "Programs" / "Ollama" / "ollama.exe")

    for cand in candidates:
        if cand.exists():
            logger.info("Ollama найден: %s", cand)
            return cand
    return None


def handle_ollama(logger) -> None:
    """Проверяет Ollama. Если нет — предлагает поставить."""
    if check_ollama_running(logger):
        return

    ollama_exe = find_ollama_exe(logger)
    if ollama_exe:
        logger.info("Ollama найден, запускаю serve")
        try:
            subprocess.Popen(
                [str(ollama_exe), "serve"],
                creationflags=CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        except Exception:
            logger.exception("Не удалось запустить ollama serve")

    logger.warning("Ollama не найдена")
    reply = msg_box(
        "Ollama не найдена.\n\n"
        "Без неё Феникс работает в УРЕЗАННОМ режиме:\n"
        "  ✓ Команды\n"
        "  ✓ Распознавание речи\n"
        "  ✓ Синтез речи\n"
        "  ✗ Свободный диалог с ИИ\n"
        "  ✗ Разбор сложных фраз\n\n"
        "Поставить Ollama?\n"
        "(откроется ollama.com/download)",
        "Феникс — Ollama",
        MB_YESNO | MB_ICONQUESTION,
    )
    if reply == IDYES:
        try:
            os.startfile(OLLAMA_DOWNLOAD_PAGE)
        except Exception:
            logger.exception("Не удалось открыть ollama.com")


# ============================================================
# Запуск Феникса
# ============================================================

def run_jarvis(project_dir: Path, pythonw: Path, logger) -> None:
    logger.info("Запускаю Феникс: %s -m jarvis", pythonw)
    try:
        proc = subprocess.Popen(
            [str(pythonw), "-m", "jarvis"],
            cwd=str(project_dir),
            creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
            close_fds=True,
        )
        logger.info("Феникс запущен, PID=%d", proc.pid)
    except Exception:
        logger.exception("Не удалось запустить Феникс")
        error("Не удалось запустить Феникс. Логи: logs\\launcher.log")


# ============================================================
# Главная функция
# ============================================================

def main() -> None:
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
    else:
        exe_dir = Path(__file__).resolve().parent

    log_file = _setup_logging(exe_dir)
    logger = logging.getLogger("launcher")

    logger.info("=" * 60)
    logger.info("Лаунчер стартует")
    logger.info("exe: %s", sys.executable)
    logger.info("cwd: %s", os.getcwd())
    logger.info("log: %s", log_file)
    logger.info("=" * 60)

    if already_running(logger):
        info("Феникс уже запущен.\n\nПроверь панель задач или трей.")
        return

    project_dir = find_project_dir(logger)
    if not (project_dir / "jarvis" / "__init__.py").exists():
        error(
            "Не найден пакет jarvis/ рядом с Феникс.exe.\n\n"
            "Переустанови Феникс. Логи: logs\\launcher.log",
        )
        return

    python_exe = find_python(logger)
    if python_exe is None:
        logger.info("Python не найден, предлагаю установить")
        reply = msg_box(
            "Python 3.10-3.12 не найден.\n\n"
            "Фениксу нужен Python 3.11.\n\n"
            "Сейчас будет скачан официальный установщик Python "
            "(~25 МБ). После скачивания откроется окно установки — "
            "нажми «Install Now».\n\n"
            "Продолжить?",
            "Феникс — нужен Python",
            MB_OKCANCEL | MB_ICONQUESTION,
        )
        if reply != IDOK:
            logger.info("Пользователь отменил установку Python")
            return

        installer = download_python_installer(logger)
        if installer is None:
            return

        if not run_python_installer(installer, logger):
            error(
                "Python не установлен.\n\n"
                "Установи вручную: https://www.python.org/downloads/\n"
                "Затем запусти Феникс.exe снова.",
            )
            return

        python_exe = find_python(logger)
        if python_exe is None:
            error(
                "Python установлен, но не найден.\n\n"
                "Перезапусти Феникс.exe.",
            )
            return
        logger.info("Python после установки: %s", python_exe)

    pythonw = find_venv_pythonw(project_dir, logger)
    if pythonw is None:
        if not create_venv(project_dir, python_exe, logger):
            return
        pythonw = find_venv_pythonw(project_dir, logger)
        if pythonw is None:
            error("venv создан, но pythonw не найден. Логи: logs\\launcher.log")
            return

    if not check_dependencies(project_dir, logger):
        if not install_dependencies(project_dir, logger):
            return

    if not check_vosk_model(project_dir, logger):
        if not download_vosk_model(project_dir, logger):
            return

    handle_ollama(logger)

    run_jarvis(project_dir, pythonw, logger)


if __name__ == "__main__":
    main()