"""Build the complete Windows application and its installer, not launcher.py."""
import argparse
import hashlib
import importlib.metadata as metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from scripts.build_setup import find_iscc, validate_version
from scripts.release_payload import collect_payload

EXE = "Феникс.exe"
SETUP = "Феникс_Nuitka_Setup.exe"
INCLUDES = (
    "--include-package=jarvis", "--include-module=pyttsx3.drivers.sapi5",
    "--include-package=winrt", "--include-package=comtypes", "--include-package=piper",
    "--include-package=pystray", "--include-package=omegaconf", "--include-package=pymorphy3_dicts_ru",
    "--include-module=flet_desktop", "--include-module=flet_desktop.win_taskbar",
    # flet.controls.material.icons импортируется динамически и без пакета целиком
    # падает уже в self-test: ModuleNotFoundError 'flet.controls.material.icons'.
    "--include-package=flet",
    "--include-module=scripts.check_caps", "--include-module=onnxruntime",
    "--include-module=torchaudio", "--include-module=yaml",
    "--include-module=torch", "--include-module=faster_whisper", "--include-module=ctranslate2",
)
DATA_PACKAGES = ("flet", "flet_desktop", "certifi", "pymorphy3_dicts_ru", "onnxruntime", "piper",
                 # winrt 4 читает таблицу проекций _table.pywinrt рядом с модулем;
                 # без её данных self-test падает на winrt.windows.media.control.
                 "winrt")
REQUIRES = ("vosk", "faster_whisper", "ctranslate2", "sounddevice", "numpy", "piper",
            "pyttsx3", "winrt", "flet", "flet_desktop", "torch", "torchaudio", "onnxruntime",
            "pymorphy3", "pymorphy3_dicts_ru", "certifi", "omegaconf")
EXCLUDE_METADATA = {"pip", "setuptools", "wheel", "nuitka", "ordered-set", "zstandard",
                    "pytest", "pytest-asyncio", "iniconfig", "pluggy"}

# Тестовые модули torch не нужны в работе приложения и валят gcc: на
# torch.testing._internal.common_methods_invocations cc1 падает с
# 'out of memory'. Пакет torch.testing._internal целиком исключать нельзя:
# torch/utils/checkpoint.py безусловно импортирует logging_tensor.
NOFOLLOW = ("pip", "pytest", "_pytest", "tests", "*.tests", "comtypes.test",
            "torch.testing._internal.common_methods_invocations",
            "torch.testing._internal.common_utils",
            "torch.testing._internal.common_modules",
            "torch.testing._internal.common_nn",
            "torch.testing._internal.common_optimizers",
            "torch.testing._internal.common_quantization",
            "torch.testing._internal.opinfo",
            "torch.testing._internal.distributed")


# Forced metadata is not an inventory of the build environment. Nuitka rejects
# metadata when its associated import was pruned (e.g. docopt, pypiwin32).
# Only these explicitly included packages need an unconditional version record.
# Other dependencies use Nuitka's normal metadata dependency detection.
FORCED_METADATA = frozenset(("flet", "flet-desktop", "torch"))


def metadata_arguments(distributions):
    installed = {re.sub(r"[-_.]+", "-", name).lower() for name in distributions}
    return [f"--include-distribution-metadata={name}"
            for name in sorted(installed & FORCED_METADATA)]


def args_for(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--check", action="store_true")
    p.add_argument("--console", action="store_true")
    p.add_argument("--compiler", choices=("auto", "msvc", "mingw64"), default="auto")
    p.add_argument("--jobs", type=int, default=2)
    p.add_argument("--low-memory", action="store_true", help="Use Nuitka low-memory compilation options")
    p.add_argument("--version", default="2.1.2")
    p.add_argument("--no-setup", action="store_true")
    p.add_argument("--skip-compile", action="store_true",
                   help="Reuse the existing standalone output; only verify, publish and install")
    p.add_argument("--sandbox", action="store_true", help="Prepare and open offline Windows Sandbox after setup")
    args = p.parse_args(argv)
    if not 1 <= args.jobs <= 64:
        p.error("--jobs must be 1..64")
    validate_version(args.version)
    if args.sandbox and args.no_setup:
        p.error("--sandbox requires an installer")
    return args


def resources(root):
    files = collect_payload(root, include_exe=False)
    roots = {"jarvis/icon.ico", "LICENSE", "config.example.json", "docs/USER_GUIDE.md", "docs/FULL_NUITKA_BUILD.md"}
    return [name for name in files if name in roots or name.startswith(
        ("jarvis/assets/", "jarvis/sounds/", "assets/nonverbal/", "packs/"))]


def command(args, root=BASE, *, distributions=()):
    root = Path(root).resolve()
    output = root / "build/nuitka-app"
    cmd = [sys.executable, "-m", "nuitka", "--mode=standalone", "--enable-plugin=tk-inter",
           "--python-flag=isolated", "--python-flag=no_site", "--file-reference-choice=runtime",
           "--module-parameter=torch-disable-jit=no", "--nofollow-import-to=" + ",".join(NOFOLLOW),
           f"--output-dir={output}", f"--output-filename={EXE}",
           f"--windows-icon-from-ico={root / 'jarvis/icon.ico'}",
           f"--windows-console-mode={'force' if args.console else 'disable'}",
           f"--report={output / 'compilation-report.xml'}", f"--jobs={args.jobs}",
           "--assume-yes-for-downloads", *INCLUDES]
    cmd.extend(f"--include-package-data={name}" for name in DATA_PACKAGES)
    cmd.extend(metadata_arguments(distributions))
    cmd.extend(f"--include-data-files={root / name}={name}" for name in resources(root))
    if args.low_memory:
        cmd.append("--low-memory")
    if args.compiler == "msvc":
        cmd.append("--msvc=latest")
    elif args.compiler == "mingw64":
        cmd.append("--mingw64")
    cmd.append(str(root / "phoenix_app.py"))
    return cmd


def validate_environment():
    if sys.platform != "win32":
        raise RuntimeError("A Windows build host is required. --check only validates the plan on Linux.")
    if sys.version_info[:2] != (3, 11) or struct.calcsize("P") != 8:
        raise RuntimeError("Build with CPython 3.11 x64")
    if metadata.version("Nuitka") != "4.3.1":
        raise RuntimeError("Install requirements-nuitka-app.txt in the isolated build environment")
    missing = [name for name in REQUIRES if importlib.util.find_spec(name) is None]
    if missing:
        raise RuntimeError("Missing builder dependencies: " + ", ".join(missing))
    if metadata.version("flet") != metadata.version("flet-desktop"):
        raise RuntimeError("Flet and flet-desktop versions differ")
    import tkinter
    tkinter.Tcl().eval("info patchlevel")



TORCH_PROBE_CODE = r"""
import io
import json
from importlib.metadata import version, requires
from packaging.requirements import Requirement
from packaging.version import Version
import torch
import torchaudio

torch_version, audio_version = version("torch"), version("torchaudio")
torch_requirements = []
for raw in requires("torchaudio") or ():
    requirement = Requirement(raw)
    if requirement.name.lower().replace("_", "-") != "torch":
        continue
    if requirement.marker is not None and not requirement.marker.evaluate({"extra": ""}):
        continue
    torch_requirements.append(str(requirement))
    if requirement.specifier and not requirement.specifier.contains(Version(torch_version), prereleases=True):
        raise RuntimeError("Installed Torch does not satisfy Torchaudio's declared requirement: "
                           + torch_version + " / " + str(requirement))
traced = torch.jit.trace(lambda value: value + 1, torch.zeros(1))
buffer = io.BytesIO()
torch.jit.save(traced, buffer)
buffer.seek(0)
model = torch.jit.load(buffer, map_location="cpu")
if float(model(torch.zeros(1))[0]) != 1.0:
    raise RuntimeError("TorchScript CPU probe failed")
print(json.dumps({"ok": True, "torch": torch_version, "torchaudio": audio_version, "torch_requirements": torch_requirements}))
"""


def validate_torch_runtime(output):
    """Imports and CPU JIT must work before starting an expensive compilation."""
    report = Path(output) / "torch-builder-preflight.log"
    try:
        with report.open("w", encoding="utf-8") as stream:
            result = subprocess.run([sys.executable, "-I", "-c", TORCH_PROBE_CODE],
                                    stdout=stream, stderr=subprocess.STDOUT, timeout=120,
                                    check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Torch builder preflight timed out; see {report}") from exc
    if result.returncode != 0:
        raise RuntimeError(f"Torch/Torchaudio imports, declared dependency requirements or CPU JIT failed. "
                           f"Compilation was not started. See {report}")


def environment_versions():
    return {dist.metadata["Name"]: dist.version for dist in metadata.distributions()
            if dist.metadata.get("Name") and dist.metadata["Name"].lower().replace("_", "-") not in EXCLUDE_METADATA}


def prepare_client():
    """Builder-only official Flet cache. Never copy a user's entire cache/profile."""
    from jarvis.https_trust import configure_https_trust
    configure_https_trust()
    import flet_desktop
    os.environ["FLET_DESKTOP_FLAVOR"] = "full"
    cache = Path(flet_desktop.ensure_client_cached())
    client = cache / "flet"
    validate_client(client)
    return client


def validate_client(client):
    client = Path(client)
    if client.is_symlink():
        raise RuntimeError("Linked Flet client directory")
    for name in ("flet.exe", "flutter_windows.dll", "data/icudtl.dat"):
        if not (client / name).is_file() or not (client / name).stat().st_size:
            raise RuntimeError(f"Incomplete Flet Windows client: {name}")
    if not (client / "data/flutter_assets").is_dir():
        raise RuntimeError("Flet Flutter assets are missing")
    if any(p.is_symlink() for p in client.rglob("*")):
        raise RuntimeError("Linked Flet client resource")


def validate_report(report):
    data = Path(report).read_bytes()
    # Nuitka объявляет кодировку как encoding='utf8'; expat такой псевдоним не
    # принимает и падает на первом не-ASCII символе (кириллица в имени EXE).
    data = re.sub(rb"encoding=([\"'])utf-?8\1", rb"encoding='utf-8'", data, count=1)
    tree = ET.ElementTree(ET.fromstring(data))
    modules = {node.get("name"): node.get("kind", "") for node in tree.iter("module")}
    for name in ("jarvis.main", "jarvis.gui", "jarvis.stt", "jarvis.tts", "jarvis.compiled_runtime"):
        if "Compiled" not in modules.get(name, ""):
            raise RuntimeError(f"Nuitka report does not confirm compiled application module {name}")


def validate_native(native):
    native = Path(native)
    for name in (EXE, "python311.dll"):
        if not (native / name).is_file() or not (native / name).stat().st_size:
            raise RuntimeError(f"Missing standalone runtime file: {name}")
    names = [p.relative_to(native).as_posix().lower() for p in native.rglob("*") if p.is_file()]
    for fragment in ("libvosk", "portaudio", "torch_cpu", "ctranslate2", "onnxruntime"):
        if not any(fragment in name and name.endswith((".dll", ".pyd")) for name in names):
            raise RuntimeError(f"Missing native dependency: {fragment}")
    for p in native.rglob("*"):
        rel = p.relative_to(native)
        if p.is_symlink():
            raise RuntimeError(f"Linked standalone output: {rel}")
        if p.is_file() and p.name.lower() in ("python.exe", "pythonw.exe"):
            raise RuntimeError(f"Unexpected external interpreter: {rel}")
        if any(part.lower().startswith(".venv") for part in rel.parts):
            raise RuntimeError(f"Unexpected environment in output: {rel}")
        if rel.parts[0] in ("profiles", "logs", "models") or str(rel) in (
            "config.json", "system_caps.json", "launcher.py", "phoenix_app.py", "phoenix_app.py", "tasks.json", "timers.json", "dialog.json"):
            raise RuntimeError(f"Unexpected developer data in output: {rel}")
        if rel.parts[0] in ("jarvis", "scripts") and p.suffix.lower() in (".py", ".pyc", ".pyo"):
            raise RuntimeError(f"Application source leaked instead of compiled code: {rel}")


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stage(root, native, client, *, versions, version):
    if Path(native).is_symlink():
        raise RuntimeError("Linked native output directory")
    root, native = Path(root).resolve(), Path(native).resolve()
    validate_native(native)
    validate_client(client)
    destination = root / "dist/nuitka-app"
    if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
        raise RuntimeError("Unsafe distribution destination")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="nuitka-app-", dir=destination.parent))
    try:
        shutil.copytree(native, temp, dirs_exist_ok=True)
        for name in resources(root):
            target = temp / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / name, target)
        shutil.copytree(client, temp / "runtime/flet", dirs_exist_ok=True)
        build_info = {"schema": 1, "kind": "nuitka-application-standalone", "version": version,
                      "entry_point": "phoenix_app.py", "external_python_required": False,
                      "model_policy": "download-on-consent; no personal caches bundled",
                      "python": platform.python_version(), "packages": versions}
        (temp / "build-info.json").write_text(json.dumps(build_info, ensure_ascii=False, indent=2), encoding="utf-8")
        (temp / "README_STANDALONE.txt").write_text(
            "Standalone application. Start Феникс.exe. No external Python, pip or .venv311 is used.\n"
            "Models may be downloaded with consent. Ollama is a separate optional service.\n"
            "See docs/FULL_NUITKA_BUILD.md.\n", encoding="utf-8")
        manifest = [{"path": p.relative_to(temp).as_posix(), "sha256": file_hash(p)}
                    for p in sorted(temp.rglob("*")) if p.is_file()]
        (temp / "release-manifest.json").write_text(
            json.dumps({"schema": 1, "files": manifest}, ensure_ascii=False, indent=2), encoding="utf-8")
        # Renaming a locked previous build fails without deleting it piecemeal.
        backup = destination.with_name("nuitka-app-previous-" + uuid.uuid4().hex)
        had_previous = destination.exists()
        if had_previous:
            destination.replace(backup)
        try:
            temp.replace(destination)
        except OSError:
            if had_previous:
                backup.replace(destination)
            raise
        if had_previous:
            try:
                shutil.rmtree(backup)
            except OSError:
                print(f"Previous build is still busy; retained at {backup}", file=sys.stderr)
    finally:
        if temp.exists():
            shutil.rmtree(temp)
    return destination


def installer_command(iscc, payload, args, root=BASE):
    root = Path(root).resolve()
    return [str(iscc), f"/DPayloadDir={Path(payload).resolve()}", f"/DMyAppVersion={args.version}",
            str(root / "installer_nuitka.iss")]


def run_probe(executable, report, mode):
    report = Path(report)
    report.unlink(missing_ok=True)
    subprocess.run([str(executable), mode, str(report)], check=True, timeout=240,
                   cwd=str(Path(executable).parent))
    result = json.loads(report.read_text(encoding="utf-8"))
    if result.get("ok") is not True or result.get("compiled") is not True:
        raise RuntimeError(f"Standalone probe failed: {report}")


def main(argv=None):
    try:
        args = args_for(argv)
        required = ("phoenix_app.py", "installer_nuitka.iss", "docs/FULL_NUITKA_BUILD.md",
                    "scripts/verify_nuitka_sandbox.ps1")
        for name in required:
            if not (BASE / name).is_file():
                raise RuntimeError(f"Missing full-build resource: {name}")
        public = resources(BASE)
        if args.check:
            cmd = command(args)
            print(f"Plan OK: full application; {len(public)} public resources; entry={Path(cmd[-1]).name}")
            print("Standalone Python runtime included. No external Python/pip bootstrap.")
            print("No compiler, native probe, installer or Windows Sandbox was run.")
            return 0
        validate_environment()
        iscc = None if args.no_setup else find_iscc()
        versions = environment_versions()
        output = BASE / "build/nuitka-app"
        if output.is_symlink():
            raise RuntimeError("Unsafe compiler output directory")
        output.mkdir(parents=True, exist_ok=True)
        validate_torch_runtime(output)
        client = prepare_client()
        cmd = command(args, distributions=versions)
        (output / "build-command.json").write_text(json.dumps(cmd, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.skip_compile:
            dist = output / "phoenix_app.dist"
            if not (dist / EXE).is_file() or not (output / "compilation-report.xml").is_file():
                raise RuntimeError("--skip-compile requires an existing standalone output and report")
            print("Reusing the existing standalone output; Nuitka is not run.", flush=True)
        else:
            print("Compiling the full application, Torch and native libraries. This is not launcher.py.", flush=True)
            subprocess.run(cmd, cwd=BASE, check=True)
        validate_report(output / "compilation-report.xml")
        payload = stage(BASE, output / "phoenix_app.dist", client, versions=versions, version=args.version)
        # Probes can generate COM/third-party caches. Never add them to the installer.
        with tempfile.TemporaryDirectory(prefix="probe-", dir=output) as scratch:
            probe_payload = Path(scratch) / "app"
            shutil.copytree(payload, probe_payload)
            run_probe(probe_payload / EXE, output / "native-probe.json", "--self-test")
        if args.no_setup:
            print(f"Ready: {payload / EXE}; native probe passed; no clean-machine test yet.")
            return 0
        subprocess.run([sys.executable, str(BASE / "scripts/make_installer_images.py"), "--version", args.version], check=True)
        setup = BASE / "dist" / SETUP
        setup.unlink(missing_ok=True)
        subprocess.run(installer_command(iscc, payload, args), cwd=BASE, check=True)
        if not setup.is_file() or not setup.stat().st_size:
            raise RuntimeError("Inno Setup did not produce the full application installer")
        print(f"Installer ready: {setup}")
        print("Builder native probe passed. This does not prove a clean Windows installation.")
        if args.sandbox:
            from scripts.prepare_nuitka_sandbox import prepare, launch
            config, results = prepare(BASE, setup)
            print(f"Sandbox report folder: {results}")
            launch(config)
            print("Sandbox launch requested. Only results/summary.json can confirm its checks passed.")
        return 0
    except (OSError, ValueError, RuntimeError, metadata.PackageNotFoundError, ET.ParseError, subprocess.SubprocessError) as exc:
        print(f"Full Nuitka build failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
