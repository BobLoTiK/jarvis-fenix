"""Стадии обработки команды. Порядок = приоритет.

Порядок критичен:
    1. cancel       — «стоп» перехватывает всё
    2. onboarding   — первый запуск, LLM-диалог
    3. correction   — «это не то, я сказал …» подменяет cmd
    4. password     — pending_password ждёт ответа
    5. memory       — команды памяти (clear, «что обсуждали»)
    6. pending      — pending_question ждёт уточнения
    7. clipboard    — 4 команды буфера
    8. modes        — commands / llm / combo
    9. compound     — «открой стим и запусти доту»
    10. fast        — реестр быстрых правил
    11. llm         — brain.parse / chat_stream
"""

from jarvis.intents.stages.cancel import CancelStage
from jarvis.intents.stages.onboarding import OnboardingStage
from jarvis.intents.stages.correction import CorrectionStage
from jarvis.intents.stages.password import PasswordStage
from jarvis.intents.stages.memory import MemoryStage
from jarvis.intents.stages.pending import PendingStage
from jarvis.intents.stages.clipboard import ClipboardStage
from jarvis.intents.stages.modes import ModesStage
from jarvis.intents.stages.compound import CompoundStage
from jarvis.intents.stages.fast import FastHandlersStage
from jarvis.intents.stages.llm import LLMStage


def build_pipeline(handler) -> list:
    """Собирает pipeline стадий. Порядок фиксирован."""
    return [
        CancelStage(),
        OnboardingStage(),
        CorrectionStage(),
        PasswordStage(),
        MemoryStage(),
        PendingStage(),
        ClipboardStage(),
        ModesStage(),
        CompoundStage(),
        FastHandlersStage(),
        LLMStage(),
    ]