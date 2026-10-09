"""Первый запуск — знакомство через LLM-диалог.

Никаких сценариев `if/elif`. LLM ведёт диалог, мы только
проверяем: «это команда или свободный текст?».

Если команда — пропускаем (пусть идёт в обычный handle).
Если LLM недоступна — молча завершаем онбординг.
"""

import logging

from jarvis.intents.stages.base import Stage
from jarvis.intents.verbs import COMMAND_VERBS

log = logging.getLogger("jarvis.intents")


class OnboardingStage(Stage):
    name = "onboarding"

    def handle(self, ctx):
        from jarvis import first_run, persona, profile

        if not first_run.is_first_run():
            return None

        h = ctx.handler

        # LLM нет — молча завершаем онбординг.
        if h.brain is None or not h.brain.available:
            first_run.mark_done()
            return None

        # Если это команда — не перехватываем.
        if self._looks_like_command(ctx.cmd):
            return None

        # Собираем историю диалога.
        history = list(h.dialog)[-10:]

        # 6+ фраз от юзера — принудительно завершаем.
        user_msgs = sum(1 for m in h.dialog if m.get("role") == "user")
        force_done = user_msgs >= 6

        result = h.brain.onboarding_chat(ctx.cmd, history)
        reply = result.get("reply") or ""

        # Сохраняем что LLM вытащила.
        name = result.get("name")
        if name and not profile.get("name"):
            profile.set("name", name)
            log.info("Онбординг: name=%r", name)

        style_raw = result.get("style")
        if style_raw:
            style = persona.normalize_style(style_raw)
            if style and persona.get().get("speech_style") == "friendly":
                persona.set_field("speech_style", style)
                log.info("Онбординг: style=%r", style)

        if result.get("onboarding_done") or force_done:
            first_run.mark_done()
            log.info("Онбординг завершён (LLM=%s, force=%s)",
                     result.get("onboarding_done"), force_done)

        return reply or None

    def _looks_like_command(self, cmd: str) -> bool:
        """Быстрая проверка: команда или свободный текст?"""
        if not cmd:
            return False
        first = cmd.split()[0] if cmd.split() else ""
        return first in COMMAND_VERBS