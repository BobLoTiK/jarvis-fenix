"""Explicit standalone probes and consent contracts without native Windows imports."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from jarvis import compiled_runtime as runtime


def resources(root):
    for name in runtime.RESOURCE_FILES:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"public fixture")
    (root / "runtime/flet/data/flutter_assets").mkdir()


def fake_imports(monkeypatch, root):
    monkeypatch.setattr(runtime, "PROBE_MODULES", ("jarvis.main",))
    monkeypatch.setattr(runtime.importlib, "import_module", lambda name: NS(__file__=str(root / "jarvis/main.py")))
    torch = NS(zeros=lambda n: [0], jit=NS(trace=lambda fn, value: object(),
        save=lambda traced, buffer: buffer.write(b"jit"), load=lambda *args, **kwargs: lambda value: [1]))
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "pymorphy3", NS(MorphAnalyzer=lambda: NS(parse=lambda word: [word])))


def test_source_python_cannot_report_a_passed_compiled_probe(tmp_path, monkeypatch):
    resources(tmp_path)
    fake_imports(monkeypatch, tmp_path)
    report = runtime.self_test(tmp_path, compiled=False)
    assert report["ok"] is False
    assert report["checks"]["compiled_entry"] is False
    assert "microphone" in report["not_tested"]


def test_probe_checks_embedded_modules_resources_and_dictionaries(tmp_path, monkeypatch):
    resources(tmp_path)
    fake_imports(monkeypatch, tmp_path)
    report = runtime.self_test(tmp_path, compiled=True)
    assert report["ok"] is True
    assert report["checks"]["torchscript_cpu"] is True
    assert report["checks"]["russian_dictionary"] is True


def test_probe_rejects_module_imported_from_external_environment(tmp_path, monkeypatch):
    resources(tmp_path)
    fake_imports(monkeypatch, tmp_path)
    monkeypatch.setattr(runtime.importlib, "import_module", lambda name: NS(__file__="/outside/main.py"))
    report = runtime.self_test(tmp_path, compiled=True)
    assert report["ok"] is False
    assert report["checks"]["jarvis.main"]["ok"] is False


def test_probe_rejects_external_python_binary(tmp_path, monkeypatch):
    resources(tmp_path)
    fake_imports(monkeypatch, tmp_path)
    (tmp_path / "python.exe").write_bytes(b"not allowed")
    assert runtime.self_test(tmp_path, compiled=True)["ok"] is False


def test_report_is_utf8_atomic_and_does_not_leave_temp_files(tmp_path):
    report = tmp_path / "report.json"
    runtime.write_report(report, {"ok": False, "message": "Ошибка"})
    assert json.loads(report.read_text(encoding="utf-8"))["message"] == "Ошибка"
    assert list(tmp_path.iterdir()) == [report]


def test_flet_missing_bundle_is_error_not_download(tmp_path):
    with pytest.raises(FileNotFoundError, match="flet.exe"):
        runtime.configure_environment(tmp_path)


def test_flet_uses_distribution_path_not_personal_cache(tmp_path, monkeypatch):
    resources(tmp_path)
    from jarvis import https_trust
    monkeypatch.setattr(https_trust, "configure_https_trust", Mock())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FLET_VIEW_PATH", "old-client")
    monkeypatch.setenv("FLET_DESKTOP_FLAVOR", "light")
    monkeypatch.setenv("FLET_APP_USER_MODEL_ID", "old")
    runtime.configure_environment(tmp_path)
    assert runtime.os.environ["FLET_VIEW_PATH"] == str(tmp_path / "runtime/flet")
    assert runtime.os.environ["FLET_DESKTOP_FLAVOR"] == "full"


def test_silero_denial_never_imports_or_executes_torch_hub(monkeypatch):
    session = NS(ask=Mock(return_value=False), notice="")
    hub = Mock(side_effect=AssertionError("unapproved repository execution"))
    monkeypatch.setitem(sys.modules, "torch", NS(hub=NS(load=hub)))
    assert runtime.prepare_silero(session) is False
    hub.assert_not_called()
    assert "отменена" in session.notice


def test_silero_approval_is_explicit_and_uses_fixed_repository(tmp_path, monkeypatch):
    from jarvis import paths
    monkeypatch.setattr(paths, "program_dir", lambda: tmp_path)
    monkeypatch.setenv("TORCH_HOME", str(tmp_path))
    load = Mock()
    monkeypatch.setitem(sys.modules, "torch", NS(hub=NS(load=load)))
    session = NS(ask=Mock(return_value=True), stage=Mock())
    assert runtime.prepare_silero(session) is True
    assert load.call_args.args == ("snakers4/silero-models", "silero_tts")
    assert load.call_args.kwargs["trust_repo"] is True
    session.ask.assert_called_once()


def test_gui_smoke_awaits_close_and_does_not_start_assistant(tmp_path, monkeypatch):
    page = NS(title="", add=Mock(), update=Mock(), window=NS(prevent_close=True, close=AsyncMock()))
    def run(fn, **kwargs):
        asyncio.run(fn(page))
    fake = NS(run=run, Text=lambda text: text, AppView=NS(FLET_APP="desktop"))
    monkeypatch.setitem(sys.modules, "flet", fake)
    async def no_sleep(delay):
        pass
    monkeypatch.setattr(runtime.asyncio, "sleep", no_sleep)
    destination = tmp_path / "gui.json"
    assert runtime.gui_smoke(tmp_path, destination, compiled=True) == 0
    page.window.close.assert_awaited_once()
    report = json.loads(destination.read_text(encoding="utf-8"))
    assert report["ok"] is True and report["session_opened"] is True
    assert "assistant_workflow" in report["not_tested"]


def test_gui_smoke_failure_is_not_success(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "flet", NS(run=Mock(side_effect=OSError("missing client")),
        AppView=NS(FLET_APP="desktop")))
    destination = tmp_path / "gui.json"
    assert runtime.gui_smoke(tmp_path, destination, compiled=True) == 1
    assert json.loads(destination.read_text(encoding="utf-8"))["ok"] is False


def test_runtime_refuses_non_windows_without_launching_core(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    assert runtime.run([], root=tmp_path, compiled=False) == 1


def test_com_cache_does_not_write_to_application_directory(tmp_path, monkeypatch):
    from types import ModuleType
    from jarvis import paths
    monkeypatch.setattr(paths, "user_dir", lambda: tmp_path / "user")
    com = ModuleType("comtypes")
    client = NS(gen_dir="old")
    monkeypatch.setitem(sys.modules, "comtypes", com)
    def load(name):
        if name == "comtypes.gen":
            raise ModuleNotFoundError("dynamic package", name="comtypes.gen")
        if name == "comtypes.client":
            assert sys.modules["comtypes.gen"].__path__ == [str(tmp_path / "user/comtypes-cache")]
            return client
        raise AssertionError(name)
    monkeypatch.setattr(runtime.importlib, "import_module", load)
    monkeypatch.setitem(sys.modules, "comtypes.gen", None)
    target = runtime.configure_com_cache()
    assert target.is_dir()
    assert client.gen_dir == str(target)
    assert com.gen.__path__ == [str(target)]


def test_native_preload_precedes_com_initialization(monkeypatch):
    events = []
    monkeypatch.setitem(sys.modules, "jarvis.main", NS(_preload_whisper_backend=lambda: events.append("ct2")))
    monkeypatch.setattr(runtime, "configure_com_cache", lambda: events.append("com"))
    runtime.prepare_native_imports()
    assert events == ["ct2", "com"]
