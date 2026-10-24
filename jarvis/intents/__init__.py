"""Стадии обработки команды. Порядок = приоритет.

Порядок критичен:
    1. cancel       — явная отмена
    2. pending      — ответ на текущий слот; возврат в обычный pipeline
    3. onboarding   — первый запуск
    4. correction   — сохранённые коррекции (не для ответа на слот)
    5. password     — защита опасных действий
    6. memory       — команды памяти
    7. clipboard    — команды буфера
    8. modes        — commands / llm / combo
    9. compound     — составные команды
    10. clarification — недостающий target/time/unit
    11. fast        — реестр быстрых правил
    12. llm         — brain.parse / chat_stream
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
from jarvis.intents.stages.clarification import ClarificationStage


def build_pipeline(handler) -> list:
    """Собирает pipeline стадий. Порядок фиксирован."""
    return [
        CancelStage(),
        PendingStage(),
        OnboardingStage(),
        CorrectionStage(),
        PasswordStage(),
        MemoryStage(),
        ClipboardStage(),
        ModesStage(),
        CompoundStage(),
        ClarificationStage(),
        FastHandlersStage(),
        LLMStage(),
    ]