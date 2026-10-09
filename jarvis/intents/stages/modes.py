"""Режимы работы: commands / llm / combo.

`modes.handle_mode_command` возвращает (reply, new_mode).
Если режим изменился — пушим в history для отката.
"""

from jarvis import history, modes
from jarvis.intents.stages.base import Stage


class ModesStage(Stage):
    name = "modes"

    def handle(self, ctx):
        # Быстрый фильтр: если в фразе нет «режим» — не наше дело.
        if not any(w in ctx.cmd for w in ("режим", "комбо", "комбинирован")):
            return None

        h = ctx.handler
        prev_mode = h.mode
        reply, new_mode = modes.handle_mode_command(ctx.cmd, h.mode, h.config)
        if reply:
            if new_mode != prev_mode:
                history.push({
                    "action": "set_mode",
                    "prev_value": prev_mode,
                })
            h.mode = new_mode
            return reply
        return None