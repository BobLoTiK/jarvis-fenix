"""Чистка устаревшего байткода после обновления файлов приложения.

Python считает ``__pycache__`` свежим по времени изменения и размеру исходника.
Когда файлы установленного Феникса заменяют вручную (скопировали .py поверх,
распаковали патч), метка времени может совпасть — и тогда продолжает
исполняться старый ``.pyc``. Внешне это выглядит так, будто правка «не
применилась», а при несовпадении набора модулей падает с ImportError, который
очень трудно связать с кэшем.

Поэтому при смене версии приложения кэш удаляется один раз. Ошибки доступа не
прерывают запуск: нечитаемый кэш — не повод не стартовать.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from jarvis import paths

log = logging.getLogger("jarvis.cache")

MARKER_NAME = "bytecode-version.txt"

# Тяжёлые и не относящиеся к нашему коду каталоги: там кэш либо чужой, либо
# создаётся пакетным менеджером и трогать его не наше дело.
_SKIP_DIRS = {".venv311", ".venv", "venv", "models", "voices", "logs", "secrets",
              "profiles", "comtypes-cache", "torch", "runtime"}


def marker_path() -> Path:
    """Файл, в котором записана версия, для которой кэш уже почищен."""
    return paths.user_dir() / MARKER_NAME


def purge_stale_bytecode(version: str, *, root: Path | None = None,
                         marker: Path | None = None) -> int:
    """Удаляет ``__pycache__`` в каталоге программы, если версия изменилась.

    Возвращает число удалённых каталогов (для логов и тестов).
    """
    root = Path(root) if root is not None else paths.program_dir()
    marker = Path(marker) if marker is not None else marker_path()
    try:
        previous = marker.read_text(encoding="utf-8").strip()
    except OSError:
        previous = ""
    if previous == str(version):
        return 0
    if not root.is_dir():
        log.debug("Каталог программы %s недоступен — кэш не чищу", root)
        return 0

    removed = 0
    for current, dirnames, _files in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in _SKIP_DIRS]
        for name in [item for item in dirnames if item == "__pycache__"]:
            target = Path(current) / name
            try:
                shutil.rmtree(target)
                removed += 1
            except OSError as error:
                log.debug("Кэш %s не удалён: %s", target, error)
            dirnames.remove(name)

    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(version), encoding="utf-8")
    except OSError as error:
        log.debug("Маркер кэша не записан: %s", error)
    if removed:
        log.info("Сброшен устаревший __pycache__: каталогов %d (версия %s)",
                 removed, version)
    return removed
