"""«Расскажи шутку» — свой банк реплик вместо импровизации LLM.

Ловим только общие просьбы. «Шутку про кота» оставляем LLM: у нас нет
тематических шуток, и отвечать не по теме хуже, чем импровизировать.
"""

from jarvis import jokes

_TRIGGERS = (
    "шутк",
    "анекдот",
    "пошути",
    "развесели",
    "рассмеши",
)


def joke_fast(handler, cmd: str) -> str | None:
    text = cmd.lower()
    if "про " in text:
        return None
    if not any(trigger in text for trigger in _TRIGGERS):
        return None
    return jokes.next_joke()
