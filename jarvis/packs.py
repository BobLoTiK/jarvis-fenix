"""Загрузка и выгрузка паков команд из папки packs/.

Пак — JSON-файл с массивом команд в формате custom_commands.
Активные паки хранятся в config.json в поле "active_packs".

Голосом: «загрузи пак игр», «выгрузи пак игр», «какие паки».
Запись — через config_manager (единый FileLock, атомарная замена).
"""

import json
import logging
import re
from pathlib import Path

from jarvis import config_manager

log = logging.getLogger("jarvis.packs")

BASE_DIR = Path(__file__).resolve().parent.parent
PACKS_DIR = BASE_DIR / "packs"


def list_available() -> list[str]:
    if not PACKS_DIR.exists():
        return []
    return sorted(p.stem for p in PACKS_DIR.glob("*.json"))


def load_pack(name: str) -> list | None:
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


def load_active(config: dict) -> list:
    active = config.get("active_packs", [])
    result = []
    for name in active:
        pack = load_pack(name)
        if pack:
            result.extend(pack)
            log.info("Пак '%s': загружено %d команд", name, len(pack))
    return result


def save_active(active: list[str]) -> None:
    if config_manager.update("active_packs", sorted(set(active))):
        log.info("Активные паки сохранены: %s", active)
    else:
        log.error("Не удалось сохранить active_packs")


def handle_pack_command(cmd: str, current_active: list[str]) -> tuple[str | None, list[str]]:
    available = list_available()

    if re.search(r"(какие|список|покажи)\s+пак", cmd) \
            or cmd in {"какие паки", "список паков", "покажи паки"}:
        if not available:
            return "Папка packs пуста.", current_active
        active_str = ", ".join(current_active) if current_active else "нет"
        return f"Доступны: {', '.join(available)}. Активны: {active_str}.", current_active

    m = re.search(r"(загрузи|включи|подключи)\s+пак\s+(\S+)", cmd)
    if m:
        name = m.group(2).strip().rstrip(".")
        if name not in available:
            return f"Пак '{name}' не найден. Доступны: {', '.join(available)}.", current_active
        if name in current_active:
            return f"Пак '{name}' уже активен.", current_active
        new_active = current_active + [name]
        save_active(new_active)
        return f"Пак '{name}' загружен.", new_active

    # «активируй все паки» / «загрузи все паки»
    if re.search(r"(активируй|загрузи|включи|подключи)\s+все\s+пак", cmd) \
            or cmd in {"активируй все паки", "загрузи все паки", "включи все паки"}:
        if not available:
            return "Папка packs пуста.", current_active
        new_active = sorted(set(current_active + available))
        save_active(new_active)
        return f"Активированы все паки: {', '.join(available)}.", new_active

    # «выгрузи все паки» / «отключи все паки»
    if re.search(r"(выгрузи|отключи|убери)\s+все\s+пак", cmd) \
            or cmd in {"выгрузи все паки", "отключи все паки"}:
        save_active([])
        return "Все паки выгружены.", []

    m = re.search(r"(выгрузи|отключи|убери)\s+пак\s+(\S+)", cmd)
    if m:
        name = m.group(2).strip().rstrip(".")
        if name not in current_active:
            return f"Пак '{name}' и так не активен.", current_active
        new_active = [p for p in current_active if p != name]
        save_active(new_active)
        return f"Пак '{name}' выгружен.", new_active

    return None, current_active