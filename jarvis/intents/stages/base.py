"""Базовая стадия pipeline."""

from typing import Iterator, Optional

from jarvis.intents.context import Ctx


class Stage:
    """Одна стадия pipeline.

    Возвращает:
        str              — команда обработана, это ответ
        Iterator[str]    — стрим (chat_stream)
        None             — пропустить дальше
    """
    name: str = "base"

    def handle(self, ctx: Ctx) -> Optional[object]:
        raise NotImplementedError