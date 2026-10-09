"""Хеширование пароля и действия, требующие пароля.

Пароль хранится как `sha256:<hex>`. Legacy-plaintext поддерживается,
но мигрируется в sha256 при старте.
"""

import hashlib
import logging

log = logging.getLogger("jarvis.intents")


_PASSWORD_PREFIX = "sha256:"


def hash_password(password: str) -> str:
    """SHA-256 с префиксом. Префикс отличает хеш от legacy-plaintext."""
    digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return f"{_PASSWORD_PREFIX}{digest}"


def is_hashed(value: str) -> bool:
    """Уже захеширован?"""
    return bool(value) and value.startswith(_PASSWORD_PREFIX)


def verify_password(candidate: str, stored: str) -> bool:
    """Сравнивает введённый пароль с сохранённым.

    Если stored ещё legacy (plaintext) — сравнивает напрямую.
    Миграция происходит при старте через `migrate_password_if_needed`.
    """
    if not stored:
        return False
    if is_hashed(stored):
        return hash_password(candidate) == stored
    return candidate == stored


def migrate_password_if_needed(config) -> None:
    """Если danger_password в plaintext — захешировать (№81)."""
    raw = str(config.get("danger_password") or "").strip()
    if not raw or is_hashed(raw):
        return
    config.set("danger_password", hash_password(raw))
    log.info("Пароль миграции: plaintext → sha256")


# Действия, требующие пароля (если danger_password задан).
DANGER_ACTIONS = frozenset({
    "shutdown_pc", "reboot_pc", "kill_process",
    "clear_tasks", "cancel_timers", "delete_profile",
})


def is_danger(intent: dict, stored_password: str) -> bool:
    """Проверяет, опасно ли действие.

    stored_password — уже захешированный (или пустой).
    """
    if not stored_password:
        return False
    action = intent.get("action")
    if action in DANGER_ACTIONS:
        return True
    if action == "open_app":
        target = str(intent.get("target") or "").lower()
        if "shutdown" in target or "выключ" in target or "перезагруз" in target:
            return True
    return False


# Человеческие названия для озвучки — при запросе пароля.
ACTION_HUMAN = {
    "shutdown_pc": "выключение компьютера",
    "reboot_pc": "перезагрузку",
    "kill_process": "закрытие процесса",
    "clear_tasks": "очистку списка задач",
    "cancel_timers": "отмену напоминаний",
    "delete_profile": "удаление профиля",
    "open_app": "это действие",
}