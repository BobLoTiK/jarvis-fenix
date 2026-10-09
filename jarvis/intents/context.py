"""Контекст, который передаётся между стадиями pipeline."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Ctx:
    """Одна команда и её окружение.

    cmd         — текущая команда (может измениться после коррекции)
    original_cmd — исходная команда (до коррекции) — для логов
    handler     — ссылка на IntentHandler
    state       — словарь для передачи данных между стадиями
    """
    cmd: str
    original_cmd: str = ""
    handler: Any = None
    state: dict = field(default_factory=dict)