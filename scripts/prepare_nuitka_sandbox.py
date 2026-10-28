"""Create a least-scope offline Windows Sandbox test; never enable Windows features."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

BASE = Path(__file__).resolve().parents[1]


def prepare(root, installer):
    root, installer = Path(root).resolve(), Path(installer).resolve()
    if not installer.is_file() or not installer.stat().st_size:
        raise RuntimeError("Installer does not exist; build it on Windows first")
    workspace = root / "build/sandbox-nuitka" / uuid.uuid4().hex[:12]
    if any(parent.is_symlink() for parent in [root / "build", root / "build/sandbox-nuitka"]):
        raise RuntimeError("Linked sandbox workspace")
    incoming, results = workspace / "input", workspace / "results"
    incoming.mkdir(parents=True)
    results.mkdir()
    target = incoming / "setup.exe"
    shutil.copy2(installer, target)
    shutil.copy2(root / "scripts/verify_nuitka_sandbox.ps1", incoming / "verify.ps1")
    with target.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    (incoming / "expected.json").write_text(json.dumps({"sha256": digest}), encoding="utf-8")
    config = ET.Element("Configuration")
    for name in ("Networking", "vGPU", "AudioInput", "VideoInput", "PrinterRedirection", "ClipboardRedirection"):
        ET.SubElement(config, name).text = "Disable"
    folders = ET.SubElement(config, "MappedFolders")
    for host, guest, readonly in ((incoming, r"C:\PhoenixTest\input", True),
                                   (results, r"C:\PhoenixTest\results", False)):
        folder = ET.SubElement(folders, "MappedFolder")
        ET.SubElement(folder, "HostFolder").text = str(host)
        ET.SubElement(folder, "SandboxFolder").text = guest
        ET.SubElement(folder, "ReadOnly").text = "true" if readonly else "false"
    command = ET.SubElement(ET.SubElement(config, "LogonCommand"), "Command")
    command.text = r'powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File C:\PhoenixTest\input\verify.ps1'
    path = workspace / "Phoenix_Nuitka_Test.wsb"
    ET.ElementTree(config).write(path, encoding="utf-8", xml_declaration=True)
    return path, results


def launch(config):
    if sys.platform != "win32":
        raise RuntimeError("Windows Sandbox can only be launched on Windows")
    exe = shutil.which("WindowsSandbox.exe")
    if exe is None:
        raise RuntimeError("Windows Sandbox is unavailable. Enable it manually on a supported Windows edition, or use a clean Windows VM.")
    subprocess.Popen([exe, str(config)])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", type=Path, default=BASE / "dist/Феникс_Nuitka_Setup.exe")
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args(argv)
    try:
        config, results = prepare(BASE, args.installer)
        print(f"Sandbox configuration: {config}")
        print(f"Results (not yet verified): {results}")
        if args.open:
            launch(config)
        return 0
    except (OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
