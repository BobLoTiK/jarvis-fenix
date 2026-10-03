"""Списки задач.

Голосом:
    «добавь в список купить хлеб»             → добавляет
    «что в списке»                            → перечисляет
    «отметь хлеб выполненным»                 → помечает
    «убери хлеб из списка»                    → удаляет
    «очисти список»                           → удаляет всё

Хранение: tasks.json.
"""

import json
import logging
import re
import threading
from difflib import SequenceMatcher
from pathlib import Path

log = logging.getLogger("jarvis.tasks")

BASE_DIR = Path(__file__).resolve().parent.parent
TASKS_FILE = BASE_DIR / "tasks.json"
_lock = threading.Lock()


# ---------------------------------------------------------------
# Хранение
# ---------------------------------------------------------------

def _load() -> list:
    if not TASKS_FILE.exists():
        return []
    try:
        data = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        log.exception("Не удалось прочитать tasks.json")
        return []


def _save(tasks: list) -> None:
    try:
        tmp = TASKS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(TASKS_FILE)
    except Exception:
        log.exception("Не удалось сохранить tasks.json")


# ---------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------

def add(text: str) -> dict:
    """Добавляет задачу."""
    with _lock:
        tasks = _load()
        task = {
            "id": (max((t["id"] for t in tasks), default=0) + 1),
            "text": text.strip(),
            "done": False,
            "created_at": __import__("time").time(),
        }
        tasks.append(task)
        _save(tasks)
    log.info("Задача добавлена: %s", task["text"])
    return task


def find(query: str) -> dict | None:
    """Находит задачу по нечёткому совпадению."""
    tasks = _load()
    query_low = query.lower().strip()
    if not query_low:
        return None
    # 1. точная подстрока
    for t in tasks:
        if query_low in t["text"].lower():
            return t
    # 2. нечёткое совпадение
    best, best_ratio = None, 0.5
    for t in tasks:
        ratio = SequenceMatcher(None, query_low, t["text"].lower()).ratio()
        if ratio > best_ratio:
            best_ratio, best = ratio, t
    return best


def mark_done(query: str) -> dict | None:
    """Помечает задачу выполненной."""
    with _lock:
        tasks = _load()
        target = find(query)
        if not target:
            return None
        for t in tasks:
            if t["id"] == target["id"]:
                t["done"] = True
                _save(tasks)
                return t
    return None


def remove(query: str) -> dict | None:
    """Удаляет задачу."""
    with _lock:
        tasks = _load()
        target = find(query)
        if not target:
            return None
        tasks = [t for t in tasks if t["id"] != target["id"]]
        _save(tasks)
    return target


def clear_all() -> int:
    """Удаляет все задачи. Возвращает количество."""
    with _lock:
        tasks = _load()
        count = len(tasks)
        _save([])
    return count


# ---------------------------------------------------------------
# Озвучка
# ---------------------------------------------------------------

def format_list(tasks: list | None = None) -> str:
    """Человекочитаемый список для озвучки."""
    if tasks is None:
        tasks = _load()
    if not tasks:
        return "Список пуст."

    active = [t for t in tasks if not t.get("done")]
    done = [t for t in tasks if t.get("done")]

    parts = []
    if active:
        items = ", ".join(t["text"] for t in active[:15])
        parts.append(f"Активные: {items}")
    if done:
        items = ", ".join(t["text"] for t in done[:5])
        parts.append(f"Выполнено: {items}")
    return ". ".join(parts) + "."


# ---------------------------------------------------------------
# Обработка команд
# ---------------------------------------------------------------

def _extract_text(cmd: str, verb: str) -> str:
    """Вырезает текст задачи после глагола."""
    # убираем «в список», «из списка», «задачу» и т.п.
    text = re.sub(rf"^{verb}\s+", "", cmd, count=1)
    text = re.sub(r"^(в\s+список|в\s+задачи|задачу|задачу\s+в\s+список)\s*", "", text)
    text = re.sub(r"^(из\s+списка|из\s+задач|задачу)\s*", "", text)
    return text.strip(" ,.:!?")


def handle_task_command(cmd: str) -> str | None:
    """Разбирает команды списка задач. Возвращает ответ или None."""

    # показать список
    if re.search(r"(что|что\s+там)\s+в\s+списке", cmd) \
            or cmd in {"что в списке", "покажи список", "список задач", "мои задачи"}:
        return format_list()

    # очистить
    if re.search(r"(очисти|удали)\s+(весь\s+)?список", cmd) \
            or cmd in {"очисти список", "удали все задачи"}:
        n = clear_all()
        return f"Очищено задач: {n}." if n else "Список и так пуст."

    # отметить выполненным
    m = re.match(r"^(?:отметь|помечу|пометь|сделано|выполнено|готово)\s+(.+)$", cmd)
    if m:
        query = m.group(1).strip()
        query = re.sub(r"\s+(выполненным|сделанным|готовым)$", "", query)
        query = re.sub(r"^(задачу|задачу\s+)?", "", query)
        task = mark_done(query)
        if task:
            return f"Отметил: {task['text']}."
        return f"Задачу «{query}» не нашёл."

    # удалить одну
    m = re.match(r"^(?:убери|удали)\s+(?:из\s+списка\s+)?(.+)$", cmd)
    if m:
        query = m.group(1).strip()
        task = remove(query)
        if task:
            return f"Убрал: {task['text']}."
        return f"Задачу «{query}» не нашёл."

    # добавить
    m = re.match(r"^(?:добавь|запиши|внеси)\s+(?:в\s+список\s+|в\s+задачи\s+)?(.+)$", cmd)
    if m:
        text = m.group(1).strip(" ,.:!?")
        if not text:
            return "Что добавить?"
        task = add(text)
        return f"Добавил: {task['text']}."

    return None