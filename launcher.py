"""Лаунчер Феникса: молча запускает `pythonw -m jarvis` без окна консоли.

Собирается в exe и кладётся в корень проекта. Вычисляет рабочую папку
(где лежит exe) и интерпретатор (pythonw из PATH). Защищён от повторного
запуска именованным мьютексом.
"""

import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path

MUTEX_NAME = "Global\\JarvisPhoenixSingleInstance"

# №88: держим HANDLE мьютекса на уровне модуля, чтобы он не терялся.
# Без этого второй вызов already_running() в том же процессе вернул бы
# True ложно (мьютекс уже наш, но HANDLE потерян — Windows посчитала бы,
# что мы «уже запущены» и это не мы).
_MUTEX_HANDLE = None


def already_running() -> bool:
    """Проверяет, запущен ли уже Феникс.

    №88: HANDLE мьютекса сохраняется в _MUTEX_HANDLE. Пока процесс жив,
    мьютекс остаётся захваченным — второй запуск увидит ERROR_ALREADY_EXISTS.
    """
    global _MUTEX_HANDLE

    # Если уже проверяли в этом процессе — не создаём второй мьютекс.
    if _MUTEX_HANDLE is not None:
        return False

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    last_error = kernel32.GetLastError()

    if last_error == 183:  # ERROR_ALREADY_EXISTS
        # Мьютекс уже занят другим процессом — закрываем наш HANDLE
        if handle:
            kernel32.CloseHandle(handle)
        return True

    # Наш мьютекс — держим HANDLE до конца процесса.
    # НЕ закрываем — если закроем, мьютекс освободится и второй
    # запуск не увидит «уже запущен».
    _MUTEX_HANDLE = handle
    return False


def project_dir() -> Path:
    base = Path(sys.executable if getattr(sys, "frozen", False) else __file__)
    return base.resolve().parent


def find_pythonw() -> str:
    for name in ("pythonw.exe", "pythonw"):
        found = shutil.which(name)
        if found:
            return found
    cand = Path(sys.base_prefix) / "pythonw.exe"
    return str(cand) if cand.exists() else "pythonw"


def main() -> None:
    if already_running():
        return
    cwd = project_dir()
    pythonw = find_pythonw()
    creationflags = 0x08000000 | 0x00000008  # NO_WINDOW | DETACHED_PROCESS
    subprocess.Popen(
        [pythonw, "-m", "jarvis"],
        cwd=str(cwd),
        creationflags=creationflags,
        close_fds=True,
    )


if __name__ == "__main__":
    main()