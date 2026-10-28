"""Nuitka application entry. Never starts an external Python interpreter."""
import multiprocessing
from pathlib import Path

from jarvis.compiled_runtime import run


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(run(root=Path(__file__).resolve().parent,
                         compiled=globals().get("__compiled__") is not None))
