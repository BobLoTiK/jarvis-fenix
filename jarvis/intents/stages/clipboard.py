"""4 команды буфера обмена. Все — до LLM.

Скопировать выделенное, скопировать свой ответ,
прочитать буфер, очистить буфер.
"""

import logging
import re
import time

from jarvis import actions
from jarvis.intents.stages.base import Stage

log = logging.getLogger("jarvis.intents")


class ClipboardStage(Stage):
    name = "clipboard"

    def handle(self, ctx):
        cmd = ctx.cmd

        if (re.search(r"скопируй\s+(выделенное|выделенный|это\s+выделенное)", cmd)
                or re.search(r"(выдели|выделенное)\s+(и\s+)?скопируй", cmd)
                or cmd in {"скопируй выделенное", "скопируй это выделенное"}):
            return self._copy_selection()

        if (re.search(r"скопируй\s+(свой\s+)?(ответ|ответь|последнее|сказанное)", cmd)
                or cmd in {"скопируй свой ответ", "скопируй ответ", "скопируй что ты сказал"}):
            return self._copy_last_reply(ctx)

        if (re.search(r"(что|чё)\s+(в\s+)?буфере", cmd)
                or re.search(r"(покажи|прочитай|что)\s+буфер", cmd)
                or cmd in {"что скопировано", "что в буфере"}):
            return self._read_buffer()

        if (re.search(r"(очисти|сотри|удали)\s+буфер", cmd)
                or cmd in {"очисти буфер", "сотри буфер"}):
            return self._clear_buffer()

        return None

    def _copy_selection(self) -> str:
        if not actions.copy_selection():
            return "Не удалось скопировать."
        time.sleep(0.15)
        text = actions.clipboard_read()
        if text:
            short = text[:200] + ("..." if len(text) > 200 else "")
            return f"Скопировал: {short}"
        return "Скопировал выделенное."

    def _copy_last_reply(self, ctx) -> str:
        last = ctx.handler._last_reply
        if not last:
            return "Нечего копировать."
        ok = actions.clipboard_write(last)
        return "Скопировал свой ответ в буфер." if ok else "Не удалось скопировать."

    def _read_buffer(self) -> str:
        text = actions.clipboard_read()
        if not text:
            return "Буфер обмена пуст."
        return f"В буфере: {text[:400]}"

    def _clear_buffer(self) -> str:
        ok = actions.clipboard_clear()
        return "Буфер очищен." if ok else "Не удалось очистить буфер."