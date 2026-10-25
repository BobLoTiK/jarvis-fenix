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


def _load_entries(data, wake_words=()) -> list:
    from jarvis.command_builder import validate_entry
    result = []
    if not isinstance(data, list):
        return result
    for entry in data:
        if not isinstance(entry, dict) or not entry.get("enabled", True):
            continue
        if "builder_version" in entry and entry["builder_version"] != 1:
            log.warning("Неизвестная версия команды конструктора пропущена")
            continue
        if entry.get("builder_version") == 1:
            try:
                entry = validate_entry(entry, wake_words)
            except (ValueError, TypeError):
                log.warning("Повреждённая команда конструктора пропущена")
                continue
            result.append((entry["phrases"], entry["steps"], "", {"exact": True}))
            continue
        raw = entry.get("phrases", [])
        phrases = [normalize(p) for p in raw if isinstance(p, str) and p.strip()] if isinstance(raw, list) else []
        action = entry.get("action", "")
        action = action.strip() if isinstance(action, str) else ""
        action = action or entry.get("steps")
        if phrases and isinstance(action, (str, list)) and action:
            result.append((phrases, action, entry.get("reply", "Выполняю.")))
    return result


def load_custom(config, *, include_packs=True) -> list:
    """Legacy commands keep their format; builder entries use strict exact matching."""
    result = _load_entries(config.get("custom_commands", []), config.get("wake_words", []))
    if include_packs:
        result.extend(load_packs_as_custom(config))
    return result


def load_packs_as_custom(config) -> list:
    return _load_entries(packs.load_active(config), config.get("wake_words", []))


def reload_custom(handler):
    handler._config_custom_original = load_custom(handler.config, include_packs=False)
    handler.custom = load_custom(handler.config)


def match_custom(handler, cmd: str) -> str | None:
    """Тот же matcher используется уточнениями, но исполнение только здесь."""
    matched = find_custom(handler.custom, cmd)
    if matched is None:
        # The microphone already removes the address; typed GUI commands may include it.
        from jarvis.command_builder import clean_phrase
        typed = [item for item in handler.custom if len(item) > 3 and item[3].get("exact")]
        matched = find_custom(typed, clean_phrase(cmd, handler.config.get("wake_words", [])))
    if matched is not None:
        return execute_custom(handler, *matched)
    return None


def find_custom(custom: list, cmd: str) -> tuple | None:
    """Чистый поиск: точное или нечёткое совпадение, без побочных действий."""
    # Exact matches across the whole list take precedence over legacy fuzzy ones.
    for item in custom:
        phrases, action, reply = item[:3]
        if cmd in phrases:
            return action, reply
    for item in custom:
        phrases, action, reply = item[:3]
        if len(item) > 3 and item[3].get("exact"):
            continue
        for phrase in phrases:
            if len(cmd) >= 12 and len(phrase) >= 12:
                if SequenceMatcher(None, cmd, phrase).ratio() >= 0.85:
                    return action, reply
    return None


def execute_custom(handler, action, reply: str, *, authorized: bool = False) -> str:
    """Проверяет весь сценарий ДО первого шага, включая строковые команды."""
    from jarvis import actions
    from jarvis.intents.execute import execute_steps
    from jarvis.intents.password import danger_gate

    intent = ({"steps": action} if isinstance(action, list)
              else {"action": "open_app", "target": action})
    if not authorized:
        # Один гейт на все кастомные команды: пароль задан → спрашиваем;
        # пароля нет и действие необратимо (питание, kill, строковый
        # shutdown) → отказ. Раньше здесь проверялся только shutdown/reboot
        # среди шагов, а строковая ветка уходила в Popen молча.
        gate = danger_gate(handler, intent,
                           pending={"action": "custom_command",
                                    "spec": action, "reply": reply})
        if gate:
            return gate
    if isinstance(action, list):
        return execute_steps(handler, action) or reply
    if not actions.run_spec(actions.spec_from_string(action)):
        return "Не удалось выполнить команду."
    return reply
