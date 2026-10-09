"""Коррекция: «это не то, я сказал логи».

Сохраняет связку (wrong → right) в learning.
Работает через handler._last_cmd — он запоминается в handle().
"""

import re

from jarvis import learning


def correction_fast(handler, cmd: str) -> str | None:
    m = re.match(
        r"^(?:это\s+)?не\s+то\s*,?\s*(?:я\s+сказал[а]?\s+)?(.+)$",
        cmd,
    )
    if not m:
        return None

    right = m.group(1).strip(" ,.:!?")
    if not right:
        return None

    wrong = handler._last_cmd
    if wrong and wrong != cmd:
        learning.add_correction(wrong, right)
        return f"Понял, запомнил. Повторяю: {right}."
    return "Что было не так?"