"""Голоса Piper — обёртка над модулем `voices`.

Никакой своей логики. Просто передаём cmd в `voices.handle_voice_command`.
"""

from jarvis import voices


def voices_fast(handler, cmd: str) -> str | None:
    return voices.handle_voice_command(cmd, handler.config)