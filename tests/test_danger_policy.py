"""Политика опасных действий: пароль решает «можно ли», а не «опасно ли».

До аудита `is_danger()` при пустом `danger_password` сразу возвращал False:
«пароля нет — значит ничего не опасно». В результате «удали профиль X»,
`shutdown /r /t 10` из пак-команды и kill-процесса исполнялись без
подтверждения, хотя типизированный `_do_power` пароль требует.

Теперь классификация (`is_danger`) не зависит от пароля, а решение
принимает единственная точка `danger_gate`:
    * пароль задан            → спросить пароль;
    * пароля нет + необратимо → безопасный отказ (NO_PASSWORD_REPLY);
    * пароля нет + отменяемо  → исполнять как раньше (clear_tasks).
"""

import pytest

from jarvis.intents.password import (
    NO_PASSWORD_REPLY,
    danger_gate,
    is_danger,
    is_irreversible,
)


class FakeHandler:
    """Минимальный IntentHandler для гейта: только config и _ask_password."""

    def __init__(self, password: str = ""):
        self.config = {"danger_password": password}
        self.asked: list[dict] = []

    def _ask_password(self, intent: dict) -> str:
        self.asked.append(intent)
        return "ASK_PASSWORD"


@pytest.mark.parametrize("intent", [
    {"action": "delete_profile", "target": "максим"},
    {"action": "shutdown_pc", "seconds": 10},
    {"action": "reboot_pc"},
    {"action": "kill_process", "target": "notepad.exe"},
    {"action": "open_app", "target": "shutdown /r /t 10"},
    {"steps": [{"action": "screenshot"}, {"action": "delete_profile"}]},
])
def test_danger_classification_ignores_password(intent):
    """Раньше при пустом пароле is_danger возвращал False — это и был дефект."""
    assert is_danger(intent) is True
    assert is_danger(intent, "") is True
    assert is_danger(intent, "sha256:deadbeef") is True


def test_safe_action_is_not_danger():
    assert is_danger({"action": "open_app", "target": "notepad"}) is False
    assert danger_gate(FakeHandler(), {"action": "open_app",
                                       "target": "notepad"}) is None


@pytest.mark.parametrize("intent", [
    {"action": "delete_profile", "target": "максим"},
    {"action": "shutdown_pc", "seconds": 10},
    {"action": "open_app", "target": "shutdown /s /t 10"},
    {"steps": [{"action": "reboot_pc"}]},
])
def test_irreversible_without_password_is_refused_not_executed(intent):
    handler = FakeHandler()  # danger_password пуст

    assert danger_gate(handler, intent) == NO_PASSWORD_REPLY
    assert handler.asked == [], "нельзя спрашивать пароль, которого нет"


@pytest.mark.parametrize("intent", [
    {"action": "delete_profile", "target": "максим"},
    {"action": "clear_tasks"},
])
def test_password_set_asks_for_it(intent):
    handler = FakeHandler("sha256:abc")

    assert danger_gate(handler, intent) == "ASK_PASSWORD"
    assert handler.asked == [intent]


def test_reversible_actions_stay_passwordless():
    """Уборка задач без настроенного пароля должна работать как раньше."""
    handler = FakeHandler()

    assert danger_gate(handler, {"action": "clear_tasks"}) is None
    assert danger_gate(handler, {"action": "cancel_timers"}) is None
    assert handler.asked == []


def test_custom_command_keeps_its_own_pending_intent():
    """После пароля кастомная команда должна исполниться целиком, а не по шагам."""
    handler = FakeHandler("sha256:abc")
    steps = [{"action": "shutdown_pc", "seconds": 30}]
    pending = {"action": "custom_command", "spec": steps, "reply": "Готово."}

    gate = danger_gate(handler, {"steps": steps}, pending=pending)

    assert gate == "ASK_PASSWORD"
    assert handler.asked == [pending]


def test_is_irreversible_separates_power_from_cleanup():
    assert is_irreversible({"action": "delete_profile"}) is True
    assert is_irreversible({"action": "clear_tasks"}) is False


def test_delete_profile_stage_refuses_without_password(monkeypatch):
    """Голосовой путь: «удали профиль максим» без пароля не удаляет ничего."""
    from jarvis.intents.stages.password import PasswordStage
    from jarvis import profile

    called = []
    monkeypatch.setattr(profile, "delete", lambda name: called.append(name) or True)

    class Ctx:
        cmd = "удали профиль максим"
        handler = FakeHandler()

    stage = PasswordStage()
    reply = stage._maybe_delete_profile(Ctx())

    assert reply == NO_PASSWORD_REPLY
    assert called == [], "профиль удалён без пароля"
