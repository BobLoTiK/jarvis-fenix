"""Реестр быстрых обработчиков.

Порядок = приоритет. Специфичные — ВЫШЕ общих.
open_profile ВЫШЕ open — иначе open_fast съест «открой профиль».

Каждая функция: (handler, cmd) -> str | None.
"""

from jarvis.intents.fast.custom import match_custom, load_custom
from jarvis.intents.fast.small_talk import small_talk
from jarvis.intents.fast.music import music_fast
from jarvis.intents.fast.screenshot import screenshot_fast
from jarvis.intents.fast.open import open_fast, open_profile_fast
from jarvis.intents.fast.voices import voices_fast
from jarvis.intents.fast.packs import packs_fast
from jarvis.intents.fast.timers import timers_fast
from jarvis.intents.fast.tasks import tasks_fast
from jarvis.intents.fast.persona import persona_fast
from jarvis.intents.fast.profile import profile_fast
from jarvis.intents.fast.memory import memory_fast
from jarvis.intents.fast.system import system_fast
from jarvis.intents.fast.debug import debug_fast
from jarvis.intents.fast.undo import undo_fast
from jarvis.intents.fast.correction import correction_fast
from jarvis.intents.fast.weather import weather_currency_fast


__all__ = ["build_registry", "load_custom", "match_custom"]


def build_registry(handler) -> list:
    """Собирает реестр для конкретного handler'а."""
    return [
        ("custom",           lambda cmd: match_custom(handler, cmd)),
        ("small_talk",       lambda cmd: small_talk(handler, cmd)),
        ("music",            lambda cmd: music_fast(handler, cmd)),
        ("screenshot",       lambda cmd: screenshot_fast(handler, cmd)),
        ("open_profile",     lambda cmd: open_profile_fast(handler, cmd)),
        ("open",             lambda cmd: open_fast(handler, cmd)),
        ("voices",           lambda cmd: voices_fast(handler, cmd)),
        ("packs",            lambda cmd: packs_fast(handler, cmd)),
        ("timers",           lambda cmd: timers_fast(handler, cmd)),
        ("tasks",            lambda cmd: tasks_fast(handler, cmd)),
        ("persona",          lambda cmd: persona_fast(handler, cmd)),
        ("profile",          lambda cmd: profile_fast(handler, cmd)),
        ("memory",           lambda cmd: memory_fast(handler, cmd)),
        ("system",           lambda cmd: system_fast(handler, cmd)),
        ("debug",            lambda cmd: debug_fast(handler, cmd)),
        ("correction",       lambda cmd: correction_fast(handler, cmd)),
        ("undo",             lambda cmd: undo_fast(handler, cmd)),
        ("weather_currency", lambda cmd: weather_currency_fast(handler, cmd)),
    ]