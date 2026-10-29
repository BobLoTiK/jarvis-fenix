"""Full application build contracts. No Windows compiler/installers or downloads run."""
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from scripts import build_nuitka_app as build
from scripts import prepare_nuitka_sandbox as sandbox

ROOT = Path(__file__).resolve().parents[1]


def write(path, data=b"fixture"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.fixture
def native(tmp_path):
    root = tmp_path / "native"
    for name in (build.EXE, "python311.dll", "vosk/libvosk.dll", "_sounddevice_data/libportaudio64bit.dll",
                 "torch/lib/torch_cpu.dll", "ctranslate2/_ext.pyd", "onnxruntime/capi/onnxruntime.pyd"):
        write(root / name)
    return root


@pytest.fixture
def client(tmp_path):
    root = tmp_path / "client"
    for name in ("flet.exe", "flutter_windows.dll", "data/icudtl.dat", "data/flutter_assets/AssetManifest.bin"):
        write(root / name)
    return root


def test_full_command_targets_application_and_embeds_runtime():
    command = build.command(build.args_for([]), distributions=["torch", "flet"])
    assert command[-1] == str(ROOT / "phoenix_app.py")
    assert "--mode=standalone" in command
    assert "--include-package=jarvis" in command
    assert "--module-parameter=torch-disable-jit=no" in command
    assert "--python-flag=isolated" in command
    assert "--include-module=pyttsx3.drivers.sapi5" in command
    assert "--include-distribution-metadata=torch" in command
    assert not any(Path(value).name == "launcher.py" for value in command)
    # command[0] — интерпретатор сборщика (build/nuitka-app-env), это нормально;
    # проектная .venv311 не должна попадать ни в один аргумент сборки.
    assert not any(".venv311" in value for value in command[1:])


@pytest.mark.parametrize("compiler,flag", [("msvc", "--msvc=latest"), ("mingw64", "--mingw64")])
def test_explicit_compilers(compiler, flag):
    assert flag in build.command(build.args_for(["--compiler", compiler]))


def test_resource_list_never_includes_developer_code_or_config():
    files = build.resources(ROOT)
    assert "jarvis/icon.ico" in files
    assert "config.example.json" in files
    assert "packs/games.json" in files
    assert "docs/FULL_NUITKA_BUILD.md" in files
    assert not any(name.endswith((".py", ".bat")) or name in ("config.json", "system_caps.json") for name in files)


def test_preflight_never_imports_native_packages_or_runs_tools(monkeypatch):
    monkeypatch.setattr(build, "validate_environment", Mock(side_effect=AssertionError("native validation")))
    monkeypatch.setattr(build, "prepare_client", Mock(side_effect=AssertionError("download")))
    monkeypatch.setattr(build.subprocess, "run", Mock(side_effect=AssertionError("compiler")))
    assert build.main(["--check"]) == 0


def test_non_windows_build_is_rejected_before_dependency_probe(monkeypatch):
    monkeypatch.setattr(build.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="Windows build host"):
        build.validate_environment()


@pytest.mark.parametrize("argv", [["--jobs", "0"], ["--jobs", "65"], ["--sandbox", "--no-setup"]])
def test_invalid_modes_and_limits(argv):
    with pytest.raises(SystemExit):
        build.args_for(argv)


def test_report_requires_compiled_application_not_launcher(tmp_path):
    path = tmp_path / "report.xml"
    write(path, b'<nuitka><module name="launcher" kind="CompiledPythonModule"/></nuitka>')
    with pytest.raises(RuntimeError, match="jarvis.main"):
        build.validate_report(path)
    modules = ("jarvis.main", "jarvis.gui", "jarvis.stt", "jarvis.tts", "jarvis.compiled_runtime")
    write(path, ('<nuitka>' + ''.join(f'<module name="{name}" kind="CompiledPythonModule"/>' for name in modules) + '</nuitka>').encode())
    build.validate_report(path)


@pytest.mark.parametrize("name", ["python.exe", "pythonw.exe", ".venv311/Scripts/python.exe",
                                  "config.json", "profiles/private.json", "launcher.py", "jarvis/main.py"])
def test_native_output_rejects_external_interpreter_and_user_files(native, name):
    write(native / name)
    with pytest.raises(RuntimeError):
        build.validate_native(native)


def test_native_output_requires_embedded_python_dll(native):
    (native / "python311.dll").unlink()
    with pytest.raises(RuntimeError, match="python311.dll"):
        build.validate_native(native)


def test_stage_includes_whole_runtime_and_client_without_source(tmp_path, native, client, monkeypatch):
    root = tmp_path / "project"
    write(root / "LICENSE")
    monkeypatch.setattr(build, "resources", lambda root: ["LICENSE"])
    output = build.stage(root, native, client, versions={"torch": "test"}, version="2.1.1")
    assert (output / build.EXE).is_file()
    assert (output / "runtime/flet/flet.exe").is_file()
    assert (output / "python311.dll").is_file()
    info = json.loads((output / "build-info.json").read_text(encoding="utf-8"))
    assert info["kind"] == "nuitka-application-standalone"
    assert info["external_python_required"] is False
    manifest = json.loads((output / "release-manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        assert build.file_hash(output / entry["path"]) == entry["sha256"]
    assert not (output / "launcher.py").exists()


def test_failed_client_validation_preserves_existing_output(tmp_path, native, client, monkeypatch):
    root = tmp_path / "project"
    write(root / "dist/nuitka-app/previous", b"keep")
    (client / "flet.exe").unlink()
    monkeypatch.setattr(build, "resources", lambda root: [])
    with pytest.raises(RuntimeError, match="Incomplete Flet"):
        build.stage(root, native, client, versions={}, version="2.1.1")
    assert (root / "dist/nuitka-app/previous").read_bytes() == b"keep"


def test_probe_requires_exit_success_and_true_compiled_report(tmp_path, monkeypatch):
    report = tmp_path / "report.json"
    def run(command, **kwargs):
        write(report, b'{"ok":true,"compiled":false}')
    monkeypatch.setattr(build.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="probe failed"):
        build.run_probe(tmp_path / build.EXE, report, "--self-test")


def test_installer_uses_full_payload_not_legacy_bootstrap():
    args = build.args_for([])
    command = build.installer_command("ISCC.exe", ROOT / "dist/nuitka-app", args)
    assert command[-1].endswith("installer_nuitka.iss")
    text = (ROOT / "installer_nuitka.iss").read_text(encoding="utf-8")
    assert 'OutputBaseFilename=Феникс_Nuitka_Setup' in text
    assert 'UsePreviousAppDir=no' in text
    assert 'Parameters: "--prepare-silero"' in text
    assert 'Source: "{#PayloadDir}\\*"' in text
    assert 'uninsdeletevalue' in text
    assert '[UninstallDelete]' not in text  # no broad deletion of profiles/models
    assert 'pip install' not in text


def test_sandbox_maps_only_input_and_reports_and_disables_network(tmp_path):
    root = tmp_path / "project & data"
    write(root / "scripts/verify_nuitka_sandbox.ps1")
    installer = write(root / "dist/setup.exe")
    config, results = sandbox.prepare(root, installer)
    tree = ET.parse(config).getroot()
    for name in ("Networking", "vGPU", "AudioInput", "VideoInput", "ClipboardRedirection"):
        assert tree.findtext(name) == "Disable"
    folders = tree.findall("MappedFolders/MappedFolder")
    assert len(folders) == 2
    assert [folder.findtext("ReadOnly") for folder in folders] == ["true", "false"]
    assert all(folder.findtext("HostFolder") != str(root) for folder in folders)
    assert Path(folders[1].findtext("HostFolder")) == results
    incoming = Path(folders[0].findtext("HostFolder"))
    expected = json.loads((incoming / "expected.json").read_text(encoding="utf-8"))
    assert expected["sha256"] == build.file_hash(incoming / "setup.exe")
    assert set(path.name for path in incoming.iterdir()) == {"setup.exe", "verify.ps1", "expected.json"}
    assert not list(results.iterdir())  # launch is never recorded as a passed test


def test_sandbox_does_not_launch_on_linux(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox.sys, "platform", "linux")
    launch = Mock(side_effect=AssertionError("must not launch"))
    monkeypatch.setattr(sandbox.subprocess, "Popen", launch)
    with pytest.raises(RuntimeError, match="on Windows"):
        sandbox.launch(tmp_path / "test.wsb")
    launch.assert_not_called()


def test_sandbox_harness_has_strict_failure_and_scope_guards():
    text = (ROOT / "scripts/verify_nuitka_sandbox.ps1").read_text(encoding="utf-8")
    for required in ("WaitForExit", "ExitCode", "Get-FileHash", "summary.json", "--self-test", "--gui-smoke",
                     "user_data_preserved", "not_tested", "window_close_awaited"):
        assert required in text
    assert '$summary.ok = $true' in text
    assert 'Enable-WindowsOptionalFeature' not in text


def test_sandbox_harness_stays_ascii_for_windows_powershell():
    # Windows PowerShell 5.1 читает .ps1 без BOM как ANSI: кириллический литерал
    # в тексте скрипта превращается в кракозябры. Так уже ломался реальный
    # Sandbox-прогон: установка прошла, а 'Феникс.exe' не находился, потому что
    # имя EXE было захардкожено кириллицей. Имя берётся поиском по папке.
    script = ROOT / "scripts/verify_nuitka_sandbox.ps1"
    script.read_bytes().decode("ascii")  # UnicodeDecodeError = регрессия


def test_full_bat_isolated_env_and_preflight_before_install():
    text = (ROOT / "build_nuitka_full.bat").read_text(encoding="utf-8")
    assert r"build\nuitka-app-env" in text
    assert ".venv311" not in text
    assert text.index('goto check') < text.index('pip install')
    assert 'requirements-nuitka-app.txt' in text


def test_locked_previous_build_is_not_deleted(tmp_path, native, client, monkeypatch):
    root = tmp_path / "project"
    previous = write(root / "dist/nuitka-app/previous", b"keep")
    monkeypatch.setattr(build, "resources", lambda root: [])
    original = Path.replace
    def locked(path, target):
        if path == previous.parent:
            raise PermissionError("locked previous build")
        return original(path, target)
    monkeypatch.setattr(Path, "replace", locked)
    with pytest.raises(PermissionError, match="locked"):
        build.stage(root, native, client, versions={}, version="2.1.1")
    assert previous.read_bytes() == b"keep"


def test_publish_failure_rolls_back_previous_build(tmp_path, native, client, monkeypatch):
    root = tmp_path / "project"
    previous = write(root / "dist/nuitka-app/previous", b"keep")
    monkeypatch.setattr(build, "resources", lambda root: [])
    original = Path.replace
    def fail_publish(path, target):
        if path.name.startswith("nuitka-app-") and "previous" not in path.name and Path(target).name == "nuitka-app":
            raise PermissionError("publish failure")
        return original(path, target)
    monkeypatch.setattr(Path, "replace", fail_publish)
    with pytest.raises(PermissionError, match="publish failure"):
        build.stage(root, native, client, versions={}, version="2.1.1")
    assert previous.read_bytes() == b"keep"


@pytest.mark.parametrize("unrelated", ["docopt", "pypiwin32", "Pygments", "pytest", "silero", "setuptools", "unknown-build-only-package"])
def test_installed_build_packages_do_not_force_unusable_metadata(unrelated):
    command = build.command(build.args_for([]), distributions=[unrelated, "flet", "flet-desktop", "torch"])
    flags = [arg for arg in command if arg.startswith("--include-distribution-metadata=")]
    assert flags == ["--include-distribution-metadata=flet", "--include-distribution-metadata=flet-desktop", "--include-distribution-metadata=torch"]
    assert f"--include-module={unrelated}" not in command


def test_metadata_names_are_canonical_and_deduplicated():
    assert build.metadata_arguments(["Flet", "FLET_desktop", "flet-desktop", "Torch", "docopt"]) == [
        "--include-distribution-metadata=flet", "--include-distribution-metadata=flet-desktop", "--include-distribution-metadata=torch"]


def test_metadata_is_not_forced_when_distribution_is_absent():
    assert build.metadata_arguments(["docopt", "pypiwin32"]) == []


def test_comtypes_single_named_test_package_is_excluded():
    flags = build.command(build.args_for([]))
    nofollow = next(flag for flag in flags if flag.startswith("--nofollow-import-to="))
    assert "comtypes.test" in nofollow.partition("=")[2].split(",")
    assert "--include-package=comtypes" in flags  # production COM code is retained



def test_runtime_critical_packages_are_fully_included():
    flags = build.command(build.args_for([]))
    # flet.controls.material.icons импортируется динамически: без пакета
    # self-test падал на ModuleNotFoundError уже после успешной линковки.
    assert "--include-package=flet" in flags
    # winrt 4 читает таблицу проекций _table.pywinrt рядом с модулем; без
    # данных пакета self-test падал на winrt.windows.media.control.
    assert "--include-package-data=winrt" in flags


def test_torch_internal_tests_are_excluded_but_jit_is_retained():
    flags = build.command(build.args_for([]))
    nofollow = next(flag for flag in flags if flag.startswith("--nofollow-import-to="))
    excluded = nofollow.partition("=")[2].split(",")
    # Пакет целиком исключать нельзя: torch/utils/checkpoint.py безусловно
    # импортирует torch.testing._internal.logging_tensor, поэтому import torch
    # в сборке падал с ImportError "... actively excluded".
    assert "torch.testing._internal" not in excluded
    # Тяжёлые тестовые модули исключены: common_methods_invocations роняет gcc
    # с 'cc1: out of memory'.
    assert "torch.testing._internal.common_methods_invocations" in excluded
    assert "--include-module=torch" in flags
    assert "--module-parameter=torch-disable-jit=no" in flags
    assert not any("--nofollow-import-to=torch," in flag for flag in flags)


def test_low_memory_is_explicit_and_jobs_can_be_one():
    flags = build.command(build.args_for(["--low-memory", "--jobs", "1"]))
    assert "--low-memory" in flags
    assert "--jobs=1" in flags
    assert "--low-memory" not in build.command(build.args_for([]))


def test_torch_builder_probe_checks_imports_versions_and_jit(tmp_path, monkeypatch):
    def run(command, **kwargs):
        assert command[:3] == [build.sys.executable, "-I", "-c"]
        code = command[3]
        assert "import torchaudio" in code
        assert "torch.jit.load" in code
        assert "requires(\"torchaudio\")" in code
        assert "requirement.specifier.contains" in code
        assert kwargs["timeout"] == 120
        return NS(returncode=0)
    monkeypatch.setattr(build.subprocess, "run", run)
    build.validate_torch_runtime(tmp_path)
    assert (tmp_path / "torch-builder-preflight.log").is_file()


def test_torch_builder_probe_failure_stops_before_compilation(tmp_path, monkeypatch):
    monkeypatch.setattr(build.subprocess, "run", lambda *a, **kw: NS(returncode=1))
    with pytest.raises(RuntimeError, match="Compilation was not started"):
        build.validate_torch_runtime(tmp_path)


def test_torch_builder_probe_timeout_is_bounded(tmp_path, monkeypatch):
    def run(*a, **kw):
        raise build.subprocess.TimeoutExpired("probe", 120)
    monkeypatch.setattr(build.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="timed out"):
        build.validate_torch_runtime(tmp_path)


@pytest.mark.parametrize('torch_version,audio_version,requirements,ok', [
    ('2.14.1', '2.11.0', ['torch>=2.11'], True),
    ('2.11.0+cpu', '2.11.0', ['torch>=2.11'], True),
    ('2.14.1+cu128', '2.11.0', ['torch>=2.11'], True),
    ('2.10.0', '2.11.0', ['torch>=2.11'], False),
    ('2.10.0', '2.10.0', ['torch==2.10.0'], True),
    ('2.14.1', '2.10.0', ['torch==2.10.0'], False),
    ('2.14.1', '2.11.0', ['numpy>=1', 'torch<1; extra == "test"', 'torch>=2.11'], True),
])
def test_builder_probe_uses_declared_requirements_not_equal_versions(torch_version, audio_version, requirements, ok, monkeypatch, capsys):
    import sys
    fake = NS(zeros=lambda n: [0], jit=NS(trace=lambda *a: object(),
        save=lambda traced, buffer: buffer.write(b'jit'),
        load=lambda *a, **kw: lambda value: [1]))
    monkeypatch.setitem(sys.modules, 'torch', fake)
    monkeypatch.setitem(sys.modules, 'torchaudio', NS())
    monkeypatch.setattr(build.metadata, 'version', lambda name: torch_version if name == 'torch' else audio_version)
    monkeypatch.setattr(build.metadata, 'requires', lambda name: requirements)
    if not ok:
        with pytest.raises(RuntimeError, match='declared requirement'):
            exec(build.TORCH_PROBE_CODE, {})
    else:
        exec(build.TORCH_PROBE_CODE, {})
        report = json.loads(capsys.readouterr().out)
        assert report['ok'] is True
        assert report['torch'] == torch_version
        assert 'torch_requirements' in report


def test_release_workflow_builds_nuitka_installer():
    """CI обязан собирать автономный установщик, а не только bootstrap."""
    workflow = (ROOT / '.github/workflows/release.yml').read_text(encoding='utf-8')
    # Изолированное окружение и зафиксированный стек сборки.
    assert 'build/nuitka-app-env' in workflow
    assert 'requirements-nuitka-app.txt' in workflow
    assert 'constraints-nuitka-app.txt' in workflow
    # Реальный вызов сборщика полного приложения с проверенным компилятором.
    assert 'scripts/build_nuitka_app.py' in workflow
    assert '--compiler mingw64' in workflow
    # Установщик Nuitka и независимый self-test попадают в артефакты.
    assert 'dist/Феникс_Nuitka_Setup.exe' in workflow
    assert '--self-test' in workflow
    # GitHub вырезает кириллицу из имён вложений: публикуются ASCII-имена.
    assert 'Feniks_Nuitka_Setup_' in workflow
    assert 'Feniks_Setup_' in workflow
    assert 'SHA256SUMS.txt' in workflow
    # Лимит GitHub на job — 360 минут.
    assert 'timeout-minutes: 345' in workflow


def test_nuitka_constraints_match_requirements_and_pin_versions():
    """Пины не должны расходиться с требованиями и быть строгими."""
    constraints = (ROOT / 'constraints-nuitka-app.txt').read_text(encoding='utf-8')
    requirements = (ROOT / 'requirements-nuitka-app.txt').read_text(encoding='utf-8')
    assert 'Nuitka==4.3.1' in requirements
    assert 'flet==1.0.3' in requirements
    pinned = {
        line.split('==')[0].strip().lower()
        for line in constraints.splitlines()
        if '==' in line and not line.strip().startswith('#')
    }
    for required in ('torch', 'torchaudio', 'vosk', 'winrt-runtime', 'numpy'):
        assert required in pinned, required
    for line in constraints.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        # Каждая строка — точный пин или комментарий: диапазоны ломают повторяемость.
        assert '==' in stripped, stripped
