"""Prepare the native Flet client inside the consented bootstrap stage."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def prepare():
    from jarvis.https_trust import configure_https_trust
    configure_https_trust()
    # Public API present in the supported Flet 1.0.3+ line. No GUI is opened.
    from flet_desktop import ensure_client_cached
    cache = Path(ensure_client_cached())
    if not cache.is_dir() or not (cache / "flet" / "flet.exe").is_file():
        raise RuntimeError("Native Flet client is missing after preparation")
    return cache


def main():
    try:
        cache = prepare()
    except Exception as exc:
        print("FLET_CLIENT_FAILED:" + type(exc).__name__, file=sys.stderr)
        return 1
    print("FLET_CLIENT_READY")
    print(cache)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
