"""Стадия pipeline: jarvis.intents.stages.password.

Ожидание пароля + команда «удали профиль X».

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

        # Ввод пароля имеет приоритет над всеми другими командами.
        if h._pending_password:
            if time.time() >= h._pending_password.get("expires_at", 0):
                h._pending_password = None
                return "Время ввода пароля истекло. Повторите команду."
            return self._handle_answer(ctx)

        reply = self._maybe_delete_profile(ctx)
        if reply is not None:
            return reply

        # 3. Опасные fast-команды («очисти список», «отмени все напоминания»):
        # fast-реестр идёт после этой стадии, а проверка is_danger живёт
        # только в LLMStage — без гейта здесь такие команды выполнялись
        # без пароля, хотя входят в DANGER_ACTIONS.
        return self._maybe_gate_fast_danger(ctx)

    # ----------------------------------------------------------------

    def _maybe_gate_fast_danger(self, ctx) -> str | None:
        """Пароль для опасных fast-команд (clear_tasks / cancel_timers)."""
        h = ctx.handler
        if not h._danger_password():
            return None
        from jarvis import tasks as _tasks
        from jarvis import timers as _timers
        if _tasks.is_clear_command(ctx.cmd):
            return h._ask_password({"action": "clear_tasks"})
        if _timers.is_cancel_all_command(ctx.cmd):
            return h._ask_password({"action": "cancel_timers"})
        return None

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
            h._pending_question = None
            h._reset_requested = True
            return "Жду обращение, сэр."

        # Убираем «пароль», «код», «пин», если сказали.
        raw = ctx.original_cmd or ctx.cmd
        candidate = re.sub(r"^(?:пароль|код|пин)\s+", "", raw.strip(),
                           count=1, flags=re.IGNORECASE).strip()

        stored = str(h.config.get("danger_password") or "").strip()
        if not verify_password(candidate, stored):
            log.warning("Пароль неверный")
            return "Пароль неверный. Действие отменено."

        from jarvis.intents.execute import execute_intent, execute_steps

        intent = pending.get("intent") or {}
        if intent.get("action") == "custom_command":
            from jarvis.intents.fast.custom import execute_custom
            result = execute_custom(h, intent["spec"],
                                    intent.get("reply", "Выполняю."),
                                    authorized=True)
        elif isinstance(intent.get("steps"), list):
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