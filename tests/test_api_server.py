"""Локальный стык API: живой HTTP на 127.0.0.1, авторизация, pending, приватность."""
import json
import socket
import threading
import time
import urllib.error
import urllib.request

import flet as ft
import pytest

from jarvis import api_server, peer_client
from jarvis import gui as module
from jarvis import mood, profile
from jarvis.api_server import ApiServer, normalize_port, normalize_session, normalize_token
from jarvis.config import Config
from jarvis.peer_client import PeerClient, PeerError
from jarvis.reply import Reply

TOKEN = "test-token-0123456789abcdef"


class FakeHandler:
    """Ядро-заглушка: считает вызовы, помнит pending, отвечает по правилу."""

    def __init__(self):
        self._pending_password = None
        self._pending_question = None
        self.calls = []
        self.finalized = []

    def handle(self, text):
        self.calls.append(text)
        if "пароль" in text:
            self._pending_password = {"kind": "custom"}
            return Reply("Скажите пароль.")
        if "уточни" in text:
            self._pending_question = {"question": "Какой блокнот?", "expires_at": time.time() + 60}
            return Reply("Какой блокнот?")
        if "поток" in text:
            def chunks():
                yield "При"
                yield "вет"
            return Reply(stream=chunks())
        return Reply(f"эхо: {text}")

    def finalize_stream(self, text):
        self.finalized.append(text)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def server():
    port = free_port()
    core = FakeHandler()
    api = ApiServer(core, port=port, token=TOKEN, version="9.9.9")
    ok, message = api.start()
    assert ok, message
    try:
        yield api, core
    finally:
        api.stop()


def get(api, path, token=TOKEN):
    request = urllib.request.Request(api.url + path, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def post(api, path, payload, token=TOKEN):
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(api.url + path, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def post_error(api, path, payload, token=TOKEN):
    with pytest.raises(urllib.error.HTTPError) as caught:
        post(api, path, payload, token=token)
    body = json.loads(caught.value.read().decode("utf-8"))
    return caught.value.code, body


def test_health_and_capabilities(server):
    api, _core = server
    status, health = get(api, "/v1/health")
    assert status == 200
    assert health["schema"] == 1 and health["status"] == "ok"
    assert health["version"] == "9.9.9"
    status, caps = get(api, "/v1/capabilities")
    assert status == 200
    assert set(caps["capabilities"]) == {"health", "capabilities", "turn", "pending"}
    assert caps["auth"] == "bearer" and caps["stream"] is False
    assert "профиль не уходит" in caps["privacy"]


def test_only_loopback_is_used(server):
    api, _core = server
    assert api.host == "127.0.0.1" and api.url.startswith("http://127.0.0.1:")
    other = ApiServer(FakeHandler(), port=free_port(), token=TOKEN, host="0.0.0.0")
    assert other.host == "127.0.0.1"


def test_requests_without_token_are_rejected(server):
    api, core = server
    with pytest.raises(urllib.error.HTTPError) as caught:
        get(api, "/v1/health", token="wrong-token-0123456789")
    assert caught.value.code == 401
    code, body = post_error(api, "/v1/turn", {"session_id": "s1", "text": "привет"}, token=None)
    assert code == 401 and "Bearer" in body["error"]
    assert core.calls == []


def test_turn_requires_session_and_text(server):
    api, core = server
    code, body = post_error(api, "/v1/turn", {"text": "привет"})
    assert code == 400 and "session_id" in body["error"]
    code, body = post_error(api, "/v1/turn", {"session_id": "s1"})
    assert code == 400 and "text" in body["error"]
    code, _body = post_error(api, "/v1/turn", {"session_id": "s" * 200, "text": "привет"})
    assert code == 400
    assert core.calls == []


def test_turn_returns_answer_and_echoes_session(server):
    api, core = server
    status, body = post(api, "/v1/turn", {"session_id": "sess-1", "text": "  привет  "})
    assert status == 200
    assert body["status"] == "ok" and body["pending"] is False
    assert body["text"] == "эхо: привет" and body["session_id"] == "sess-1"
    assert core.calls == ["привет"]


def test_pending_question_is_a_status_not_success(server):
    api, core = server
    status, body = post(api, "/v1/turn", {"session_id": "s1", "text": "уточни"})
    assert status == 200 and body["status"] == "pending"
    assert body["pending"] == "question" and body["text"] == "Какой блокнот?"


def test_password_never_goes_through_api(server):
    api, core = server
    core._pending_password = {"kind": "custom"}
    status, body = post(api, "/v1/turn", {"session_id": "s1", "text": "1234"})
    assert status == 200 and body["status"] == "pending" and body["pending"] == "password"
    assert "окне Феникса" in body["text"]
    assert core.calls == []  # ядро пароль из API не получает


def test_stream_reply_is_collected_and_finalized(server):
    api, core = server
    status, body = post(api, "/v1/turn", {"session_id": "s1", "text": "поток"})
    assert status == 200 and body["text"] == "Привет"
    assert core.finalized == ["Привет"]


def test_core_failure_is_not_reported_as_success(server):
    api, core = server

    def boom(_text):
        raise RuntimeError("ядро сломалось")

    core.handle = boom
    code, body = post_error(api, "/v1/turn", {"session_id": "s1", "text": "привет"})
    assert code == 500 and body["status"] == "error"
    assert "сломалось" not in json.dumps(body)


def test_unknown_paths_are_404(server):
    api, _core = server
    with pytest.raises(urllib.error.HTTPError) as caught:
        get(api, "/v1/secret")
    assert caught.value.code == 404
    code, _body = post_error(api, "/v1/tools/invoke", {"session_id": "s1", "text": "x"})
    assert code == 404


def test_turn_serializes_calls(server):
    api, core = server
    order = []
    original = core.handle

    def slow(text):
        order.append(("start", text))
        time.sleep(0.15)
        order.append(("end", text))
        return original(text)

    core.handle = slow
    threads = [threading.Thread(target=post, args=(api, "/v1/turn",
                                                   {"session_id": f"s{i}", "text": "привет"}))
               for i in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert len(order) == 6
    assert order[0][0] == "start" and order[1][0] == "end"


def test_tokens_and_sessions_are_validated():
    assert normalize_token(TOKEN) == TOKEN
    assert normalize_token("short") == "" and normalize_token("with space 1234567") == ""
    assert normalize_session("sess-1:alpha_2.3") == "sess-1:alpha_2.3"
    assert normalize_session("") == "" and normalize_session("плохая сессия") == ""
    assert normalize_port(8765) == 8765 and normalize_port(80) == 8765
    assert normalize_port("abc") == 8765 and normalize_port(None) == 8765
    assert normalize_port("9000") == 9000


def test_stop_frees_the_port():
    port = free_port()
    api = ApiServer(FakeHandler(), port=port, token=TOKEN)
    assert api.start()[0] is True
    api.stop()
    assert api.running is False
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))  # порт снова свободен
    again = ApiServer(FakeHandler(), port=port, token=TOKEN)
    assert again.start()[0] is True
    again.stop()


def test_start_without_token_or_core_is_honest():
    api = ApiServer(FakeHandler(), port=free_port(), token="")
    ok, message = api.start()
    assert ok is False and "токен" in message.lower()
    api = ApiServer(None, port=free_port(), token=TOKEN)
    ok, message = api.start()
    assert ok is False and "ядро" in message.lower()


def test_busy_port_is_reported_not_faked():
    port = free_port()
    first = ApiServer(FakeHandler(), port=port, token=TOKEN)
    assert first.start()[0] is True
    second = ApiServer(FakeHandler(), port=port, token=TOKEN)
    try:
        ok, message = second.start()
        assert ok is False and str(port) in message
    finally:
        first.stop()


def test_token_is_not_in_logs_or_repr(server, caplog):
    api, core = server
    caplog.set_level("DEBUG")
    post(api, "/v1/turn", {"session_id": "s1", "text": "привет"})
    get(api, "/v1/health")
    text = "\n".join(record.getMessage() for record in caplog.records)
    assert TOKEN not in text
    assert "привет" not in text
    client = PeerClient(api.url, TOKEN)
    assert TOKEN not in repr(client) and "***" in repr(client)


# --- клиент-сосед ------------------------------------------------------


def test_peer_client_talks_to_the_same_api(server):
    api, core = server
    client = PeerClient(api.url, TOKEN, timeout=5)
    assert client.health()["status"] == "ok"
    assert "turn" in client.capabilities()["capabilities"]
    answer = client.ask("привет", session_id="peer-1")
    assert answer["status"] == "ok" and answer["text"] == "эхо: привет"
    assert answer["session_id"] == "peer-1"


def test_peer_client_rejects_bad_inputs():
    with pytest.raises(ValueError):
        PeerClient("127.0.0.1:8765", TOKEN)
    with pytest.raises(ValueError):
        PeerClient("http://127.0.0.1:8765", "short")
    client = PeerClient("http://127.0.0.1:8765", TOKEN)
    with pytest.raises(ValueError):
        client.ask("   ")


def test_peer_client_reports_errors_without_secrets(server):
    api, _core = server
    with pytest.raises(PeerError) as caught:
        PeerClient(api.url, "wrong-token-0123456789").health()
    assert caught.value.status == 401
    assert "wrong-token" not in str(caught.value)
    with pytest.raises(PeerError):
        PeerClient("http://127.0.0.1:1", TOKEN, timeout=1).health()


# --- настройки в GUI ---------------------------------------------------


@pytest.fixture
def window(tmp_path):
    gui = module.FenixGUI(None, Config(tmp_path / "config.json"))
    page = type("Page", (), {"update": lambda self: None})()
    gui._page = page
    yield gui
    gui.stop()
    module._apply_palette("dark")
    profile.unsubscribe(gui._on_profile_switch)
    mood.unsubscribe(gui._on_mood_change)


def test_api_is_off_by_default_and_toggle_is_honest(window):
    assert window.config.get("api_enabled") is False
    assert window._sync_api_server() == (False, "API выключен.")
    ok = window.set_api_enabled(True, update=False)
    assert ok is False  # ядро не передано — сервер не поднимается
    assert window._api_server is None
    assert "ядра" in window._api_status
    assert window.config.get("api_enabled") is True
    assert window.set_api_enabled(False, update=False) is True
    assert window._api_status == "API выключен."


def test_api_port_is_normalized(window):
    assert window.set_api_port(9001) is True
    assert window.config.get("api_port") == 9001
    window.set_api_port(80)
    assert window.config.get("api_port") == 8765


def test_gui_runs_the_api_for_its_core(tmp_path, monkeypatch):
    """Сквозной путь: галочка в GUI → живой сервер → клиент-сосед → ядро."""
    core = FakeHandler()
    gui = module.FenixGUI(type("Jarvis", (), {"handler": core})(),
                          Config(tmp_path / "config.json"))
    gui.config.set("api_port", free_port())
    page = type("Page", (), {"update": lambda self: None})()
    gui._page = page
    monkeypatch.setattr(api_server, "ensure_token", lambda: (TOKEN, "Токен готов."))
    try:
        assert gui.set_api_enabled(True, update=False) is True
        assert gui._api_server is not None and gui._api_server.running
        client = PeerClient(gui._api_server.url, TOKEN)
        assert client.ask("привет")["text"] == "эхо: привет"
        assert core.calls == ["привет"]
        assert gui.set_api_enabled(False, update=False) is True
        assert gui._api_server is None
    finally:
        gui.stop()
        module._apply_palette("dark")
        profile.unsubscribe(gui._on_profile_switch)
        mood.unsubscribe(gui._on_mood_change)
