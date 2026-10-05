"""Память диалога — на профиль.

Архитектура:
    profiles/<user>/dialog.json  — история диалога пользователя.

API чистое:
    load(limit)         — читает последние N сообщений.
    append(message)     — добавляет одно сообщение на диск.
    clear()             — очищает историю текущего профиля.
    describe(messages)  — пересказ для озвучки.
    handle_memory_command(cmd, messages) — команды памяти.

Лимиты — НЕ здесь. Их задаёт вызывающий (IntentHandler) из config.
"""

import json
import logging
import re
import threading
from pathlib import Path

from jarvis import profile as _profile

log = logging.getLogger("jarvis.memory")

_lock = threading.Lock()


# ---------------------------------------------------------------
# Чтение / запись
# ---------------------------------------------------------------

def load(limit: int | None = None) -> list:
    """Загружает историю диалога. Без limit — все сообщения."""
    path = _profile.dialog_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            log.warning("%s — не массив, игнорирую", path)
            return []
        if limit and limit > 0:
            return data[-limit:]
        return data
    except Exception:
        log.exception("Не удалось прочитать %s", path)
        return []


def append(message: dict) -> None:
    """Добавляет одно сообщение и пишет на диск."""
    if not isinstance(message, dict):
        return
    path = _profile.dialog_path()
    with _lock:
        try:
            data = []
            if path.exists():
                raw = path.read_text(encoding="utf-8")
                if raw.strip():
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        data = parsed
            data.append(message)
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            log.exception("Не удалось дописать в %s", path)


def clear() -> None:
    """Очищает память текущего профиля."""
    path = _profile.dialog_path()
    try:
        if path.exists():
            path.unlink()
        log.info("Память диалога очищена: %s", path)
    except Exception:
        log.exception("Не удалось очистить %s", path)


# ---------------------------------------------------------------
# Команды / описание
# ---------------------------------------------------------------

def describe(messages: list, limit: int = 6) -> str:
    """Краткий пересказ последних тем."""
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
    if re.search(r"(что|о\s+ч[её]м)\s+(мы\s+)?(обсуждал|говорил|болтал)", cmd) \
            or cmd in {"что мы обсуждали", "о чём мы говорили", "что обсуждали"}:
        return describe(messages), False

    if re.search(r"(забудь|очисти|сбрось|сотри)\s+(вс[её]|память|историю|диалог)", cmd) \
            or cmd in {"забудь всё", "очисти память", "сбрось память", "сотри память"}:
        clear()
        return "Память очищена.", True

    if re.search(r"(сохрани|запиши)\s+память", cmd) \
            or cmd in {"сохрани память", "запиши память"}:
        return "Память сохраняется автоматически.", False

    return None, False