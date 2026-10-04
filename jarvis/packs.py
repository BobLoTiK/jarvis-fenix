"""Загрузка и выгрузка паков команд из папки packs/."""

import json
import logging
import re
from pathlib import Path

log = logging.getLogger("jarvis.packs")

BASE_DIR = Path(__file__).resolve().parent.parent
PACKS_DIR = BASE_DIR / "packs"

# Алиасы имён паков: что говорит пользователь → имя файла
_PACK_ALIASES = {
    "игр": "games", "игры": "games", "игра": "games",
    "играм": "games", "игру": "games", "гейм": "games", "геймс": "games",
    "приложение": "apps", "приложения": "apps", "приложению": "apps",
    "приложений": "apps", "прог": "apps", "проги": "apps", "прогу": "apps",
    "сайт": "sites", "сайты": "sites", "сайтов": "sites", "сайту": "sites",
    "работа": "work", "работы": "work", "работу": "work", "рабочий": "work",
    "система": "system", "системы": "system", "систем": "system",
    "системный": "system", "системные": "system",
}


def normalize_name(name: str) -> str:
    """Приводит «игр» → «games», «приложение» → «apps» и т.п."""
    n = name.strip().lower().rstrip(".,!?")
    return _PACK_ALIASES.get(n, n)


def list_available() -> list[str]:
    if not PACKS_DIR.exists():
        return []
    return sorted(p.stem for p in PACKS_DIR.glob("*.json"))


def load_pack(name: str) -> list | None:
    name = normalize_name(name)
    path = PACKS_DIR / f"{name}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            log.warning("Пак %s — не массив, игнорирую", name)
            return None
        return data
    except Exception:
        log.exception("Не удалось прочитать пак %s", name)
        return None


def load_active(config) -> list:
    active = config.get("active_packs", [])
    result = []
    for name in active:
        pack = load_pack(name)
        if pack:
            result.extend(pack)
            log.info("Пак '%s': загружено %d команд", name, len(pack))
    return result


def save_active(active: list[str], config=None) -> None:
    if config is not None:
        config.set("active_packs", sorted(set(active)))
    else:
        from jarvis import config_manager
        config_manager.update("active_packs", sorted(set(active)))
    log.info("Активные паки сохранены: %s", active)


def handle_pack_command(cmd: str, current_active: list[str], config=None) -> tuple[str | None, list[str]]:
    available = list_available()

    if re.search(r"(какие|список|покажи)\s+пак", cmd) \
            or cmd in {"какие паки", "список паков", "покажи паки"}:
        if not available:
            return "Папка packs пуста.", current_active
        active_str = ", ".join(current_active) if current_active else "нет"
        return f"Доступны: {', '.join(available)}. Активны: {active_str}.", current_active

    m = re.search(r"(загрузи|включи|подключи)\s+пак\s+(\S+)", cmd)
    if m:
        name = normalize_name(m.group(2))
        if name not in available:
            return f"Пак '{name}' не найден. Доступны: {', '.join(available)}.", current_active
        if name in current_active:
            return f"Пак '{name}' уже активен.", current_active
        new_active = current_active + [name]
        save_active(new_active, config)
        return f"Пак '{name}' загружен.", new_active

    if re.search(r"(активируй|загрузи|включи|подключи)\s+все\s+пак", cmd) \
            or cmd in {"активируй все паки", "загрузи все паки", "включи все паки"}:
        if not available:
            return "Папка packs пуста.", current_active
        new_active = sorted(set(current_active + available))
        save_active(new_active, config)
        return f"Активированы все паки: {', '.join(available)}.", new_active

    if re.search(r"(выгрузи|отключи|убери)\s+все\s+пак", cmd) \
            or cmd in {"выгрузи все паки", "отключи все паки"}:
        save_active([], config)
        return "Все паки выгружены.", []

    m = re.search(r"(выгрузи|отключи|убери)\s+пак\s+(\S+)", cmd)
    if m:
        name = normalize_name(m.group(2))
        if name not in current_active:
            return f"Пак '{name}' и так не активен.", current_active
        new_active = [p for p in current_active if p != name]
        save_active(new_active, config)
        return f"Пак '{name}' выгружен.", new_active

    return None, current_active