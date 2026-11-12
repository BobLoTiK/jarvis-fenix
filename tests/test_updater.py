# -*- coding: utf-8 -*-
"""Обновления: версии, строгий разбор релиза, SHA-256, помощник, карточка GUI.

Сеть не нужна: подменяются загрузчик релиза и opener. Реальные установщики здесь
не запускаются — это проверяет отдельный opt-in сценарий на Windows.
"""
import queue
import threading
import time
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import flet as ft
import pytest

from jarvis import gui as gui_module
from jarvis import updater
from jarvis.config import Config

REPO_URL = "https://github.com/BobLoTiK/jarvis-fenix"
LIGHT = f"{REPO_URL}/releases/download/v2.2.0/Feniks_Setup_2.2.0.exe"
FAST = f"{REPO_URL}/releases/download/v2.2.0/Feniks_Fast_Setup_2.2.0.exe"
SUMS = f"{REPO_URL}/releases/download/v2.2.0/SHA256SUMS.txt"


def release_payload(tag="v2.2.0", version="2.2.0"):
    return {
        "tag_name": tag,
        "html_url": f"{REPO_URL}/releases/tag/{tag}",
        "body": "Что нового:\r\n- автообновление\r\n",
        "assets": [
            {"name": f"Feniks_Setup_{version}.exe", "browser_download_url": LIGHT,
             "size": 14_000_000, "digest": "sha256:" + "a" * 64},
            {"name": f"Feniks_Fast_Setup_{version}.exe", "browser_download_url": FAST,
             "size": 310_000_000},
            {"name": "SHA256SUMS.txt", "browser_download_url": SUMS, "size": 128},
            {"name": "notes.zip", "browser_download_url": f"{REPO_URL}/releases/download/v2.2.0/notes.zip"},
        ],
    }


class FakeResponse:
    def __init__(self, url, data=b"", headers=None):
        self._url = url
        self._data = data
        self._pos = 0
        self.headers = headers if headers is not None else {"Content-Length": str(len(data))}

    def read(self, size=-1):
        if size is None or size < 0:
            size = len(self._data) - self._pos
        chunk = self._data[self._pos:self._pos + size]
        self._pos += len(chunk)
        return chunk

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    def __init__(self, data, url, headers=None):
        self.response = FakeResponse(url, data, headers)
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        return self.response


@pytest.fixture
def updates_dir(tmp_path):
    folder = tmp_path / "updates"
    folder.mkdir()
    return folder


# ---------------------------------------------------------------- версии

@pytest.mark.parametrize("text,expected", [
    ("v2.1.3", (2, 1, 3)), ("2.1.3", (2, 1, 3)), ("V2.2", (2, 2)),
    ("2", (2,)), ("2.1.3.4", (2, 1, 3, 4)),
])
def test_parse_version_accepts_plain_numbers(text, expected):
    assert updater.parse_version(text) == expected


@pytest.mark.parametrize("text", [None, "", "v", "2.1.3-beta", "2.1.3+build",
                                  "latest", "2..3", "2.1.3.4.5", [2, 1]])
def test_parse_version_rejects_suffixes_and_noise(text):
    assert updater.parse_version(text) is None


def test_is_newer_pads_short_versions():
    assert updater.is_newer((2, 2), (2, 1, 3)) is True
    assert updater.is_newer((2, 1, 3), (2, 1, 3)) is False
    assert updater.is_newer((2, 1, 2), (2, 1, 3)) is False
    assert updater.is_newer((2, 2, 0, 0), (2, 2)) is False


# ---------------------------------------------------------------- релиз

def test_parse_release_keeps_only_expected_assets():
    release = updater.parse_release(release_payload())
    assert release.version == "2.2.0" and release.tag == "v2.2.0"
    assert [asset.name for asset in release.assets] == [
        "Feniks_Setup_2.2.0.exe", "Feniks_Fast_Setup_2.2.0.exe", "SHA256SUMS.txt"]
    assert release.installer("light").size == 14_000_000
    assert release.installer("standalone").url == FAST
    assert release.sums().name == "SHA256SUMS.txt"
    assert release.notes == "Что нового:\n- автообновление"
    assert release.page.endswith("/tag/v2.2.0")


def test_parse_release_drops_assets_from_foreign_hosts():
    payload = release_payload()
    payload["assets"][0]["browser_download_url"] = "https://evil.example/Feniks_Setup_2.2.0.exe"
    page = updater.parse_release(payload)
    assert page.installer("light") is None
    assert page.installer("standalone") is not None


def test_parse_release_refuses_prerelease_tags():
    with pytest.raises(updater.UpdateError) as error:
        updater.parse_release(release_payload(tag="v2.2.0-rc1"))
    assert error.value.kind == "unavailable"


def test_check_reports_update_current_and_error():
    newer = updater.check("2.1.3", loader=lambda url: release_payload())
    assert newer.status == "update" and newer.release.version == "2.2.0"
    same = updater.check("2.2.0", loader=lambda url: release_payload())
    assert same.status == "current" and same.release is not None

    def broken(url):
        raise updater.UpdateError("dns", updater.ERROR_TEXTS["dns"])

    failed = updater.check("2.1.3", loader=broken)
    assert failed.status == "error" and failed.release is None
    assert "DNS" in failed.error


def test_describe_is_honest_for_each_status():
    update = updater.check("2.1.3", loader=lambda url: release_payload())
    assert "2.2.0" in updater.describe(update) and "2.1.3" in updater.describe(update)
    assert "последняя" in updater.describe(
        updater.check("2.2.0", loader=lambda url: release_payload())).lower()
    assert "нет связи" in updater.describe(
        updater.CheckResult("error", "2.1.3", None, "Нет связи с GitHub.")).lower()


def test_foreign_url_is_rejected():
    with pytest.raises(updater.UpdateError):
        updater._check_url("http://github.com/x")
    with pytest.raises(updater.UpdateError):
        updater._check_url("https://github.com.evil.example/x")
    with pytest.raises(updater.UpdateError):
        updater._check_url("https://user:pw@github.com/x")
    assert updater._check_url(LIGHT) == LIGHT


# ---------------------------------------------------------------- скачивание

def test_parse_sums_reads_published_format():
    text = ("  " + "a" * 64 + "  Feniks_Setup_2.2.0.exe\r\n"
            + "B" * 64 + " *Feniks_Fast_Setup_2.2.0.exe\r\n"
            + "# comment\nbroken line\n")
    sums = updater.parse_sums(text)
    assert sums["feniks_setup_2.2.0.exe"] == "a" * 64
    assert sums["feniks_fast_setup_2.2.0.exe"] == "b" * 64
    assert len(sums) == 2


def test_download_verifies_hash_and_keeps_only_final_file(tmp_path, monkeypatch):
    data = b"MZ" + b"x" * 5000
    digest = __import__("hashlib").sha256(data).hexdigest()
    asset = updater.Asset(name="Feniks_Setup_2.2.0.exe", url=LIGHT,
                          size=len(data), digest=digest)
    monkeypatch.setattr(updater, "_opener", lambda: FakeOpener(data, LIGHT))
    seen = []
    path = updater.download(asset, tmp_path, progress=lambda d, t: seen.append((d, t)))
    assert path == tmp_path / "Feniks_Setup_2.2.0.exe" and path.read_bytes() == data
    assert not (tmp_path / "Feniks_Setup_2.2.0.exe.part").exists()
    assert seen[-1] == (len(data), len(data))


def test_download_refuses_wrong_hash_and_leaves_nothing(tmp_path, monkeypatch):
    data = b"MZ" + b"x" * 100
    asset = updater.Asset(name="Feniks_Setup_2.2.0.exe", url=LIGHT,
                          size=len(data), digest="b" * 64)
    monkeypatch.setattr(updater, "_opener", lambda: FakeOpener(data, LIGHT))
    with pytest.raises(updater.UpdateError):
        updater.download(asset, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_download_without_any_hash_is_refused(tmp_path):
    asset = updater.Asset(name="Feniks_Setup_2.2.0.exe", url=LIGHT, size=10)
    with pytest.raises(updater.UpdateError) as error:
        updater.download(asset, tmp_path)
    assert "контрольной суммы" in str(error.value)


def test_download_rejects_unexpected_asset_name(tmp_path):
    asset = updater.Asset(name="setup.exe", url=LIGHT, size=10, digest="a" * 64)
    with pytest.raises(updater.UpdateError):
        updater.download(asset, tmp_path)


def test_download_stops_on_size_mismatch(tmp_path, monkeypatch):
    data = b"x" * 100
    asset = updater.Asset(name="Feniks_Setup_2.2.0.exe", url=LIGHT, size=90, digest="a" * 64)
    monkeypatch.setattr(updater, "_opener", lambda: FakeOpener(data, LIGHT,
                                                              {"Content-Length": "100"}))
    with pytest.raises(updater.UpdateError) as error:
        updater.download(asset, tmp_path)
    assert "размер" in str(error.value).lower()
    assert list(tmp_path.iterdir()) == []


def test_fetch_sums_uses_published_asset(monkeypatch):
    text = ("a" * 64 + "  Feniks_Setup_2.2.0.exe\n").encode("utf-8")
    monkeypatch.setattr(updater, "_opener", lambda: FakeOpener(text, SUMS))
    sums = updater.fetch_sums(updater.Asset(name="SHA256SUMS.txt", url=SUMS))
    assert sums == {"feniks_setup_2.2.0.exe": "a" * 64}


def test_cleanup_keeps_requested_installer(updates_dir):
    keep = updates_dir / "Feniks_Setup_2.2.0.exe"
    keep.write_bytes(b"MZ")
    (updates_dir / "Feniks_Fast_Setup_2.1.2.exe").write_bytes(b"MZ")
    (updates_dir / "Feniks_Setup_2.2.0.exe.part").write_bytes(b"MZ")
    (updates_dir / "apply_update.ps1").write_text("x", encoding="utf-8")
    assert updater.cleanup_installers(updates_dir, keep=keep) == 2
    assert [item.name for item in updates_dir.iterdir()] == [
        "Feniks_Setup_2.2.0.exe", "apply_update.ps1"] or keep.is_file()


# ---------------------------------------------------------------- тип сборки

def test_install_kind_from_files(tmp_path):
    source = tmp_path / "src"
    (source / ".git").mkdir(parents=True)
    (source / "launcher.py").write_text("# app", encoding="utf-8")
    assert updater.install_kind(source) == "source"

    light = tmp_path / "light"
    (light / "jarvis").mkdir(parents=True)
    (light / "launcher.py").write_text("# launcher", encoding="utf-8")
    (light / "jarvis" / "__init__.py").write_text("", encoding="utf-8")
    (light / updater.APP_EXE).write_bytes(b"MZ")
    assert updater.install_kind(light) == "light"

    # Свежая установка до первого запуска: launcher.py есть, .venv311 ещё нет.
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    (fresh / "launcher.py").write_text("# launcher", encoding="utf-8")
    (fresh / updater.APP_EXE).write_bytes(b"MZ")
    assert updater.install_kind(fresh) == "light"

    # Автономная сборка: exe есть, исходников и launcher.py нет по построению.
    standalone = tmp_path / "fast"
    (standalone / "jarvis" / "assets").mkdir(parents=True)
    (standalone / updater.APP_EXE).write_bytes(b"MZ")
    assert updater.install_kind(standalone) == "standalone"

    empty = tmp_path / "empty"
    empty.mkdir()
    assert updater.install_kind(empty) == "source"


# ---------------------------------------------------------------- помощник

def test_helper_script_is_ascii_safe_bom_and_covers_the_flow(updates_dir):
    path = updater.write_helper(updates_dir)
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # PowerShell 5.1 читает BOM корректно
    text = raw.decode("utf-8-sig")
    for marker in ("PHOENIX_UPDATE_INSTALLER", "PHOENIX_UPDATE_SHA", "PHOENIX_UPDATE_PID",
                   "/VERYSILENT", "/DIR=", "SHA256", "Start-Process", "Save-Result",
                   "JarvisPhoenixSingleInstance", "Restart-Phoenix"):
        assert marker in text, marker
    assert "{0}" not in text and "{version}" not in text


def test_helper_script_quotes_installer_paths(updates_dir):
    """Путь с пробелом обязан приезжать в установщик одной строкой в кавычках.

    Проверено живьём до правки: /DIR=C:\\...\\Temp\\phx e2e b уходил без кавычек,
    установщик видел первый кусок и создавал мусорный каталог "...\\Temp\\phx".
    """
    text = updater.write_helper(updates_dir).read_text(encoding="utf-8-sig")
    assert '/DIR="' in text
    assert '" /LOG="' in text
    assert '"/DIR=$root"' not in text
    assert '"/LOG=$env:PHOENIX_UPDATE_SETUP_LOG"' not in text
    # одним аргументом: массив PowerShell 5.1 склеивает пробелами без кавычек
    assert text.count("-ArgumentList $argumentLine") == 2
    assert "-ArgumentList $arguments" not in text


def test_spawn_installer_passes_values_through_environment(tmp_path, monkeypatch):
    root = tmp_path / "Phoenix"
    root.mkdir()
    (root / updater.APP_EXE).write_bytes(b"MZ")
    installer = tmp_path / "updates" / "Feniks_Setup_2.2.0.exe"
    installer.parent.mkdir()
    installer.write_bytes(b"MZ")
    seen = {}

    class FakeProcess:
        pid = 4321

    def fake_popen(command, **kwargs):
        seen["command"] = command
        seen.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr(updater.os, "name", "nt")
    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)
    process = updater.spawn_installer(installer, "2.2.0", root=root, pid=999)
    assert process.pid == 4321
    assert seen["command"][-1].endswith(updater.HELPER_NAME)
    assert seen["env"]["PHOENIX_UPDATE_ROOT"] == str(root)
    assert seen["env"]["PHOENIX_UPDATE_VERSION"] == "2.2.0"
    assert seen["env"]["PHOENIX_UPDATE_ELEVATE"] == "1"  # standalone требует прав
    assert seen["env"]["PHOENIX_UPDATE_PID"] == "999"
    assert len(seen["env"]["PHOENIX_UPDATE_SHA"]) == 64
    assert seen["creationflags"] == updater.CREATE_NO_WINDOW
    assert seen["stdin"] is updater.subprocess.DEVNULL


def test_spawn_installer_refuses_missing_app(tmp_path, monkeypatch):
    installer = tmp_path / "Feniks_Setup_2.2.0.exe"
    installer.write_bytes(b"MZ")
    monkeypatch.setattr(updater.os, "name", "nt")
    with pytest.raises(updater.UpdateError):
        updater.spawn_installer(installer, "2.2.0", root=tmp_path / "nowhere")


def test_spawn_installer_requires_windows(tmp_path, monkeypatch):
    installer = tmp_path / "Feniks_Setup_2.2.0.exe"
    installer.write_bytes(b"MZ")
    monkeypatch.setattr(updater.os, "name", "posix")
    with pytest.raises(updater.UpdateError):
        updater.spawn_installer(installer, "2.2.0", root=tmp_path)


def test_last_result_roundtrip_and_cleanup(updates_dir):
    target = updates_dir / updater.RESULT_NAME
    target.write_text('{"status": "ok", "version": "2.2.0", "exit_code": 0, '
                      '"message": "ok", "at": "2026-11-11T10:00:00"}',
                      encoding="utf-8-sig")
    result = updater.read_last_result(updates_dir)
    assert result == {"status": "ok", "version": "2.2.0", "exit_code": 0, "message": "ok"}
    assert updater.read_last_result(updates_dir) is None  # файл удалён
    assert not target.exists()


@pytest.mark.parametrize("payload", ["", "не json", "[]", '{"status": "wat"}'])
def test_last_result_ignores_junk(updates_dir, payload):
    (updates_dir / updater.RESULT_NAME).write_text(payload, encoding="utf-8")
    assert updater.read_last_result(updates_dir) is None


# ---------------------------------------------------------------- карточка GUI

def walk(control):
    yield control
    content = getattr(control, "content", None)
    if isinstance(content, ft.Control):
        yield from walk(content)
    for child in getattr(control, "controls", []) or []:
        yield from walk(child)


@pytest.fixture
def gui(tmp_path, monkeypatch):
    window = gui_module.FenixGUI(None, Config(tmp_path / "config.json"))
    window._page = NS(add=Mock(), update=Mock(), window=NS(), overlay=None)
    monkeypatch.setattr(window, "_get_voice_options", lambda: [ft.dropdown.Option("ruslan")])
    window._build_ui(window._page)
    yield window
    window.stop()


def take(gui, kind, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            item = gui._queue.get(timeout=0.05)
        except queue.Empty:
            continue
        if item and item[0] == kind:
            return item[1]
    raise AssertionError(f"нет сообщения {kind}")


def test_settings_card_has_updates_block_without_network(gui):
    screen = gui._preferences()
    card = screen.build_settings()
    texts = [getattr(control, "value", "") for control in walk(card)]
    assert any("Обновления" in str(value) for value in texts)
    assert screen.update_check_button is not None
    assert screen.update_button is not None and screen.update_button.visible is False
    assert screen.update_label.value == "Обновления ещё не проверялись."


def test_check_result_lands_in_card_and_shows_install_button(gui, monkeypatch):
    screen = gui._preferences()
    screen.build_settings()
    monkeypatch.setattr(updater, "install_kind", lambda root=None: "light")
    monkeypatch.setattr(updater, "check", lambda current=None, loader=None: updater.CheckResult(
        "update", "2.1.3", updater.parse_release(release_payload())))
    assert screen.start_update_check() is True
    screen.apply_update_result(take(gui, "update_result"))
    assert "2.2.0" in screen.update_label.value
    assert screen.update_notes_label.visible is True and "автообновление" in screen.update_notes
    assert screen.update_button.visible is True
    assert screen.update_button.content == "Скачать обновление"
    assert screen.update_busy is False


def test_source_run_never_offers_install(gui, monkeypatch):
    screen = gui._preferences()
    screen.build_settings()
    monkeypatch.setattr(updater, "check", lambda current=None, loader=None: updater.CheckResult(
        "update", "2.1.3", updater.parse_release(release_payload())))
    screen.start_update_check()
    screen.apply_update_result(take(gui, "update_result"))
    assert screen.update_button.visible is False
    assert screen.start_update_download() is False
    assert "установленной копии" in screen.update_status


def test_download_worker_reports_file_and_install_uses_it(gui, monkeypatch, updates_dir):
    screen = gui._preferences()
    screen.build_settings()
    monkeypatch.setattr(updater, "install_kind", lambda root=None: "light")
    screen.update_generation = 7
    screen.update_release = updater.parse_release(release_payload())
    installer = updates_dir / "Feniks_Setup_2.2.0.exe"
    installer.write_bytes(b"MZ")
    screen.apply_update_result(("download", 7, (installer, "")))
    assert screen.update_file == installer
    assert screen.update_button.content == "Установить и перезапустить"
    spawned = {}
    monkeypatch.setattr(updater, "spawn_installer",
                        lambda path, version, **kwargs: spawned.update(path=path, version=version))
    assert screen.start_update_apply() is True
    assert spawned == {"path": installer, "version": "2.2.0"}
    assert take(gui, "update_quit") is None


def test_cancel_button_stops_download_and_clears_state(gui, monkeypatch):
    """Отмена обрывает поток, недокачанный файл не остаётся, кнопки гаснут."""
    screen = gui._preferences()
    screen.build_settings()
    monkeypatch.setattr(updater, "install_kind", lambda root=None: "light")
    monkeypatch.setattr(updater, "cleanup_installers", lambda *a, **k: 0)
    monkeypatch.setattr(updater, "fetch_sums", lambda asset: {})
    screen.update_release = updater.parse_release(release_payload())
    started = threading.Event()
    seen = {}

    def fake_download(asset, dest_dir=None, *, sums=None, progress=None, cancel=None):
        seen["cancel"] = cancel
        started.set()
        if not cancel.wait(5):
            raise AssertionError("поток скачивания не получил сигнал отмены")
        raise updater.UpdateError("cancelled", updater.ERROR_TEXTS["cancelled"])

    monkeypatch.setattr(updater, "download", fake_download)
    assert screen.start_update_download() is True
    assert started.wait(5)
    assert screen.update_cancel_button.visible is True
    assert screen.cancel_update_download() is True
    screen.apply_update_result(take(gui, "update_result"))
    assert seen["cancel"].is_set()
    assert screen.update_busy is False and screen.update_file is None
    assert "отменено" in screen.update_status.lower()
    assert screen.update_cancel_button.visible is False


def test_check_click_while_busy_explains_what_is_running(gui):
    """Раньше кнопка молча ничего не делала и это выглядело как поломка."""
    screen = gui._preferences()
    screen.build_settings()
    screen.update_busy = True
    screen.update_phase = "download"
    assert screen.start_update_check() is False
    assert "скачивание" in screen.update_status.lower()


def test_stale_result_from_previous_generation_is_ignored(gui):
    screen = gui._preferences()
    screen.build_settings()
    screen.update_generation = 3
    screen.update_status = "Проверяю GitHub…"
    screen.apply_update_result(("check", 2, updater.CheckResult("current", "2.1.3")))
    assert screen.update_status == "Проверяю GitHub…"


def test_update_toggle_persists_flag(gui):
    screen = gui._preferences()
    screen.build_settings()
    assert gui.config.get("update_check_enabled", True) is True
    control = NS(control=NS(value=False))
    screen._on_update_toggle(control)
    assert gui.config.get("update_check_enabled") is False
    assert control.control.value is False
