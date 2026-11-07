"""Клиент к стыку `health` / `capabilities` / `turn` — своему или соседнего проекта.

Договор тот же: Bearer-токен, `session_id` обязателен, `pending` — отдельный
статус. Клиент не логирует ни токен, ни текст запроса; ошибки приходят как
`PeerError` с кодом HTTP, а не как сырой текст ответа в журнале.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
import uuid

log = logging.getLogger("jarvis.peer_client")

DEFAULT_TIMEOUT = 5.0


class PeerError(Exception):
    """Ошибка стыка: код HTTP (если был) и короткая причина, без секретов."""

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


def normalize_url(value, default_port: int | None = None) -> str:
    """Адрес соседа: только http/https, без пробелов и лишних слэшей."""
    if not isinstance(value, str):
        return ""
    url = value.strip().rstrip("/")
    if not url:
        return ""
    if not url.lower().startswith(("http://", "https://")):
        return ""
    if any(ch.isspace() for ch in url):
        return ""
    if default_port and ":" not in url.split("://", 1)[1]:
        url = f"{url}:{default_port}"
    return url


class PeerClient:
    """Минимальный клиент: без зависимостей, с таймаутом и честной ошибкой."""

    def __init__(self, base_url: str, token: str, *, timeout: float = DEFAULT_TIMEOUT):
        url = normalize_url(base_url)
        if not url:
            raise ValueError("Адрес стыка должен начинаться с http:// или https://")
        token = (token or "").strip()
        if len(token) < 16 or any(ch.isspace() for ch in token):
            raise ValueError("Нужен токен не короче 16 символов без пробелов")
        self.base_url = url
        self.token = token
        try:
            self.timeout = max(0.5, min(60.0, float(timeout)))
        except (TypeError, ValueError):
            self.timeout = DEFAULT_TIMEOUT

    def __repr__(self) -> str:
        return f"PeerClient({self.base_url!r}, token=***)"

    # --- запросы ---------------------------------------------------

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        data = None
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = urllib.request.Request(self.base_url + path, data=data,
                                         headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            raise PeerError(f"стык ответил {exc.code}", status=exc.code) from None
        except urllib.error.URLError as exc:
            raise PeerError(f"стык недоступен: {exc.reason}") from None
        except TimeoutError:
            raise PeerError("стык не ответил вовремя") from None
        try:
            result = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise PeerError(f"стык вернул не JSON (код {status})", status=status) from None
        if not isinstance(result, dict):
            raise PeerError("стык вернул не объект", status=status)
        return result

    def health(self) -> dict:
        return self._request("GET", "/v1/health")

    def capabilities(self) -> dict:
        return self._request("GET", "/v1/capabilities")

    def ask(self, text: str, session_id: str | None = None) -> dict:
        """Один поворот диалога. `pending` — это данные, а не исключение."""
        body = (text or "").strip()
        if not body:
            raise ValueError("Пустой текст не отправляется")
        session = (session_id or f"peer-{uuid.uuid4().hex}").strip()
        if not session:
            session = f"peer-{uuid.uuid4().hex}"
        return self._request("POST", "/v1/turn",
                             {"session_id": session, "text": body})
