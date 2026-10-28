"""Nuitka build plans and staging tests; no compiler, network or Tk display."""

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import launcher
from scripts import build_nuitka as builder


def test_launcher_source_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "__compiled__", None, raising=False)
    monkeypatch.setattr(launcher.sys, "frozen", False, raising=False)
    monkeypatch.setattr(launcher, "__file__", str(tmp_path / "launcher.py"))
    assert launcher.launcher_directory() == tmp_path


def test_launcher_pyinstaller_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "__compiled__", None, raising=False)
    monkeypatch.setattr(launcher.sys, "frozen", True, raising=False)
    monkeypatch.setattr(launcher.sys, "executable", str(tmp_path / "Феникс.exe"))
    assert launcher.launcher_directory() == tmp_path


def test_launcher_nuitka_onefile_uses_real_executable_directory(monkeypatch, tmp_path):
    installed = tmp_path / "installed"
    package = installed / "jarvis"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    # find_project_dir() по контракту смотрит и текущую папку: из корня проекта
    # он нашёл бы C:\jarvis с рабочим .venv311 и тест проверял бы cwd, а не EXE.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(launcher, "__compiled__", SimpleNamespace(containing_dir=str(installed)), raising=False)
    monkeypatch.setattr(launcher, "__file__", str(tmp_path / "unpacked" / "launcher.py"))
    monkeypatch.setattr(launcher.sys, "executable", str(tmp_path / "unpacked" / "Феникс.exe"))
    assert launcher.launcher_directory() == installed
    assert launcher.find_project_dir(logging.getLogger("test.nuitka")) == installed


def test_launcher_nuitka_fallback_uses_argv_not_extracted_file(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "__compiled__", SimpleNamespace(), raising=False)
    monkeypatch.setattr(launcher.sys, "argv", [str(tmp_path / "Феникс.exe")])
    monkeypatch.setattr(launcher, "__file__", str(tmp_path / "unpacked" / "launcher.py"))
    assert launcher.launcher_directory() == tmp_path


@pytest.mark.parametrize("mode", ["standalone", "onefile"])
@pytest.mark.parametrize("compiler", ["auto", "msvc", "mingw64"])
def test_command_has_native_gui_flags_without_runtime_stack(tmp_path, mode, compiler):
    args = builder.parse_args(["--mode", mode, "--compiler", compiler])
    cmd = builder.command(args, root=tmp_path)
    assert f"--mode={mode}" in cmd
    assert "--enable-plugin=tk-inter" in cmd
    assert f"--output-filename={builder.EXE_NAME}" in cmd
    assert "--windows-console-mode=disable" in cmd
    assert cmd[-1] == str(tmp_path / "launcher.py")
    assert ("--msvc=latest" in cmd) == (compiler == "msvc")
    assert ("--mingw64" in cmd) == (compiler == "mingw64")
    assert not any("include-package=torch" in value or "include-package=flet" in value for value in cmd)


def test_debug_console_is_explicit():
    assert "--windows-console-mode=force" in builder.command(builder.parse_args(["--console"]))


@pytest.mark.parametrize("jobs", ["0", "-1", "65"])
def test_job_limits(jobs):
    with pytest.raises(SystemExit):
        builder.parse_args(["--jobs", jobs])


def test_native_build_rejects_non_windows_without_running_tools(monkeypatch):
    monkeypatch.setattr(builder.platform, "system", lambda: "Linux")
    with pytest.raises(RuntimeError, match="Windows"):
        builder.validate_environment()


@pytest.mark.parametrize("python_version,bits", [((3, 13), 8), ((3, 11), 4)])
def test_native_build_rejects_wrong_python(monkeypatch, python_version, bits):
    monkeypatch.setattr(builder.platform, "system", lambda: "Windows")
    monkeypatch.setattr(builder.sys, "version_info", python_version)
    monkeypatch.setattr(builder.struct, "calcsize", lambda spec: bits)
    with pytest.raises(RuntimeError, match="Python 3.11 x64"):
        builder.validate_environment()


def test_native_build_requires_nuitka(monkeypatch):
    monkeypatch.setattr(builder.platform, "system", lambda: "Windows")
    monkeypatch.setattr(builder.sys, "version_info", (3, 11))
    monkeypatch.setattr(builder, "version", Mock(side_effect=builder.PackageNotFoundError("Nuitka")))
    with pytest.raises(RuntimeError, match="requirements-nuitka"):
        builder.validate_environment()


def test_native_build_checks_tk_without_opening_window(monkeypatch):
    monkeypatch.setattr(builder.platform, "system", lambda: "Windows")
    monkeypatch.setattr(builder.sys, "version_info", (3, 11))
    monkeypatch.setattr(builder, "version", Mock(return_value="4.3.1"))
    tk = Mock()
    monkeypatch.setattr(builder, "check_bootstrap_ui", tk)
    builder.validate_environment()
    tk.assert_called_once()


def test_check_does_not_compile_or_require_windows(monkeypatch):
    monkeypatch.setattr(builder, "collect_payload", Mock(return_value=["launcher.py"]))
    compiler = Mock(side_effect=AssertionError("must not compile"))
    monkeypatch.setattr(builder.subprocess, "run", compiler)
    monkeypatch.setattr(builder, "validate_environment", Mock(side_effect=AssertionError("must not validate Windows")))
    assert builder.main(["--check"]) == 0
    compiler.assert_not_called()


@pytest.mark.parametrize("mode", ["standalone", "onefile"])
def test_publish_keeps_required_payload_and_native_dependencies(tmp_path, monkeypatch, mode):
    source = tmp_path / "launcher.py"
    source.write_text("# public", encoding="utf-8")
    monkeypatch.setattr(builder, "collect_payload", lambda root, include_exe: ["launcher.py"])
    output = builder.build_directory(tmp_path, mode)
    native = output / "launcher.dist" if mode == "standalone" else output
    native.mkdir(parents=True)
    (native / builder.EXE_NAME).write_bytes(b"compiler-output-fixture")
    (native / "native.dll").write_bytes(b"standalone dependency")
    (tmp_path / "config.json").write_text('{"private": true}', encoding="utf-8")
    executable = builder.publish(tmp_path, mode)
    assert executable.read_bytes() == b"compiler-output-fixture"
    assert (executable.parent / "launcher.py").is_file()
    assert not (executable.parent / "config.json").exists()
    assert (executable.parent / "native.dll").exists() is (mode == "standalone")


def test_publish_requires_compiler_output(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "collect_payload", lambda root, include_exe: [])
    with pytest.raises(RuntimeError, match="did not produce"):
        builder.publish(tmp_path, "onefile")


def test_nuitka_batch_uses_isolated_build_environment():
    root = Path(__file__).resolve().parents[1]
    text = (root / "build_nuitka.bat").read_text(encoding="utf-8")
    assert r"build\nuitka-env" in text
    assert ".venv311" not in text
    assert "requirements-nuitka.txt" in text
    assert "errorlevel" in text