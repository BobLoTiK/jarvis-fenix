"""LLM — последний шанс разобрать команду.

Сюда попадаем, если ни одна стадия выше не справилась.

Проверки перед LLM:
    - режим commands → отказ
    - LLM недоступна → отказ
    - мусорный ввод (одна буква, слишком коротко) → отказ

После LLM:
    - если intent требует пароля → PasswordStage отработает на след. шаге
    - если search без «найди» → предупреждение
    - если answer → chat_stream
"""

import logging

from jarvis.intents.password import is_danger
from jarvis.intents.stages.base import Stage
from jarvis.intents.verbs import SEARCH_VERBS

log = logging.getLogger("jarvis.intents")


class LLMStage(Stage):
    name = "llm"

    def handle(self, ctx):
        h = ctx.handler
        cmd = ctx.cmd

        if h.mode == "commands":
            h._last_debug = {
                "cmd": cmd, "reason": "режим commands",
                "mode": h.mode, "llm": False,
            }
            return "Я не понял команду. Скажите «режим ИИ» или добавьте фразу в конфиг."

        if h.brain is None or not h.brain.available:
            h._last_debug = {
                "cmd": cmd, "reason": "LLM недоступна",
                "mode": h.mode, "llm": False,
            }
            return "LLM недоступна. Скажите «режим команды»."

        # Мусорный ввод (№70): LLM галлюцинирует на «ааа» или «эээ».
        # Исключения «да», «нет», «ок» — это ответы на pending.
        clean = cmd.replace(" ", "")
        if cmd not in {"да", "нет", "ок"}:
            if len(cmd) < 3 or (clean and len(set(clean)) <= 2):
                h._last_debug = {
                    "cmd": cmd, "reason": "мусорный ввод",
                    "mode": h.mode, "llm": False,
                }
                return "Не расслышал, сэр. Повторите, пожалуйста."

        intent = h.brain.parse(cmd)
        h._last_debug = {
            "cmd": cmd, "intent": intent,
            "mode": h.mode, "llm": True,
        }

        if intent and intent.get("action") not in ("answer", "none"):
            if is_danger(intent, str(h.config.get("danger_password") or "").strip()):
                return h._ask_password(intent)

            if (intent.get("action") == "search"
                    and not any(v in cmd for v in SEARCH_VERBS)):
                return "Сэр, чтобы поискать, скажите «найди» и запрос. Например: «найди погоду»."

            # Импорт здесь, чтобы не было цикла
            from jarvis.intents.execute import execute_intent, execute_steps

            if isinstance(intent.get("steps"), list):
                reply = execute_steps(h, intent["steps"])
            else:
                reply = execute_intent(h, intent)
            if reply:
                return reply

        if intent and intent.get("action") == "answer":
            gen = h._chat_stream(cmd)
            if gen is not None:
                h.last_was_chat = True
                return gen
            if intent.get("reply"):
                return str(intent["reply"])[:600]

        gen = h._chat_stream(cmd)
        if gen is not None:
            h.last_was_chat = True
            return gen
        return "Я не понял команду."