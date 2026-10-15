"""Slot filling uses real handler/pipeline, no devices, models or private data."""

from collections import deque
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
import time

import pytest

from jarvis import first_run, learning, memory, mood, timers
from jarvis.intents.handler import IntentHandler
from jarvis.intents.stages import build_pipeline
from jarvis.intents.fast.timers import timers_fast
from jarvis.intents.clarification import pending_alive
from jarvis.intents.password import hash_password


@pytest.fixture
def h(monkeypatch):
    monkeypatch.setattr(first_run, "is_first_run", lambda: False)
    monkeypatch.setattr(memory, "append", Mock())
    monkeypatch.setattr(memory, "handle_memory_command", lambda *a: (None, False))
    monkeypatch.setattr(mood, "apply_from_text", Mock())
    monkeypatch.setattr(learning, "find_correction", Mock(return_value=None))
    monkeypatch.setattr(learning, "add_correction", Mock())
    monkeypatch.setattr(timers, "add", Mock(return_value={}))
    a = IntentHandler.__new__(IntentHandler)
    a.config = {}
    a.apps = [
        NS(key="notepad", title="Блокнот", aliases=["блокнот", "notepad"]),
        NS(key="steam", title="Стим", aliases=["стим", "steam"]),
    ]
    a.brain = NS(available=True, parse=Mock(return_value={"action": "none"}))
    a.mode = "combo"
    a.dialog = deque(maxlen=100)
    a._recent_phrases = deque(maxlen=10)
    a._pending_password = a._pending_question = None
    a._installed = {"OBS Studio": Path("test-only.lnk")}
    a._steam_games = [("Test Game", "123")]
    a._reset_requested = False
    a._last_cmd = a._raw_cmd = a._last_reply = ""
    a._llm_context = 20
    a.opened = Mock(return_value="Открываю приложение.")
    a._fast_handlers_cache = [
        ("open", lambda cmd: a.opened(cmd) if cmd.startswith("открой ") else None),
        ("timers", lambda cmd: timers_fast(a, cmd)),
        ("time", lambda cmd: "Сейчас полдень." if cmd == "который час" else None),
    ]
    a._pipeline = build_pipeline(a)
    return a


@pytest.mark.parametrize("start", ["открой", "запусти", "включи", "открывай", "врубай"])
def test_missing_target_then_answer(h, start):
    assert "приложение" in h.handle(start).text
    h.opened.assert_not_called()
    assert not h.handle("Блокнот").allow_nonverbal
    h.opened.assert_called_once_with("открой блокнот")
    assert h._pending_question is None
    h.brain.parse.assert_not_called()
    learning.add_correction.assert_not_called()


@pytest.mark.parametrize("target", ["стим", "steam", "OBS Studio", "Test Game"])
def test_exact_known_targets(h, target):
    h.handle("открой")
    h.handle(target)
    h.opened.assert_called_once()


@pytest.mark.parametrize(
    "answer", ["это", "какая то штука", "не блокнот", "блокнот или стим", "блок"]
)
def test_ambiguous_target_does_not_execute_or_guess_site(h, answer):
    h.handle("открой")
    h.handle(answer)
    h.opened.assert_not_called()
    h.brain.parse.assert_not_called()
    assert h._pending_question is not None


def test_target_self_correction_before_execution(h):
    h.handle("открой")
    h.handle("блокнот, нет, стим")
    h.opened.assert_called_once_with("открой стим")


@pytest.mark.parametrize(
    "start", ["таймер", "поставь таймер", "установи таймер", "напомни"]
)
def test_missing_timer_then_duration(h, start):
    h.handle(start)
    timers.add.assert_not_called()
    before = time.time()
    h.handle("на пятнадцать минут")
    timers.add.assert_called_once()
    assert abs(timers.add.call_args.args[1] - before - 900) < 2
    assert h._pending_question is None
    h.brain.parse.assert_not_called()


def test_preserve_reminder_body(h):
    h.handle("напомни выпить чай")
    h.handle("через пять минут")
    assert timers.add.call_args.args[0] == "выпить чай"


@pytest.mark.parametrize(
    "answer", ["на десять... нет, на пятнадцать минут", "точнее на пятнадцать минут"]
)
def test_replace_time_before_execution(h, answer):
    h.handle("таймер")
    h.handle(answer)
    timers.add.assert_called_once()
    assert abs(timers.add.call_args.args[1] - time.time() - 900) < 2


def test_unit_is_required_and_previous_number_retained(h):
    h.handle("таймер")
    assert "единицах" in h.handle("на десять").text
    timers.add.assert_not_called()
    h.handle("минут")
    timers.add.assert_called_once()
    assert abs(timers.add.call_args.args[1] - time.time() - 600) < 2


def test_initial_bare_number_does_not_default_to_minutes(h):
    assert "единицах" in h.handle("поставь таймер на десять").text
    timers.add.assert_not_called()
    h.handle("секунд")
    assert abs(timers.add.call_args.args[1] - time.time() - 10) < 2


@pytest.mark.parametrize(
    "answer",
    [
        "не на пять минут",
        "пять или десять минут",
        "на ноль минут",
        "через -5 минут",
        "в 25:90",
        "завтра утром",
        "на пять минут выключи компьютер",
    ],
)
def test_unclear_time_never_executes(h, answer):
    h.handle("таймер")
    h.handle(answer)
    timers.add.assert_not_called()
    h.brain.parse.assert_not_called()


@pytest.mark.parametrize("answer", ["в 18:30", "18:30", "в восемнадцать тридцать"])
def test_absolute_time_uses_existing_timer_dispatch(h, answer):
    h.handle("напомни выпить чай")
    h.handle(answer)
    timers.add.assert_called_once()
    assert timers.add.call_args.args[0] == "выпить чай"


@pytest.mark.parametrize(
    "cancel", ["отмена", "отмени", "стоп", "не надо", "не нужно", "нет"]
)
def test_cancel_discards_state(h, cancel):
    h.handle("таймер")
    h.handle(cancel)
    assert h._pending_question is None
    timers.add.assert_not_called()


def test_monotonic_deadline_not_wall_clock(h, monkeypatch):
    h.handle("таймер")
    state = h._pending_question
    monkeypatch.setattr(time, "time", lambda: state["expires_at"] + 9999)
    assert pending_alive(state)
    monkeypatch.setattr(time, "monotonic", lambda: state["deadline"] + 1)
    assert not pending_alive(state)
    assert "истекло" in h.handle("на пять минут").text
    timers.add.assert_not_called()
    h.brain.parse.assert_not_called()


def test_invalid_answer_does_not_extend_deadline_and_attempts_bounded(h):
    h.handle("таймер")
    deadline = h._pending_question["deadline"]
    for _ in range(2):
        h.handle("эээ")
        assert h._pending_question["deadline"] == deadline
    assert "отменено" in h.handle("эээ").text
    assert h._pending_question is None
    h.brain.parse.assert_not_called()


def test_new_command_replaces_pending(h):
    h.handle("таймер")
    h.handle("открой блокнот")
    h.opened.assert_called_once_with("открой блокнот")
    timers.add.assert_not_called()
    assert h._pending_question is None


def test_new_incomplete_command_replaces_slot(h):
    h.handle("открой")
    h.handle("таймер")
    assert h._pending_question["slot"] == "time"
    h.handle("на пять минут")
    timers.add.assert_called_once()
    h.opened.assert_not_called()


def test_password_prompt_clears_old_slot_and_password_is_not_history(h, monkeypatch):
    h.config["danger_password"] = hash_password("AbC-42!")
    h.handle("открой")
    h.handle("отмени все таймеры")
    assert h._pending_question is None
    assert h._pending_password
    monkeypatch.setattr(
        "jarvis.intents.execute.execute_intent", Mock(return_value="Готово.")
    )
    h.handle("пароль AbC-42!")
    assert all("AbC-42!" not in m["content"] for m in h.dialog)


def test_slot_answer_not_rewritten_by_learned_fuzzy_correction(h):
    h.handle("открой")
    learning.find_correction.reset_mock()
    h.handle("блокнот")
    learning.find_correction.assert_not_called()


def test_timings_have_no_text_and_no_stream_claim(h):
    h.handle("открой")
    timings = h._last_timings
    assert timings["handler_ms"] >= 0
    assert timings["stages_ms"]["clarification"] >= 0
    assert "открой" not in str(timings)


def test_profile_change_clears_transient_state(h, monkeypatch):
    h.handle("таймер")
    h._memory_max = 100
    monkeypatch.setattr(memory, "load", lambda **kw: [])
    raw = h._raw_cmd
    h._on_profile_switch("old", "new")
    assert h._raw_cmd == raw  # Don't blank the in-flight history message.
    assert h._pending_question is None
    assert h._pending_password is None


def test_new_independent_command_does_not_become_app_name(h):
    h.handle("открой")
    assert "полдень" in h.handle("который час").text
    assert h._pending_question is None
    h.opened.assert_not_called()


def test_compound_stops_at_missing_slot(h):
    h.handle("открой и запусти стим")
    assert h._pending_question["slot"] == "target"
    h.opened.assert_not_called()
    h.handle("блокнот")
    h.opened.assert_called_once_with("открой блокнот")


def test_same_utterance_correction_keeps_reminder_payload(h):
    h.handle("напомни через пять минут выпить чай, нет, через десять минут")
    timers.add.assert_called_once()
    assert timers.add.call_args.args[0] == "выпить чай"
    assert abs(timers.add.call_args.args[1] - time.time() - 600) < 2


def test_new_command_still_runs_after_expiry(h):
    h.handle("таймер")
    h._pending_question["deadline"] = 0
    h.handle("открой блокнот")
    h.opened.assert_called_once_with("открой блокнот")
    timers.add.assert_not_called()


def test_exact_custom_retains_priority_over_missing_slot(h, monkeypatch):
    from jarvis.intents.fast.custom import match_custom

    h.custom = [(["таймер"], [{"action": "screenshot"}], "Готово.")]
    execute = Mock(return_value="Custom выполнена.")
    monkeypatch.setattr("jarvis.intents.fast.custom.execute_custom", execute)
    h._fast_handlers_cache.insert(0, ("custom", lambda cmd: match_custom(h, cmd)))
    assert "Custom" in h.handle("таймер").text
    assert h._pending_question is None
    execute.assert_called_once()


def test_low_confidence_slot_answer_is_not_consumed_or_observed(h):
    from tests.test_recognition_quality import app, method, BAD, PCM

    h.handle("таймер")
    state = h._pending_question.copy()
    a = app(primary=BAD, whisper=False)
    a.handler = h
    method("jarvis/main.py", "Jarvis", "_process")(a, "на пять минут", PCM)
    assert h._pending_question == state
    timers.add.assert_not_called()
    a.observer.observe.assert_not_called()


def test_confident_slot_answer_not_forwarded_to_observer(h):
    from tests.test_recognition_quality import app, method, PCM

    h.handle("таймер")
    a = app(whisper=False)
    a.handler = h
    method("jarvis/main.py", "Jarvis", "_process")(a, "на пять минут", PCM)
    timers.add.assert_called_once()
    assert not any(c.args[0] == "user" for c in a.observer.observe.call_args_list)


def test_weather_pending_still_uses_same_stage(h, monkeypatch):
    from jarvis import profile, weather

    h._pending_question = {
        "type": "city_for_weather",
        "day": "today",
        "expires_at": time.time() + 20,
    }
    monkeypatch.setattr(profile, "set", Mock(return_value=True))
    monkeypatch.setattr(weather, "get_weather", Mock(return_value={"test": True}))
    monkeypatch.setattr(weather, "describe_weather", lambda w: "Погода.")
    assert "Погода" in h.handle("Москва").text
    weather.get_weather.assert_called_once_with("москва", day="today")


def test_previous_command_timing_is_available_without_user_text(h):
    from jarvis.intents.fast.debug import debug_fast

    h._fast_handlers_cache.append(("debug", lambda cmd: debug_fast(h, cmd)))
    h.handle("таймер")
    reply = h.handle("покажи время обработки").text
    assert "мс" in reply
    assert "Без распознавания" in reply
    assert "таймер" not in reply


def test_initial_alternative_times_request_single_value(h):
    assert "одно время" in h.handle("таймер на пять минут или десять минут").text
    timers.add.assert_not_called()
    h.handle("на десять минут")
    timers.add.assert_called_once()


def test_volume_command_replaces_pending_without_becoming_duration(h):
    h._fast_handlers_cache.append(
        ("volume", lambda cmd: "Громкость 50." if cmd == "громкость 50" else None)
    )
    h.handle("таймер")
    assert "Громкость" in h.handle("громкость 50").text
    assert h._pending_question is None
    timers.add.assert_not_called()


def test_answer_does_not_reanalyze_unrelated_original_command(h, monkeypatch):
    import jarvis.intents.clarification as slots

    h._raw_cmd = "случайная фраза"
    h._number_analysis = NS(command="случайная фраза")
    from jarvis.intents.context import Ctx

    # A non-timer stage must not perform a second full numeric parse.
    monkeypatch.setattr(
        slots, "analyze_command", Mock(side_effect=AssertionError("duplicate parse"))
    )
    assert slots.begin(Ctx(cmd="случайная фраза", handler=h)) is None


def test_otmeni_without_pending_still_reaches_existing_undo(h):
    undo = Mock(return_value="Нечего отменять.")
    h._fast_handlers_cache.append(
        ("undo", lambda cmd: undo() if cmd == "отмени" else None)
    )
    assert "Нечего" in h.handle("отмени").text
    undo.assert_called_once()


def test_otmeni_pending_does_not_undo_previous_action(h):
    undo = Mock(return_value="Откатываю.")
    h._fast_handlers_cache.append(
        ("undo", lambda cmd: undo() if cmd == "отмени" else None)
    )
    h.handle("таймер")
    assert "отменено" in h.handle("отмени").text
    undo.assert_not_called()
    assert h._pending_question is None


def test_surrounding_whitespace_does_not_hide_incomplete_timer(h):
    assert "сколько" in h.handle("   Поставь таймер   ").text
    h.handle("на пять минут")
    timers.add.assert_called_once()


@pytest.mark.parametrize("answer", [".5 минуты", ",5 минуты"])
def test_leading_decimal_separator_does_not_turn_half_into_five(h, answer):
    h.handle("таймер")
    h.handle(answer)
    timers.add.assert_not_called()


def test_slot_filling_works_without_local_llm(h):
    h.brain = None
    h.handle("таймер")
    h.handle("на пять минут")
    timers.add.assert_called_once()
