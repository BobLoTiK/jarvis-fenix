"""Команды памяти диалога.

`memory.handle_memory_command` возвращает (reply, clear_requested).
Если clear_requested — очищаем dialog.
"""

from jarvis import memory
from jarvis.intents.stages.base import Stage


class MemoryStage(Stage):
    name = "memory"

    def handle(self, ctx):
        h = ctx.handler
        reply, clear = memory.handle_memory_command(ctx.cmd, list(h.dialog))
        if reply:
            if clear:
                h.dialog.clear()
            return reply
        return None