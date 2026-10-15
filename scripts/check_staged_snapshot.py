"""Check the Git index, not an unstaged working-tree snapshot; never stage files."""

import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


class CheckError(RuntimeError):
    """The prepared commit cannot be checked safely."""


def git(root, *args, data=None):
    result = subprocess.run(
        ["git", "-C", str(root), *args], input=data, capture_output=True, check=False
    )
    if result.returncode:
        raise CheckError(result.stderr.decode("utf-8", errors="replace").strip()[:500])
    return result.stdout


def staged_files(root):
    records = []
    for entry in git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if not entry:
            continue
        meta, raw_path = entry.split(b"\t", 1)
        mode, oid, stage = meta.decode("ascii").split()
        name = os.fsdecode(raw_path)
        path = PurePosixPath(name)
        if stage != "0":
            raise CheckError("Resolve index conflicts before committing")
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in name
            or ".git" in path.parts
        ):
            raise CheckError("Unsafe index path")
        records.append((name, mode, oid))
    return records


def checkout(root, target, names):
    if names:
        git(
            root,
            "checkout-index",
            "--force",
            "--prefix=" + target.as_posix().rstrip("/") + "/",
            "-z",
            "--stdin",
            data=b"\0".join(os.fsencode(n) for n in names) + b"\0",
        )


def check_staged(root):
    root = Path(os.fsdecode(git(root, "rev-parse", "--show-toplevel")).strip())
    records = staged_files(root)
    by_name = {name: (mode, oid) for name, mode, oid in records}
    for required in ("snapshot.py", "SNAPSHOT.md"):
        if required not in by_name or by_name[required][0] not in {"100644", "100755"}:
            raise CheckError(f"Stage a regular {required} file before committing")
    if "pytest-log.txt" in by_name:
        raise CheckError(
            "pytest-log.txt is tracked. Keep it locally: git rm --cached -- pytest-log.txt"
        )
    with tempfile.TemporaryDirectory(prefix="fenix-index-") as name:
        target = Path(name)
        checkout(root, target, ["snapshot.py"])
        spec = importlib.util.spec_from_file_location(
            "fenix_staged_snapshot", target / "snapshot.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # Apply the STAGED generator's exclusions, not unstaged local edits.
        needed = []
        for path, mode, oid in records:
            parts = PurePosixPath(path).parts
            if path == "SNAPSHOT.md":
                needed.append((path, oid))
                continue
            if any(part in module.EXCLUDE_DIRS for part in parts):
                continue
            if (
                parts[-1] in module.EXCLUDE_FILES
                or Path(path).suffix.lower() in module.EXCLUDE_EXT
            ):
                continue
            if mode not in {"100644", "100755"}:
                raise CheckError("Snapshot input is not a regular file: " + path)
            needed.append((path, oid))
        # Do not materialize large tracked assets just to discover their size.
        sizes = git(
            root,
            "cat-file",
            "--batch-check=%(objectsize)",
            data="".join(oid + "\n" for _, oid in needed).encode("ascii"),
        ).splitlines()
        if len(sizes) != len(needed) or any(not size.isdigit() for size in sizes):
            raise CheckError("Cannot read staged blob sizes")
        names = [
            path
            for (path, _), size in zip(needed, sizes)
            if path == "SNAPSHOT.md" or int(size) <= module.MAX_FILE_SIZE
        ]
        # snapshot.py was copied already; checkout-index safely replaces it in temp only.
        checkout(root, target, names)
        result = subprocess.run(
            [sys.executable, "-X", "utf8", str(target / "snapshot.py"), "--check"],
            cwd=target,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            print(
                (result.stdout + result.stderr).decode("utf-8", errors="replace")[
                    -1800:
                ]
            )
            print(
                "Snapshot differs from the staged commit. Run python snapshot.py, then stage the intended files and SNAPSHOT.md."
            )
            return 1
    print("SNAPSHOT: staged files are consistent; index/worktree unchanged")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        return check_staged(args.repo)
    except Exception as error:  # noqa: BLE001 -- fail closed at the CLI boundary
        print(
            f"Snapshot check BLOCKED: {type(error).__name__}: {str(error)[:600]}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
