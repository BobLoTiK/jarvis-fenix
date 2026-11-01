"""Вкладка «Движки»: каталог, кнопка установки, прогресс и «активно» из конфига."""

import asyncio
import queue
import threading
import time
from types import SimpleNamespace as NS
from unittest.mock import Mock

import flet as ft
import pytest

from jarvis import engines, gui as module, mood, paths, profile
from jarvis.config import Config


@pytest.fixture
def screen(tmp_path, monkeypatch):
    monkeypatch.setattr(profile, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(profile, "_current", "test")
    monkeypatch.setattr(profile, "_cache", {})
    monkeypatch.setattr(profile, "_listeners", [])
    monkeypatch.setattr(paths, "program_models_dir", lambda: tmp_path / "models")
    monkeypatch.setattr(paths, "program_whisper_cache_dir", lambda: tmp_path / "whisper")
    (tmp_path / "models").mkdir()
    cfg = Config(tmp_path / "config.json")
    window = module.FenixGUI(None, cfg)
    window._page = NS(add=Mock(), update=Mock(), window=NS())
    monkeypatch.setattr(window, "_get_voice_options",
                        lambda: [ft.dropdown.Option("ruslan")])
    window._build_ui(window._page)
    view = window._engines_screen
    view.window = window
    yield view
    window.stop()
    profile.unsubscribe(window._on_profile_switch)
    mood.unsubscribe(window._on_mood_change)
    module._apply_palette("dark")


def collect(window, timeout=6.0, until="engines_done"):
    events = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            kind, value = window._queue.get_nowait()
        except queue.Empty:
            time.sleep(0.02)
            continue
        if kind.startswith("engines_"):
            events.append((kind, value))
        if kind == until:
            return events
    return events


def apply(screen, events):
    for kind, value in events:
        if kind == "engines_progress":
            screen.on_progress(value)
        elif kind == "engines_done":
            screen.on_done(value)


def test_engines_tab_lists_every_engine_and_is_wired(screen):
    window = screen.window
    assert window._tabs[module.ENGINES_TAB] is screen
    assert [item.key for item in screen.items] == [
        "vad", "vosk", "whisper", "piper", "silero", "sapi", "ollama", "cloud"]
    assert module.NAV_ITEMS[module.ENGINES_TAB][0] == "Движки"
    assert screen.is_busy() is False


def test_install_reports_progress_and_finishes(screen, monkeypatch):
    seen = []

    def fake_install(key, progress, config=None):
        progress(0.5, "середина")
        seen.append(key)
        return True, "готово"

    monkeypatch.setattr(engines, "install", fake_install)
    screen.start_install("vad")
    assert screen.is_busy()
    events = collect(screen.window)
    apply(screen, events)
    assert seen == ["vad"]
    assert not screen.is_busy()
    assert screen.messages["vad"] == ("готово", False)
    assert any(kind == "engines_progress" for kind, _ in events)


def test_failed_install_is_shown_as_error(screen, monkeypatch):
    monkeypatch.setattr(engines, "install", lambda key, progress, config=None:
                        (False, "Нет сети"))
    screen.start_install("vosk")
    apply(screen, collect(screen.window))
    assert screen.messages["vosk"] == ("Нет сети", True)


def test_second_install_is_refused_while_first_runs(screen, monkeypatch):
    gate = threading.Event()

    def slow_install(key, progress, config=None):
        gate.wait(5)
        return True, "готово"

    monkeypatch.setattr(engines, "install", slow_install)
    screen.start_install("vad")
    screen.start_install("vosk")
    assert "Дождитесь" in screen.messages["vosk"][0]
    gate.set()
    apply(screen, collect(screen.window))
    assert not screen.is_busy()


def test_ollama_status_updates_the_row(screen):
    screen.on_status(("http://127.0.0.1:11434", ["qwen2.5:7b-instruct"], True))
    ollama = next(item for item in screen.items if item.key == "ollama")
    assert ollama.installed
    assert "qwen2.5:7b-instruct" in ollama.detail


def test_busy_screen_survives_tab_reselect(screen):
    screen._busy.add("vad")
    screen.window._select_tab(module.ENGINES_TAB)
    assert screen.window._tabs[module.ENGINES_TAB] is screen
    screen._busy.clear()


def test_inactive_chip_is_visible(screen):
    """Чип «НЕТ» раньше сливался с карточкой: оставался только текст."""
    item = engines.EngineInfo("probe", engines.GROUP_STT, "Проба", "описание",
                              False, False, "нет модели", installable=True)
    column = screen._row(item)
    chip = column.controls[0].controls[1]
    assert chip.border is not None
    assert chip.bgcolor


def test_active_chip_has_no_border(screen):
    item = engines.EngineInfo("probe", engines.GROUP_STT, "Проба", "описание",
                              True, True, "есть", installable=False)
    column = screen._row(item)
    chip = column.controls[0].controls[1]
    assert chip.border is None

def test_queue_routes_engines_events_to_the_screen(screen):
    window = screen.window
    window._running = True
    window._queue.put(("engines_progress", ("vad", 0.4, "качаю")))
    window._queue.put(("engines_done", ("vad", True, "готово")))
    window._queue.put(("stop", None))
    asyncio.run(window._process_queue())
    assert screen.messages["vad"] == ("готово", False)
