"""Archive-review regressions: no network, native audio or system automation."""

import json
import logging
import stat
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import launcher
from jarvis import model, tasks, timers
from jarvis.intents.execute import execute_intent
from jarvis.language import analyze_command
from jarvis.text_utils import normalize


@pytest.fixture
def timer_store(tmp_path, monkeypatch):
    target = tmp_path / "timers.json"
    monkeypatch.setattr(timers, "_timers_file", lambda: target)
    monkeypatch.setattr(timers, "_scheduled", {})
    monkeypatch.setattr(timers, "_on_fire_callback", None)
    return target


def fail_replace(*args, **kwargs):
    raise PermissionError("simulated locked JSON file")


@pytest.mark.parametrize("phrase", [
    "напомни через 5 минут выпить чай",
    "напомни в 18:30 выпить чай",
])
def test_timer_write_failure_is_not_reported_as_success(timer_store, monkeypatch, phrase):
    scheduled = Mock()
    monkeypatch.setattr(timers, "_schedule_one", scheduled)
    monkeypatch.setattr(timers.os, "replace", fail_replace)
    reply = timers.handle_timer_command(phrase)
    assert reply and "не удалось" in reply.lower()
    assert not timer_store.exists()
    assert not list(timer_store.parent.glob("*.tmp"))
    scheduled.assert_not_called()


def test_timer_intent_write_failure_does_not_report_success(timer_store, monkeypatch):
    scheduled = Mock()
    monkeypatch.setattr(timers, "_schedule_one", scheduled)
    monkeypatch.setattr(timers.os, "replace", fail_replace)
    reply = execute_intent(SimpleNamespace(), {
        "action": "set_timer", "seconds": 300, "text": "выпить чай",
    })
    assert "не удалось" in reply.lower()
    scheduled.assert_not_called()
    assert not timer_store.exists()


def test_timer_add_persists_before_scheduling(timer_store, monkeypatch):
    def schedule(timer):
        assert json.loads(timer_store.read_text(encoding="utf-8")) == [timer]

    monkeypatch.setattr(timers, "_schedule_one", schedule)
    item = timers.add("чай", time.time() + 300)
    assert timers.list_all() == [item]


def test_timer_cancel_write_failure_keeps_running_timers(timer_store, monkeypatch):
    monkeypatch.setattr(timers, "_schedule_one", Mock())
    item = timers.add("чай", time.time() + 300)
    running = Mock()
    timers._scheduled[item["id"]] = running
    monkeypatch.setattr(timers.os, "replace", fail_replace)
    reply = timers.handle_timer_command("отмени все напоминания")
    assert "не удалось" in reply.lower()
    running.cancel.assert_not_called()
    assert timers._scheduled[item["id"]] is running
    assert timers.list_all() == [item]


def test_timer_cancel_success_persists_and_cancels(timer_store, monkeypatch):
    monkeypatch.setattr(timers, "_schedule_one", Mock())
    item = timers.add("чай", time.time() + 300)
    running = Mock()
    timers._scheduled[item["id"]] = running
    assert timers.remove_all() == 1
    running.cancel.assert_called_once()
    assert timers.list_all() == []
    assert timers._scheduled == {}


def test_due_timer_still_notifies_if_removal_cannot_be_saved(timer_store, monkeypatch):
    monkeypatch.setattr(timers, "_schedule_one", Mock())
    item = timers.add("чай", time.time() + 300)
    callback = Mock()
    monkeypatch.setattr(timers, "_on_fire_callback", callback)
    timers._scheduled[item["id"]] = Mock()
    monkeypatch.setattr(timers.os, "replace", fail_replace)
    timers._fire(item["id"])
    callback.assert_called_once_with(item)
    assert item["id"] not in timers._scheduled


@pytest.mark.parametrize("phrase", [
    "убери хлеб из списка", "удали хлеб из списка",
    "убери из списка хлеб", "удали из списка хлеб",
    "убери хлеб", "удали хлеб",
])
def test_documented_task_removal_forms(tmp_path, monkeypatch, phrase):
    monkeypatch.setattr(tasks, "_tasks_file", lambda: tmp_path / "tasks.json")
    tasks.add("купить хлеб")
    reply = tasks.handle_task_command(normalize(analyze_command(phrase).command))
    assert reply.startswith("Убрал:")
    assert tasks.list_items() == []


def test_task_removal_without_name_does_not_remove_anything(tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, "_tasks_file", lambda: tmp_path / "tasks.json")
    item = tasks.add("купить хлеб")
    reply = tasks.handle_task_command("убери из списка")
    assert "какую задачу" in reply.lower()
    assert tasks.list_items() == [item]


def make_model(directory):
    for name in model.REQUIRED_MODEL_FILES:
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"model fixture")
    return directory


def fake_download(monkeypatch, missing=None, extra=None):
    def retrieve(_url, filename, reporthook=None):
        with zipfile.ZipFile(filename, "w") as archive:
            for name in model.REQUIRED_MODEL_FILES:
                if name != missing:
                    archive.writestr(f"{model.MODEL_NAME}/{name}", b"model fixture")
            if extra is not None:
                archive.writestr(extra, b"test marker")
        return str(filename), None

    retrieve = Mock(side_effect=retrieve)
    monkeypatch.setattr(model.urllib.request, "urlretrieve", retrieve)
    return retrieve


@pytest.fixture
def models_dir(tmp_path, monkeypatch):
    directory = tmp_path / "models"
    directory.mkdir()
    monkeypatch.setattr(model.paths, "program_models_dir", lambda: directory)
    return directory


@pytest.mark.parametrize("broken", ["am-only", "missing-file", "empty-file", "directory"])
def test_vosk_incomplete_model_is_repaired(models_dir, monkeypatch, broken):
    target = models_dir / model.MODEL_NAME
    if broken == "am-only":
        (target / "am").mkdir(parents=True)
    else:
        make_model(target)
        required = target / "am/final.mdl"
        if broken == "empty-file":
            required.write_bytes(b"")
        else:
            required.unlink()
            if broken == "directory":
                required.mkdir()
    assert not model.model_is_ready(target)
    retrieve = fake_download(monkeypatch)
    assert model.ensure_model() == target
    retrieve.assert_called_once()
    assert model.model_is_ready(target)
    assert list(models_dir.iterdir()) == [target]


def test_vosk_complete_model_does_not_download(models_dir, monkeypatch):
    target = make_model(models_dir / model.MODEL_NAME)
    retrieve = Mock(side_effect=AssertionError("unexpected network access"))
    monkeypatch.setattr(model.urllib.request, "urlretrieve", retrieve)
    assert model.ensure_model() == target
    retrieve.assert_not_called()


@pytest.mark.parametrize("entry", [
    f"{model.MODEL_NAME}/../escaped.txt",
    f"{model.MODEL_NAME}/../../escaped.txt",
    f"{model.MODEL_NAME}\\..\\escaped.txt",
    f"{model.MODEL_NAME}/.. /escaped.txt",
    f"{model.MODEL_NAME}/.../escaped.txt",
    f"{model.MODEL_NAME}/C:/escaped.txt",
    f"{model.MODEL_NAME}/am/final.mdl:stream",
    f"/{model.MODEL_NAME}/am/final.mdl",
    "other-model/am/final.mdl",
])
def test_vosk_zip_rejects_unsafe_paths(models_dir, monkeypatch, entry):
    fake_download(monkeypatch, extra=entry)
    with pytest.raises(ValueError):
        model.ensure_model()
    assert not (models_dir / model.MODEL_NAME).exists()
    assert not (models_dir / "escaped.txt").exists()
    assert not (models_dir.parent / "escaped.txt").exists()
    assert list(models_dir.iterdir()) == []


def test_vosk_zip_rejects_symlinks(models_dir, monkeypatch):
    link = zipfile.ZipInfo(f"{model.MODEL_NAME}/am/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    fake_download(monkeypatch, extra=link)
    with pytest.raises(ValueError):
        model.ensure_model()
    assert list(models_dir.iterdir()) == []


def test_vosk_incomplete_download_is_not_published(models_dir, monkeypatch):
    fake_download(monkeypatch, missing="am/final.mdl")
    with pytest.raises(RuntimeError, match="неполная"):
        model.ensure_model()
    assert list(models_dir.iterdir()) == []


def test_vosk_failed_download_preserves_previous_directory(models_dir, monkeypatch):
    target = models_dir / model.MODEL_NAME
    target.mkdir()
    marker = target / "previous.txt"
    marker.write_bytes(b"keep")
    retrieve = Mock(side_effect=OSError("offline"))
    monkeypatch.setattr(model.urllib.request, "urlretrieve", retrieve)
    with pytest.raises(OSError, match="offline"):
        model.ensure_model()
    assert marker.read_bytes() == b"keep"
    assert list(models_dir.iterdir()) == [target]


def test_vosk_unsafe_zip_preserves_previous_directory(models_dir, monkeypatch):
    target = models_dir / model.MODEL_NAME
    target.mkdir()
    marker = target / "previous.txt"
    marker.write_bytes(b"keep")
    fake_download(monkeypatch, extra=f"{model.MODEL_NAME}/../escaped.txt")
    with pytest.raises(ValueError):
        model.ensure_model()
    assert marker.read_bytes() == b"keep"
    assert list(models_dir.iterdir()) == [target]


def test_vosk_local_copy_needs_no_network(models_dir, tmp_path, monkeypatch):
    local = tmp_path / "локальные-модели"
    source = make_model(local / model.MODEL_NAME)
    retrieve = Mock(side_effect=AssertionError("unexpected network access"))
    monkeypatch.setattr(model.urllib.request, "urlretrieve", retrieve)
    target = model.ensure_model(local)
    assert model.model_is_ready(target)
    assert model.model_is_ready(source)
    retrieve.assert_not_called()


def test_vosk_failed_local_copy_falls_back_to_clean_download(models_dir, tmp_path, monkeypatch):
    local = tmp_path / "local"
    make_model(local / model.MODEL_NAME)

    def interrupted_copy(source, destination):
        (destination / "am").mkdir(parents=True)
        raise OSError("interrupted copy")

    monkeypatch.setattr(model.shutil, "copytree", interrupted_copy)
    retrieve = fake_download(monkeypatch)
    target = model.ensure_model(local)
    retrieve.assert_called_once()
    assert model.model_is_ready(target)
    assert list(models_dir.iterdir()) == [target]


def test_vosk_launcher_progress_hook_is_passed_to_downloader(models_dir, monkeypatch):
    retrieve = fake_download(monkeypatch)
    progress = Mock()
    model.ensure_model(reporthook=progress)
    assert retrieve.call_args.kwargs["reporthook"] is progress


def test_vosk_failed_publication_restores_previous_directory(models_dir, tmp_path, monkeypatch):
    target = models_dir / model.MODEL_NAME
    target.mkdir()
    marker = target / "previous.txt"
    marker.write_bytes(b"keep")
    local = tmp_path / "local"
    make_model(local / model.MODEL_NAME)
    original = Path.replace

    def fail_publish(self, destination):
        if self.name == "model":
            raise PermissionError("cannot publish")
        return original(self, destination)

    monkeypatch.setattr(Path, "replace", fail_publish)
    with pytest.raises(PermissionError, match="cannot publish"):
        model.ensure_model(local)
    assert marker.read_bytes() == b"keep"
    assert list(models_dir.iterdir()) == [target]


def test_launcher_uses_same_model_validation(models_dir):
    target = models_dir / model.MODEL_NAME
    (target / "am").mkdir(parents=True)
    logger = logging.getLogger("test.launcher")
    assert not launcher.check_vosk_model(models_dir.parent, logger)
    make_model(target)
    assert launcher.check_vosk_model(models_dir.parent, logger)


def test_launcher_prepares_local_model_with_shared_installer(models_dir, tmp_path, monkeypatch):
    project = tmp_path / "project"
    make_model(project / "models" / model.MODEL_NAME)
    retrieve = Mock(side_effect=AssertionError("unexpected network access"))
    monkeypatch.setattr(model.urllib.request, "urlretrieve", retrieve)
    monkeypatch.setattr(launcher, "info", Mock())
    monkeypatch.setattr(launcher, "error", Mock())
    assert launcher.download_vosk_model(project, logging.getLogger("test.launcher"))
    assert model.model_is_ready(models_dir / model.MODEL_NAME)
    retrieve.assert_not_called()


def test_launcher_reports_model_installation_failure(models_dir, tmp_path, monkeypatch):
    fake_download(monkeypatch, missing="am/final.mdl")
    monkeypatch.setattr(launcher, "info", Mock())
    error = Mock()
    monkeypatch.setattr(launcher, "error", error)
    assert not launcher.download_vosk_model(tmp_path, logging.getLogger("test.launcher"))
    error.assert_called_once()
    assert not (models_dir / model.MODEL_NAME).exists()