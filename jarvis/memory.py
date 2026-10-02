"""Память диалога на диске.

История диалога сохраняется в dialog.json при каждом ответе.
При старте — подгружается обратно. Ограничение — 200 последних сообщений.

Голосом: «что мы обсуждали», «забудь всё», «сохрани память».
"""

import json
import logging
import re
from pathlib import Path

log = logging.getLogger("jarvis.memory")

BASE_DIR = Path(__file__).resolve().parent.parent
MEMORY_FILE = BASE_DIR / "dialog.json"
MAX_MESSAGES = 200


def load() -> list:
    """Загружает историю диалога с диска. Возвращает список сообщений."""
    if not MEMORY_FILE.exists():
        return []
    try:
        data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            log.warning("dialog.json — не массив, игнорирую")
            return []
        log.info("Память диалога загружена: %d сообщений", len(data))
        return data[-MAX_MESSAGES:]
    except Exception:
        log.exception("Не удалось прочитать dialog.json")
        return []


def save(messages: list) -> None:
    """Сохраняет историю диалога на диск (последние MAX_MESSAGES)."""
    try:
        trimmed = list(messages)[-MAX_MESSAGES:]
        MEMORY_FILE.write_text(
            json.dumps(trimmed, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        log.exception("Не удалось сохранить dialog.json")


def clear() -> None:
    """Очищает память."""
    try:
        if MEMORY_FILE.exists():
            MEMORY_FILE.unlink()
        log.info("Память диалога очищена")
    except Exception:
        log.exception("Не удалось очистить dialog.json")


def describe(messages: list, limit: int = 6) -> str:
    """Краткий пересказ последних тем: «вы говорили о ...»."""
    if not messages:
        return "Пока ничего не обсуждали."
    user_msgs = [m.get("content", "") for m in messages
                 if m.get("role") == "user" and m.get("content")]
    if not user_msgs:
        return "Пока ничего не обсуждали."
    recent = user_msgs[-limit:]
    topics = ", ".join(f"«{t}»" for t in recent)
    return f"Последние темы: {topics}."


def handle_memory_command(cmd: str, messages: list) -> tuple[str | None, bool]:
    """Разбирает команды памяти.

    Возвращает (ответ_или_None, нужно_очистить_память).
    """
    # что обсуждали
    if re.search(r"(что|о\s+ч[её]м)\s+(мы\s+)?(обсуждал|говорил|болтал)", cmd) \
            or cmd in {"что мы обсуждали", "о чём мы говорили", "что обсуждали"}:
        return describe(messages), False

    # забудь всё
    if re.search(r"(забудь|очисти|сбрось|сотри)\s+(вс[её]|память|историю|диалог)", cmd) \
            or cmd in {"забудь всё", "очисти память", "сбрось память", "сотри память"}:
        clear()
        return "Память очищена.", True

    # сохрани память
    if re.search(r"(сохрани|запиши)\s+память", cmd) or cmd in {"сохрани память", "запиши память"}:
        save(messages)
        return "Память сохранена.", False

    return None, False