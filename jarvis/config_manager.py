"""Единый менеджер записи в config.json.

Зачем:
    Раньше _atomic_write был продублирован в modes.py, voices.py, packs.py.
    Три лока, три .tmp, гонка между модулями.
    Плюс path.with_suffix(".tmp") давал общий временный файл.

Как работает:
    - Один FileLock на весь проект (работает и между процессами).
    - Уникальный .tmp через tempfile.mkstemp.
    - os.replace для атомарной подмены.
    - Логи: сколько ключей прочитано / записано.
"""

import json
import logging
import os
import tempfile
from pathlib import Path

from filelock import FileLock

log = logging.getLogger("jarvis.config_manager")

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"
_LOCK_PATH = BASE_DIR / "config.json.lock"
_lock = FileLock(str(_LOCK_PATH))


def load(path: Path | None = None) -> dict:
    """Читает JSON. Если файла нет или он битый — возвращает {}."""
    p = Path(path) if path else CONFIG_PATH
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            log.warning("Файл %s не словарь (%s) — возвращаю {}", p.name, type(data).__name__)
            return {}
        return data
    except Exception:
        log.exception("Не удалось прочитать %s", p)
        return {}


def save(data: dict, path: Path | None = None) -> bool:
    """Атомарно записывает JSON. Возвращает True при успехе."""
    p = Path(path) if path else CONFIG_PATH
    if not isinstance(data, dict):
        log.error("save: data не словарь (%s) — отказ", type(data).__name__)
        return False
    try:
        with _lock:
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
    p = Path(path) if path else CONFIG_PATH
    try:
        with _lock:
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