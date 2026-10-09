"""Напоминания — обёртка над `timers`."""

from jarvis import timers


def timers_fast(handler, cmd: str) -> str | None:
    return timers.handle_timer_command(cmd)