"""Многослойные команды: «открой стим и запусти доту».

Разбиваем по « и » (с пробелами) или «, ».
Все части должны начинаться с глагола-команды — иначе это не compound,
а обычная фраза («добавь в список купить хлеб и молоко»).

Части уходят обратно в `_handle_single` рекурсией.
"""

import logging
import re

from jarvis.intents.stages.base import Stage
from jarvis.intents.verbs import COMMAND_VERBS

log = logging.getLogger("jarvis.intents")


class CompoundStage(Stage):
    name = "compound"

    def handle(self, ctx):
        parts = self._split(ctx.cmd)
        if not parts:
            return None

        replies = []
        for part in parts:
            sub = ctx.handler._handle_single(part)
            if isinstance(sub, str) and sub.strip():
                replies.append(sub.strip())
            # Если sub — генератор (chat_stream) — пропускаем.

        if replies:
            return ". ".join(replies) + "."
        return None

    def _split(self, cmd: str) -> list[str] | None:
        """Возвращает список частей или None, если не compound."""
        parts = re.split(r"\s+и\s+|,\s*", cmd)
        if len(parts) < 2:
            return None

        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) < 2:
            return None

        for part in parts:
            first = part.split()[0].lower() if part.split() else ""
            if first not in COMMAND_VERBS:
                return None

        return parts