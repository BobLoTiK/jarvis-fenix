"""GUI → config: каждый элемент окна реально отсылает изменение.

Зачем: GUI — тонкий слой над Config. «Кнопка работает» = после её
нажатия в config.json появился нужный ключ (а подписчик Config, см.
tests/test_main_wiring.py, доводит ключ до компонента). Раньше это
проверялось руками, и часть элементов молча ничего не делала
(порог VAD, «хвост» VAD, смена микрофона требовали перезапуска).

Тесты зовут обработчики FenixGUI напрямую с фейковым событием Flet
(e.control.value) — окно не запускается.
"""

import importlib.util
from types import SimpleNamespace

import pytest

if importlib.util.find_spec("flet") is None:
    pytest.skip("flet не установлен — тесты GUI пропущены",
                allow_module_level=True)

import flet as ft  # noqa: E402

from jarvis import gui as gui_mod  # noqa: E402
from jarvis import mood as mood_mod  # noqa: E402
from jarvis import persona as persona_mod  # noqa: E402
from jarvis import profile as profile_mod  # noqa: E402
from jarvis.config import Config  # noqa: E402


def ev(value):
    """Фейковое событие Flet: e.control.value."""
    return SimpleNamespace(control=SimpleNamespace(value=value))


def test_all_tabs_build(gui):
    """Smoke: все пять вкладок собираются без ошибок.

    Раньше вкладка «Аудио» не собиралась вообще (обработчиков «хвоста»
    VAD не существовало), и падало это только в реальном окне.
    """
    for name in ("_build_main_tab", "_build_mic_tab", "_build_audio_tab",
                 "_build_persona_tab", "_build_settings_tab"):
        control = getattr(gui, name)()
        assert control is not None, f"{name} вернул None"


@pytest.fixture()
def cfg(tmp_path):
    """Изолированный config.json — реальные настройки не трогаем."""
    return Config(tmp_path / "config.json")


@pytest.fixture()
def gui(cfg):
    """FenixGUI без Flet-страницы и без Jarvis."""
    window = gui_mod.FenixGUI(None, cfg)
    yield window
    # GUI подписывается на profile/mood — отписываемся, чтобы подписки
    # не копились между тестами.
    profile_mod.unsubscribe(window._on_profile_switch)
    mood_mod.unsubscribe(window._on_mood_change)
    gui_mod._apply_palette("dark")


@pytest.fixture()
def stub_tabs(monkeypatch):
    """Заглушки построителей вкладок.

    _on_tts_change пересобирает вкладки, а это создаёт настоящие
    Flet-контролы и лезет в sounddevice. Для проверки wiring хватает
    заглушек — заодно видно, что пересборка вообще вызывается.
    """
    built = []
    for name in ("_build_main_tab", "_build_mic_tab", "_build_audio_tab",
                 "_build_persona_tab", "_build_settings_tab"):
        monkeypatch.setattr(
            gui_mod.FenixGUI, name,
            lambda self, _name=name: built.append(_name) or ft.Text("stub"),
        )
    return built


# =================================================================
# Главная вкладка
# =================================================================

def test_mode_radio_sends_mode(gui, cfg):
    gui._on_mode_change(ev("llm"))
    assert cfg["mode"] == "llm"


def test_mode_radio_updates_running_handler(gui, cfg):
    handler = SimpleNamespace(mode="combo")
    gui.jarvis = SimpleNamespace(handler=handler)
    gui._on_mode_change(ev("commands"))
    assert handler.mode == "commands"


def test_voice_dropdown_sends_tts_voice(gui, cfg):
    gui._on_voice_change(ev("irina"))
    assert cfg["tts_voice"] == "irina"


def test_memory_radio_long_preset(gui, cfg):
    gui._on_memory_change(ev("long"))
    assert cfg["memory_max"] == 200
    assert cfg["llm_context_messages"] == 40


def test_memory_radio_short_preset(gui, cfg):
    gui._on_memory_change(ev("short"))
    assert cfg["memory_max"] == 40
    assert cfg["llm_context_messages"] == 10


def test_send_button_runs_trimmed_command(gui, monkeypatch):
    """Кнопка «отправить» отдаёт текст в ядро (и чистит поле)."""
    commands = []
    monkeypatch.setattr(gui, "_run_command", lambda cmd: commands.append(cmd))
    gui._input_field = SimpleNamespace(value="  феникс, время  ")

    gui._on_send(None)

    assert commands == ["феникс, время"]
    assert gui._input_field.value == ""


def test_send_button_ignores_empty_input(gui, monkeypatch):
    commands = []
    monkeypatch.setattr(gui, "_run_command", lambda cmd: commands.append(cmd))
    gui._input_field = SimpleNamespace(value="   ")

    gui._on_send(None)

    assert commands == []


# =================================================================
# Вкладка «Аудио» — VAD + Prosody + распознавание
# =================================================================

def test_audio_tab_has_hangover_slider(gui):
    """Ползунок «хвоста» VAD реально есть во вкладке."""
    gui._build_audio_tab()
    assert gui._vad_hangover_slider.max == 3000
    assert "Хвост" in gui._vad_hangover_label.value


def test_prosody_enabled_sends_flag(gui, cfg):
    gui._on_prosody_enabled(ev(False))
    assert cfg["prosody_enabled"] is False


def test_prosody_priority_sends_value(gui, cfg):
    gui._on_prosody_priority(ev("text"))
    assert cfg["prosody_priority"] == "text"


def test_prosody_priority_rejects_unknown(gui, cfg):
    gui._on_prosody_priority(ev("мусор"))
    assert cfg["prosody_priority"] == "prosody"


def test_vad_enabled_checkbox(gui, cfg):
    gui._on_vad_enabled(ev(False))
    assert cfg["vad_enabled"] is False


def test_vad_adaptive_checkbox(gui, cfg):
    gui._on_vad_adaptive(ev(False))
    assert cfg["vad_adaptive"] is False


def test_vad_threshold_slider_end(gui, cfg):
    gui._on_vad_threshold_end(ev(0.23))
    assert cfg["vad_threshold"] == 0.23


def test_vad_hangover_slider_end(gui, cfg):
    gui._on_vad_hangover_end(ev(750.6))
    assert cfg["vad_hangover_ms"] == 751


def test_vad_hangover_slider_zero(gui, cfg):
    gui._on_vad_hangover_end(ev(0))
    assert cfg["vad_hangover_ms"] == 0


def test_barge_checkbox(gui, cfg):
    gui._on_barge_enabled(ev(False))
    assert cfg["barge_enabled"] is False


def test_wake_word_checkbox(gui, cfg):
    gui._on_wake_required(ev(False))
    assert cfg["wake_word_required"] is False


# =================================================================
# Вкладка «Микрофон»
# =================================================================

def test_mic_select_sends_input_device(gui, cfg):
    gui._on_mic_change(ev("USB Headset"))
    assert cfg["input_device"] == "USB Headset"


def test_mic_select_default_is_none(gui, cfg):
    gui._on_mic_change(ev("по умолчанию"))
    assert cfg["input_device"] is None


def test_mic_toggle_pauses_and_resumes(gui):
    gui.jarvis = SimpleNamespace(listening_enabled=True)
    gui._mic_btn = ft.IconButton(icon=ft.Icons.MIC, icon_color=gui_mod.ACCENT)

    gui._on_mic_toggle(None)
    assert gui.jarvis.listening_enabled is False
    assert gui._mic_btn.icon == ft.Icons.MIC_OFF

    gui._on_mic_toggle(None)
    assert gui.jarvis.listening_enabled is True


def test_mic_toggle_without_jarvis_is_noop(gui):
    gui.jarvis = None
    gui._on_mic_toggle(None)  # не должно падать


# =================================================================
# Вкладка «Настройки»
# =================================================================

def test_llm_model_dropdown(gui, cfg):
    gui._on_llm_change(ev("gemma2:9b"))
    assert cfg["llm_model"] == "gemma2:9b"


def test_ollama_url_field(gui, cfg):
    gui._on_ollama_change(ev("http://127.0.0.1:12345"))
    assert cfg["ollama_url"] == "http://127.0.0.1:12345"


def test_tts_backend_sends_and_rebuilds_tabs(gui, cfg, stub_tabs):
    gui._on_tts_change(ev("sapi"))
    assert cfg["tts_backend"] == "sapi"
    assert "_build_main_tab" in stub_tabs, "вкладки не пересобраны"


def test_voice_quality_sends_and_switches_engine(gui, cfg):
    switched = []
    gui.jarvis = SimpleNamespace(speaker=SimpleNamespace(
        switch_backend=lambda backend: switched.append(backend) or True,
    ))

    gui._on_voice_quality_change(ev("high"))

    assert cfg["tts_voice_quality"] == "high"
    assert switched == [cfg["tts_backend"]]


def test_voice_quality_rejects_unknown(gui, cfg):
    gui._on_voice_quality_change(ev("ультра"))
    assert cfg["tts_voice_quality"] == "medium"


def test_rate_slider(gui, cfg):
    gui._on_rate_change(ev(1.34))
    assert cfg["voice_rate"] == 1.34


def test_theme_dropdown(gui, cfg):
    gui._on_theme_change(ev("Светлая"))
    assert cfg["gui_theme"] == "Светлая"


def test_theme_dropdown_rejects_unknown(gui, cfg):
    gui._on_theme_change(ev("радужная"))
    assert cfg["gui_theme"] == "Системная"


# =================================================================
# Вкладка «Персона»
# =================================================================

def test_persona_name_goes_to_config(gui, cfg):
    gui._on_persona_name(ev("Маша"))
    assert cfg["name"] == "Маша"


def test_persona_fields_go_to_persona_module(gui, monkeypatch):
    saved = {}
    monkeypatch.setattr(
        persona_mod, "set_field",
        lambda field, value: saved.__setitem__(field, value),
    )

    gui._on_persona_assistant_name(ev("Джарвис"))
    gui._on_persona_style(ev("кратко"))
    gui._on_persona_traits(ev("добрый, умный"))
    gui._on_persona_backstory(ev("живу в ноутбуке"))

    assert saved["assistant_name"] == "Джарвис"
    assert saved["speech_style"] == "кратко"
    assert saved["traits"] == ["добрый", "умный"]
    assert saved["backstory"] == "живу в ноутбуке"


def test_persona_tone_rejects_unknown(gui, monkeypatch):
    saved = {}
    monkeypatch.setattr(
        persona_mod, "set_field",
        lambda field, value: saved.__setitem__(field, value),
    )

    gui._on_persona_tone(ev("злой"))

    assert saved["tone"] == "auto"


def test_persona_assistant_name_empty_uses_default(gui, monkeypatch):
    saved = {}
    monkeypatch.setattr(
        persona_mod, "set_field",
        lambda field, value: saved.__setitem__(field, value),
    )

    gui._on_persona_assistant_name(ev("   "))

    assert saved["assistant_name"] == "Феникс"
