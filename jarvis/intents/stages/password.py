"""Ожидание пароля + команда «удали профиль X».

«Удали профиль X» ловится здесь, ДО fast-обработчиков.
Иначе tasks_fast перехватит «удали X» как удаление задачи.
"""

import logging
import re
import time

from jarvis import profile
from jarvis.intents.password import ACTION_HUMAN, verify_password
from jarvis.intents.stages.base import Stage
from jarvis.intents.verbs import CANCEL

log = logging.getLogger("jarvis.intents")


class PasswordStage(Stage):
    name = "password"

    def handle(self, ctx):
        h = ctx.handler

        # 1. Проверяем «удали профиль X» — это всегда до fast.
        reply = self._maybe_delete_profile(ctx)
        if reply is not None:
            return reply

        # 2. Если ждём ввода пароля — обрабатываем.
        if not h._pending_password:
            return None
        if time.time() >= h._pending_password.get("expires_at", 0):
            h._pending_password = None
            return None
        return self._handle_answer(ctx)

    # ----------------------------------------------------------------

    def _maybe_delete_profile(self, ctx) -> str | None:
        """«удали профиль X» → пароль или удаление."""
        h = ctx.handler
        m = re.match(r"^удали\s+профиль\s+(\S+)$", ctx.cmd)
        if not m:
            return None

        name = m.group(1)

        if h._danger_password():
            # Пароль задан — спрашиваем.
            return h._ask_password({"action": "delete_profile", "target": name})

        # Пароля нет — удаляем сразу.
        if profile.delete(name):
            return f"Профиль {name} удалён."
        return f"Профиль {name} не найден или активен."

    # ----------------------------------------------------------------

    def _handle_answer(self, ctx) -> str:
        h = ctx.handler
        pending = h._pending_password
        h._pending_password = None

        if ctx.cmd in CANCEL:
            return "Жду обращение, сэр."

        # Убираем «пароль», «код», «пин», если сказали.
        candidate = re.sub(r"^(?:пароль|код|пин)\s*", "", ctx.cmd).strip()

        stored = str(h.config.get("danger_password") or "").strip()
        if not verify_password(candidate, stored):
            log.warning("Пароль неверный")
            return "Пароль неверный. Действие отменено."

        from jarvis.intents.execute import execute_intent, execute_steps

        intent = pending.get("intent") or {}
        if isinstance(intent.get("steps"), list):
            result = execute_steps(h, intent["steps"])
        else:
            result = execute_intent(h, intent)
        return result or "Готово."


def build_ask_password(intent: dict, expires_sec: int = 30) -> tuple[dict, str]:
    """Готовит данные для _pending_password и текст запроса."""
    pending = {
        "intent": intent,
        "expires_at": time.time() + expires_sec,
    }
    action = intent.get("action")
    human = ACTION_HUMAN.get(action, "это действие")
    return pending, f"Для этого нужен пароль ({human}). Назовите пароль."