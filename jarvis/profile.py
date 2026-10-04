"""Профиль пользователя.

Хранит данные, специфичные для пользователя:
    - город по умолчанию
    - имя
    - предпочтения
    - произвольные факты (для будущего модуля памяти)

Файл: user_profile.json в корне проекта.
НЕ отправляется в гит (см. .gitignore).
Запись — через config_manager (единый FileLock, атомарная замена).
"""

import logging
from pathlib import Path

from jarvis import config_manager

log = logging.getLogger("jarvis.profile")

BASE_DIR = Path(__file__).resolve().parent.parent
PROFILE_PATH = BASE_DIR / "user_profile.json"


def get(key: str, default=None):
    """Читает одно поле."""
    return config_manager.load(path=PROFILE_PATH).get(key, default)


def set(key: str, value) -> None:
    """Записывает одно поле."""
    config_manager.update(key, value, path=PROFILE_PATH)
    log.info("Профиль: %s = %r", key, value)


def all_data() -> dict:
    return config_manager.load(path=PROFILE_PATH)


def forget(key: str) -> bool:
    """Удаляет одно поле."""
    data = config_manager.load(path=PROFILE_PATH)
    if key not in data:
        return False
    del data[key]
    config_manager.save(data, path=PROFILE_PATH)
    log.info("Профиль: удалено %s", key)
    return True