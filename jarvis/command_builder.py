"""Typed custom commands. No execution, model calls or shell parsing in the editor."""
from copy import deepcopy
import re
from urllib.parse import urlsplit
from uuid import uuid4

from jarvis.text_utils import normalize

ACTIONS = {
    "open_app": ("Открыть приложение", "Название из меню Пуск", "target"),
    "open_site": ("Открыть сайт", "https://example.com", "target"),
    "set_volume": ("Установить громкость", "Проценты: 0–100", "percent"),
    "set_timer": ("Поставить таймер", "Секунды: 1–86400", "seconds"),
    "play_pause": ("Музыка: играть / пауза", "", None),
    "next_track": ("Следующий трек", "", None),
    "prev_track": ("Предыдущий трек", "", None),
    "screenshot": ("Сделать скриншот", "", None),
    "answer": ("Сказать текст", "Что сказать", "reply"),
    "shutdown_pc": ("Выключить компьютер", "Задержка, секунды: 10–600", "seconds"),
    "reboot_pc": ("Перезагрузить компьютер", "Задержка, секунды: 10–600", "seconds"),
    "cancel_shutdown": ("Отменить выключение / перезагрузку", "", None),
}
POWER_ACTIONS = frozenset({"shutdown_pc", "reboot_pc"})
RESERVED = frozenset({"отмена", "отмени", "стоп", "хватит", "выход", "замолчи", "отмени выключение", "отмена выключения", "отмени перезагрузку"})


def clean_phrase(value, wake_words=()) -> str:
    text = normalize(str(value))
    # The listener removes the address before handing the phrase to the pipeline.
    for wake in sorted((normalize(str(w)) for w in wake_words), key=len, reverse=True):
        if wake and (text == wake or text.startswith(wake + " ")):
            return text[len(wake):].strip()
    return text


def _integer(value, low, high, label):
    if isinstance(value, bool) or not re.fullmatch(r"\d+", str(value).strip()):
        raise ValueError(f"{label}: требуется целое число {low}–{high}.")
    number = int(value)
    if not low <= number <= high:
        raise ValueError(f"{label}: допустимо {low}–{high}.")
    return number


def validate_step(step):
    if not isinstance(step, dict) or step.get("action") not in ACTIONS:
        raise ValueError("Выбери поддерживаемое действие.")
    action = step["action"]
    title, _, field = ACTIONS[action]
    result = {"action": action}
    if field:
        value = str(step.get(field, "")).strip()
        if action == "set_volume":
            value = _integer(step.get(field), 0, 100, title)
        elif action == "set_timer":
            value = _integer(step.get(field), 1, 86400, title)
        elif action in POWER_ACTIONS:
            value = _integer(step.get(field), 10, 600, title)
        elif not value or len(value) > (2048 if action == "open_site" else 600):
            raise ValueError(f"{title}: заполни параметр (до 600 символов, URL — до 2048).")
        elif action == "open_site":
            try:
                url = urlsplit(value)
                valid = url.scheme in ("http", "https") and url.hostname and not url.username and not url.password
                _ = url.port
            except ValueError:
                valid = False
            if not valid or any(ch.isspace() for ch in value):
                raise ValueError("Сайт: нужен полный адрес http:// или https:// без логина и пароля.")
        elif action == "open_app":
            if (len(value) > 120 or re.search(r'[\\/:;&|<>"\r\n]', value)
                    or normalize(value).split()[0] in {"shutdown", "cmd", "powershell", "pwsh", "rundll32"}):
                raise ValueError("Приложение: укажи название из меню Пуск, не shell-команду или путь.")
        result[field] = value
    return result


def validate_entry(entry, wake_words=()):
    if not isinstance(entry, dict):
        raise ValueError("Неверный формат команды.")
    if not isinstance(entry.get("enabled", True), bool):
        raise ValueError("Включение команды должно быть true или false.")
    name = str(entry.get("name", "")).strip()
    if not name or len(name) > 80:
        raise ValueError("Название: от 1 до 80 символов.")
    raw = entry.get("phrases", [])
    if not isinstance(raw, list) or not 1 <= len(raw) <= 12:
        raise ValueError("Добавь 1–12 фраз, каждую с новой строки.")
    phrases = []
    for phrase in raw:
        if not isinstance(phrase, str):
            raise ValueError("Фразы должны быть строками.")
        text = clean_phrase(phrase, wake_words)
        if not text or len(text) > 160 or text in RESERVED:
            raise ValueError("Фраза пустая, слишком длинная или совпадает с командой отмены.")
        if text in phrases:
            raise ValueError("Две фразы совпали после нормализации.")
        phrases.append(text)
    steps = entry.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 6:
        raise ValueError("В сценарии должно быть от 1 до 6 действий.")
    steps = [validate_step(step) for step in steps]
    if any(s["action"] in POWER_ACTIONS for s in steps[:-1]):
        raise ValueError("Выключение или перезагрузка должны быть последним действием.")
    return {"builder_version": 1, "id": str(entry.get("id") or uuid4().hex),
            "name": name, "enabled": bool(entry.get("enabled", True)),
            "match": "exact", "phrases": phrases, "steps": steps, "reply": ""}


def entries(config):
    data = config.get("custom_commands", [])
    if not isinstance(data, list) or any(not isinstance(x, dict) for x in data):
        raise ValueError("custom_commands повреждён. Исправь формат config.json; данные не перезаписаны.")
    return deepcopy(data)


def save_entry(config, draft):
    current = entries(config)
    entry = validate_entry(draft, config.get("wake_words", []))
    existing = [i for i, x in enumerate(current) if x.get("id") == entry["id"]]
    if len(existing) > 1:
        raise ValueError("Повторяющийся ID в конфиге; данные не перезаписаны.")
    from jarvis import packs
    others = [x for x in current if x.get("id") != entry["id"]] + packs.load_active(config)
    if entry["enabled"]:
        used = {clean_phrase(p, config.get("wake_words", [])) for x in others if x.get("enabled", True)
                for p in x.get("phrases", []) if isinstance(p, str)}
        if used.intersection(entry["phrases"]):
            raise ValueError("Такая фраза уже есть в другой команде или активном паке.")
    if existing:
        if current[existing[0]].get("builder_version") != 1:
            raise ValueError("Старую команду нельзя перезаписывать конструктором.")
        current[existing[0]] = entry
    else:
        current.append(entry)
    if not config.set("custom_commands", current):
        raise OSError("Не удалось сохранить config.json. Изменения не применены.")
    return entry


def delete_entry(config, entry_id):
    current = entries(config)
    matches = [x for x in current if x.get("id") == entry_id and x.get("builder_version") == 1]
    if len(matches) != 1:
        raise ValueError("Команда изменилась или не найдена; обнови список.")
    if not config.set("custom_commands", [x for x in current if x.get("id") != entry_id]):
        raise OSError("Не удалось удалить команду. Данные не изменены.")


def describe_steps(steps):
    return " → ".join(ACTIONS.get(s.get("action"), ("Неизвестное действие",))[0]
                      for s in steps if isinstance(s, dict))
