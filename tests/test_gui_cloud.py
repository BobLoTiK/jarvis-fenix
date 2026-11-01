"""Вкладка «Облако»: черновик, сохранение, ключ и проверка — без сети и DPAPI.

secrets_store подменяется словарём: тесты переносимы и не пишут в профиль
Windows. Проверяется поведение экрана, а не DPAPI (он проверен отдельно).
"""

import queue
import time
from types import SimpleNamespace as NS
from unittest.mock import Mock

import flet as ft
import pytest

from jarvis import gui as module, gui_cloud, mood, profile, secrets_store
from jarvis.config import Config


class FakeSecrets:
    CLOUD_LLM_KEY = "cloud_llm_key"

    def __init__(self):
        self.data = {}

    def has_secret(self, name):
        return name in self.data

    def load_secret(self, name):
        return self.data.get(name)

    def save_secret(self, name, value):
        self.data[name] = value
        return True

    def delete_secret(self, name):
        self.data.pop(name, None)
        return True

    def secret_fingerprint(self, name):
        return "deadbeef" if name in self.data else None


@pytest.fixture
def cloud(tmp_path, monkeypatch):
    monkeypatch.setattr(profile, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(profile, "_current", "test")
    monkeypatch.setattr(profile, "_cache", {})
    monkeypatch.setattr(profile, "_listeners", [])
    store = FakeSecrets()
    monkeypatch.setattr(gui_cloud, "_secrets", lambda: store)
    for name in ("has_secret", "load_secret", "save_secret", "delete_secret",
                 "secret_fingerprint"):
        monkeypatch.setattr(secrets_store, name, getattr(store, name), raising=True)
    cfg = Config(tmp_path / "config.json")
    window = module.FenixGUI(None, cfg)
    window._page = NS(add=Mock(), update=Mock(), window=NS())
    monkeypatch.setattr(window, "_get_voice_options",
                        lambda: [ft.dropdown.Option("ruslan")])
    window._build_ui(window._page)
    screen = window._cloud_screen
    screen.store = store
    screen.window = window
    yield screen
    window.stop()
    profile.unsubscribe(window._on_profile_switch)
    mood.unsubscribe(window._on_mood_change)
    module._apply_palette("dark")


def drain(screen, timeout=6.0):
    """Достаёт cloud_probe из очереди и применяет так же, как FenixGUI."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            kind, value = screen.window._queue.get_nowait()
        except queue.Empty:
            time.sleep(0.02)
            continue
        if kind == "cloud_probe":
            screen.on_probe(value)
            return value
    raise AssertionError("событие cloud_probe не пришло")


def test_cloud_tab_is_wired_and_explains_current_mode(cloud):
    window = cloud.window
    assert window._tabs[module.CLOUD_TAB] is cloud
    assert window._rail.selected_index == module.HOME_TAB
    assert "локальная Ollama" in cloud.mode_label.value
    assert module.NAV_ITEMS[module.CLOUD_TAB][0] == "Облако"


def test_fields_cover_every_cloud_key(cloud):
    assert set(cloud.fields) >= set(gui_cloud.CLOUD_KEYS)
    for key in gui_cloud.CLOUD_KEYS:
        assert cloud.fields[key].value is not None


def test_provider_switch_applies_preset_address_and_model(cloud):
    cloud.change("cloud_provider", "deepseek")
    assert cloud.draft["cloud_base_url"] == "https://api.deepseek.com/v1"
    assert cloud.draft["cloud_model"] == "deepseek-chat"
    assert cloud.fields["cloud_base_url"].value == "https://api.deepseek.com/v1"
    assert cloud.fields["cloud_model"].value == "deepseek-chat"


def test_provider_switch_keeps_hand_edited_values(cloud):
    cloud.change("cloud_base_url", "https://my.gateway/v1")
    cloud.change("cloud_model", "my-model")
    cloud.change("cloud_provider", "groq")
    assert cloud.draft["cloud_base_url"] == "https://my.gateway/v1"
    assert cloud.draft["cloud_model"] == "my-model"


def test_custom_provider_without_address_is_rejected(cloud):
    cloud.change("cloud_base_url", "")
    cloud.change("cloud_provider", "custom")
    cloud.save()
    assert cloud.error and "адрес" in cloud.notice.lower()
    assert cloud.window.config.get("cloud_provider") == "openai"


def test_save_persists_cloud_keys_and_reloads(cloud):
    cloud.change("cloud_provider", "deepseek")
    cloud.change("cloud_enabled", True)
    cloud.save()
    assert not cloud.error, cloud.notice
    config = cloud.window.config
    assert config.get("cloud_provider") == "deepseek"
    assert config.get("cloud_base_url") == "https://api.deepseek.com/v1"
    assert config.get("cloud_enabled") is True
    assert "сохранены" in cloud.notice
    assert not cloud.is_busy()


def test_save_without_key_warns_but_keeps_settings(cloud):
    cloud.change("cloud_enabled", True)
    cloud.save()
    assert not cloud.error
    assert "Ключ не сохранён" in cloud.notice
    assert cloud.window.config.get("cloud_enabled") is True


def test_timeout_and_token_limits_are_validated(cloud):
    cloud.change("cloud_max_tokens", "5")
    cloud.save()
    assert cloud.error and "50" in cloud.notice
    cloud.change("cloud_max_tokens", "600")
    cloud.change("cloud_timeout", 1.0)
    cloud.save()
    assert cloud.error and "Таймаут" in cloud.notice


def test_consent_is_recorded_in_profile_with_version_and_time(cloud):
    cloud.change("cloud_send_profile", True)
    cloud.save()
    assert not cloud.error
    consent = profile.get("cloud_consent")
    assert consent["cloud_send_profile"] is True
    assert consent["version"] == gui_preferences_version()
    assert consent["at"]
    assert "разрешена" in cloud.consent_label.value


def gui_preferences_version():
    from jarvis import gui_preferences

    return gui_preferences.CLOUD_CONSENT_VERSION


def test_consent_withdrawal_is_recorded_too(cloud):
    cloud.window.config.set("cloud_send_profile", True)
    cloud.load()
    cloud.change("cloud_send_profile", False)
    cloud.save()
    assert not cloud.error
    assert profile.get("cloud_consent")["cloud_send_profile"] is False
    assert "отозвано" in cloud.consent_label.value


def test_key_is_saved_fingerprinted_and_deleted(cloud):
    cloud.key_field.value = "sk-test-123"
    assert cloud.save_key() is True
    assert cloud.store.data[secrets_store.CLOUD_LLM_KEY] == "sk-test-123"
    assert cloud.key_field.value == ""
    assert "Ключ сохранён" in cloud.notice
    assert cloud.delete_key() is True
    assert secrets_store.CLOUD_LLM_KEY not in cloud.store.data
    assert "удалён" in cloud.notice


def test_probe_without_key_explains_there_is_nothing_to_check(cloud):
    assert cloud.start_probe() is False
    assert "Ключ не сохранён" in cloud.probe_status


def test_probe_success_reports_provider_and_model_count(cloud, monkeypatch):
    cloud.store.data[secrets_store.CLOUD_LLM_KEY] = "sk-test"
    cloud.load()
    monkeypatch.setattr(gui_cloud, "probe_cloud",
                        lambda provider, base_url, model, key: {"provider": provider,
                                                                "models": 5})
    assert cloud.start_probe() is True
    drain(cloud)
    assert "5 шт." in cloud.probe_status
    assert "Ключ принят" in cloud.probe_status
    assert not cloud.is_busy()


def test_probe_auth_error_is_reported_instead_of_success(cloud, monkeypatch):
    cloud.store.data[secrets_store.CLOUD_LLM_KEY] = "sk-test"
    cloud.load()

    def boom(*args, **kwargs):
        raise gui_cloud.cloud_llm.CloudAuthError("401")

    monkeypatch.setattr(gui_cloud, "probe_cloud", boom)
    assert cloud.start_probe() is True
    drain(cloud)
    assert "401/403" in cloud.probe_status


def test_parameter_change_invalidates_previous_probe_result(cloud):
    cloud.change("cloud_model", "another-model")
    assert "Проверьте ключ заново" in cloud.probe_status
