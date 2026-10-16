"""Imported Flet controls + real GUI worker threads; no window, ASR or audio device.

These are component/integration-boundary tests, not a Windows desktop acceptance.
"""
import queue
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ft = pytest.importorskip("flet")
from jarvis import gui as module, mood, profile  # noqa: E402
from jarvis.config import Config  # noqa: E402
from jarvis.reply import Reply  # noqa: E402


@pytest.fixture
def gui(tmp_path, monkeypatch):
    config = Config(tmp_path / "config.json")
    core = SimpleNamespace(
        handler=SimpleNamespace(_pending_question=None, _pending_password=None,
                                handle=Mock(return_value=Reply(text="Готово."))),
        speaker=SimpleNamespace(stop=Mock(), wait_end=Mock(return_value=True)),
        cmd_lock=threading.Lock(), say=Mock(), listener=None, listening_enabled=True,
    )
    window = module.FenixGUI(core, config)
    monkeypatch.setattr(window, "_get_voice_options", lambda: [ft.dropdown.Option("ruslan")])
    window._build_main_tab()
    yield window
    if window._command_thread is not None:
        window._command_thread.join(timeout=5)
    profile.unsubscribe(window._on_profile_switch)
    mood.unsubscribe(window._on_mood_change)
    module._apply_palette("dark")


def finish(gui):
    gui._command_thread.join(timeout=5)
    assert not gui._command_thread.is_alive()
    assert not gui._command_busy


def events(gui):
    values = []
    while True:
        try:
            values.append(gui._queue.get_nowait())
        except queue.Empty:
            return values


def test_real_controls_have_chat_shortcuts_and_stop(gui):
    assert gui._input_field.multiline and gui._input_field.shift_enter
    assert gui._input_field.max_lines == 4
    assert gui._history_list.controls == [gui._empty_chat]
    assert gui._stop_btn.disabled
    gui._fill_input("Который час?")
    assert gui._input_field.value == "Который час?"
    gui.jarvis.handler.handle.assert_not_called()


def test_duplicate_click_does_not_queue_or_erase_draft(gui):
    entered, release = threading.Event(), threading.Event()
    def handle(cmd):
        entered.set()
        assert release.wait(3)
        return Reply(text="Готово.")
    gui.jarvis.handler.handle = Mock(side_effect=handle)
    gui._input_field.value = "первая"
    gui._on_send(None)
    try:
        assert entered.wait(2)
        assert gui._send_btn.disabled
        gui._input_field.value = "вторая"
        gui._on_send(None)
        assert gui._input_field.value == "вторая"
        assert gui._run_command("третья") is False
        assert gui.jarvis.handler.handle.call_count == 1
    finally:
        release.set()
        finish(gui)
    gui._apply_busy(False)
    assert not gui._send_btn.disabled
    assert gui._command_lock.acquire(blocking=False)
    gui._command_lock.release()


def test_no_core_keeps_input_and_reports_unavailable(gui):
    gui.jarvis = None
    gui._input_field.value = "команда"
    gui._on_send(None)
    assert gui._input_field.value == "команда"
    assert events(gui)[0][0] == "command_error"


def test_exception_is_sanitized_and_worker_unlocks(gui, caplog):
    gui.jarvis.handler.handle.side_effect = RuntimeError("private-password-or-server-payload")
    assert gui._run_command("секретная фраза")
    finish(gui)
    emitted = events(gui)
    assert any(k == "command_error" for k, _ in emitted)
    assert "private-password" not in repr(emitted)
    assert "private-password" not in caplog.text
    assert emitted[-1] == ("busy", False)
    gui._apply_error(next(v for k, v in emitted if k == "command_error"))
    assert gui._error_banner.visible and gui._state == "error"


def test_failed_thread_start_keeps_input_and_unlocks(gui, monkeypatch):
    class BrokenThread:
        def __init__(self, **kwargs): pass
        def start(self): raise RuntimeError("failed")
    monkeypatch.setattr(module.threading, "Thread", BrokenThread)
    gui._input_field.value = "команда"
    gui._on_send(None)
    assert gui._input_field.value == "команда"
    assert not gui._command_busy
    assert gui._command_lock.acquire(blocking=False)
    gui._command_lock.release()
    gui._command_thread = None


def test_existing_voice_lock_serializes_gui_handler(gui):
    gui.jarvis.cmd_lock.acquire()
    try:
        assert gui._run_command("время")
        gui.jarvis.handler.handle.assert_not_called()
    finally:
        gui.jarvis.cmd_lock.release()
    finish(gui)
    gui.jarvis.handler.handle.assert_called_once_with("время")


def test_speech_not_stopped_no_new_action(gui):
    gui.jarvis.speaker.wait_end.return_value = False
    assert gui._run_command("время")
    finish(gui)
    gui.jarvis.handler.handle.assert_not_called()
    gui.jarvis.say.assert_not_called()
    assert any(k == "command_error" for k, _ in events(gui))


def test_stop_is_audio_only_and_does_not_fake_cancellation(gui):
    gui._apply_state("speaking")
    assert not gui._stop_btn.disabled
    gui._on_stop_speech(None)
    gui.jarvis.speaker.stop.assert_called_once()
    assert gui._state == "speaking"  # caller finishes normally; don't unlock a live request
    gui.jarvis.handler.handle.assert_not_called()


def test_pending_state_and_password_mask(gui):
    gui.jarvis.handler._pending_question = {"type": "command_slot", "deadline": time.monotonic()+10}
    gui._apply_state("idle")
    assert gui._state == "awaiting"
    gui.jarvis.handler._pending_password = {"action": "delete_profile"}
    gui._apply_state("idle")
    assert gui._state == "password" and gui._input_field.password
    gui._apply_state("thinking")
    assert gui._input_field.password
    assert not gui._input_field.multiline and gui._input_field.max_lines == 1
    assert not gui._input_field.autocorrect and not gui._input_field.enable_suggestions
    gui.jarvis.handler._pending_password = None
    gui.jarvis.handler._pending_question["deadline"] = 0
    gui._apply_state("idle")
    assert gui._state == "idle" and not gui._input_field.password


def test_theme_rebuild_preserves_draft_stream_and_recolors(gui):
    gui._apply_message("user", "Привет")
    gui._apply_stream_chunk("Здравствуйте")
    gui._input_field.value = "черновик"
    module._apply_palette("light")
    gui._rebuild_ui_for_theme()
    gui._apply_stream_chunk("!")
    assert len(gui._messages) == 2
    assert gui._stream_label.value == "Здравствуйте!"
    assert gui._input_field.value == "черновик"
    assert gui._history_list.controls[0].bgcolor == module.PALETTES["light"]["bg_bubble_user"]
    gui._apply_stream_end()
    assert gui._messages[-1]["text"] == "Здравствуйте!"
    assert gui._stream_bubble is None


def test_password_draft_never_revealed_after_rebuild(gui):
    gui.jarvis.handler._pending_password = {"action": "shutdown"}
    gui._apply_state("idle")
    gui._input_field.value = "not-a-real-password"
    gui.jarvis.handler._pending_password = None
    gui._rebuild_ui_for_theme()
    assert gui._input_field.value == ""
    assert gui._draft == ""


def test_scroll_up_disables_forced_follow(gui):
    gui._on_chat_scroll(SimpleNamespace(max_scroll_extent=1000, pixels=100, event_type=ft.ScrollType.USER, direction=ft.ScrollDirection.FORWARD))
    assert not gui._history_list.auto_scroll and gui._latest_btn.visible
    gui._apply_message("assistant", "Новое сообщение")
    assert not gui._history_list.auto_scroll
    gui._on_chat_scroll(SimpleNamespace(max_scroll_extent=1000, pixels=990, event_type=ft.ScrollType.UPDATE, direction=None))
    assert gui._history_list.auto_scroll and not gui._latest_btn.visible


@pytest.mark.asyncio
async def test_copy_stream_uses_current_text(gui, monkeypatch):
    from unittest.mock import AsyncMock
    clipboard = SimpleNamespace(set=AsyncMock())
    monkeypatch.setattr(module.ft, "Clipboard", lambda: clipboard)
    gui._apply_stream_chunk("Один")
    record = gui._stream_record
    gui._apply_stream_chunk(" два")
    await gui._copy_message(record)
    clipboard.set.assert_awaited_once_with("Один два")


@pytest.mark.asyncio
async def test_scroll_latest_scrolls_before_enabling_follow(gui):
    from unittest.mock import AsyncMock
    gui._history_list.scroll_to = AsyncMock()
    gui._follow_chat = False
    await gui._scroll_latest()
    gui._history_list.scroll_to.assert_awaited_once_with(offset=-1, duration=0)
    assert gui._follow_chat and gui._history_list.auto_scroll


@pytest.mark.parametrize("state", list(module.STATES))
def test_all_states_are_visible(gui, state):
    gui._apply_state(state)
    assert gui._status_text.value
    assert gui._status_sub.value


def test_layout_update_does_not_disable_follow(gui):
    gui._on_chat_scroll(SimpleNamespace(max_scroll_extent=1000, pixels=0,
                                        event_type=ft.ScrollType.UPDATE, direction=None))
    assert gui._follow_chat and gui._history_list.auto_scroll
    assert not gui._latest_btn.visible


def test_scenario_cards_prefill_without_execution(gui):
    for card, text in zip(gui._scenario_cards,
                          ("Поставь таймер", "Открой", "Расскажи что-нибудь")):
        card.on_click(None)
        assert gui._input_field.value == text
    gui.jarvis.handler.handle.assert_not_called()
    gui.jarvis.speaker.stop.assert_not_called()
    gui._apply_state("password")
    gui._input_field.value = ""
    gui._scenario_cards[0].on_click(None)
    assert gui._input_field.value == ""


def test_sidebar_selects_all_real_tabs_and_keeps_theme_selection(gui):
    gui._page = SimpleNamespace(update=Mock())
    gui._rail = module._Sidebar(gui._select_tab)
    gui._tabs = {i: ft.Text(label) for i, (label, _) in enumerate(module.NAV_ITEMS)}
    gui._content_area = ft.Container()
    for index in range(5):
        gui._rail.nav_buttons[index].on_click(None)
        assert gui._rail.selected_index == index
        assert gui._content_area.content is gui._tabs[index]
    module._apply_palette("light")
    gui._rail.refresh_palette()
    assert gui._rail.selected_index == 4
    assert gui._rail.bgcolor == module.P.sidebar
    assert gui._rail.nav_buttons[4].bgcolor == module.P.selected
    gui._select_tab(99)
    assert gui._rail.selected_index == 4


def test_sidebar_profile_and_configured_model_are_not_network_status(gui):
    sidebar = module._Sidebar(lambda i: None)
    assert sidebar.profile_label.value == profile.current()
    gui._on_llm_change(SimpleNamespace(control=SimpleNamespace(value="my-local-model:latest")))
    assert gui._model_label.value == "Модель: my-local-model:latest"
    assert gui._model_caption() == "Модель: my-local-model:latest"
    gui.config.set("mode", "commands")
    assert gui._model_caption() == "Команды · без LLM"


def test_monogram_reflects_processing_not_fake_microphone_data(gui):
    gui._apply_state("thinking")
    assert gui._brand_mark.border.top.color == module.ACCENT
    gui._apply_state("idle")
    assert gui._brand_mark.border.top.color == module.P.brand
