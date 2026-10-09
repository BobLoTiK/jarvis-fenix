"""Применение коррекции «это не то» перед разбором команды.

Ищем в `learning.find_correction`: если для команды сохранена
коррекция (пользователь раньше сказал «это не то, я сказал логи») —
подменяем cmd.
"""

import logging

from jarvis import learning
from jarvis.intents.stages.base import Stage

log = logging.getLogger("jarvis.intents")


class CorrectionStage(Stage):
    name = "correction"

    def handle(self, ctx):
        corrected = learning.find_correction(ctx.cmd)
        if corrected and corrected != ctx.cmd:
            log.info("Применена коррекция: %r → %r", ctx.cmd, corrected)
            ctx.cmd = corrected
        return None