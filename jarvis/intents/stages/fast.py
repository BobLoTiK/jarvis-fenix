"""Вызов реестра быстрых обработчиков.

Реестр собирается один раз в `IntentHandler.__init__` через
`fast.build_registry(handler)`. Порядок = приоритет.

Исключение в обработчике — логируется, не роняет команду.
"""

import logging

from jarvis.intents.stages.base import Stage

log = logging.getLogger("jarvis.intents")


class FastHandlersStage(Stage):
    name = "fast"

    def handle(self, ctx):
        for name, fn in ctx.handler._fast_handlers_cache:
            try:
                reply = fn(ctx.cmd)
            except Exception:
                log.exception("Обработчик %s упал на %r", name, ctx.cmd)
                continue
            if reply:
                log.debug("Команда %r обработана: %s", ctx.cmd, name)
                return reply
        return None