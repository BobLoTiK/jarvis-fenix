"""Парольные примитивы: jarvis.intents.password (не стадия pipeline).

Хеширование пароля и действия, требующие пароля.

Пароль хранится как `pbkdf2_sha256:<iterations>:<salt_hex>:<hash_hex>` —
PBKDF2-HMAC-SHA256 с солью (600 000 итераций). Legacy-форматы читаются и
мигрируют: `sha256:<hex>` (без соли, до 2.1.3) и plaintext — оба принимаются
при проверке, но при первом успешном вводе пароля запись перезаписывается
на текущий формат (`verify_password(..., config=...)`).
"""

import hashlib
import hmac
import logging
import secrets

log = logging.getLogger("jarvis.intents")

_PASSWORD_PREFIX = "pbkdf2_sha256:"
_LEGACY_PREFIX = "sha256:"
KDF_ITERATIONS = 600_000
_SALT_BYTES = 16


def _hash_legacy_sha256(password: str) -> str:
    return "sha256:" + hashlib.sha256(password.encode("utf-8")).hexdigest()


def hash_password(password: str, iterations: int = KDF_ITERATIONS) -> str:
    """PBKDF2-HMAC-SHA256 со случайной солью.

    Итерации пишутся в саму запись: старые хеши не нужно пересчитывать вслепую,
    а `needs_rehash` видит, когда формат устарел.
    """
    salt = secrets.token_hex(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations
    ).hex()
    return f"{_PASSWORD_PREFIX}{iterations}:{salt}:{digest}"


def is_hashed(value: str) -> bool:
    """Уже захеширован (текущий формат или legacy `sha256:`)."""
    return bool(value) and value.startswith((_PASSWORD_PREFIX, _LEGACY_PREFIX))


def needs_rehash(stored: str) -> bool:
    """Слабый формат: plaintext, legacy без соли или меньше итераций, чем сейчас."""
    if not stored:
        return False
    if stored.startswith(_LEGACY_PREFIX):
        return True
    if not stored.startswith(_PASSWORD_PREFIX):
        return True
    rest = stored[len(_PASSWORD_PREFIX):]
    try:
        iterations = int(rest.split(":", 1)[0])
    except (ValueError, IndexError):
        return True
    return iterations < KDF_ITERATIONS


def _parse_pbkdf2(stored: str) -> tuple[int, str, str] | None:
    rest = stored[len(_PASSWORD_PREFIX):]
    parts = rest.split(":")
    if len(parts) != 3:
        return None
    try:
        iterations = int(parts[0])
    except ValueError:
        return None
    salt_hex, digest = parts[1], parts[2]
    try:
        bytes.fromhex(salt_hex)
    except ValueError:
        return None
    return iterations, salt_hex, digest


def verify_password(candidate: str, stored: str, config=None) -> bool:
    """Сравнивает введённый пароль с сохранённым.

    Принимает текущий формат, legacy `sha256:` и legacy plaintext. Если передан
    `config` и хеш устарел, после успешной проверки запись перезаписывается
    на PBKDF2 с солью — так legacy уходит без сброса пароля.
    """
    if not stored:
        return False
    stored = str(stored).strip()
    ok = False
    if stored.startswith(_PASSWORD_PREFIX):
        parsed = _parse_pbkdf2(stored)
        if parsed is None:
            return False
        iterations, salt_hex, digest = parsed
        computed = hashlib.pbkdf2_hmac(
            "sha256", candidate.encode("utf-8"), bytes.fromhex(salt_hex), iterations
        ).hex()
        ok = hmac.compare_digest(computed, digest)
    elif stored.startswith(_LEGACY_PREFIX):
        ok = hmac.compare_digest(_hash_legacy_sha256(candidate), stored)
    else:
        ok = hmac.compare_digest(candidate.encode("utf-8"), stored.encode("utf-8"))
    if ok and config is not None and needs_rehash(stored) and hasattr(config, "set"):
        try:
            config.set("danger_password", hash_password(candidate))
            log.info("Парольной записи назначен PBKDF2 с солью")
        except Exception:
            log.exception("Не удалось обновить формат парольной записи")
    return ok


def migrate_password_if_needed(config) -> None:
    """Если danger_password в plaintext — захешировать (№81).

    Legacy `sha256:` без пароля не пересчитать: он обновится при первом
    успешном вводе через `verify_password(..., config=...)`.
    """
    raw = str(config.get("danger_password") or "").strip()
    if not raw or is_hashed(raw):
        return
    config.set("danger_password", hash_password(raw))
    log.info("Пароль миграции: plaintext → pbkdf2_sha256")


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