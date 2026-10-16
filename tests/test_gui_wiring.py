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


def test_voice_quality_updates_config(gui, cfg):
    # Движок пересоздаёт make_config_listener по ключу tts_voice_quality:
    # ручной switch_backend(текущий) был no-op (ранний return по backend).
    gui.jarvis = SimpleNamespace(speaker=SimpleNamespace())

    gui._on_voice_quality_change(ev("high"))

    assert cfg["tts_voice_quality"] == "high"


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


def test_observer_enabled_checkbox(gui, cfg):
    """Observer — согласие: галочка пишет флаг в config."""
    gui._on_observer_enabled(ev(True))
    assert cfg["observer_enabled"] is True
    gui._on_observer_enabled(ev(False))
    assert cfg["observer_enabled"] is False


def test_memory_rag_checkbox(gui, cfg):
    """Векторная память: галочка пишет флаг, Observer при этом не включается."""
    gui._on_memory_rag_enabled(ev(True))
    assert cfg["memory_rag_enabled"] is True
    assert cfg["observer_enabled"] is False

    gui._on_memory_rag_enabled(ev(False))
    assert cfg["memory_rag_enabled"] is False


# =================================================================
# Вкладка «Персона»
# =================================================================

def test_persona_name_is_staged_not_written_to_global_config(gui, cfg):
    gui._build_persona_tab()
    before = cfg.get("name")
    editor = gui._preferences()
    editor.persona_fields["name"].on_change(ev("Маша"))
    assert editor.persona_draft["name"] == "Маша"
    assert cfg.get("name") == before


def test_persona_fields_are_real_draft_controls(gui):
    gui._build_persona_tab()
    editor = gui._preferences()
    editor.persona_fields["assistant_name"].on_change(ev("Искра"))
    editor.persona_fields["backstory"].on_change(ev("Контекст"))
    assert editor.persona_draft["assistant_name"] == "Искра"
    assert editor.persona_draft["backstory"] == "Контекст"


def test_persona_unknown_tone_is_rejected_without_writing(gui):
    gui._build_persona_tab()
    editor = gui._preferences()
    editor.persona_draft["tone"] = "bogus"
    editor.save_persona()
    assert editor.persona_error


def test_persona_empty_assistant_name_is_validation_error(gui):
    gui._build_persona_tab()
    editor = gui._preferences()
    editor.persona_fields["assistant_name"].on_change(ev("   "))
    editor.save_persona()
    assert editor.persona_error


# =================================================================
# Вкладка «Аудио» — авто-скачивание модели VAD
# =================================================================

def _find_checkbox(control, needle):
    """Ищет ft.Checkbox с needle в label по дереву контролов."""
    stack = [control]
    while stack:
        ctrl = stack.pop()
        if isinstance(ctrl, ft.Checkbox):
            label = getattr(ctrl, "label", "") or ""
            if needle in label:
                return ctrl
        content = getattr(ctrl, "content", None)
        if content is not None:
            stack.append(content)
        for child in getattr(ctrl, "controls", None) or []:
            stack.append(child)
    return None


def test_audio_tab_has_vad_auto_download_checkbox(gui):
    """Чекбокс «качать модель VAD» реально есть во вкладке.

    Модель silero_vad.onnx в репозиторий не входит — без этого
    чекбокса на машине без сети VAD выключался бы молча.
    """
    tab = gui._build_audio_tab()
    box = _find_checkbox(tab, "Скачивать модель VAD")

    assert box is not None, "во вкладке нет чекбокса авто-скачивания модели"
    assert box.value is True


def test_vad_auto_download_sends_flag(gui, cfg):
    """Чекбокс пишет ключ в config — дальше его ведёт подписчик Config."""
    gui._on_vad_auto_download(ev(False))
    assert cfg["vad_auto_download"] is False

    gui._on_vad_auto_download(ev(True))
    assert cfg["vad_auto_download"] is True


# =================================================================
# Окно: позиция + «закрыть в трей»
# =================================================================

class FakeWindow:
    """Заглушка page.window: помним то, что Flet реально меняет."""

    def __init__(self, left=10, top=20):
        self.left = left
        self.top = top
        self.visible = True
        self.minimized = False
        self.prevent_close = False
        self.closed = False
        self.on_event = None

    def close(self):
        self.closed = True


class FakePage:
    """Заглушка ft.Page для событий окна."""

    def __init__(self, left=10, top=20):
        self.window = FakeWindow(left, top)
        self.updates = 0

    def update(self):
        self.updates += 1


def win_event(kind, page=None):
    """Фейковое событие окна Flet."""
    return SimpleNamespace(type=kind, page=page)


def test_window_moved_saves_position(gui, cfg):
    """Позиция окна сохраняется (gui_x/gui_y), как было и раньше."""
    gui._page = FakePage(left=100, top=200)

    gui._on_window_event(win_event(ft.WindowEventType.MOVED))

    assert cfg["gui_x"] == 100
    assert cfg["gui_y"] == 200


def test_window_close_hides_to_tray(gui):
    """Крестик при живом трее прячет окно, а не убивает Феникса."""
    page = FakePage()
    gui._page = page
    gui.tray_active = True

    gui._on_window_event(win_event(ft.WindowEventType.CLOSE, page))

    assert page.window.prevent_close is True
    assert page.window.visible is False
    assert page.updates == 1


def test_window_close_without_tray_exits(gui):
    """Без трея крестик закрывает окно штатно (Flet завершит сессию)."""
    page = FakePage()
    gui._page = page
    gui.tray_active = False

    gui._on_window_event(win_event(ft.WindowEventType.CLOSE, page))

    assert page.window.prevent_close is False
    assert page.window.visible is True


def test_quit_closes_window(gui):
    """«Выход» из трея закрывает окно — иначе процесс остаётся жить."""
    page = FakePage()
    gui._page = page
    page.window.prevent_close = True

    gui.quit()

    assert page.window.prevent_close is False
    assert page.window.closed is True


def test_quit_without_page_is_safe(gui):
    """GUI ещё не поднялся — quit() не падает."""
    gui._page = None

    gui.quit()


def test_set_tray_active_toggles_prevent_close(gui):
    """Трей включили на лету — окно больше не закрывается крестиком."""
    page = FakePage()
    gui._page = page

    gui.set_tray_active(True)
    assert gui.tray_active is True
    assert gui._queue.get_nowait() == ("tray_active", True)
    assert page.window.prevent_close is False  # worker applies it, not caller thread

    gui.set_tray_active(False)
    assert gui.tray_active is False
    assert gui._queue.get_nowait() == ("tray_active", False)
    assert page.window.prevent_close is False


def test_set_tray_active_without_page_is_safe(gui):
    """Страница Flet ещё не создана — флаг всё равно выставляется."""
    gui._page = None

    gui.set_tray_active(True)

    assert gui.tray_active is True


def test_show_window_makes_window_visible(gui):
    """Пункт трея «Открыть окно» реально возвращает окно на экран."""
    page = FakePage()
    gui._page = page
    page.window.visible = False
    page.window.minimized = True

    gui._show_window_now()

    assert page.window.visible is True
    assert page.window.minimized is False
    assert page.updates == 1


# =================================================================
# Вкладка «Настройки» — трей и режим запуска
# =================================================================

def test_settings_tab_has_tray_controls(gui):
    """Native switch stages a value; only Apply persists it."""
    gui._build_settings_tab()
    editor = gui._preferences()
    control = editor.settings_fields["tray_enabled"]
    assert isinstance(control, ft.Switch)
    assert control.value is True
    control.on_change(ev(False))
    assert gui.config.get("tray_enabled") is True
    assert editor.settings_draft["tray_enabled"] is False
    editor.save_settings()
    assert gui.config.get("tray_enabled") is False


def test_tray_enabled_sends_flag(gui, cfg):
    gui._on_tray_enabled(ev(False))
    assert cfg["tray_enabled"] is False

    gui._on_tray_enabled(ev(True))
    assert cfg["tray_enabled"] is True


def test_launch_mode_sends_value(gui, cfg):
    gui._on_launch_mode(ev("tray"))
    assert cfg["launch_mode"] == "tray"


def test_launch_mode_rejects_unknown(gui, cfg):
    gui._on_launch_mode(ev("неведома зверушка"))
    assert cfg["launch_mode"] == "gui"
