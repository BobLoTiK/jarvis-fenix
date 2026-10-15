"""Пользовательские команды: из config.json и из паков.

`load_custom(config)` — собирает список (phrases, action, reply).
`match_custom(handler, cmd)` — ищет совпадение.
`load_packs_as_custom(config)` — команды из активных паков.
"""

import logging
from difflib import SequenceMatcher

from jarvis import packs
from jarvis.text_utils import normalize

log = logging.getLogger("jarvis.intents")


def load_custom(config) -> list:
    """Собирает custom-команды из config.json + активных паков.

    Каждый элемент: (phrases: list[str], action: str | list, reply: str).
    """
    result = []

    # Из config.json → custom_commands
    for entry in config.get("custom_commands", []):
        phrases = [normalize(p) for p in entry.get("phrases", []) if p.strip()]
        action = entry.get("action", "").strip() or entry.get("steps")
        if phrases and action:
            result.append((phrases, action, entry.get("reply", "Выполняю.")))

    # Из активных паков
    result.extend(load_packs_as_custom(config))
    return result


def load_packs_as_custom(config) -> list:
    """Только команды из активных паков."""
    result = []
    for entry in packs.load_active(config):
        phrases = [normalize(p) for p in entry.get("phrases", []) if p.strip()]
        action = entry.get("action", "").strip() or entry.get("steps")
        if phrases and action:
            result.append((phrases, action, entry.get("reply", "Выполняю.")))
    return result


def match_custom(handler, cmd: str) -> str | None:
    """Точное совпадение или нечёткое (>=0.85, обе фразы >=12 символов)."""
    for phrases, action, reply in handler.custom:
        for phrase in phrases:
            if cmd == phrase:
                log.info("Custom (точно): %r → %r, action=%r", cmd, phrase, action)
                return execute_custom(handler, action, reply)

            # Нечёткий матч — только для длинных фраз.
            # Короткие («вк», «отк») слишком легко путаются.
            if len(cmd) >= 12 and len(phrase) >= 12:
                ratio = SequenceMatcher(None, cmd, phrase).ratio()
                if ratio >= 0.85:
                    log.info("Custom (нечётко %.2f): %r → %r, action=%r",
                             ratio, cmd, phrase, action)
                    return execute_custom(handler, action, reply)
    return None


def execute_custom(handler, action, reply: str, *, authorized: bool = False) -> str:
    """Проверяет весь сценарий ДО первого шага, включая строковые команды."""
    from jarvis import actions
    from jarvis.intents.execute import execute_steps
    from jarvis.intents.password import is_danger

    intent = ({"steps": action} if isinstance(action, list)
              else {"action": "open_app", "target": action})
    stored = str(handler.config.get("danger_password") or "").strip()
    if not authorized and is_danger(intent, stored):
        return handler._ask_password({
            "action": "custom_command", "spec": action, "reply": reply,
        })
    if isinstance(action, list):
        return execute_steps(handler, action) or reply
    if not actions.run_spec(actions.spec_from_string(action)):
        return "Не удалось выполнить команду."
    return reply
