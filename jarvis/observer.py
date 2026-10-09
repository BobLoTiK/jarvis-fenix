"""Observer — фоновое наблюдение за диалогом.

Извлекает факты из речи пользователя и ответов Феникса,
сохраняет в profile / learning.

Работает параллельно основному диалогу. Не блокирует.
Если LLM недоступна — молчит.
"""

import json
import logging
import threading
import time
from collections import deque

log = logging.getLogger("jarvis.observer")


EXTRACT_PROMPT = """Ты — анализатор диалога. На вход даётся история сообщений.
Извлеки ЛЮБЫЕ факты о пользователе, которые упомянуты в диалоге.

Верни ТОЛЬКО JSON:
{
  "name": null или "Максим",
  "city": null или "Нижний Новгород",
  "age": null или 18,
  "style": null или "formal|friendly|sarcastic|brief",
  "facts": {
    "ключ": "значение"
  }
}

Правила:
- name — имя пользователя («меня зовут Максим», «я Максим»).
- city — город в ИМЕНИТЕЛЬНОМ падеже («живу в нижнем» → «Нижний Новгород»).
- age — целое число лет.
- style — если юзер описал предпочтения общения.
- facts — объект с фактами: «нравится», «не нравится», «работа», «увлечение», «настроение».
- Если факт не упомянут — null или {}.
- НЕ выдумывай. Только то, что явно сказано.
- Отвечай ТОЛЬКО JSON."""


class DialogObserver:
    """Наблюдатель диалога. Работает в отдельном потоке."""

    def __init__(self, config, brain, profile_module, learning_module,
                 min_interval: float = 30.0, batch_size: int = 6):
        self.config = config
        self.brain = brain
        self.profile = profile_module
        self.learning = learning_module

        self.min_interval = min_interval
        self.batch_size = batch_size

        self._history: deque = deque(maxlen=20)
        self._last_extract = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self._enabled = bool(
            brain is not None
            and getattr(brain, "available", False)
            and config.get("observer_enabled", True)
        )
        if self._enabled:
            log.info("Observer: включён (интервал %.0f сек, батч %d)",
                     min_interval, batch_size)
        else:
            log.info("Observer: выключен (LLM недоступна или отключён в конфиге)")

    def start(self) -> None:
        if not self._enabled:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="observer"
        )
        self._thread.start()
        log.info("Observer: поток запущен")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def observe(self, role: str, text: str) -> None:
        """Добавляет сообщение в буфер."""
        if not self._enabled or not text:
            return
        with self._lock:
            self._history.append({"role": role, "text": text})

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(5.0)
            if self._stop.is_set():
                break

            now = time.time()
            with self._lock:
                history_len = len(self._history)
                if history_len < self.batch_size:
                    continue
                if now - self._last_extract < self.min_interval:
                    continue
                history = list(self._history)

            try:
                self._extract(history)
                self._last_extract = time.time()
            except Exception:
                log.exception("Observer: ошибка извлечения")

    def _extract(self, history: list) -> None:
        if not history:
            return

        lines = []
        for msg in history[-self.batch_size:]:
            role = "Пользователь" if msg["role"] == "user" else "Феникс"
            lines.append(f"{role}: {msg['text']}")
        dialog = "\n".join(lines)

        log.debug("Observer: извлекаю факты из %d сообщений", len(history))

        try:
            raw = self.brain._request(
                [
                    {"role": "system", "content": EXTRACT_PROMPT},
                    {"role": "user", "content": dialog},
                ],
                timeout=15.0,
                num_predict=200,
            )
            data = json.loads(raw)
        except json.JSONDecodeError:
            log.debug("Observer: LLM вернула не JSON")
            return
        except Exception:
            log.exception("Observer: LLM не справилась")
            return

        if not isinstance(data, dict):
            return

        self._apply(data)

    def _apply(self, data: dict) -> None:
        applied = []

        name = (data.get("name") or "").strip()
        if name and not self.profile.get("name"):
            self.profile.set("name", name[:40])
            applied.append(f"name={name}")

        city = (data.get("city") or "").strip()
        if city and not self.profile.get("default_city"):
            self.profile.set("default_city", city[:60])
            applied.append(f"city={city}")

        age = data.get("age")
        if isinstance(age, (int, float)) and 5 < age < 130:
            if not self.profile.get("age"):
                self.profile.set("age", int(age))
                applied.append(f"age={int(age)}")

        style_raw = (data.get("style") or "").strip().lower()
        if style_raw:
            try:
                from jarvis import persona
                style = persona.normalize_style(style_raw)
                if style:
                    current = persona.get().get("speech_style", "friendly")
                    if current == "friendly":
                        persona.set_field("speech_style", style)
                        applied.append(f"style={style}")
            except Exception:
                log.exception("Observer: ошибка установки стиля")

        facts = data.get("facts") or {}
        if isinstance(facts, dict):
            for key, value in facts.items():
                if not isinstance(value, str) or not value.strip():
                    continue
                key = key.strip().lower()[:40]
                value = value.strip()[:200]
                if self.learning.get_fact(key):
                    continue
                self.learning.add_fact(key, value)
                applied.append(f"{key}={value}")

        if applied:
            log.info("Observer: применил — %s", ", ".join(applied))