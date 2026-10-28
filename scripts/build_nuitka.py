"""Build the Windows bootstrap launcher with Nuitka, not the complete runtime.

The default standalone folder is easier to diagnose than a onefile bootstrap.
The application source/resources remain beside the executable; the launcher
continues to manage .venv311. --check validates resources without compiling.
"""

import argparse
from importlib.metadata import PackageNotFoundError, version
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from scripts.build_exe import check_bootstrap_ui
from scripts.release_payload import collect_payload

EXE_NAME = "Феникс.exe"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("standalone", "onefile"), default="standalone")
    parser.add_argument("--compiler", choices=("auto", "msvc", "mingw64"), default="auto")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--console", action="store_true", help="Keep console for startup diagnostics")
    parser.add_argument("--check", action="store_true", help="Resource/command preflight only")
    args = parser.parse_args(argv)
    if not 1 <= args.jobs <= 64:
        parser.error("--jobs must be between 1 and 64")
    return args


def build_directory(root, mode):
    return Path(root) / "build" / f"nuitka-{mode}"


def command(args, root=BASE):
    root = Path(root).resolve()
    output = build_directory(root, args.mode)
    cmd = [
        sys.executable, "-m", "nuitka",
        f"--mode={args.mode}",
        "--enable-plugin=tk-inter",
        f"--output-dir={output}",
        f"--output-filename={EXE_NAME}",
        f"--windows-icon-from-ico={root / 'jarvis' / 'icon.ico'}",
        f"--windows-console-mode={'force' if args.console else 'disable'}",
        f"--report={output / 'compilation-report.xml'}",
        f"--jobs={args.jobs}",
        "--assume-yes-for-downloads",
    ]
    if args.compiler == "msvc":
        cmd.append("--msvc=latest")
    elif args.compiler == "mingw64":
        cmd.append("--mingw64")
    cmd.append(str(root / "launcher.py"))
    return cmd


def validate_environment():
    if platform.system() != "Windows":
        raise RuntimeError("Windows EXE must be built on Windows; --check works on other platforms.")
    if sys.version_info[:2] != (3, 11) or struct.calcsize("P") != 8:
        raise RuntimeError("Use official Python 3.11 x64 with Tcl/Tk to build this launcher.")
    try:
        version("Nuitka")
    except PackageNotFoundError as exc:
        raise RuntimeError("Install requirements-nuitka.txt in the isolated build environment.") from exc
    check_bootstrap_ui()


def publish(root, mode):
    """Stage a complete public distribution, never only the EXE or private data."""
    root = Path(root).resolve()
    files = collect_payload(root, include_exe=False)
    output = build_directory(root, mode)
    native = output / "launcher.dist" if mode == "standalone" else output
    executable = native / EXE_NAME
    if not executable.is_file() or not executable.stat().st_size:
        raise RuntimeError(f"Nuitka did not produce {executable}")

    destination = root / "dist" / f"nuitka-{mode}"
    if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
        raise RuntimeError("Build destination must be a regular builder-owned directory.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=f"nuitka-{mode}-", dir=destination.parent))
    try:
        if mode == "standalone":
            shutil.copytree(native, staged, dirs_exist_ok=True)
        else:
            shutil.copy2(executable, staged / EXE_NAME)
        for name in files:
            target = staged / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / name, target)
        if destination.exists():
            shutil.rmtree(destination)
        staged.replace(destination)
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    return destination / EXE_NAME


def main(argv=None):
    args = parse_args(argv)
    try:
        files = collect_payload(BASE, include_exe=False)
        cmd = command(args)
        print(f"Public payload: {len(files)} files; mode={args.mode}")
        print(subprocess.list2cmdline(cmd), flush=True)
        if args.check:
            print("Preflight OK. No compilation, Windows validation or downloads performed.")
            return 0
        validate_environment()
        output = build_directory(BASE, args.mode)
        if output.is_symlink():
            raise RuntimeError("Nuitka output must not be a symlink.")
        output.mkdir(parents=True, exist_ok=True)
        print("Nuitka may download compiler/cache tools. This builds the launcher only.", flush=True)
        subprocess.run(cmd, cwd=BASE, check=True)
        executable = publish(BASE, args.mode)
        print(f"Ready: {executable}")
        print("Keep the entire distribution folder; the assistant still uses .venv311.")
        return 0
    except subprocess.CalledProcessError as exc:
        print(f"Nuitka failed with exit code {exc.returncode}", file=sys.stderr)
        return exc.returncode or 1
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Build error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())