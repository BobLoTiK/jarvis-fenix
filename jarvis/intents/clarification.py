"""Запрос недостающего слота до fast/LLM, без выполнения догадок."""

from jarvis.intents.clarification import begin
from jarvis.intents.stages.base import Stage


class ClarificationStage(Stage):
    name = "clarification"

    def handle(self, ctx):
        return begin(ctx)
