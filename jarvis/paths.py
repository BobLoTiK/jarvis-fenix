"""Централизованное определение путей Феникса.

Два корня:

    PROGRAM_DIR  — код, модели, всё что читает Vosk.
                   ВСЕГДА ASCII. По умолчанию: C:\\ProgramData\\Phoenix
                   (или fallback, если нет прав / не-ASCII).

    USER_DIR     — config.json, profiles/, logs/.
                   Может содержать кириллицу — Vosk их не читает.
                   По умолчанию: %APPDATA%\\Phoenix

Почему так:
    Vosk (C++ на Kaldi) ломается на не-ASCII путях.
    Значит модель ОБЯЗАНА быть в ASCII-пути.
    Всё остальное (настройки, логи, профили) — где угодно.

Fallback для PROGRAM_DIR:
    1. C:\\ProgramData\\Phoenix          (стандарт, ASCII)
    2. C:\\Phoenix                       (если ProgramData недоступен)
    3. %TEMP%\\Phoenix                   (последний шанс)
    4. <рядом с exe>                     (если совсем ничего)
"""

import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger("jarvis.paths")

APP_NAME = "Phoenix"


def _is_ascii(path: Path | str) -> bool:
    """Проверяет, что путь — чистая ASCII (без кириллицы, иероглифов)."""
    try:
        str(path).encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _try_mkdir(path: Path) -> bool:
    """Пробует создать папку. Возвращает True, если получилось."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        # Проверяем, что можем писать
        probe = path / ".write_test"
        probe.write_text("ok", encoding="ascii")
        probe.unlink()
        return True
    except Exception:
        return False


def _pick_program_dir() -> Path:
    """Выбирает ASCII-путь для кода и моделей.

    Порядок:
        1. C:\\ProgramData\\Phoenix
        2. C:\\Phoenix
        3. %TEMP%\\Phoenix
        4. <рядом с jarvis/>
    """
    candidates = []

    program_data = os.environ.get("PROGRAMDATA")
    if program_data:
        candidates.append(Path(program_data) / APP_NAME)

    candidates.append(Path(r"C:\Phoenix"))

    temp = Path(tempfile.gettempdir())
    candidates.append(temp / APP_NAME)

    # Последний — рядом с кодом
    candidates.append(Path(__file__).resolve().parent.parent / "runtime")

    for cand in candidates:
        if not _is_ascii(cand):
            log.debug("Пропускаю не-ASCII путь: %s", cand)
            continue
        if _try_mkdir(cand):
            log.info("PROGRAM_DIR: %s", cand)
            return cand
        log.debug("Не удалось создать: %s", cand)

    # Совсем крайний случай — temp (гарантированно есть)
    fallback = temp / APP_NAME
    fallback.mkdir(parents=True, exist_ok=True)
    log.warning("PROGRAM_DIR: fallback на %s", fallback)
    return fallback


def _pick_user_dir() -> Path:
    """Путь для данных юзера. Может быть с кириллицей — это ок."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        d = Path(appdata) / APP_NAME
    else:
        # Linux/macOS fallback
        d = Path.home() / f".{APP_NAME.lower()}"

    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        log.exception("Не удалось создать USER_DIR %s", d)
        d = Path(tempfile.gettempdir()) / APP_NAME
        d.mkdir(parents=True, exist_ok=True)

    log.info("USER_DIR: %s", d)
    return d


# ============================================================
# Публичный API
# ============================================================

# Ленивая инициализация — чтобы не дёргать файловую систему при импорте
_PROGRAM_DIR: Path | None = None
_USER_DIR: Path | None = None


def program_dir() -> Path:
    """ASCII-путь для кода и моделей."""
    global _PROGRAM_DIR
    if _PROGRAM_DIR is None:
        _PROGRAM_DIR = _pick_program_dir()
    return _PROGRAM_DIR


def user_dir() -> Path:
    """Путь для config.json, profiles/, logs/."""
    global _USER_DIR
    if _USER_DIR is None:
        _USER_DIR = _pick_user_dir()
    return _USER_DIR


def program_models_dir() -> Path:
    """Модели Vosk — ВСЕГДА в ASCII-пути."""
    d = program_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def program_whisper_cache_dir() -> Path:
    """Кэш Whisper — ВСЕГДА в ASCII-пути."""
    d = program_dir() / "whisper-cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def logs_dir() -> Path:
    """Логи — в USER_DIR (кириллица ок)."""
    d = user_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def profiles_dir() -> Path:
    """Профили — в USER_DIR."""
    d = user_dir() / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    """config.json — в USER_DIR."""
    return user_dir() / "config.json"