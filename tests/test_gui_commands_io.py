"""Импорт/экспорт команд через GUI-редактор: превью, применение, отмена."""

import json
from types import SimpleNamespace

import pytest

ft = pytest.importorskip("flet")

from jarvis import commands_io, gui as module, mood, profile  # noqa: E402
from jarvis.config import Config  # noqa: E402
from jarvis.gui_commands import CommandBuilder  # noqa: E402


@pytest.fixture
def editor(tmp_path):
    cfg = Config(tmp_path / "config.json")
    gui = module.FenixGUI(None, cfg)
    gui._rail = module._Sidebar(gui._select_tab)
    gui._content_area = ft.Container()
    gui._tabs = {i: ft.Text(str(i)) for i in range(5)}
    gui._command_builder = CommandBuilder(gui)
    gui._tabs[5] = gui._build_commands_tab()
    gui._select_tab(5)
    yield gui._command_builder
    profile.unsubscribe(gui._on_profile_switch)
    mood.unsubscribe(gui._on_mood_change)
    module._apply_palette("dark")


def _payload(commands):
    return commands_io.dumps({
        "format": commands_io.FORMAT,
        "version": commands_io.VERSION,
        "commands": commands,
    })


def _entry(name="Проверка", phrase="проверка импорта", entry_id="io1"):
    return {
        "builder_version": 1,
        "id": entry_id,
        "name": name,
        "enabled": True,
        "phrases": [phrase],
        "steps": [{"action": "screenshot"}],
    }


def test_export_text_contains_saved_commands(editor):
    editor.gui.config.set("custom_commands", [_entry()])
    data = json.loads(editor.export_text())
    assert data["format"] == commands_io.FORMAT
    assert data["commands"][0]["id"] == "io1"


def test_prepare_import_does_not_touch_config(editor):
    plan = editor.prepare_import(_payload([_entry()]))
    assert plan["add"]
    assert editor._import_plan is not None
    assert editor.gui.config.get("custom_commands") == []
    assert "Импорт:" in editor.notice


def test_apply_import_writes_once_and_clears_plan(editor):
    editor.prepare_import(_payload([_entry()]))
    editor.apply_import()
    assert editor.gui.config.get("custom_commands")[0]["id"] == "io1"
    assert editor._import_plan is None
    assert "добавлено 1" in editor.notice


def test_cancel_import_keeps_config(editor):
    editor.prepare_import(_payload([_entry()]))
    editor.cancel_import()
    assert editor.gui.config.get("custom_commands") == []
    assert editor._import_plan is None
    assert "отменён" in editor.notice


def test_bad_file_is_explained_and_not_planned(editor):
    plan = editor.prepare_import("не json")
    assert plan is None
    assert editor._import_plan is None
    assert "Импорт не выполнен" in editor.notice
    assert "JSON" in editor.notice


def _walk(control):
    """Все вложенные контролы: content и controls, без Flet-специфики."""
    if control is None:
        return
    yield control
    yield from _walk(getattr(control, "content", None))
    for child in getattr(control, "controls", None) or []:
        yield from _walk(child)


def test_conflicts_block_apply_button(editor):
    editor.gui.config.set("custom_commands", [_entry()])
    editor.prepare_import(_payload([_entry(name="Дубль", entry_id="io2")]))
    preview = editor._import_preview()
    apply_buttons = [
        control for control in _walk(preview)
        if isinstance(control, ft.Button)
        and str(getattr(control, "content", "")) == "Применить импорт"
    ]
    assert apply_buttons and apply_buttons[0].disabled


def test_dialog_unavailable_is_honest(editor):
    editor.gui._page = None
    editor.start_import()
    assert "только в открытом окне" in editor.notice
