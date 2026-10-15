"""Opt-in install of one local pre-commit hook; preserve all existing hooks/config."""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def install(root):
    result = git(root, "rev-parse", "--show-toplevel")
    if result.returncode:
        raise RuntimeError(
            "Not a Git working tree; initialize/open the project repository first"
        )
    root = Path(result.stdout.strip())
    configured = git(root, "config", "--get", "core.hooksPath")
    if configured.returncode not in (0, 1):
        raise RuntimeError("Cannot read core.hooksPath")
    if configured.returncode == 0:
        raise RuntimeError(
            "core.hooksPath is already configured; integrate scripts/check_staged_snapshot.py into your existing hook manually"
        )
    result = git(root, "rev-parse", "--git-path", "hooks")
    if result.returncode:
        raise RuntimeError("Cannot locate Git hooks directory")
    hooks = Path(result.stdout.strip())
    if not hooks.is_absolute():
        hooks = root / hooks
    template = (root / ".githooks/pre-commit").read_bytes().replace(b"\r\n", b"\n")
    if (
        not template.startswith(b"#!/bin/sh\n")
        or b"fenix-snapshot-pre-commit-v1" not in template
    ):
        raise RuntimeError("Hook template is missing or incompatible")
    if not (root / "scripts/check_staged_snapshot.py").is_file():
        raise RuntimeError("Staged snapshot checker is missing")
    destination = hooks / "pre-commit"
    if destination.is_symlink():
        raise RuntimeError("Existing symlink hook will not be replaced")
    if destination.exists():
        if destination.read_bytes() != template:
            raise RuntimeError(
                "Existing pre-commit hook preserved; integrate the checker manually"
            )
    else:
        hooks.mkdir(parents=True, exist_ok=True)
        # Exclusive creation: never clobber an existing hook, including a race.
        with destination.open("xb") as stream:
            stream.write(template)
    destination.chmod(destination.stat().st_mode | 0o111)
    print(
        "Installed local snapshot pre-commit check; no git add/commit/push or hooksPath changes"
    )
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        return install(args.repo)
    except (OSError, RuntimeError) as error:
        print("Hook not installed: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
