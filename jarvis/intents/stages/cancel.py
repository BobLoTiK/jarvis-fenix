"""«Стоп», «хватит», «отбой» — самый первый этап."""

from jarvis.intents.stages.base import Stage
from jarvis.intents.verbs import CANCEL


class CancelStage(Stage):
    name = "cancel"

    def handle(self, ctx):
        if ctx.cmd in CANCEL:
            h = ctx.handler
            h._pending_password = None
            h._pending_question = None
            h._reset_requested = True
            return "Жду обращение, сэр."
        return None