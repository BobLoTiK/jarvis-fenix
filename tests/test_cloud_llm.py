"""Стражи облачной LLM: ключ не утекает, личное не уходит без согласия.

Тесты делятся на три группы:

* транспорт (`jarvis.cloud_llm`) — на фейковом opener, без сети;
* приватность (`jarvis.brain`) — что именно попадает в системный промпт;
* хранилище ключа (`jarvis.secrets_store`) — только на Windows, там DPAPI.

Живой провайдер здесь не вызывается: ни одного сетевого запроса.
"""

import io
import json
import os
import urllib.error

import pytest

from jarvis import cloud_llm, config, secrets_store

KEY = "sk-test-0123456789abcdef"


class FakeResponse:
    """Минимальный ответ urllib: read() и итерация строк для SSE."""

    def __init__(self, payload: bytes = b"", lines=None):
        self._payload = payload
        self._lines = list(lines or [])

    def read(self, limit=None):
        return self._payload if limit is None else self._payload[:limit]

    def __iter__(self):
        return iter([line + b"\n" for line in self._lines])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def make_client(**kwargs):
    captured = {}

    def opener(request, timeout=None):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8")) if request.data else None
        return captured.get("response", FakeResponse(
            json.dumps({"choices": [{"message": {"content": "ответ"}}]}).encode()))

    client = cloud_llm.CloudLLM("openai", KEY, "gpt-4o-mini", opener=opener, **kwargs)
    return client, captured, opener


# --- адрес и ключ ---------------------------------------------------------

def test_open_http_rejected_because_key_would_travel_in_cleartext():
    with pytest.raises(ValueError, match="https"):
        cloud_llm.validated_base_url("http://api.openai.com/v1")


def test_localhost_http_allowed_for_local_gateways():
    assert cloud_llm.validated_base_url("http://127.0.0.1:1234/v1") == "http://127.0.0.1:1234/v1"
    assert cloud_llm.validated_base_url("https://api.openai.com/v1/") == "https://api.openai.com/v1"


def test_credentials_in_url_rejected():
    with pytest.raises(ValueError, match="ключ передаётся заголовком"):
        cloud_llm.validated_base_url("https://user:secret@example.com/v1")


def test_repr_never_reveals_key():
    client, _, _ = make_client()
    assert KEY not in repr(client)
    assert "key=<set>" in repr(client)


def test_config_has_no_secret_fields():
    """Ключ живёт в DPAPI-хранилище, а не в читаемом config.json."""
    forbidden = ("api_key", "apikey", "secret", "password")
    suspicious = [name for name in config.DEFAULT_CONFIG
                  if name != "danger_password"
                  and (any(word in name for word in forbidden)
                       or name.endswith("_key") or name.endswith("_token"))]
    assert suspicious == []


# --- транспорт ------------------------------------------------------------

def test_key_goes_to_header_not_to_payload():
    client, captured, _ = make_client()
    client.chat([{"role": "user", "content": "привет"}])
    body = json.dumps(captured["body"], ensure_ascii=False)
    assert KEY not in body
    headers = {name.lower(): value for name, value in captured["headers"].items()}
    assert headers["authorization"] == f"Bearer {KEY}"


def test_payload_contains_only_messages_given_by_caller():
    client, captured, _ = make_client()
    client.chat([{"role": "system", "content": "инструкция"},
                 {"role": "user", "content": "привет"}])
    assert captured["body"]["messages"] == [{"role": "system", "content": "инструкция"},
                                            {"role": "user", "content": "привет"}]
    assert captured["body"]["model"] == "gpt-4o-mini"
    assert captured["body"]["stream"] is False


def test_json_mode_sets_response_format():
    client, captured, _ = make_client()
    client.chat([{"role": "user", "content": "верни json"}], json_mode=True)
    assert captured["body"]["response_format"] == {"type": "json_object"}


def test_anthropic_moves_system_out_of_messages():
    captured = {}

    def opener(request, timeout=None):
        captured["url"] = request.full_url
        captured["headers"] = {n.lower(): v for n, v in request.header_items()}
        captured["body"] = json.loads(request.data.decode())
        payload = {"content": [{"type": "text", "text": "ответ"}]}
        return FakeResponse(json.dumps(payload).encode())

    client = cloud_llm.CloudLLM("anthropic", KEY, "claude-3-5-haiku-latest", opener=opener)
    assert client.chat([{"role": "system", "content": "система"},
                        {"role": "user", "content": "привет"}]) == "ответ"
    assert captured["body"]["system"] == "система"
    assert captured["body"]["messages"] == [{"role": "user", "content": "привет"}]
    assert captured["headers"]["x-api-key"] == KEY
    assert "authorization" not in captured["headers"]
    assert captured["url"].endswith("/messages")


def test_auth_error_does_not_echo_key():
    def opener(request, timeout=None):
        body = io.BytesIO(json.dumps({"error": {"message": f"invalid key {KEY}"}}).encode())
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, body)

    client = cloud_llm.CloudLLM("openai", KEY, "gpt-4o-mini", opener=opener)
    with pytest.raises(cloud_llm.CloudAuthError) as error:
        client.chat([{"role": "user", "content": "привет"}])
    assert KEY not in str(error.value)
    assert "Ключ не принят" in str(error.value)


def test_stream_parses_openai_sse():
    lines = [
        b'data: ' + json.dumps({"choices": [{"delta": {"content": "при"}}]}).encode(),
        b'data: ' + json.dumps({"choices": [{"delta": {"content": "вет"}}]}).encode(),
        b"data: [DONE]",
    ]
    client = cloud_llm.CloudLLM("openai", KEY, "gpt-4o-mini",
                                opener=lambda request, timeout=None: FakeResponse(lines=lines))
    assert "".join(client.chat_stream([{"role": "user", "content": "привет"}])) == "привет"


def test_stream_parses_anthropic_events():
    lines = [
        b'data: ' + json.dumps({"type": "content_block_delta",
                                "delta": {"text": "да"}}).encode(),
        b'data: ' + json.dumps({"type": "message_stop"}).encode(),
    ]
    client = cloud_llm.CloudLLM("anthropic", KEY, "claude-3-5-haiku-latest",
                                opener=lambda request, timeout=None: FakeResponse(lines=lines))
    assert "".join(client.chat_stream([{"role": "user", "content": "привет"}])) == "да"


def test_stream_surfaces_provider_error_instead_of_empty_answer():
    """Ошибка внутри SSE раньше молча терялась: пользователь получал пустой ответ."""
    lines = [
        b'data: ' + json.dumps({"choices": [{"delta": {"content": "нач"}}]}).encode(),
        b'data: ' + json.dumps({"error": {"message": "rate limit"}}).encode(),
    ]
    client = cloud_llm.CloudLLM("openai", KEY, "gpt-4o-mini",
                                opener=lambda request, timeout=None: FakeResponse(lines=lines))
    chunks = []
    with pytest.raises(cloud_llm.CloudLLMError, match="rate limit"):
        for chunk in client.chat_stream([{"role": "user", "content": "привет"}]):
            chunks.append(chunk)
    assert chunks == ["нач"]  # уже отданное не отзываем, но ошибку видно


def test_anthropic_stream_error_event_is_not_silent():
    lines = [b'data: ' + json.dumps({"type": "error", "error": {
        "type": "overloaded_error", "message": "Overloaded"}}).encode()]
    client = cloud_llm.CloudLLM("anthropic", KEY, "claude-3-5-haiku-latest",
                                opener=lambda request, timeout=None: FakeResponse(lines=lines))
    with pytest.raises(cloud_llm.CloudLLMError, match="Overloaded"):
        list(client.chat_stream([{"role": "user", "content": "привет"}]))


def test_stream_error_does_not_echo_key():
    lines = [b'data: ' + json.dumps({"error": {"message": f"bad key {KEY}"}}).encode()]
    client = cloud_llm.CloudLLM("openai", KEY, "gpt-4o-mini",
                                opener=lambda request, timeout=None: FakeResponse(lines=lines))
    with pytest.raises(cloud_llm.CloudLLMError) as error:
        list(client.chat_stream([{"role": "user", "content": "привет"}]))
    assert KEY not in str(error.value)


def test_anthropic_merges_consecutive_roles_and_drops_leading_assistant():
    """Роли у Anthropic чередуются, первым идёт user: иначе 400 вместо ответа."""
    captured = {}

    def opener(request, timeout=None):
        captured["body"] = json.loads(request.data.decode())
        return FakeResponse(json.dumps({"content": [{"type": "text", "text": "ok"}]}).encode())

    client = cloud_llm.CloudLLM("anthropic", KEY, "claude-3-5-haiku-latest", opener=opener)
    assert client.chat([
        {"role": "assistant", "content": "старый ответ"},
        {"role": "user", "content": "раз"},
        {"role": "user", "content": ""},          # пустая реплика отбрасывается
        {"role": "user", "content": "два"},
        {"role": "assistant", "content": "ок"},
        {"role": "assistant", "content": "и ещё"},
    ]) == "ok"
    assert captured["body"]["messages"] == [
        {"role": "user", "content": "раз\n\nдва"},
        {"role": "assistant", "content": "ок\n\nи ещё"},
    ]


def test_missing_key_refuses_to_build_client():
    with pytest.raises(ValueError, match="ключ"):
        cloud_llm.CloudLLM("openai", "  ", "gpt-4o-mini")


def test_json_mode_retried_without_response_format_when_gateway_rejects_it():
    """Старые vLLM/LM Studio отвечают 400 на response_format: разбор команд не должен ломаться."""
    bodies = []

    def opener(request, timeout=None):
        body = json.loads(request.data.decode())
        bodies.append(body)
        if "response_format" in body:
            stream = io.BytesIO(json.dumps(
                {"error": {"message": "response_format is not supported"}}).encode())
            raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {}, stream)
        return FakeResponse(json.dumps(
            {"choices": [{"message": {"content": '{"action":"none"}'}}]}).encode())

    client = cloud_llm.CloudLLM("custom", KEY, "test-model",
                                base_url="http://127.0.0.1:9/v1", opener=opener)
    answer = client.chat([{"role": "user", "content": "верни json"}], json_mode=True)
    assert json.loads(answer)["action"] == "none"
    assert "response_format" in bodies[0]
    assert "response_format" not in bodies[1]


# --- приватность в Brain --------------------------------------------------

class FakeConfig:
    def __init__(self, **data):
        self.data = dict(data)
        self.listeners = []

    def get(self, key, default=None):
        return self.data.get(key, default)

    def subscribe(self, callback):
        self.listeners.append(callback)

    def set(self, key, value):
        self.data[key] = value
        for callback in list(self.listeners):
            callback(key, value)


@pytest.fixture
def brain_cloud(monkeypatch):
    """Brain в облачном режиме: сеть и запуск Ollama полностью отключены."""
    from jarvis import brain as brain_module

    monkeypatch.setattr(brain_module.Brain, "_ping", lambda self: False, raising=True)
    monkeypatch.setattr(brain_module.Brain, "_try_start", lambda self: False, raising=True)
    monkeypatch.setattr(secrets_store, "load_secret", lambda name: KEY)
    calls = []

    class FakeCloud:
        def __init__(self, **kwargs):
            self.provider = kwargs.get("provider")
            self.model = kwargs.get("model")
            self.timeout = kwargs.get("timeout")
            calls.append(kwargs)

        def chat(self, messages, temperature=0.7, max_tokens=None, json_mode=False):
            calls.append({"messages": list(messages), "json_mode": json_mode})
            return '{"action":"none"}'

        def chat_stream(self, messages, temperature=0.7, max_tokens=None):
            yield "ответ"

    monkeypatch.setattr(cloud_llm, "CloudLLM", FakeCloud)
    cfg = FakeConfig(cloud_enabled=True, cloud_provider="openai",
                     cloud_base_url="https://api.openai.com/v1", cloud_model="gpt-4o-mini",
                     cloud_timeout=60.0, cloud_max_tokens=600, cloud_send_profile=False,
                     llm_timeout=45.0, prompt_level="auto", llm_temperature=0.7)
    instance = brain_module.Brain("qwen2.5:7b-instruct", "http://127.0.0.1:59999", config=cfg)
    return instance, cfg, calls


def test_cloud_mode_does_not_require_local_ollama(brain_cloud):
    instance, _, _ = brain_cloud
    assert instance.available is True
    assert instance.cloud is not None


def test_personal_blocks_not_sent_to_cloud_by_default(brain_cloud, monkeypatch):
    instance, _, calls = brain_cloud
    from jarvis import persona

    monkeypatch.setattr(persona, "build_prompt_block", lambda *a, **k: "\nЛИЧНОЕ_ИМЯ_МАКСИМ")
    system = instance._system_with_context("база")
    assert "ЛИЧНОЕ_ИМЯ_МАКСИМ" not in system
    assert instance._cloud_sends_profile() is False


def test_personal_blocks_sent_only_with_explicit_consent(brain_cloud, monkeypatch):
    instance, cfg, _ = brain_cloud
    from jarvis import persona

    monkeypatch.setattr(persona, "build_prompt_block", lambda *a, **k: "\nЛИЧНОЕ_ИМЯ_МАКСИМ")
    cfg.data["cloud_send_profile"] = True
    assert "ЛИЧНОЕ_ИМЯ_МАКСИМ" in instance._system_with_context("база")


def test_brain_request_goes_to_cloud(brain_cloud):
    instance, _, calls = brain_cloud
    instance._request([{"role": "user", "content": "привет"}], timeout=1, fmt=None)
    sent = [call for call in calls if "messages" in call]
    assert sent and sent[-1]["json_mode"] is False


def test_config_change_rebuilds_cloud_client(brain_cloud):
    instance, cfg, calls = brain_cloud
    before = len(calls)
    cfg.set("cloud_model", "gpt-4o")
    assert len(calls) > before
    assert instance.cloud.model == "gpt-4o"


def test_observer_background_extraction_blocked_in_cloud_by_default(brain_cloud):
    """Observer не должен отправлять переписку в облако без согласия."""
    instance, cfg, _ = brain_cloud
    assert instance.cloud_allows_background() is False
    cfg.data["cloud_send_profile"] = True
    assert instance.cloud_allows_background() is True


def test_observer_skips_extraction_when_cloud_has_no_consent(brain_cloud):
    instance, _, calls = brain_cloud
    from jarvis import observer as observer_module

    worker = observer_module.DialogObserver.__new__(observer_module.DialogObserver)
    worker.brain = instance
    worker.batch_size = 4
    before = len(calls)
    worker._extract([{"role": "user", "text": "меня зовут Максим"}])
    assert len(calls) == before, "в облако без согласия уходить не должно"


# --- живой HTTP на localhost (без внешней сети) ---------------------------

def _serving_openai(records):
    """Настоящий HTTP-сервер на localhost вместо фейкового opener."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length)
            records.append({"path": self.path,
                            "headers": {k.lower(): v for k, v in self.headers.items()},
                            "body": raw.decode("utf-8")})
            payload = json.loads(raw)
            if payload.get("stream"):
                chunk = {"choices": [{"delta": {"content": "ответ"}}]}
                body = (b": keep-alive\n\n"
                        + b"data: " + json.dumps(chunk).encode() + b"\n\n"
                        + b"data: [DONE]\n\n")
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = json.dumps({"choices": [{"message": {"content": "ответ от облака"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = __import__("threading").Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/v1"


def test_real_http_roundtrip_keeps_key_out_of_body():
    records = []
    server, base_url = _serving_openai(records)
    try:
        client = cloud_llm.CloudLLM("custom", KEY, "test-model", base_url=base_url)
        assert client.chat([{"role": "user", "content": "привет"}]) == "ответ от облака"
        chunks = "".join(client.chat_stream([{"role": "user", "content": "привет"}]))
        assert chunks == "ответ"
    finally:
        server.shutdown()
        server.server_close()
    assert len(records) == 2
    for record in records:
        assert record["path"].endswith("/chat/completions")
        assert KEY not in record["body"]
        assert record["headers"]["authorization"] == f"Bearer {KEY}"
    assert json.loads(records[0]["body"])["stream"] is False
    assert json.loads(records[1]["body"])["stream"] is True


# --- хранилище ключа ------------------------------------------------------

needs_windows = pytest.mark.skipif(os.name != "nt", reason="DPAPI есть только в Windows")


@needs_windows
def test_secret_roundtrip_and_tamper_detection():
    name = "pytest_cloud_key"
    try:
        assert secrets_store.save_secret(name, KEY) is True
        assert secrets_store.load_secret(name) == KEY
        assert secrets_store.has_secret(name) is True
        # Отпечаток — первые 8 hex SHA-256, а не сам ключ.
        fingerprint = secrets_store.secret_fingerprint(name)
        assert fingerprint and len(fingerprint) == 8 and KEY not in fingerprint
        # Испорченный блоб не расшифровывается: DPAPI проверяет целостность.
        from jarvis import paths
        path = paths.secrets_dir() / f"{name}.bin"
        blob = path.read_bytes()
        path.write_bytes(blob[: len(blob) // 2])
        assert secrets_store.load_secret(name) is None
        path.write_bytes(blob)
    finally:
        secrets_store.delete_secret(name)


@needs_windows
def test_secret_file_is_not_plaintext():
    name = "pytest_cloud_key_plain"
    try:
        secrets_store.save_secret(name, KEY)
        from jarvis import paths
        raw = (paths.secrets_dir() / f"{name}.bin").read_bytes()
        assert KEY.encode() not in raw
    finally:
        secrets_store.delete_secret(name)
