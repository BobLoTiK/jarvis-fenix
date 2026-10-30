"""Облачная LLM по HTTP: OpenAI-совместимые API и Anthropic.

Зачем отдельный модуль, а не ветка в brain.py: у облака другой транспорт
(HTTPS, заголовок авторизации, SSE-стрим) и другие правила приватности.
Brain остаётся владельцем промпта и выбора модели, а сюда уходит уже готовый
список сообщений.

Границы безопасности, зашитые в код:

* ключ живёт только в памяти экземпляра и в заголовке запроса; он не пишется
  в config.json, не попадает в repr и вырезается из текста ошибок;
* открытый http разрешён только для localhost — иначе ключ ушёл бы по сети
  в читаемом виде;
* модуль не добавляет в запрос ничего своего: ни профиля, ни истории, ни
  памяти. Что передал вызывающий, то и уйдёт. Решение о персональных блоках
  принимает brain.py (по умолчанию они не отправляются).

Провайдер выбирается пресетом, но адрес и модель можно задать свои — этого
достаточно для OpenRouter, DeepSeek, Groq, vLLM, LM Studio и любого другого
OpenAI-совместимого шлюза.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("jarvis.cloud_llm")

PROVIDERS = {
    "openai": {
        "label": "OpenAI",
        "protocol": "openai",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "openrouter": {
        "label": "OpenRouter",
        "protocol": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4o-mini",
    },
    "deepseek": {
        "label": "DeepSeek",
        "protocol": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "groq": {
        "label": "Groq",
        "protocol": "openai",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
    },
    "anthropic": {
        "label": "Anthropic",
        "protocol": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-3-5-haiku-latest",
    },
    "custom": {
        "label": "Свой адрес (OpenAI-совместимый)",
        "protocol": "openai",
        "base_url": "",
        "model": "",
    },
}

DEFAULT_PROVIDER = "openai"
ANTHROPIC_VERSION = "2023-06-01"
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_MAX_ERROR_BODY = 4096


class CloudLLMError(RuntimeError):
    """Любая неудача облачного запроса. Текст безопасен для лога."""


class CloudAuthError(CloudLLMError):
    """Ключ не принят: 401/403."""


def provider_names() -> list[str]:
    return list(PROVIDERS)


def provider_label(provider: str) -> str:
    return PROVIDERS.get(provider, PROVIDERS["custom"])["label"]


def validated_base_url(value: str) -> str:
    """Проверяет адрес: https где угодно, http только для localhost."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Укажите адрес API.")
    if any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError("В адресе API не должно быть пробелов и управляющих символов.")
    try:
        parts = urllib.parse.urlsplit(value)
        port = parts.port
    except ValueError:
        raise ValueError("Адрес API не разбирается как URL.") from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Нужен HTTP/HTTPS-адрес API.")
    if parts.username or parts.password:
        raise ValueError("Логин и пароль в адресе не нужны: ключ передаётся заголовком.")
    if parts.query or parts.fragment:
        raise ValueError("Уберите query и fragment из адреса API.")
    if port == 0:
        raise ValueError("Порт должен быть от 1 до 65535.")
    if parts.scheme == "http" and parts.hostname not in _LOCAL_HOSTS:
        raise ValueError("По открытому http ключ ушёл бы в сеть в читаемом виде. Нужен https "
                         "(http разрешён только для localhost).")
    return value.rstrip("/")


def _system_and_messages(messages):
    """Anthropic принимает system отдельным полем, остальное — как есть.

    Две нормализации, без которых провайдер отвечает 400 и пользователь видит
    пустой ответ вместо объяснения:

    * роли обязаны чередоваться — пустые реплики отбрасываются выше, поэтому
      две соседние реплики одной роли склеиваются в одну;
    * первым сообщением может быть только user — если после обрезки истории
      диалог начинается с ответа ассистента, ведущие ответы отбрасываются
      (иначе «first message must use the user role»).
    """
    system_parts, rest = [], []
    for message in messages or []:
        role = message.get("role")
        content = str(message.get("content") or "")
        if not content:
            continue
        if role == "system":
            system_parts.append(content)
        elif role in ("user", "assistant"):
            if not rest and role == "assistant":
                continue
            if rest and rest[-1]["role"] == role:
                rest[-1]["content"] += "\n\n" + content
            else:
                rest.append({"role": role, "content": content})
    return "\n\n".join(system_parts), rest


class CloudLLM:
    """Один облачный провайдер. Экземпляр создаётся на каждую смену настроек."""

    def __init__(self, provider: str, api_key: str, model: str, base_url: str | None = None,
                 timeout: float = 45.0, max_tokens: int = 600, opener=None):
        provider = provider if provider in PROVIDERS else "custom"
        preset = PROVIDERS[provider]
        self.provider = provider
        self.protocol = preset["protocol"]
        self.base_url = validated_base_url(base_url or preset["base_url"])
        self.model = str(model or preset["model"] or "").strip()
        if not self.model:
            raise ValueError("Укажите модель.")
        if len(self.model) > 256:
            raise ValueError("Слишком длинное имя модели.")
        self._key = str(api_key or "").strip()
        if not self._key:
            raise ValueError("Нужен ключ API.")
        self.timeout = max(1.0, float(timeout))
        self.max_tokens = max(1, min(int(max_tokens), 4096))
        self._open = opener or urllib.request.urlopen

    # --- безопасность -----------------------------------------------------

    def __repr__(self) -> str:
        return f"CloudLLM(provider={self.provider!r}, model={self.model!r}, key=<set>)"

    def _redact(self, text: str) -> str:
        text = str(text or "")
        if self._key:
            text = text.replace(self._key, "***")
        return text[:400]

    def _headers(self) -> dict:
        if self.protocol == "anthropic":
            return {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "x-api-key": self._key,
                "anthropic-version": ANTHROPIC_VERSION,
            }
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self._key}",
        }

    def _url(self, path: str) -> str:
        return self.base_url + path

    # --- транспорт --------------------------------------------------------

    def _open_request(self, request):
        try:
            return self._open(request, timeout=self.timeout)
        except urllib.error.HTTPError as error:
            body = b""
            try:
                body = error.read(_MAX_ERROR_BODY)
            except Exception:
                pass
            detail = body.decode("utf-8", "replace")
            try:
                parsed = json.loads(detail)
                message = parsed.get("error", {}).get("message") if isinstance(parsed, dict) else None
                if isinstance(message, str) and message:
                    detail = message
            except Exception:
                pass
            detail = self._redact(detail)
            if error.code in (401, 403):
                raise CloudAuthError(
                    f"Ключ не принят ({error.code}). Проверьте ключ и провайдера.") from None
            raise CloudLLMError(f"Облако ответило {error.code}: {detail}") from None
        except urllib.error.URLError as error:
            raise CloudLLMError(f"Нет связи с облаком: {self._redact(getattr(error, 'reason', ''))}") from None
        except OSError as error:
            raise CloudLLMError(f"Сеть недоступна: {self._redact(str(error))}") from None

    def _post(self, path: str, payload: dict):
        request = urllib.request.Request(
            self._url(path), json.dumps(payload, ensure_ascii=False).encode("utf-8"), self._headers())
        return self._open_request(request)

    # --- запросы ----------------------------------------------------------

    def _payload(self, messages, temperature, max_tokens, stream, json_mode) -> dict:
        limit = max(1, min(int(max_tokens or self.max_tokens), 4096))
        if self.protocol == "anthropic":
            system, rest = _system_and_messages(messages)
            if json_mode:
                suffix = "Ответь строго одним JSON-объектом, без пояснений и без markdown."
                system = f"{system}\n\n{suffix}".strip()
            payload = {
                "model": self.model,
                "messages": rest,
                "max_tokens": limit,
                "temperature": float(temperature),
                "stream": bool(stream),
            }
            if system:
                payload["system"] = system
            return payload
        payload = {
            "model": self.model,
            "messages": list(messages),
            "max_tokens": limit,
            "temperature": float(temperature),
            "stream": bool(stream),
        }
        if json_mode and not stream:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _endpoint(self) -> str:
        return "/messages" if self.protocol == "anthropic" else "/chat/completions"

    def _text(self, data: dict) -> str:
        if self.protocol == "anthropic":
            blocks = data.get("content")
            if not isinstance(blocks, list):
                raise CloudLLMError("Неожиданный ответ облака: нет content.")
            return "".join(str(block.get("text") or "") for block in blocks
                           if isinstance(block, dict) and block.get("type") == "text")
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise CloudLLMError("Неожиданный ответ облака: нет choices.")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            raise CloudLLMError("Неожиданный ответ облака: нет message.")
        return str(message.get("content") or "")

    def chat(self, messages, *, temperature: float = 0.7, max_tokens: int | None = None,
             json_mode: bool = False) -> str:
        payload = self._payload(messages, temperature, max_tokens, False, json_mode)
        try:
            return self._chat_once(payload)
        except CloudLLMError as error:
            # Не всякий OpenAI-совместимый шлюз знает response_format: старые
            # vLLM и LM Studio отвечают 400. Без повтора разбор команд ломался
            # бы целиком, поэтому JSON-режим — просьба, а не догма.
            if not json_mode or "response_format" not in str(error):
                raise
            log.info("Провайдер не принял response_format — повторяю без JSON-режима")
            payload.pop("response_format", None)
            return self._chat_once(payload)

    def _chat_once(self, payload: dict) -> str:
        with self._post(self._endpoint(), payload) as response:
            raw = response.read(4 * 1024 * 1024)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise CloudLLMError("Облако вернуло не JSON.") from None
        if not isinstance(data, dict):
            raise CloudLLMError("Неожиданный ответ облака.")
        if data.get("error"):
            detail = data["error"].get("message") if isinstance(data["error"], dict) else data["error"]
            raise CloudLLMError(f"Облако вернуло ошибку: {self._redact(detail)}")
        return self._text(data)

    def chat_stream(self, messages, *, temperature: float = 0.7, max_tokens: int | None = None):
        """Отдаёт чанки текста по мере прихода. Ошибки — CloudLLMError."""
        payload = self._payload(messages, temperature, max_tokens, True, False)
        with self._post(self._endpoint(), payload) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", "replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                body = line[5:].strip()
                if not body or body == "[DONE]":
                    if body == "[DONE]":
                        return
                    continue
                try:
                    event = json.loads(body)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("type") == "message_stop":
                    return
                # Ошибку внутри SSE провайдер присылает отдельным событием.
                # Раньше такой кадр молча пропускался и пользователь получал
                # пустой ответ без причины в логе.
                if event.get("type") == "error" or event.get("error"):
                    detail = event.get("error")
                    if isinstance(detail, dict):
                        detail = detail.get("message") or detail.get("type") or ""
                    raise CloudLLMError(
                        f"Облако ответило ошибкой в потоке: {self._redact(detail)}")
                chunk = ""
                if self.protocol == "anthropic":
                    delta = event.get("delta")
                    if isinstance(delta, dict):
                        chunk = str(delta.get("text") or "")
                else:
                    choices = event.get("choices")
                    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                        delta = choices[0].get("delta")
                        if isinstance(delta, dict):
                            chunk = str(delta.get("content") or "")
                if chunk:
                    yield chunk

    def probe(self) -> dict:
        """Дешёвая проверка ключа: список моделей, без генерации."""
        request = urllib.request.Request(self._url("/models"), headers=self._headers())
        with self._open_request(request) as response:
            raw = response.read(1024 * 1024)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise CloudLLMError("Проверка ключа: ответ не JSON.") from None
        models = data.get("data") if isinstance(data, dict) else None
        count = len(models) if isinstance(models, list) else None
        return {"provider": self.provider, "protocol": self.protocol,
                "base_url": self.base_url, "model": self.model, "models": count}
