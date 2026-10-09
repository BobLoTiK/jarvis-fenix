"""Скриншот: «сделай скриншот», «открой скриншот».

Первая команда сохраняет в ~/Pictures/Screenshots.
Вторая — открывает последний сделанный.
"""

import re

from jarvis import actions


def screenshot_fast(handler, cmd: str) -> str | None:
    if not re.search(r"скрин|снимок экрана", cmd):
        return None

    # «открой скриншот» / «покажи скриншот» — открыть последний.
    if re.search(r"откр|покаж", cmd):
        if handler.last_file:
            actions.open_path(handler.last_file)
            return "Открываю."
        return "Пока нечего открывать."

    # Иначе — сделать новый.
    path = actions.take_screenshot()
    handler.last_file = path
    return f"Скриншот сохранён в папку {path.parent.name}."