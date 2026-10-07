"""Единый менеджер записи в config.json.

Зачем:
    Раньше _atomic_write был продублирован в modes.py, voices.py, packs.py.
    Три лока, три .tmp, гонка между модулями.
    Плюс path.with_suffix(".tmp") давал общий временный файл.

Как работает:
    - Один FileLock на целевой файл (кэшируется per-path).
    - Уникальный .tmp через tempfile.mkstemp.
    - os.replace для атомарной подмены.
    - Логи: сколько ключей прочитано / записано.

Дефолтный путь — paths.config_path() (%APPDATA%\\Phoenix\\config.json).
Явный path= параметр — для тестов и скриптов.
"""

import json
import logging
import os
import tempfile
import threading
from pathlib import Path

from filelock import FileLock

log = logging.getLogger("jarvis.config_manager")

# Кэш локов: один FileLock на каждый resolved path.
# Иначе при параллельной записи в один файл через разные вызовы
# можно получить гонку.
_locks: dict[str, FileLock] = {}
_locks_guard = threading.Lock()


def _default_path() -> Path:
    """Дефолтный путь config.json — через paths.py (USER_DIR).

    Раньше был BASE_DIR/config.json — это писало конфиг в папку кода,
    что ломается после установки (нет прав) и мусорит в репозитории.
    """
    from jarvis import paths as _paths
    return _paths.config_path()


def _get_lock(path: Path) -> FileLock:
    """Возвращает FileLock для конкретного файла (кэшируется)."""
    key = str(path.resolve())
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = FileLock(key + ".lock")
            _locks[key] = lock
        return lock


def load(path: Path | None = None) -> dict:
    """Читает JSON. Если файла нет или он битый — возвращает {}."""
    p = Path(path) if path else _default_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            log.warning("Файл %s не словарь (%s) — возвращаю {}",
                        p.name, type(data).__name__)
            return {}
        return data
    except Exception:
        log.exception("Не удалось прочитать %s", p)
        return {}


def save(data: dict, path: Path | None = None) -> bool:
    """Атомарно записывает JSON. Возвращает True при успехе."""
    p = Path(path) if path else _default_path()
    if not isinstance(data, dict):
        log.error("save: data не словарь (%s) — отказ", type(data).__name__)
        return False
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with _get_lock(p):
            log.info("save: пишу %d ключей → %s", len(data), p.name)
            fd, tmp_name = tempfile.mkstemp(
                dir=str(p.parent), suffix=".tmp", prefix=p.stem + "."
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_name, p)
                return True
            except Exception:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
    except Exception:
        log.exception("Не удалось записать %s", p)
        return False


def update(key: str, value, path: Path | None = None) -> bool:
    """Читает, меняет одно поле, записывает. Всё под одним локом."""
    p = Path(path) if path else _default_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with _get_lock(p):
            data = load(p)
            log.info("update: key=%r, до=%d ключей, файл=%s", key, len(data), p.name)
            data[key] = value
            fd, tmp_name = tempfile.mkstemp(
                dir=str(p.parent), suffix=".tmp", prefix=p.stem + "."
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_name, p)
                return True
            except Exception:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
    except Exception:
        log.exception("Не удалось обновить %s", p)
        return False