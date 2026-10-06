"""История последних действий для отмены («стоп, не то»).

Стек на 5 действий. Каждое — dict с полем `action` и данными для отката.

Пример:
    history.push({
        "action": "open_app",
        "target": "дискорд",
        "prev_value": None,
    })

При откате:
    item = history.pop()
    if item["action"] == "open_app":
        actions.kill_process(...)
"""

import logging
import threading
from collections import deque

log = logging.getLogger("jarvis.history")

_MAX = 5
_stack: deque = deque(maxlen=_MAX)
_lock = threading.Lock()


def push(item: dict) -> None:
    """Кладёт действие в стек. Отбрасывает лишнее."""
    if not isinstance(item, dict) or "action" not in item:
        return
    with _lock:
        _stack.append(item)
    log.info("История: +%s (всего %d)", item.get("action"), len(_stack))
    
def push_macro(steps: list) -> None:
    """Кладёт макрос как ОДНУ запись в историю.

    steps — список dict с action/target (то же, что _execute_steps принимает).
    """
    if not isinstance(steps, list) or not steps:
        return
    # Отбрасываем steps с action="wait" — их откатывать нечего
    real_steps = [s for s in steps
                  if isinstance(s, dict) and s.get("action") not in ("wait",)]
    if not real_steps:
        return
    push({"action": "macro", "steps": real_steps})


def pop() -> dict | None:
    """Достаёт последнее действие. Возвращает None, если пусто."""
    with _lock:
        if not _stack:
            return None
        return _stack.pop()


def peek() -> dict | None:
    """Смотрит последнее действие без удаления."""
    with _lock:
        if not _stack:
            return None
        return _stack[-1]


def clear() -> None:
    with _lock:
        _stack.clear()


def size() -> int:
    with _lock:
        return len(_stack)