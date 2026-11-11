"""Импорт/экспорт пользовательских команд: данные, превью и атомарное применение."""

import json

import pytest

from jarvis import commands_io


class FakeConfig(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_set = False

    def set(self, key, value):
        if self.fail_set:
            return False
        self[key] = value
        return True


def _entry(name="Начать день", phrase="начни день", command="screenshot",
           target=None, entry_id="a1", enabled=True):
    return {
        "builder_version": 1,
        "id": entry_id,
        "name": name,
        "enabled": enabled,
        "phrases": [phrase],
        "steps": (
            [{"action": command}]
            if target is None
            else [{"action": command, "target": target}]
        ),
        "reply": "",
    }


def _payload(commands):
    return commands_io.dumps({
        "format": commands_io.FORMAT,
        "version": commands_io.VERSION,
        "commands": commands,
    })


def test_export_has_format_version_and_commands():
    config = FakeConfig(custom_commands=[_entry()], wake_words=[])
    payload = commands_io.export_payload(config)
    assert payload["format"] == commands_io.FORMAT
    assert payload["version"] == commands_io.VERSION
    assert payload["commands"][0]["id"] == "a1"
    assert "exported_at" in payload


def test_roundtrip_export_then_import_adds_entries():
    source = FakeConfig(custom_commands=[_entry()], wake_words=[])
    text = commands_io.dumps(commands_io.export_payload(source))
    target = FakeConfig(custom_commands=[], wake_words=[])
    plan = commands_io.plan_import(target, text)
    assert len(plan["add"]) == 1
    counts = commands_io.apply_plan(target, plan)
    assert counts["added"] == 1
    assert target["custom_commands"][0]["phrases"] == ["начни день"]


def test_import_updates_command_with_same_id():
    existing = _entry(phrase="начни день")
    config = FakeConfig(custom_commands=[existing], wake_words=[])
    text = _payload([_entry(phrase="начинай день", entry_id="a1")])
    plan = commands_io.plan_import(config, text)
    assert len(plan["update"]) == 1
    commands_io.apply_plan(config, plan)
    assert config["custom_commands"][0]["phrases"] == ["начинай день"]
    assert len(config["custom_commands"]) == 1


def test_conflict_with_existing_phrase_is_reported_not_applied():
    config = FakeConfig(custom_commands=[_entry()], wake_words=[])
    text = _payload([_entry(name="Другое", phrase="начни день", entry_id="b2")])
    plan = commands_io.plan_import(config, text)
    assert not plan["add"]
    assert len(plan["conflicts"]) == 1
    assert "занята" in plan["conflicts"][0]["reason"]
    assert "конфликтов: 1" in commands_io.describe_plan(plan)


def test_duplicate_id_inside_file_is_conflict():
    config = FakeConfig(custom_commands=[], wake_words=[])
    text = _payload([_entry(entry_id="same"), _entry(name="Второй", phrase="второй", entry_id="same")])
    plan = commands_io.plan_import(config, text)
    assert len(plan["add"]) == 1
    assert len(plan["conflicts"]) == 1
    assert "ID" in plan["conflicts"][0]["reason"]


def test_old_builder_version_is_not_overwritten():
    old = {"id": "old", "name": "Старая", "phrases": ["старая"], "steps": []}
    config = FakeConfig(custom_commands=[old], wake_words=[])
    text = _payload([_entry(entry_id="old", phrase="новая")])
    plan = commands_io.plan_import(config, text)
    assert not plan["update"]
    assert plan["conflicts"]


def test_invalid_entries_are_collected_with_index():
    config = FakeConfig(custom_commands=[], wake_words=[])
    bad = _entry(phrase="")
    text = _payload([bad, _entry(entry_id="ok", phrase="ок команда")])
    plan = commands_io.plan_import(config, text)
    assert plan["errors"][0]["index"] == 0
    assert len(plan["add"]) == 1


@pytest.mark.parametrize(
    "text,needle",
    [
        ("", "пустой"),
        ("не json", "не JSON"),
        (json.dumps({"format": "other", "version": 1, "commands": []}), "format"),
        (json.dumps({"format": "fenix-commands", "version": 99, "commands": []}), "Версия"),
        (json.dumps({"format": "fenix-commands", "version": 1, "commands": {}}), "списком"),
        (json.dumps([1, 2, 3]), "JSON-объект"),
    ],
)
def test_bad_payloads_are_rejected_with_clear_text(text, needle):
    config = FakeConfig(custom_commands=[], wake_words=[])
    with pytest.raises(ValueError) as error:
        commands_io.plan_import(config, text)
    assert needle in str(error.value)


def test_oversized_file_is_rejected():
    config = FakeConfig(custom_commands=[], wake_words=[])
    huge = "{" + " " * (commands_io.MAX_BYTES + 10) + "}"
    with pytest.raises(ValueError) as error:
        commands_io.plan_import(config, huge)
    assert "слишком большой" in str(error.value).lower()


def test_too_many_entries_are_rejected():
    config = FakeConfig(custom_commands=[], wake_words=[])
    commands = [_entry(entry_id=f"id{i}", phrase=f"фраза {i}") for i in range(commands_io.MAX_ENTRIES + 1)]
    with pytest.raises(ValueError) as error:
        commands_io.plan_import(config, _payload(commands))
    assert "Слишком много" in str(error.value)


def test_apply_is_atomic_when_config_rejects():
    config = FakeConfig(custom_commands=[], wake_words=[])
    text = _payload([_entry()])
    plan = commands_io.plan_import(config, text)
    config.fail_set = True
    with pytest.raises(OSError):
        commands_io.apply_plan(config, plan)
    assert config["custom_commands"] == []


def test_imported_data_is_not_executed():
    config = FakeConfig(custom_commands=[], wake_words=[])
    payload = _payload([_entry(command="open_app", target="calc")])
    plan = commands_io.plan_import(config, payload)
    commands_io.apply_plan(config, plan)
    steps = config["custom_commands"][0]["steps"]
    assert steps == [{"action": "open_app", "target": "calc"}]
    assert all(isinstance(value, str) for step in steps for value in step.values())
