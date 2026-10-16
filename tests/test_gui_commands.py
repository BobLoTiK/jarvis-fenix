"""Imported native builder controls; no OS actions or real passwords."""
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
ft = pytest.importorskip("flet")
from jarvis import gui as module, profile, mood
from jarvis.config import Config
from jarvis.gui_commands import CommandBuilder


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


def test_sixth_tab_and_unsaved_editor_survive_navigation(editor):
    gui = editor.gui
    assert len(module.NAV_ITEMS) == 7
    assert gui._rail.selected_index == 5
    editor.new()
    assert editor.fields["name"].on_change is not None
    assert editor.fields["phrases"].on_change is not None
    editor.fields["name"].value = "Личный запуск"
    editor.fields["phrases"].value = "моя фраза"
    button_ids = [id(x) for x in gui._rail.nav_buttons]
    gui._select_tab(0); gui._select_tab(5)
    assert [id(x) for x in gui._rail.nav_buttons] == button_ids
    assert editor.fields["name"].value == "Личный запуск"
    assert editor.fields["phrases"].value == "моя фраза"
    assert gui.config.get("custom_commands") == []


def test_editor_create_check_edit_toggle_and_confirm_delete(editor, monkeypatch):
    execute = Mock()
    monkeypatch.setattr("jarvis.intents.fast.custom.execute_custom", execute)
    editor.new({"name": "Тихо", "phrases": ["тихий вечер"], "steps": [{"action": "set_volume", "percent": 0}]})
    editor.test_field.value = "Феникс, тихий вечер"
    editor.check()
    assert "совпала" in editor.notice
    execute.assert_not_called()
    editor.save()
    entry = editor.gui.config.get("custom_commands")[0]
    assert entry["steps"][0]["percent"] == 0
    editor.edit(entry)
    editor.fields["name"].value = "Тише"
    editor.save()
    entry = editor.gui.config.get("custom_commands")[0]
    assert entry["name"] == "Тише"
    editor.toggle(entry, False)
    assert not editor.gui.config.get("custom_commands")[0]["enabled"]
    editor.delete(entry["id"])
    assert len(editor.gui.config.get("custom_commands")) == 1
    editor.delete(entry["id"], True)
    assert editor.gui.config.get("custom_commands") == []


def test_editor_step_operations_and_validation(editor):
    editor.new()
    editor.add_step()
    editor.change_step(1, "set_volume")
    editor.step_fields[1][1].value = "35"
    editor.move_step(1, -1)
    assert editor.draft["steps"][0] == {"action": "set_volume", "percent": "35"}
    editor.remove_step(1)
    editor.save()
    assert "Название" in editor.notice
    assert not editor.gui.config.get("custom_commands")


def test_password_never_becomes_editor_draft(editor):
    editor.new()
    editor.password_field.value = "Test-42!"
    editor.password_confirm.value = "Test-42!"
    editor.set_password()
    assert editor.gui.config.get("danger_password").startswith("sha256:")
    assert "Test-42!" not in repr(editor.draft)
    assert not editor.password_field.value
    assert not editor.password_confirm.value
    assert "Test-42!" not in editor.notice
    stored = editor.gui.config.get("danger_password")
    editor.password_field.value = editor.password_confirm.value = " bad-password"
    editor.set_password()
    assert editor.gui.config.get("danger_password") == stored


def test_brand_assets_and_app_icon_have_no_letter_fallback(editor):
    from pathlib import Path
    from PIL import Image
    for theme in ("dark", "light"):
        for name in ("phoenix", "dialog", "microphone", "audio", "persona", "settings", "commands"):
            from io import BytesIO
            data = module._brand_bytes(name, theme)
            assert data.startswith(b"\x89PNG")
            with Image.open(BytesIO(data)) as asset:
                assert asset.convert("RGBA").getchannel("A").getextrema()[1] > 0
    path = Path(module.__file__).parent / "icon.ico"
    with Image.open(path) as image:
        assert (16, 16) in image.ico.sizes()
        assert (256, 256) in image.ico.sizes()


def test_theme_rebuild_preserves_unsaved_command_but_not_password(editor, monkeypatch):
    gui = editor.gui
    editor.new({"name": "Черновик", "phrases": ["моя фраза"],
                "steps": [{"action": "set_timer", "seconds": 60}]})
    editor.fields["name"].value = "Мой черновик"
    editor.password_field.value = "Never-store-42"
    for name in ("_build_main_tab", "_build_mic_tab", "_build_audio_tab", "_build_persona_tab", "_build_settings_tab"):
        monkeypatch.setattr(gui, name, lambda: ft.Text("tab"))
    module._apply_palette("light")
    gui._rebuild_ui_for_theme()
    assert gui._rail.selected_index == 5
    assert editor.fields["name"].value == "Мой черновик"
    assert not editor.password_field.value
    assert "Never-store-42" not in repr(editor.draft)
