"""Паки команд — обёртка с side-effect.

`packs.handle_pack_command` возвращает (reply, new_active).
Если active изменился — обновляем handler.active_packs
и перечитываем custom-команды.
"""

from jarvis import packs


def packs_fast(handler, cmd: str) -> str | None:
    reply, new_active = packs.handle_pack_command(
        cmd, handler.active_packs, handler.config
    )
    if reply:
        if new_active != handler.active_packs:
            handler.active_packs = new_active
            _reload_packs(handler)
        return reply
    return None


def _reload_packs(handler) -> None:
    """Пересобрать handler.custom после смены активных паков."""
    from jarvis.intents.fast.custom import load_packs_as_custom
    handler.custom = (list(handler._config_custom_original)
                      + load_packs_as_custom(handler.config))