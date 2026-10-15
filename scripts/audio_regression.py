"""Run optional local audio regression tools; ordinary pytest never loads models."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == "__main__":
    from tests.audio.runner import main

    raise SystemExit(main())
