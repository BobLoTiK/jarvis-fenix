"""Честные ошибки LLM: человек понимает, что чинить."""

import socket
import urllib.error

import pytest

from jarvis.brain import Brain, describe_llm_failure


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://127.0.0.1:11434/api/chat", code, "err", {}, None)


def test_connection_refused_says_ollama_is_not_running():
    error = urllib.error.URLError(ConnectionRefusedError(10061, "refused"))
    text = describe_llm_failure(error, "qwen2.5:14b-instruct")
    assert "Ollama не запущена" in text
    assert "ollama serve" in text


def test_missing_model_tells_what_to_do():
    text = describe_llm_failure(_http_error(404), "qwen2.5:14b-instruct")
    assert "qwen2.5:14b-instruct" in text
    assert "Настройках" in text


def test_server_error_suggests_retry():
    text = describe_llm_failure(_http_error(503), "qwen2.5:14b-instruct")
    assert "HTTP 503" in text or "ошибкой сервера" in text


def test_timeout_is_named_honestly():
    text = describe_llm_failure(socket.timeout("timed out"), "qwen2.5:14b-instruct")
    assert "вовремя" in text


def test_url_timeout_reason_is_understood():
    error = urllib.error.URLError(socket.timeout("timed out"))
    assert "вовремя" in describe_llm_failure(error)


def test_unknown_error_is_not_silent():
    text = describe_llm_failure(ValueError("bad url"), "model")
    assert "LLM не ответила" in text


def _bare_brain(monkeypatch, error):
    brain = Brain.__new__(Brain)
    brain.model = "qwen2.5:14b-instruct"
    brain.url = "http://127.0.0.1:11434"
    brain.timeout = 1.0
    brain.temperature = 0.7
    brain.available = True
    brain.cloud = None
    brain.failure_hint = ""
    brain.system_prompt = "тест"
    brain.prompt_level = "medium"
    brain._config = None
    brain._last_facts = ""

    def boom(*args, **kwargs):
        raise error

    monkeypatch.setattr("jarvis.brain.urllib.request.urlopen", boom)
    monkeypatch.setattr(Brain, "_system_with_context", lambda self, base, cmd: base)
    return brain


def test_stream_yields_one_honest_message_before_first_chunk(monkeypatch):
    brain = _bare_brain(monkeypatch, urllib.error.URLError(ConnectionRefusedError(10061, "refused")))
    chunks = list(brain.chat_stream("привет"))
    assert len(chunks) == 1
    assert "Ollama не запущена" in chunks[0]
    assert brain.failure_hint == chunks[0]


def test_chat_returns_none_and_keeps_hint(monkeypatch):
    brain = _bare_brain(monkeypatch, urllib.error.URLError(ConnectionRefusedError(10061, "refused")))
    monkeypatch.setattr(Brain, "_request", lambda *a, **k: (_ for _ in ()).throw(
        urllib.error.URLError(ConnectionRefusedError(10061, "refused"))))
    assert brain.chat("привет") is None
    assert "Ollama не запущена" in brain.failure_hint


def test_stage_mentions_how_to_start_llm():
    from jarvis.intents.stages.llm import LLMStage

    class FakeHandler:
        mode = "combo"
        brain = None
        _last_debug = None

    class Ctx:
        cmd = "привет"
        handler = FakeHandler()

    reply = LLMStage().handle(Ctx())
    assert "LLM недоступна" in reply
    assert "ollama serve" in reply


@pytest.mark.parametrize("code", [401, 429])
def test_other_http_codes_are_reported(code):
    text = describe_llm_failure(_http_error(code), "model")
    assert str(code) in text
