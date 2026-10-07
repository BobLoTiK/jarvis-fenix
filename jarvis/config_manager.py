"""Единый менеджер записи в config.json.

Зачем:
    Раньше _atomic_write был продублирован в modes.py, voices.py, packs.py.
    Три лока, три .tmp, гонка между модулями.
    Плюс path.with_suffix(".tmp") давал общий временный файл.

Как работает:
    - Один threading.RLock + FileLock на целевой файл (кэш per-path).
    - threading.RLock — сериализация внутри процесса (потоки).
    - FileLock — сериализация между процессами.
    - Уникальный .tmp через tempfile.mkstemp.
    - os.replace для атомарной подмены (с retry на PermissionError).
    - Логи: сколько ключей прочитано / записано.

Дефолтный путь — paths.config_path() (%APPDATA%\\Phoenix\\config.json).
Явный path= параметр — для тестов и скриптов.
"""

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path

from filelock import FileLock

log = logging.getLogger("jarvis.config_manager")

# Кэш локов per-path. Для каждого целевого файла — свой набор.
# threading.RLock защищает от гонок внутри одного процесса.
# FileLock — от гонок между процессами.
_locks_guard = threading.Lock()
_thread_locks: dict[str, threading.RLock] = {}
_file_locks: dict[str, FileLock] = {}


def _default_path() -> Path:
    """Дефолтный путь config.json — через paths.py (USER_DIR)."""
    from jarvis import paths as _paths
    return _paths.config_path()


def _get_locks(path: Path) -> tuple[threading.RLock, FileLock]:
    """Возвращает пару (threading.RLock, FileLock) для файла (кэшируется)."""
    key = str(path.resolve())
    with _locks_guard:
        t_lock = _thread_locks.get(key)
        if t_lock is None:
            t_lock = threading.RLock()
            _thread_locks[key] = t_lock

        f_lock = _file_locks.get(key)
        if f_lock is None:
            f_lock = FileLock(key + ".lock")
            _file_locks[key] = f_lock

        return t_lock, f_lock


def _atomic_replace(tmp_name: str, target: Path) -> None:
    """os.replace с 3 retry на Windows PermissionError.

    На Windows os.replace иногда падает от антивируса или от кратковременной
    блокировки файла. 3 попытки с паузой обычно решают.
    """
    last_exc: PermissionError | None = None
    for attempt in range(3):
        try:
            os.replace(tmp_name, target)
            return
        except PermissionError as e:
            last_exc = e
            time.sleep(0.05 * (attempt + 1))
    if last_exc is not None:
        raise last_exc


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
        t_lock, f_lock = _get_locks(p)
        with t_lock, f_lock:
            log.info("save: пишу %d ключей → %s", len(data), p.name)
            fd, tmp_name = tempfile.mkstemp(
                dir=str(p.parent), suffix=".tmp", prefix=p.stem + "."
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                _atomic_replace(tmp_name, p)
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
        t_lock, f_lock = _get_locks(p)
        with t_lock, f_lock:
            data = load(p)
            log.info("update: key=%r, до=%d ключей, файл=%s", key, len(data), p.name)
            data[key] = value
            fd, tmp_name = tempfile.mkstemp(
                dir=str(p.parent), suffix=".tmp", prefix=p.stem + "."
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                _atomic_replace(tmp_name, p)
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