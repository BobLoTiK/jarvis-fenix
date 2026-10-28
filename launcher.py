"""Лаунчер Феникса — полный автозапуск.

Что делает при запуске:
    1. Ищет Python 3.11 (py -3.X, where python, типичные пути).
    2. Если не нашёл — вопрос в едином окне подготовки.
       Скачивает python-3.11.9-amd64.exe, запускает installer.
    3. Проверяет .venv311. Если нет — создаёт.
    4. Проверяет зависимости (flet, vosk, piper). Если нет — pip install.
    5. Проверяет Vosk-модель. Если нет — скачивает.
    6. Проверяет Ollama (URL + поиск на дисках). Если нет — вопрос в окне подготовки.
    7. Запускает Феникс через .venv311\\Scripts\\pythonw.exe -m jarvis.

Собирается в exe (PyInstaller). Защищён от повторного запуска.
Логи — в logs/launcher.log рядом с exe.
"""

import hashlib
import tempfile
import ctypes
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from jarvis import model as vosk_model
from launcher_download import (
    DownloadError, cleanup_download, download_python, verify_python_installer,
)

from launcher_ollama import prepare_models
from launcher_runtime import ensure_vc_runtime

# ============================================================
# Константы
# ============================================================

# Local\ вместо Global\ — работает без прав администратора
# (Global\ требует SeCreateGlobalPrivilege).
MUTEX_NAME = "Local\\JarvisPhoenixLauncherSetup"
_MUTEX_HANDLE = None

PYTHON_INSTALLER_URL = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
PYTHON_INSTALLER_FILE = "python-3.11.9-amd64.exe"

VOSK_MODEL_NAME = vosk_model.MODEL_NAME
VOSK_MODEL_URL = vosk_model.MODEL_URL

OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_DOWNLOAD_PAGE = "https://ollama.com/download"

# Где искать Python, если py launcher не работает
PYTHON_SEARCH_PATHS = [
    r"C:\Python311\python.exe",
    r"C:\Program Files\Python311\python.exe",
]

# Где искать Ollama
OLLAMA_SEARCH_PATHS = [
    r"C:\Program Files\Ollama\ollama.exe",
    r"C:\Program Files (x86)\Ollama\ollama.exe",
]

# Какие версии Python подходят
REQUIRED_PY_VERSIONS = ("3.11",)

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

_PREPARATION = None


def _download_progress(block, block_size, total):
    if _PREPARATION is not None:
        _PREPARATION.download_progress(block, block_size, total)


def msg_box(text: str, title: str = "Феникс", flags: int = MB_OK) -> int:
    """Inline question while preparing; native fallback if the UI cannot open."""
    if _PREPARATION is not None:
        if flags & MB_YESNO:
            return IDYES if _PREPARATION.ask(text, title, "Открыть сайт", "Продолжить без Ollama") else IDNO
        if flags & MB_OKCANCEL:
            answer = _PREPARATION.ask(text, title, "Продолжить", "Не сейчас")
            _PREPARATION.declined = not answer
            return IDOK if answer else IDCANCEL
        _PREPARATION.detail(text)
        return IDOK
    try:
        return ctypes.windll.user32.MessageBoxW(0, text, title, flags)
    except Exception:
        return 0


def info(text: str, title: str = "Феникс") -> None:
    if _PREPARATION is not None:
        if "уже запущен" in text.lower():
            _PREPARATION.notice = text
        else:
            _PREPARATION.stage(title, text, show=True)
        return
    msg_box(text, title, MB_OK | MB_ICONINFORMATION)


def warn(text: str, title: str = "Феникс") -> None:
    if _PREPARATION is not None:
        _PREPARATION.detail(text)
        return
    msg_box(text, title, MB_OK | MB_ICONWARNING)


def error(text: str, title: str = "Феникс — ошибка") -> None:
    if _PREPARATION is not None:
        _PREPARATION.last_error = text
        return
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
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    fh.setFormatter(logging.Formatter(
        "%(asctime)s launcher %(levelname)s %(message)s"
    ))
    logger.addHandler(fh)
    if _PREPARATION is not None:
        from launcher_ui import StageLogHandler
        logger.addHandler(StageLogHandler(_PREPARATION))

    return log_file


# ============================================================
# Мьютекс
# ============================================================

def already_running(logger) -> bool:
    global _MUTEX_HANDLE

    if _MUTEX_HANDLE is not None:
        return False

    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
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

def launcher_directory() -> Path:
    """Locate the real executable, not Nuitka onefile's extraction directory."""
    compiled = globals().get("__compiled__")
    if compiled is not None:
        containing_dir = getattr(compiled, "containing_dir", None)
        if containing_dir:
            return Path(containing_dir).resolve()
        return Path(sys.argv[0]).resolve().parent
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def find_project_dir(logger) -> Path:
    exe_dir = launcher_directory()

    candidates = list(dict.fromkeys(
        [exe_dir, *exe_dir.parents, Path.cwd().resolve()]
    ))
    projects = [
        cand for cand in candidates
        if (cand / "jarvis" / "__init__.py").is_file()
    ]

    for cand in projects:
        if find_venv_pythonw(cand, logger) is not None:
            logger.info("Проект с готовым окружением найден: %s", cand)
            return cand

    if projects:
        logger.info(
            "Проект найден (окружение требует подготовки): %s",
            projects[0],
        )
        return projects[0]

    logger.error(
        "Не найдена папка с jarvis/ (проверены: %s)",
        ", ".join(str(c) for c in candidates),
    )
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
                if version.split(".")[:2] == req.split("."):
                    return version
        return None
    except Exception:
        return None


def find_python(logger) -> str | None:
    """Ищет Python 3.11. Возвращает путь к python.exe или None."""
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
        for ver in ("311",):
            cand = Path(local_appdata) / "Programs" / "Python" / f"Python{ver}" / "python.exe"
            if cand.exists():
                version = _check_python_version(str(cand), logger)
                if version:
                    logger.info("Python %s найден: %s", version, cand)
                    return str(cand)

    logger.info("Python 3.11 не найден")
    return None


def download_python_installer(logger) -> Path | None:
    """Загрузка через Windows HTTPS с обязательной проверкой подписи."""
    info(
        "Сейчас будет скачан установщик Python 3.11 (~25 МБ).\n\n"
        "Загрузка средствами Windows; затем проверка подписи издателя.\n"
        "После скачивания нажми «Install Now» в установщике Python.\n\n"
        "Подготовка продолжится в этом окне.",
        "Феникс — установка Python",
    )
    logger.info("Скачиваю installer: %s", PYTHON_INSTALLER_URL)
    try:
        installer = download_python(PYTHON_INSTALLER_URL, logger, _download_progress)
        logger.info("Installer скачан и подпись проверена: %s", installer)
        return installer
    except Exception as exc:
        logger.exception("Не удалось скачать или проверить installer Python")
        reasons = {
            "certificate": "Windows не смогла проверить HTTPS-сертификат сервера.",
            "dns": "Не удалось определить адрес сервера загрузки Python (DNS).",
            "signature": "Подпись установщика недействительна или издатель не Python Software Foundation.",
            "timeout": "Истекло время ожидания загрузки или проверки установщика Python.",
            "unavailable": "Не удалось запустить системный Windows PowerShell для безопасной загрузки.",
            "verification": "Не удалось подтвердить успешную загрузку и проверку установщика Python.",
        }
        reason = reasons.get(getattr(exc, "kind", ""), "Не удалось скачать Python средствами Windows.")
        error(
            f"{reason}\n\n"
            "Установка Python не запущена. Проверка безопасности не отключалась.\n"
            "Проверь подключение и нажми «Повторить».\n"
            "Официальная страница: https://www.python.org/downloads/release/python-3119/\n\n"
            "Логи: logs\\launcher.log",
        )
        return None


def run_python_installer(installer: Path, logger) -> bool:
    """Запускает installer Python. Ждёт завершения."""
    try:
        verify_python_installer(installer, logger)
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
    except DownloadError:
        logger.exception("Установщик Python не прошёл повторную проверку подписи")
        error("Не удалось подтвердить подпись установщика Python перед запуском.\n"
              "Установка не запущена. Нажми «Повторить».\n\nЛоги: logs\\launcher.log")
        return False
    finally:
        cleanup_download(installer)


# ============================================================
# Venv: создание
# ============================================================

def find_venv_pythonw(project_dir: Path, logger) -> Path | None:
    folder = project_dir / ".venv311" / "Scripts"
    if ((folder/"pythonw.exe").exists() and (folder/"python.exe").exists()
            and _check_python_version(str(folder/"python.exe"),logger)):
        logger.info("Python 3.11 venv найден: %s",folder)
        return folder/"pythonw.exe"
    return None


def create_venv(project_dir: Path, python_exe: str, logger) -> bool:
    """Создаёт .venv311 через указанный Python."""
    venv_dir = project_dir / ".venv311"

    if venv_dir.exists():
        if find_venv_pythonw(project_dir,logger) is not None:
            return True
        error("Окружение .venv311 повреждено или использует не Python 3.11.\n"
              "Закрой Феникс, переименуй эту папку и запусти снова.\n"
              "Конфиг и профили удалять не нужно.")
        return False

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

DEPENDENCY_PROBE = """
import sys
from importlib.metadata import version
assert sys.version_info[:2] == (3,11)
import flet, vosk, pymorphy3, num2words, pystray, PIL
from flet import AppView
assert hasattr(AppView, 'FLET_APP_HIDDEN')
v = tuple(int(x) for x in version('flet').split('.')[:3])
assert (1,0,3) <= v < (1,1,0)
assert version('flet') == version('flet-desktop')
print('ok')
"""


def requirements_digest(project_dir):
    try:
        data = (project_dir / "requirements.txt").read_bytes()
        return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()
    except OSError:
        return None


def record_dependency_receipt(project_dir):
    digest = requirements_digest(project_dir)
    if digest is None:
        return False
    destination = project_dir / ".venv311" / "phoenix-requirements.sha256"
    fd, temp = tempfile.mkstemp(prefix="requirements-", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as out:
            out.write(digest)
        os.replace(temp, destination)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return True


def _probe_dependencies(project_dir, logger):
    python = project_dir / ".venv311" / "Scripts" / "python.exe"
    if not python.exists():
        return False
    try:
        result = subprocess.run([str(python), "-c", DEPENDENCY_PROBE],
            capture_output=True, text=True, timeout=25, creationflags=CREATE_NO_WINDOW)
        return result.returncode == 0
    except Exception:
        logger.exception("Проверка зависимостей не завершилась")
        return False


def check_dependencies(project_dir: Path, logger) -> bool:
    """A changed manifest or unsupported native Flet must trigger environment repair."""
    digest = requirements_digest(project_dir)
    try:
        receipt = (project_dir/".venv311"/"phoenix-requirements.sha256").read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return False
    return digest is not None and digest == receipt and _probe_dependencies(project_dir,logger)


def ensure_local_caps(project_dir, logger):
    """Probe the customer's machine, not the builder's. Failure is nonfatal."""
    try:
        result = subprocess.run([str(project_dir/".venv311"/"Scripts"/"python.exe"),
            str(project_dir/"scripts"/"check_caps.py"), "--if-missing"],
            cwd=str(project_dir), capture_output=True, text=True, timeout=30,
            creationflags=CREATE_NO_WINDOW)
        if result.returncode:
            logger.warning("Локальная диагностика завершилась с кодом %s",result.returncode)
    except Exception:
        logger.warning("Локальная диагностика недоступна; запуск продолжается",exc_info=True)


def prepare_flet_client(project_dir, logger):
    """Prepare the native UI while the bootstrap window can report failure/retry."""
    if _PREPARATION is not None:
        _PREPARATION.stage("Готовим интерфейс", "Проверяем клиент Flet. При первой загрузке нужен интернет.", show=True)
    try:
        result = subprocess.run(
            [str(project_dir / ".venv311" / "Scripts" / "python.exe"),
             str(project_dir / "scripts" / "prepare_flet_client.py")],
            cwd=str(project_dir), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=240, creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode == 0 and "FLET_CLIENT_READY" in result.stdout.splitlines():
            logger.info("Клиент Flet подготовлен и проверен")
            return True
        logger.error("Подготовка Flet не завершена: exit=%s; %s", result.returncode, result.stderr[-1200:])
    except (OSError, subprocess.TimeoutExpired):
        logger.exception("Подготовка клиента Flet не завершилась")
    error("Не удалось подготовить интерфейс Flet. Проверь интернет и HTTPS-сертификаты. "
          "Проверка TLS не отключалась. Логи: logs\\launcher.log")
    return False


def install_dependencies(project_dir: Path, logger) -> bool:
    """Устанавливает зависимости из requirements.txt."""
    python = project_dir / ".venv311" / "Scripts" / "python.exe"
    req = project_dir / "requirements.txt"

    if not req.exists():
        logger.error("requirements.txt не найден: %s", req)
        error("requirements.txt не найден. Феникс установлен неправильно.")
        return False

    if msg_box(
        "Нужно установить или обновить зависимости Феникса.\n\n"
        "Потребуется интернет; загрузка может занять несколько минут.\n"
        "ОК — продолжить, Отмена — выйти без установки.",
        "Феникс — установка", MB_OKCANCEL | MB_ICONQUESTION) != IDOK:
        return False

    logger.info("pip install -r requirements.txt")
    try:
        result = subprocess.run(
            [str(python), "-m", "pip", "install", "-r", str(req)],
            cwd=str(project_dir), capture_output=True, text=True,
            encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW,
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
        if not _probe_dependencies(project_dir,logger):
            error("Пакеты установлены, но проверка Python/Flet не прошла. См. logs/launcher.log")
            return False
        if not record_dependency_receipt(project_dir):
            return False
        logger.info("Зависимости установлены и проверены")
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
    """Use the application's path selection and complete-model validation."""
    model_dir = vosk_model.paths.program_models_dir() / VOSK_MODEL_NAME
    ok = vosk_model.model_is_ready(model_dir)
    logger.info("Vosk-модель в %s: %s", model_dir, "есть" if ok else "нет")
    return ok


def download_vosk_model(project_dir: Path, logger) -> bool:
    """Share the safe, staged model installation with the application."""
    info(
        "Готовлю модель Vosk. Если локальной копии нет, потребуется "
        "скачать ~45 МБ.\n\nЭто может занять 1–2 минуты.",
        "Феникс — модель Vosk",
    )
    try:
        target_dir = vosk_model.ensure_model(
            project_dir / "models", reporthook=_download_progress,
        )
        logger.info("Vosk подготовлен: %s", target_dir)
        info("Модель Vosk готова. OK", "Феникс")
        return True
    except Exception:
        logger.exception("Не удалось подготовить модель Vosk")
        error("Не удалось подготовить модель Vosk. Проверь интернет и доступ к "
              "папке моделей. Логи: logs\\launcher.log")
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


def start_ollama_server(ollama_exe, logger):
    """Start the existing local service; readiness is checked by the setup worker."""
    logger.info("Ollama найден, запускаю serve")
    return subprocess.Popen(
                [str(ollama_exe), "serve"],
                creationflags=CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


def handle_ollama(logger, project_dir=None) -> None:
    """Optional server installation/recheck and explicit model choice in one window."""
    if _PREPARATION is None:
        logger.warning("Настройка Ollama требует окна подготовки; пропускаю без изменений")
        return
    prepare_models(
        project_dir or find_project_dir(logger), _PREPARATION, logger,
        find_ollama_exe, start_ollama_server, lambda url: os.startfile(url),
    )


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

def _main() -> None:
    exe_dir = launcher_directory()

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
            "Python 3.11 не найден.\n\n"
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

    try:
        if not ensure_vc_runtime(_PREPARATION, logger):
            return
    except Exception:
        logger.exception("Не удалось подготовить Microsoft VC++ Runtime x64")
        error("Не удалось подготовить Microsoft VC++ Runtime x64. "
              "Проверь интернет и заверши официальный установщик Microsoft. Логи: logs\\launcher.log")
        return

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

    if not prepare_flet_client(project_dir, logger):
        return

    ensure_local_caps(project_dir, logger)
    handle_ollama(logger, project_dir)

    run_jarvis(project_dir, pythonw, logger)


def main() -> None:
    """UI wrapper; the existing bootstrap workflow runs on one worker."""
    base = launcher_directory()
    log_file = _setup_logging(base)
    try:
        from launcher_ui import PreparationWindow
        window = PreparationWindow(find_project_dir(logging.getLogger("launcher")), log_file)
        def prepare(session):
            global _PREPARATION
            _PREPARATION = session
            try:
                _main()
            finally:
                _PREPARATION = None
        window.run(prepare)
    except Exception:
        logging.getLogger("launcher").exception("Не удалось открыть окно подготовки")
        error("Не удалось открыть окно подготовки Феникса.\n"
              "При запуске из исходников нужен компонент Tcl/Tk Python 3.11.\n"
              "Подробности: logs\\launcher.log")


if __name__ == "__main__":
    main()