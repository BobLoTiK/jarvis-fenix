"""Задачи — обёртка над `tasks`."""

from jarvis import tasks


def tasks_fast(handler, cmd: str) -> str | None:
    return tasks.handle_task_command(cmd)