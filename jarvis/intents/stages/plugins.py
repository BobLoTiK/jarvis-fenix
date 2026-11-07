"""Стадия плагинов: фразы плагина идут тем же pipeline, что и обычные команды.

Второго разбора команд нет: стадия стоит после быстрых обработчиков и получает
уже нормализованный текст. `handler.plugins is None` — плагины не настроены,
стадия молчит и поведение прежнее.
"""

import logging

from jarvis.intents.stages.base import Stage

log = logging.getLogger("jarvis.intents")


class PluginStage(Stage):
    name = "plugins"

    def handle(self, ctx):
        plugins = getattr(ctx.handler, "plugins", None)
        if plugins is None:
            return None
        try:
            reply = plugins.try_handle(ctx.cmd)
        except Exception:
            log.exception("Плагины упали на %r", ctx.cmd)
            return "Плагин не смог обработать команду."
        if reply:
            log.debug("Команда %r обработана плагином", ctx.cmd)
            return reply
        return None
