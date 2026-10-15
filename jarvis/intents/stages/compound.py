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
            from jarvis.language import analyze_command
            analysis = analyze_command(part)
            if analysis.issue:
                return analysis.issue
            sub = ctx.handler._handle_single(normalize(analysis.command))
            if isinstance(sub, str) and sub.strip():
                replies.append(sub.strip())
            # Если sub — генератор (chat_stream) — пропускаем.

        if replies:
            return ". ".join(replies) + "."
        return None

    def _split(self, ctx) -> list[str] | None:
        """Возвращает исходные части или None, если не compound.

        Режем СЫРУЮ фразу (handler._raw_cmd): normalize() удаляет запятые,
        поэтому split по «, » на нормализованном тексте никогда не срабатывал
        и «сделай скриншот, покажи буфер» оставалось одной командой.
        """
        h = ctx.handler
        raw = getattr(h, "_raw_cmd", "") or ""
        # Сырую фразу берём только на верхнем уровне: в рекурсии ctx.cmd —
        # это уже часть, и повторный split по всему raw зациклил бы разбор.
        from jarvis.language import analyze_command
        source = raw if normalize(analyze_command(raw).command) == ctx.cmd else ctx.cmd

        parts = re.split(r"\s+и\s+|(?<!\d),\s*|,(?!\d)\s*", source)
        if len(parts) < 2:
            return None

        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) < 2:
            return None

        for part in parts:
            tokens = normalize(part).split()
            first = tokens[0] if tokens else ""
            if first not in COMMAND_VERBS:
                return None

        return parts