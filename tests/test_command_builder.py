"""Builder persistence, exact matching and runtime protection; no real OS actions."""
from copy import deepcopy
from collections import deque
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
from jarvis import command_builder as builder
from jarvis.config import Config
from jarvis.intents.fast.custom import load_custom, find_custom, execute_custom, reload_custom
from jarvis.intents.handler import IntentHandler
from jarvis.intents.password import hash_password


def draft(**changes):
    return {"name": "Ночь", "phrases": ["Феникс, спокойной ночи"],
            "steps": [{"action": "shutdown_pc", "seconds": 30}], **changes}


@pytest.fixture
def cfg(tmp_path):
    return Config(tmp_path / "config.json")


def test_crud_and_reopen_preserve_unmanaged_commands(cfg):
    old = {"phrases": ["мой блокнот"], "action": "notepad.exe", "extra": {"keep": 1}}
    cfg.set("custom_commands", [old])
    entry = builder.save_entry(cfg, draft())
    assert entry["phrases"] == ["спокойной ночи"]
    assert Config(cfg.path).get("custom_commands")[0] == old
    entry["steps"] = [{"action": "set_volume", "percent": 0}]
    builder.save_entry(cfg, entry)
    assert len(cfg.get("custom_commands")) == 2
    assert cfg.get("custom_commands")[1]["steps"][0]["percent"] == 0
    builder.delete_entry(cfg, entry["id"])
    assert cfg.get("custom_commands") == [old]


@pytest.mark.parametrize("step", [
    {"action": "run_shell", "target": "whoami"}, {"action": "set_volume", "percent": -1},
    {"action": "set_volume", "percent": 101}, {"action": "set_volume", "percent": True},
    {"action": "set_timer", "seconds": 0}, {"action": "set_timer", "seconds": "nan"},
    {"action": "shutdown_pc", "seconds": 0}, {"action": "reboot_pc", "seconds": 601},
    {"action": "open_site", "target": "file:///C:/windows"},
    {"action": "open_site", "target": "https://login:secret@example.com"},
    {"action": "open_site", "target": "https://example.com bad"},
    {"action": "open_app", "target": "shutdown /s /t 0"},
    {"action": "open_app", "target": "powershell.exe"},
    {"action": "open_app", "target": "notepad & shutdown"},
    {"action": "answer", "reply": ""},
])
def test_bad_parameters_do_not_save(cfg, step):
    before = deepcopy(cfg.get("custom_commands"))
    with pytest.raises(ValueError):
        builder.save_entry(cfg, draft(steps=[step]))
    assert cfg.get("custom_commands") == before


@pytest.mark.parametrize("phrases", [["Феникс"], ["отмена"], ["Ёлка", "елка"], [""], []])
def test_phrase_validation(cfg, phrases):
    with pytest.raises(ValueError):
        builder.save_entry(cfg, draft(phrases=phrases))


def test_limit_and_power_last(cfg):
    with pytest.raises(ValueError):
        builder.save_entry(cfg, draft(steps=[{"action": "screenshot"}] * 7))
    with pytest.raises(ValueError):
        builder.save_entry(cfg, draft(steps=[{"action": "shutdown_pc", "seconds": 30}, {"action": "screenshot"}]))


def test_duplicate_phrase_rejected_but_disabled_command_allowed(cfg):
    builder.save_entry(cfg, draft())
    with pytest.raises(ValueError):
        builder.save_entry(cfg, draft())
    other = builder.save_entry(cfg, draft(enabled=False))
    assert not other["enabled"]
    assert len(load_custom(cfg)) == 1


def test_active_pack_conflict_and_no_pack_duplication(cfg):
    cfg.set("active_packs", ["system"])
    with pytest.raises(ValueError):
        builder.save_entry(cfg, draft(phrases=["выключи компьютер"]))
    h = NS(config=cfg)
    reload_custom(h)
    count = len(h.custom)
    assert count > 0 and h._config_custom_original == []
    for _ in range(3):
        from jarvis.intents.fast.packs import _reload_packs
        _reload_packs(h)
    assert len(h.custom) == count


def test_atomic_save_failure_is_reported(cfg, monkeypatch):
    before = deepcopy(cfg.get("custom_commands"))
    monkeypatch.setattr("jarvis.config_manager.save", lambda *a, **k: False)
    with pytest.raises(OSError):
        builder.save_entry(cfg, draft())
    assert cfg.get("custom_commands") == before


def test_exact_only_and_exact_precedes_legacy_fuzzy(cfg, monkeypatch):
    entry = builder.save_entry(cfg, draft())
    custom = load_custom(cfg)
    assert find_custom(custom, "спокойной ночи") is not None
    assert find_custom(custom, "спокойной ночи!") is None
    assert find_custom(custom, "спокойной ночи дорогой") is None
    fuzzy = (["спокойной ночи друг"], "notepad.exe", "legacy")
    assert find_custom([fuzzy] + custom, "спокойной ночи")[0] == entry["steps"]
    execute = Mock(return_value="checked without execution")
    monkeypatch.setattr("jarvis.intents.fast.custom.execute_custom", execute)
    from jarvis.intents.fast.custom import match_custom
    assert match_custom(NS(config=cfg, custom=custom), "феникс спокойной ночи") == "checked without execution"
    execute.assert_called_once()



def test_config_change_updates_live_handler_without_execution(cfg, monkeypatch):
    h = IntentHandler.__new__(IntentHandler)
    h.config = cfg
    reload_custom(h)
    cfg.subscribe(h._on_config_change)
    entry = builder.save_entry(cfg, draft())
    assert find_custom(h.custom, "спокойной ночи") is not None
    builder.save_entry(cfg, {**entry, "enabled": False})
    assert find_custom(h.custom, "спокойной ночи") is None


def test_missing_password_blocks_whole_scenario_before_first_step(cfg, monkeypatch):
    steps = [{"action": "screenshot"}, {"action": "shutdown_pc", "seconds": 30}]
    h = NS(config=cfg, _ask_password=Mock())
    execute = Mock()
    monkeypatch.setattr("jarvis.intents.execute.execute_steps", execute)
    assert "пароль" in execute_custom(h, steps, "")
    execute.assert_not_called()
    h._ask_password.assert_not_called()


def test_password_required_before_first_step_and_cancel_works(cfg, monkeypatch):
    from jarvis import actions, memory, mood
    from jarvis.intents.stages.password import PasswordStage
    from jarvis.intents.stages.fast import FastHandlersStage
    from jarvis.intents.fast.custom import match_custom
    cfg.set("danger_password", hash_password("A-b42!"))
    builder.save_entry(cfg, draft(steps=[{"action": "set_volume", "percent": 0}, {"action": "shutdown_pc", "seconds": 30}]))
    h = IntentHandler.__new__(IntentHandler)
    h.config = cfg; h.mode = "commands"; h._pending_password = None
    h._pipeline = [PasswordStage(), FastHandlersStage()]
    reload_custom(h); h._fast_handlers_cache = [("custom", lambda cmd: match_custom(h, cmd))]
    h._recent_phrases = deque(maxlen=10); h.dialog = deque(maxlen=100)
    run = Mock(return_value=True); volume = Mock(return_value=True)
    monkeypatch.setattr(actions, "run_power_action", run)
    monkeypatch.setattr(actions, "set_volume", volume)
    monkeypatch.setattr(actions, "get_volume", lambda: 50)
    monkeypatch.setattr(memory, "append", Mock())
    monkeypatch.setattr(mood, "apply_from_text", Mock())
    h.handle("спокойной ночи")
    volume.assert_not_called(); run.assert_not_called()
    assert h._pending_password
    h.handle("отмена")
    run.assert_not_called(); volume.assert_not_called()
    h.handle("спокойной ночи"); h.handle("wrong-code")
    run.assert_not_called(); volume.assert_not_called()
    h.handle("спокойной ночи"); h.handle("A-b42!")
    volume.assert_called_once_with(0)
    run.assert_called_once_with("/s", 30)
    assert not h._pending_password


def test_cancel_power_does_not_depend_on_system_pack(cfg, monkeypatch):
    from jarvis.intents.fast.system import system_fast
    run = Mock(return_value=True)
    monkeypatch.setattr("jarvis.actions.run_power_action", run)
    assert system_fast(NS(config=cfg), "отмени выключение")
    run.assert_called_once_with("/a")


def test_invalid_config_not_overwritten(cfg):
    cfg.set("custom_commands", {"broken": "preserve"})
    with pytest.raises(ValueError):
        builder.save_entry(cfg, draft())
    assert cfg.get("custom_commands") == {"broken": "preserve"}
    assert load_custom(cfg) == []


def test_corrupt_or_future_builder_entries_fail_closed(cfg):
    entry = builder.validate_entry(draft(phrases=["спокойной ночи"]))
    for changed in ({"builder_version": 9}, {"enabled": "false"}, {"phrases": [None]},
                    {"steps": [{"action": "shutdown_pc", "seconds": 0}]}):
        cfg.set("custom_commands", [{**entry, **changed}])
        assert load_custom(cfg) == []


def test_power_uses_fixed_argv_and_checks_windows_exit(monkeypatch):
    from jarvis import actions
    run = Mock(return_value=NS(returncode=0))
    monkeypatch.setattr(actions.subprocess, "run", run)
    assert actions.run_power_action("/s", 30)
    assert run.call_args.args[0] == ["shutdown.exe", "/s", "/t", "30"]
    run.return_value.returncode = 1116  # No shutdown is scheduled.
    assert not actions.run_power_action("/a")
    assert run.call_args.args[0] == ["shutdown.exe", "/a"]
    run.reset_mock()
    assert not actions.run_power_action("/s & whoami", 30)
    assert not actions.run_power_action("/s", -1)
    run.assert_not_called()


def test_power_timeout_is_not_reported_as_success(monkeypatch):
    from jarvis import actions
    import subprocess
    monkeypatch.setattr(actions.subprocess, "run", Mock(side_effect=subprocess.TimeoutExpired("test-only", 5)))
    assert not actions.run_power_action("/r", 30)
