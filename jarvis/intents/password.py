"""Парольные примитивы: jarvis.intents.password (не стадия pipeline).

Хеширование пароля и действия, требующие пароля.

Пароль хранится как `sha256:<hex>`. Legacy-plaintext поддерживается,
но мигрируется в sha256 при старте.
"""

import hashlib
import hmac
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
        # compare_digest — постоянное по времени сравнение.
        # Обычный == утекает длиной совпавшего префикса.
        return hmac.compare_digest(hash_password(candidate), stored)
    # Legacy plaintext — мигрируется в sha256 при старте.
    return hmac.compare_digest(candidate.encode("utf-8"), stored.encode("utf-8"))


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

# Необратимые: без настроенного пароля их нельзя выполнять молча.
# Обратимые (clear_tasks/cancel_timers) по-прежнему разрешены без пароля —
# иначе обычная уборка требовала бы настройки, которой ещё нет.
IRREVERSIBLE_ACTIONS = frozenset({
    "shutdown_pc", "reboot_pc", "kill_process", "delete_profile",
})

NO_PASSWORD_REPLY = (
    "Для этого действия нужен пароль опасных действий. Задай его в разделе "
    "«Мои команды»: без пароля необратимые команды не выполняются."
)


def _action_is_danger(action, target) -> bool:
    if action in DANGER_ACTIONS:
        return True
    if action == "open_app":
        t = str(target or "").lower()
        if any(word in t for word in ("shutdown", "taskkill", "выключ", "перезагруз")):
            return True
    return False


def is_danger(intent: dict, stored_password: str = "") -> bool:
    """Опасно ли действие — чистая классификация, без учёта пароля.

    Раньше здесь стоял ранний `return False` при пустом пароле: «пароля нет —
    значит ничего не опасно», и «удали профиль X» / shutdown выполнялись без
    подтверждения (пункт 2.13). Пароль теперь решает не *что* опасно, а
    *можно ли это сделать*: см. `danger_gate`.

    stored_password оставлен для совместимости вызовов и на ответ не влияет.
    Смотрит и сам intent, и шаги сценария: у steps-интента action=None.
    """
    if _action_is_danger(intent.get("action"), intent.get("target")):
        return True
    for step in intent.get("steps") or []:
        if isinstance(step, dict) and _action_is_danger(step.get("action"),
                                                        step.get("target")):
            return True
    return False


def is_irreversible(intent: dict) -> bool:
    """Действие нельзя отменить (удаление, питание, убийство процесса)."""
    action, target = intent.get("action"), intent.get("target")
    if action in IRREVERSIBLE_ACTIONS:
        return True
    # Строковая пак-команда приходит как open_app с целью-командой
    # («shutdown /r /t 10»): тип действия безопасный, а эффект — нет.
    if action == "open_app" and _action_is_danger(action, target):
        return True
    for step in intent.get("steps") or []:
        if not isinstance(step, dict):
            continue
        if step.get("action") in IRREVERSIBLE_ACTIONS:
            return True
        if _action_is_danger(step.get("action"), step.get("target")):
            return True
    return False


def danger_gate(handler, intent: dict, pending: dict | None = None) -> str | None:
    """Единая точка решения «пускать или нет».

    None          — можно исполнять (не опасно, либо опасно, но отменяемо);
    готовая строка — ответ пользователю: просьба пароля или безопасный отказ.

    `pending` — что запомнить для повторного исполнения после пароля
    (кастомные команды оборачивают шаги в свой intent).
    """
    if not is_danger(intent):
        return None
    stored = str(handler.config.get("danger_password") or "").strip()
    if stored:
        return handler._ask_password(pending if pending is not None else intent)
    if is_irreversible(intent):
        log.warning("Опасное действие без настроенного пароля отклонено: %r",
                    intent.get("action") or "steps")
        return NO_PASSWORD_REPLY
    return None


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