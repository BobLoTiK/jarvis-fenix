"""Плагины: манифест, согласие, lifecycle, таймаут, падение и стадия pipeline."""
import json
import subprocess
from pathlib import Path

import pytest

from jarvis import plugins as plugin_module
from jarvis.intents.stages.plugins import PluginStage
from jarvis.plugins import (PluginError, PluginHost, PluginManifest, PluginRunner,
                            PluginSettings)


def write_plugin(root: Path, *, name="hello", entry="main.py", capabilities=("command",),
                 commands=None, timeout=5, code="print('{}')", extra=None):
    folder = root / name
    folder.mkdir(parents=True)
    manifest = {
        "name": name, "version": "1.0.0", "entry": entry,
        "capabilities": list(capabilities), "timeout_sec": timeout,
        "commands": commands if commands is not None else [
            {"phrases": ["привет от плагина", "проверка плагина"], "action": "hello"}],
    }
    if extra:
        manifest.update(extra)
    (folder / "plugin.json").write_text(json.dumps(manifest, ensure_ascii=False),
                                        encoding="utf-8")
    (folder / entry).write_text(code, encoding="utf-8")
    return folder


class FakeProcess:
    def __init__(self, stdout=b"", stderr=b"", code=0, hang=None, crash_on_communicate=None):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = code
        self.hang = hang
        self.crash_on_communicate = crash_on_communicate
        self.killed = False

    def communicate(self, input=None, timeout=None):
        if self.crash_on_communicate is not None:
            raise self.crash_on_communicate
        if self.hang is not None:
            raise subprocess.TimeoutExpired(cmd="plugin", timeout=self.hang)
        return self.stdout, self.stderr

    def kill(self):
        self.killed = True


def manifest(root, **kwargs):
    return PluginManifest.from_json(write_plugin(root, **kwargs) / "plugin.json")


# --- манифест ----------------------------------------------------------


def test_manifest_is_parsed_and_phrase_map_is_normalized(tmp_path):
    data = manifest(tmp_path)
    assert data.name == "hello" and data.entry == "main.py"
    assert data.capabilities == ("command",)
    assert data.phrase_map()["привет от плагина"].action == "hello"


@pytest.mark.parametrize("kwargs,fragment", [
    ({"name": "Hello!"}, "name"),
    ({"extra": {"version": ""}}, "version"),
    ({"entry": "../evil.py"}, "entry"),
    ({"capabilities": ("filesystem-write",)}, "вне первого шага"),
    ({"capabilities": ("command",)}, ""),
    ({"commands": []}, "commands"),
    ({"commands": [{"phrases": [], "action": "x"}]}, "phrases"),
    ({"commands": [{"phrases": ["a"], "action": ""}]}, "action"),
    ({"timeout": 500}, ""),
])
def test_bad_manifests_are_rejected_honestly(tmp_path, kwargs, fragment):
    folder = tmp_path / "plug"
    folder.mkdir()
    entry = "main.py"
    if kwargs.get("entry") == "../evil.py":
        (tmp_path / "evil.py").write_text("x", encoding="utf-8")
    (folder / entry).write_text("print(1)", encoding="utf-8")
    manifest_data = {"name": "hello", "version": "1", "entry": entry,
                     "capabilities": ["command"],
                     "commands": [{"phrases": ["a"], "action": "b"}]}
    for key, value in kwargs.items():
        if key == "extra":
            manifest_data.update(value)
        elif key in ("name", "entry", "capabilities", "commands"):
            manifest_data[key] = value
        elif key == "timeout":
            manifest_data["timeout_sec"] = value
    (folder / "plugin.json").write_text(json.dumps(manifest_data), encoding="utf-8")
    if fragment:
        with pytest.raises(PluginError) as caught:
            PluginManifest.from_json(folder / "plugin.json")
        assert fragment in str(caught.value)
    else:
        parsed = PluginManifest.from_json(folder / "plugin.json")
        assert parsed.name == "hello"


def test_broken_json_and_missing_files_are_rejected(tmp_path):
    folder = tmp_path / "bad"
    folder.mkdir()
    (folder / "plugin.json").write_text("{не json", encoding="utf-8")
    with pytest.raises(PluginError) as caught:
        PluginManifest.from_json(folder / "plugin.json")
    assert "JSON" in str(caught.value)
    with pytest.raises(PluginError):
        PluginManifest.from_json(tmp_path / "нет.json")


# --- раннер ------------------------------------------------------------


def test_runner_parses_json_answer(tmp_path):
    data = manifest(tmp_path)
    process = FakeProcess(stdout='{"text":"плагин сказал"}'.encode())
    runner = PluginRunner(popen=lambda argv, cwd: process)
    result = runner.run(data, {"command": "hello"})
    assert result.ok and result.text == "плагин сказал"


def test_runner_returns_plain_text(tmp_path):
    data = manifest(tmp_path)
    runner = PluginRunner(popen=lambda argv, cwd: FakeProcess(stdout="  просто текст ".encode()))
    assert runner.run(data, {}).text == "просто текст"


def test_runner_reports_timeout_and_kills_process(tmp_path):
    data = manifest(tmp_path, timeout=1)
    process = FakeProcess(hang=1)
    result = PluginRunner(popen=lambda argv, cwd: process).run(data, {})
    assert result.ok is False and "таймаут" in result.error
    assert process.killed is True


def test_runner_reports_crash_without_raising(tmp_path):
    data = manifest(tmp_path)
    process = FakeProcess(stderr=b"Traceback: boom", code=3)
    result = PluginRunner(popen=lambda argv, cwd: process).run(data, {})
    assert result.ok is False and "код 3" in result.error
    assert "Traceback" not in result.text


def test_runner_reports_error_field(tmp_path):
    data = manifest(tmp_path)
    process = FakeProcess(stdout='{"error":"нет такого действия"}'.encode())
    result = PluginRunner(popen=lambda argv, cwd: process).run(data, {})
    assert result.ok is False and result.error == "нет такого действия"


def test_runner_reports_launch_failure(tmp_path):
    data = manifest(tmp_path)

    def fail(argv, cwd):
        raise OSError("нет интерпретатора")

    result = PluginRunner(popen=fail).run(data, {})
    assert result.ok is False and "не запустился" in result.error


# --- хост и lifecycle --------------------------------------------------


def host_for(tmp_path, *, allowed=("hello",), runner=None):
    write_plugin(tmp_path)
    return PluginHost(tmp_path, runner=runner, allowed=allowed)


def test_discover_finds_plugins_and_collects_errors(tmp_path):
    write_plugin(tmp_path)
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "plugin.json").write_text("{", encoding="utf-8")
    host = PluginHost(tmp_path)
    found = host.discover()
    assert [m.name for m in found] == ["hello"]
    assert host.errors and host.errors[0][0] == "broken"


def test_plugin_not_started_without_consent(tmp_path):
    host = host_for(tmp_path, allowed=())
    host.discover()
    ok, message = host.start("hello")
    assert ok is False and "plugins_allowed" in message
    assert host.running() == []


def test_start_stop_lifecycle(tmp_path):
    host = host_for(tmp_path)
    host.discover()
    ok, _ = host.start("hello")
    assert ok and [m.name for m in host.running()] == ["hello"]
    assert host.stop("hello")[0] is True
    assert host.running() == []
    assert host.stop("hello")[0] is False


def test_unknown_plugin_is_honest(tmp_path):
    host = host_for(tmp_path)
    host.discover()
    ok, message = host.start("нет-такого")
    assert ok is False and "не найден" in message


def test_running_plugin_handles_only_its_phrases(tmp_path):
    calls = []

    def popen(argv, cwd):
        calls.append((argv, cwd))
        return FakeProcess(stdout='{"text":"ответ плагина"}'.encode())

    host = host_for(tmp_path, runner=PluginRunner(popen=popen))
    host.discover()
    host.start("hello")
    assert host.try_handle("открой блокнот") is None
    assert host.try_handle("  ПРИВЕТ   от   плагина ") == "ответ плагина"
    assert len(calls) == 1
    # `-I` глушит PYTHON* переменные, поэтому UTF-8 задаётся явным `-X utf8`.
    assert calls[0][0][1:4] == ["-I", "-X", "utf8"]


def test_default_popen_asks_for_utf8_output(monkeypatch, tmp_path):
    seen = {}

    def fake_popen(argv, **kwargs):
        seen["argv"] = argv
        seen.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    data = manifest(tmp_path)
    PluginRunner().run(data, {})
    assert seen["env"]["PYTHONIOENCODING"] == "utf-8"
    assert "utf8" in seen["argv"]


def test_stopped_plugin_does_not_answer(tmp_path):
    host = host_for(tmp_path, runner=PluginRunner(
        popen=lambda argv, cwd: FakeProcess(stdout=b'{"text":"x"}')))
    host.discover()
    host.start("hello")
    host.stop("hello")
    assert host.try_handle("привет от плагина") is None


def test_plugin_crash_becomes_reply_not_exception(tmp_path):
    host = host_for(tmp_path, runner=PluginRunner(
        popen=lambda argv, cwd: FakeProcess(code=9)))
    host.discover()
    host.start("hello")
    reply = host.try_handle("проверка плагина")
    assert "не ответил" in reply and "код 9" in reply


def test_plugin_settings_are_isolated(tmp_path):
    data = manifest(tmp_path)
    settings = PluginSettings(data, tmp_path / "settings")
    (tmp_path / "settings").mkdir()
    assert settings.load() == {}
    settings.set("theme", "dark")
    settings.set("theme", "light")
    assert settings.load() == {"theme": "light"}
    with pytest.raises(ValueError):
        settings.set("", 1)


def test_plugin_stage_is_inert_without_host():
    class Handler:
        plugins = None

    class Ctx:
        handler = Handler()
        cmd = "привет от плагина"

    assert PluginStage().handle(Ctx()) is None


def test_plugin_stage_calls_host_and_survives_errors():
    class Host:
        def __init__(self, reply=None, boom=None):
            self.reply, self.boom = reply, boom

        def try_handle(self, cmd):
            if self.boom:
                raise self.boom
            return self.reply

    class Ctx:
        def __init__(self, host):
            self.handler = type("H", (), {"plugins": host})()
            self.cmd = "привет от плагина"

    assert PluginStage().handle(Ctx(Host(reply="ответ"))) == "ответ"
    assert PluginStage().handle(Ctx(Host(boom=RuntimeError()))) == \
        "Плагин не смог обработать команду."


def test_example_plugin_manifest_is_valid():
    root = Path(__file__).resolve().parent.parent / "examples" / "plugins" / "hello"
    data = PluginManifest.from_json(root / "plugin.json")
    assert data.name == "hello"
    assert data.phrase_map()["проверка плагина"].action == "hello"
    assert plugin_module.READ_ONLY_CAPABILITIES >= set(data.capabilities)
