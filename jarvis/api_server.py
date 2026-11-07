"""Локальный HTTP-стык Феникса: `health` / `capabilities` / `turn`.

Это **договор об именах и формате**, а не общее ядро: каждый проект живёт сам,
совпадают три вещи — адреса, поля запроса и поля ответа. Феникс отдаёт их через
свой обычный `IntentHandler.handle()`, второй pipeline не заводится.

Правила, которые нельзя нарушать:

- слушаем только `127.0.0.1`: наружу это не выставляется ни при какой настройке;
- нужен Bearer-токен; токен лежит в `secrets_store` (DPAPI), а не в config.json;
- по умолчанию наружу не уходят профиль, история и память — только ответ на
  присланный текст;
- `pending` (пароль/вопрос) — это **статус**, а не «выполнено»: пароль через API
  отклоняется, ответ на уточняющий вопрос обрабатывается обычным путём;
- текст запроса и токен не пишутся в лог: только метод, путь, код и номер сессии.

Формат (schema 1)::

    GET  /v1/health        -> {"schema":1,"status":"ok","version":"2.1.2",...}
    GET  /v1/capabilities  -> {"schema":1,"capabilities":[...],"auth":"bearer",...}
    POST /v1/turn          -> {"session_id":"...","text":"..."}
                           <- {"status":"ok","pending":false,"text":"..."}

Ответ на пароль/вопрос:``{"status":"pending","pending":"question"|"password"}``.
"""

from __future__ import annotations

import hmac
import json
import logging
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
SCHEMA = 1
MAX_BODY_BYTES = 16 * 1024
MAX_TEXT = 4000
MAX_SESSION = 128
TOKEN_NAME = "api_token"
CAPABILITIES = ("health", "capabilities", "turn", "pending")

log = logging.getLogger("jarvis.api_server")

_SESSION_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def normalize_port(value, default: int = DEFAULT_PORT) -> int:
    """Порт API: битое значение → дефолт, диапазон 1024..65535."""
    try:
        port = int(value)
    except (TypeError, ValueError):
        return default
    if port < 1024 or port > 65535:
        return default
    return port


def normalize_text(value) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:MAX_TEXT]


def normalize_session(value) -> str:
    """`session_id` обязателен: `handle()` хранит состояние между вызовами."""
    if not isinstance(value, str):
        return ""
    session = value.strip()
    if not _SESSION_RE.match(session):
        return ""
    return session


def normalize_token(value) -> str:
    if not isinstance(value, str):
        return ""
    token = value.strip()
    if len(token) < 16 or any(ch.isspace() for ch in token):
        return ""
    return token


def new_token() -> str:
    return secrets.token_urlsafe(32)


def ensure_token(load=None, save=None) -> tuple[str, str]:
    """Токен из хранилища или новый. Возвращает (токен, сообщение человеку)."""
    from jarvis import secrets_store

    load = load or secrets_store.load_secret
    save = save or secrets_store.save_secret
    try:
        stored = normalize_token(load(TOKEN_NAME))
    except Exception:
        log.warning("API: не удалось прочитать токен", exc_info=True)
        stored = ""
    if stored:
        return stored, "Токен уже сохранён."
    token = new_token()
    try:
        saved = bool(save(TOKEN_NAME, token))
    except Exception:
        log.warning("API: не удалось сохранить токен", exc_info=True)
        saved = False
    if not saved:
        return "", ("Не удалось сохранить токен (нужно шифрование Windows). "
                    "API не запущен.")
    return token, "Создан новый токен, он сохранён в зашифрованном хранилище."


def _pending_kind(handler) -> str:
    """Что сейчас ждёт ответа: пароль, вопрос или ничего."""
    if getattr(handler, "_pending_password", None):
        return "password"
    pending = getattr(handler, "_pending_question", None)
    if pending:
        try:
            from jarvis.intents.clarification import pending_alive
            if pending_alive(pending):
                return "question"
        except Exception:
            log.debug("API: pending_question не проверен", exc_info=True)
            return "question"
    return ""


def _pending_text(handler) -> str:
    pending = getattr(handler, "_pending_question", None)
    if isinstance(pending, dict):
        return str(pending.get("question") or pending.get("text") or "")
    return ""


def _collect_reply(reply) -> str:
    """Стрим Ответа собирается в текст: API не умеет частичных ответов."""
    from jarvis import safety

    if not getattr(reply, "is_stream", False):
        return reply.text or ""
    guard: dict = {}
    try:
        text = "".join(chunk for chunk in safety.guard_stream(reply.stream, guard) if chunk)
    except Exception:
        log.exception("API: стрим ответа упал")
        return ""
    if guard.get("blocked"):
        log.error("Safety: ответ через API заблокирован (категория=%s)", guard.get("reason"))
        return safety.SAFE_REPLY
    return text


class _Handler(BaseHTTPRequestHandler):
    """Один обработчик на запрос; сервер и токен берёт у владельца."""

    server_version = "PhoenixApi/1"
    timeout = 30

    def log_message(self, fmt, *args):  # noqa: D401 - тише стандартного лога
        log.debug("API: %s", fmt % args)

    # --- служебное -------------------------------------------------

    def _owner(self):
        return self.server.owner

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        token = self._owner().token
        header = self.headers.get("Authorization", "")
        expected = f"Bearer {token}" if token else ""
        return bool(expected) and hmac.compare_digest(header, expected)

    def _body(self) -> dict:
        length = self.headers.get("Content-Length")
        try:
            size = int(length or 0)
        except (TypeError, ValueError):
            return {}
        if size <= 0 or size > MAX_BODY_BYTES:
            return {}
        raw = self.rfile.read(size)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _base(self) -> dict:
        return {"schema": SCHEMA, "server": "phoenix"}

    # --- эндпоинты -------------------------------------------------

    def do_GET(self) -> None:
        owner = self._owner()
        if not self._authorized():
            return self._send(401, {"error": "нужен заголовок Authorization: Bearer <токен>"})
        if self.path == "/v1/health":
            payload = self._base()
            payload.update({"status": "ok", "version": owner.version,
                            "uptime_sec": round(time.monotonic() - owner.started_at, 1)})
            return self._send(200, payload)
        if self.path == "/v1/capabilities":
            payload = self._base()
            payload.update({"capabilities": list(CAPABILITIES), "auth": "bearer",
                            "stream": False, "locale": ["ru"],
                            "privacy": ["профиль не уходит", "история не уходит",
                                        "память не уходит", "пароль через API запрещён"]})
            return self._send(200, payload)
        return self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        owner = self._owner()
        if not self._authorized():
            return self._send(401, {"error": "нужен заголовок Authorization: Bearer <токен>"})
        if self.path != "/v1/turn":
            return self._send(404, {"error": "not found"})
        data = self._body()
        if not data:
            return self._send(400, {"error": "нужно JSON-тело {session_id, text}"})
        session = normalize_session(data.get("session_id"))
        if not session:
            return self._send(400, {"error": "session_id обязателен (1..128 символов)"})
        text = normalize_text(data.get("text"))
        if not text:
            return self._send(400, {"error": "text обязателен"})
        owner.handle_turn(self, session, text)


class _Server(ThreadingHTTPServer):
    """Свой сервер: занятый порт обязан падать, а не делиться с другим Фениксом.

    У `ThreadingHTTPServer` включён `allow_reuse_address`, и на Windows второй
    bind на тот же порт проходит молча — два процесса делили бы один адрес.
    """

    allow_reuse_address = False
    daemon_threads = True


class ApiServer:
    """Локальный сервер API. Живёт, пока его не остановят или не закроют Феникса."""

    def __init__(self, handler, *, port=None, token=None, host=HOST,
                 version=None, collect=None):
        self.handler = handler
        self.host = HOST  # только петля: значение снаружи не принимается
        self.port = normalize_port(port)
        self.token = normalize_token(token)
        self.version = version
        self.started_at = time.monotonic()
        self._collect = collect or _collect_reply
        self._lock = threading.Lock()
        self._server = None
        self._thread = None
        self._refused = ""

    # --- жизнь -----------------------------------------------------

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> tuple[bool, str]:
        """Поднимает сервер. Возвращает (получилось, сообщение человеку)."""
        if self._server is not None:
            return True, f"API уже слушает {self.url}"
        if self.handler is None:
            return False, "API не запущен: ядро Феникса ещё не готово."
        if not self.token:
            return False, "API не запущен: нет токена."
        try:
            server = _Server((self.host, self.port), _Handler)
        except OSError as exc:
            log.warning("API: порт %s занят (%s)", self.port, exc)
            return False, f"Порт {self.port} занят: выберите другой."
        server.owner = self
        self._server = server
        self.port = server.server_address[1]
        self.started_at = time.monotonic()
        self._thread = threading.Thread(target=server.serve_forever,
                                        name="phoenix-api", daemon=True)
        self._thread.start()
        log.info("API: слушает %s (только 127.0.0.1)", self.url)
        return True, f"API слушает {self.url}"

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is not None:
            try:
                server.shutdown()
            except Exception:
                log.debug("API: shutdown упал", exc_info=True)
            try:
                server.server_close()
            except Exception:
                log.debug("API: server_close упал", exc_info=True)
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
        if server is not None:
            log.info("API: остановлен")

    # --- повороты диалога ------------------------------------------

    def handle_turn(self, http, session: str, text: str) -> None:
        """Один ход: pending-статус, вызов ядра и безопасный ответ."""
        pending = _pending_kind(self.handler)
        if pending == "password":
            return http._send(200, {
                "schema": SCHEMA, "session_id": session, "status": "pending",
                "pending": "password", "text":
                    "Пароль через API не вводится — подтвердите действие в окне Феникса."})
        with self._lock:
            started = time.monotonic()
            try:
                reply = self.handler.handle(text)
            except Exception:
                log.exception("API: handle упал")
                return http._send(500, {"schema": SCHEMA, "session_id": session,
                                        "status": "error",
                                        "error": "внутренняя ошибка Феникса"})
            answer = self._collect(reply)
            if getattr(reply, "is_stream", False) and answer and hasattr(self.handler, "finalize_stream"):
                try:
                    self.handler.finalize_stream(answer)
                except Exception:
                    log.debug("API: finalize_stream упал", exc_info=True)
            after = _pending_kind(self.handler)
        payload = {"schema": SCHEMA, "session_id": session,
                   "elapsed_ms": int((time.monotonic() - started) * 1000)}
        if after:
            payload.update({"status": "pending", "pending": after,
                            "text": _pending_text(self.handler) or answer})
            return http._send(200, payload)
        payload.update({"status": "ok", "pending": False, "text": answer})
        return http._send(200, payload)
