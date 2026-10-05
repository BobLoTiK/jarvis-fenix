"""Профиль пользователя.

Хранит данные, специфичные для пользователя:
    - город по умолчанию
    - имя
    - предпочтения
    - произвольные факты (для будущего модуля памяти)

Файл: user_profile.json в корне проекта.
НЕ отправляется в гит (см. .gitignore).
Запись — через config_manager (единый FileLock, атомарная замена).

Защита: если user_profile.json битый — не перезаписываем молча,
логируем и НЕ сохраняем (чтобы не потерять данные при ошибке чтения).
"""

import json
import logging
from pathlib import Path

from jarvis import config_manager

log = logging.getLogger("jarvis.profile")

BASE_DIR = Path(__file__).resolve().parent.parent
PROFILE_PATH = BASE_DIR / "user_profile.json"


def _safe_load() -> dict:
    """Читает профиль. Возвращает {} при отсутствии файла.
    Логирует отдельно, если файл есть, но битый.
    """
    if not PROFILE_PATH.exists():
        return {}
    raw = PROFILE_PATH.read_text(encoding="utf-8")
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        log.error("user_profile.json битый — не могу прочитать. "
                  "НЕ перезаписываю, чтобы не потерять данные. "
                  "Почини файл вручную: %s", PROFILE_PATH)
        raise


def get(key: str, default=None):
    """Читает одно поле. При битом файле — возвращает default."""
    try:
        return _safe_load().get(key, default)
    except json.JSONDecodeError:
        return default


def set(key: str, value) -> bool:
    """Записывает одно поле. Возвращает True при успехе.
    При битом файле — НЕ перезаписывает, возвращает False.
    """
    try:
        data = _safe_load()
    except json.JSONDecodeError:
        return False

    data[key] = value
    ok = config_manager.save(data, path=PROFILE_PATH)
    if ok:
        log.info("Профиль: %s = %r", key, value)
    else:
        log.error("Профиль: не удалось сохранить %s", key)
    return ok


def all_data() -> dict:
    """Возвращает все данные профиля. При битом — пустой dict."""
    try:
        return _safe_load()
    except json.JSONDecodeError:
        return {}


def forget(key: str) -> bool:
    """Удаляет одно поле."""
    try:
        data = _safe_load()
    except json.JSONDecodeError:
        return False
    if key not in data:
        return False
    del data[key]
    ok = config_manager.save(data, path=PROFILE_PATH)
    if ok:
        log.info("Профиль: удалено %s", key)
    return ok
