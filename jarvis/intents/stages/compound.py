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
from jarvis.text_utils import normalize

log = logging.getLogger("jarvis.intents")


class CompoundStage(Stage):
    name = "compound"

    def handle(self, ctx):
        parts = self._split(ctx)
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

    def _split(self, ctx) -> list[str] | None:
        """Возвращает нормализованные части или None, если не compound.

        Режем СЫРУЮ фразу (handler._raw_cmd): normalize() удаляет запятые,
        поэтому split по «, » на нормализованном тексте никогда не срабатывал
        и «сделай скриншот, покажи буфер» оставалось одной командой.
        """
        h = ctx.handler
        raw = getattr(h, "_raw_cmd", "") or ""
        # Сырую фразу берём только на верхнем уровне: в рекурсии ctx.cmd —
        # это уже часть, и повторный split по всему raw зациклил бы разбор.
        source = raw if normalize(raw) == ctx.cmd else ctx.cmd

        parts = re.split(r"\s+и\s+|,\s*", source)
        if len(parts) < 2:
            return None

        parts = [normalize(p) for p in parts if p.strip()]
        if len(parts) < 2:
            return None

        for part in parts:
            first = part.split()[0] if part.split() else ""
            if first not in COMMAND_VERBS:
                return None

        return parts