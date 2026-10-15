"""Recognition policy and integration tested without a microphone or model weights."""

import ast
from array import array
from collections import deque
import logging
from pathlib import Path
import threading
import time
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from jarvis.recognition import (
    Quality,
    assess_pcm,
    assess_vosk,
    assess_whisper,
    transcripts_agree,
)
from jarvis.reply import Reply
from jarvis.text_utils import normalize

GOOD = Quality(True, "test")
BAD = Quality(False, "test")
PCM = array("h", [500, -500] * 4000).tobytes()
REJECT, UNCERTAIN = object(), object()


def method(filename, classname, name, **extra):
    path = Path(__file__).resolve().parents[1] / filename
    tree = ast.parse(path.read_text())
    cls = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == classname
    )
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    env = {
        "time": time,
        "normalize": normalize,
        "Reply": Reply,
        "log": logging.getLogger("test.asr"),
        "_REJECT": REJECT,
        "_UNCERTAIN": UNCERTAIN,
        **extra,
    }
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), "exec"), env)
    return env[name]


def segment(**kw):
    return NS(
        **{
            "text": "Открой блокнот",
            "avg_logprob": -0.2,
            "no_speech_prob": 0.02,
            "compression_ratio": 1.1,
            **kw,
        }
    )


@pytest.mark.parametrize(
    "pcm",
    [
        b"",
        b"\0",
        b"\0\0" * 8000,
        array("h", [1] * 8000).tobytes(),
        array("h", [32767] * 8000).tobytes(),
        array("h", [1000] * 10).tobytes(),
    ],
)
def test_invalid_silent_or_clipped_audio_rejected(pcm):
    assert not assess_pcm(pcm).accepted


def test_signal_is_not_claimed_to_be_speech():
    q = assess_pcm(PCM)
    assert q.accepted and q.reason == "signal_present"
    assert not assess_pcm(PCM, 0).accepted


@pytest.mark.parametrize(
    "scores,accepted",
    [
        ([0.9, 0.85], True),
        ([0.8, 0.49], False),
        ([0.64, 0.64], False),
        ([0.95], True),
        ([], False),
        ([float("nan")], False),
        ([1.01], False),
    ],
)
def test_vosk_word_confidence(scores, accepted):
    q = assess_vosk({"text": "Феникс открой", "result": [{"conf": v} for v in scores]})
    assert q.accepted == accepted
    assert "Феникс" not in str(q)


@pytest.mark.parametrize(
    "result",
    [
        {},
        {"text": "да"},
        {"text": "", "result": [{"conf": 0.99}]},
        {"text": "нет", "result": [{}]},
        {"text": "нет", "result": [{"conf": "invalid"}]},
    ],
)
def test_missing_vosk_evidence_is_not_confident(result):
    assert not assess_vosk(result).accepted


@pytest.mark.parametrize(
    "changes,accepted",
    [
        ({}, True),
        ({"avg_logprob": -1.2}, False),
        ({"no_speech_prob": 0.9}, False),
        ({"compression_ratio": 3}, False),
        ({"avg_logprob": float("nan")}, False),
        ({"no_speech_prob": -1}, False),
        ({"text": ""}, False),
        ({"text": "Квантовый Кракозябр"}, True),
    ],
)
def test_whisper_evidence_not_vocabulary_blacklist(changes, accepted):
    assert assess_whisper([segment(**changes)]).accepted == accepted


def test_whole_utterance_rejected_if_one_fragment_unclear():
    assert not assess_whisper([segment(), segment(text="не", avg_logprob=-2)]).accepted
    assert not assess_whisper([NS(text="да")]).accepted
    assert not assess_whisper([]).accepted


def test_thresholds_are_configurable_and_invalid_settings_safe():
    result = {"text": "да", "result": [{"conf": 0.6}]}
    assert assess_vosk(result, {"stt_min_word_confidence": 0.55}).accepted
    assert not assess_vosk(result, {"stt_min_word_confidence": float("nan")}).accepted
    assert assess_whisper(
        [segment(avg_logprob=-1.1)], {"stt_min_avg_logprob": -1.3}
    ).accepted


@pytest.mark.parametrize(
    "a,b,agrees",
    [
        ("открой блокнот", "закрой блокнот", False),
        ("включи звук", "не включи звук", False),
        ("громкость 15", "громкость 50", False),
        ("громкость пятьдесят", "громкость 50", True),
        ("напомни через 1 час", "напомни через 60 минут", True),
        ("открой Steam", "открой стим", True),
        ("открой браузер", "открой блокнот", False),
        ("открой", "открой блокнот", False),
        ("Расскажи о космосе", "Расскажи про космос", True),
    ],
)
def test_critical_disagreements(a, b, agrees):
    assert transcripts_agree(a, b) == agrees


def app(primary=GOOD, refined="открой блокнот", whisper=True):
    a = NS(
        config={
            "sample_rate": 16000,
            "prosody_enabled": False,
            "command_window_sec": 6,
        },
        handler=NS(handle=Mock(return_value=Reply(text="Готово"))),
        gui=Mock(),
        observer=Mock(),
        cmd_lock=threading.Lock(),
        speaker=Mock(),
        say=Mock(return_value=False),
        listener=NS(last_quality=primary, recent_phrases=deque(maxlen=10)),
        _awaiting_until=time.time() + 30,
        _extract_command=lambda s: s,
        _refine=Mock(return_value=refined),
        whisper=object() if whisper else None,
    )
    a._request_repeat = lambda: method("jarvis/main.py", "Jarvis", "_request_repeat")(a)
    return a


@pytest.mark.parametrize("refined", [UNCERTAIN, None])
def test_uncertain_never_reaches_commands_gui_or_learning(refined):
    a = app(primary=BAD, refined=refined)
    method("jarvis/main.py", "Jarvis", "_process")(a, "открой блокнот", PCM)
    a.handler.handle.assert_not_called()
    a.observer.observe.assert_not_called()
    assert all(call.args[0] != "user" for call in a.gui.add_message.call_args_list)
    assert "открой блокнот" not in str(a.gui.add_message.mock_calls)
    assert not a.listener.recent_phrases
    assert "Повтори" in a.say.call_args.args[0].text


def test_silence_cannot_trigger_actions_even_with_confident_text():
    a = app()
    method("jarvis/main.py", "Jarvis", "_process")(a, "открой блокнот", b"\0\0" * 8000)
    a.handler.handle.assert_not_called()
    a._refine.assert_not_called()


@pytest.mark.parametrize("primary", [None, BAD])
def test_vosk_only_requires_evidence(primary):
    a = app(primary=primary, whisper=False)
    method("jarvis/main.py", "Jarvis", "_process")(a, "открой блокнот", PCM)
    a.handler.handle.assert_not_called()


def test_stronger_whisper_can_rescue_vosk():
    a = app(primary=BAD)
    method("jarvis/main.py", "Jarvis", "_process")(a, "открой что-то", PCM)
    a.handler.handle.assert_called_once_with("открой блокнот")
    assert list(a.listener.recent_phrases) == ["открой блокнот"]


def test_failed_whisper_may_fall_back_only_to_confident_vosk():
    a = app(refined=None)
    method("jarvis/main.py", "Jarvis", "_process")(a, "открой блокнот", PCM)
    a.handler.handle.assert_called_once_with("открой блокнот")


def test_reliable_but_disagreeing_commands_require_repeat():
    a = app(refined="закрой блокнот")
    method("jarvis/main.py", "Jarvis", "_process")(a, "открой блокнот", PCM)
    a.handler.handle.assert_not_called()
    assert not a.listener.recent_phrases


def test_unconfirmed_wake_is_ignored_not_answered():
    a = app(refined=REJECT)
    method("jarvis/main.py", "Jarvis", "_process")(a, "открой блокнот", PCM)
    a.handler.handle.assert_not_called()
    a.say.assert_not_called()


def test_repeat_prompt_is_rate_limited():
    a = app()
    a._request_repeat()
    a._request_repeat()
    a.say.assert_called_once()
    assert a._awaiting_until > time.time()


@pytest.mark.parametrize(
    "quality,text,expected",
    [
        (BAD, "выдумка", UNCERTAIN),
        (None, "выдумка", UNCERTAIN),
        (GOOD, "", UNCERTAIN),
        (GOOD, "Феникс, громкость 15", "громкость 15"),
    ],
)
def test_refine_requires_fresh_evidence(quality, text, expected):
    a = NS(
        whisper=NS(transcribe=Mock(return_value=text), last_quality=quality),
        config={},
        _wake_word_required=True,
        _is_wake=lambda s: s == "феникс",
    )
    assert method("jarvis/main.py", "Jarvis", "_refine")(a, PCM, True) == expected


@pytest.mark.parametrize(
    "required,awaiting,expected",
    [
        (True, False, REJECT),
        (False, False, "закрой блокнот"),
        (True, True, "закрой блокнот"),
    ],
)
def test_no_weak_wake_guess(required, awaiting, expected):
    a = NS(
        whisper=NS(transcribe=Mock(return_value="закрой блокнот"), last_quality=GOOD),
        config={},
        _wake_word_required=required,
        _is_wake=lambda s: False,
    )
    assert method("jarvis/main.py", "Jarvis", "_refine")(a, PCM, awaiting) == expected


def test_transcriber_checks_segments_and_has_no_content_priming():
    np = pytest.importorskip("numpy")
    transcribe = method("jarvis/stt.py", "WhisperTranscriber", "transcribe", np=np)
    a = NS(
        _ensure_loaded=Mock(),
        _config={},
        _model=NS(transcribe=Mock(return_value=(iter([segment()]), None))),
    )
    assert transcribe(a, PCM) == "Открой блокнот"
    kw = a._model.transcribe.call_args.kwargs
    assert kw["initial_prompt"] is None
    assert kw["condition_on_previous_text"] is False
    assert kw["temperature"] == 0
    assert a.last_quality.accepted
    a._model.transcribe.return_value = (iter([segment(no_speech_prob=0.99)]), None)
    assert transcribe(a, PCM) == ""
    assert not a.last_quality.accepted
    a._model.transcribe.reset_mock()
    assert transcribe(a, b"\0\0" * 8000) == ""
    a._model.transcribe.assert_not_called()


def test_parser_abstention_is_clarification_not_second_guess():
    from jarvis.intents.context import Ctx
    from jarvis.intents.stages.llm import LLMStage

    h = NS(
        mode="combo",
        brain=NS(available=True, parse=Mock(return_value={"action": "none"})),
        _chat_stream=Mock(),
    )
    reply = LLMStage().handle(Ctx(cmd="открой эту штуку", handler=h))
    assert "Уточни" in reply
    h._chat_stream.assert_not_called()


def test_transcription_error_does_not_keep_old_quality():
    np = pytest.importorskip("numpy")
    transcribe = method("jarvis/stt.py", "WhisperTranscriber", "transcribe", np=np)
    a = NS(
        last_quality=GOOD, _ensure_loaded=Mock(side_effect=RuntimeError("not loaded"))
    )
    with pytest.raises(RuntimeError):
        transcribe(a, PCM)
    assert a.last_quality is None


def test_uncertain_password_never_reaches_handler_or_history():
    a = app(primary=BAD)
    a.handler._pending_password = {"expires_at": time.time() + 20}
    a._is_wake = lambda s: s == "феникс"
    method("jarvis/main.py", "Jarvis", "_process")(a, "пароль секрет", PCM)
    a.handler.handle.assert_not_called()
    a._refine.assert_not_called()
    a.observer.observe.assert_not_called()
    assert "секрет" not in str(a.gui.mock_calls)
    assert not a.listener.recent_phrases


def test_pending_question_opens_window_before_extracting_answer():
    a = app(whisper=False)
    a.handler._pending_question = {"expires_at": time.time() + 20}
    a._awaiting_until = 0
    a._wake_word_required = True
    a._is_wake = lambda s: False
    a._extract_command = lambda s: method(
        "jarvis/main.py", "Jarvis", "_extract_command"
    )(a, s)
    method("jarvis/main.py", "Jarvis", "_process")(a, "второй вариант", PCM)
    a.handler.handle.assert_called_once_with("второй вариант")
