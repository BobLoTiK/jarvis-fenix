"""Отмена последнего действия («не то», «отмени»)."""

import re

from jarvis import actions, history, modes, voices
from jarvis.intents.execute import _do_close


def undo_fast(handler, cmd: str) -> str | None:
    if not re.search(r"(не\s+то|отмени|верни\s+как\s+было|откат)", cmd):
        return None

    item = history.pop()
    if not item:
        return "Нечего отменять."

    action = item.get("action")

    if action == "macro":
        steps = item.get("steps") or []
        if not steps:
            return "Нечего отменять."
        results = []
        for step in reversed(steps):
            s_action = step.get("action")
            s_target = step.get("target")
            if s_action == "open_app" and s_target:
                results.append(_do_close(handler, s_target))
        if results:
            return "Откатываю макрос: " + "; ".join(results)
        return "Макрос отменён."

    if action == "open_app":
        target = item.get("target") or ""
        if target:
            return f"Откатываю: {_do_close(handler, target)}"

    if action == "set_mode":
        prev = item.get("prev_value")
        if prev:
            reply = modes.set_mode(prev, handler.config)
            handler.mode = prev
            return f"Вернул режим: {reply}"

    if action == "change_voice":
        prev = item.get("prev_value")
        if prev:
            reply = voices.switch(prev, handler.config)
            return f"Вернул голос: {reply}"

    if action == "set_volume":
        prev = item.get("prev_value")
        if prev is not None:
            actions.set_volume(int(prev))
            return f"Вернул громкость: {prev}%."

    if action == "set_brightness":
        prev = item.get("prev_value")
        if prev is not None:
            actions.set_brightness(int(prev))
            return f"Вернул яркость: {prev}%."

    if action == "switch_layout":
        actions.switch_layout()
        return "Переключил раскладку обратно."

    return f"Действие «{action}» отменить нельзя."