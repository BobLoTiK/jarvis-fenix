"""IntentHandler — оркестрация.

Единственный класс. Собирает pipeline стадий и реестр быстрых
обработчиков, ведёт диалог, подписки на config / profile.

Вся бизнес-логика — в `stages/`, `fast/`, `execute.py`.
"""

import logging
import time
from collections import deque

from jarvis import memory, profile
from jarvis.intents.fast import build_registry, load_custom
from jarvis.intents.password import migrate_password_if_needed
from jarvis.intents.stages import build_pipeline
from jarvis.intents.stages.password import build_ask_password
from jarvis.reply import Reply
from jarvis.text_utils import normalize

log = logging.getLogger("jarvis.intents")
actions_log = logging.getLogger("jarvis.actions")


class IntentHandler:

    def __init__(self, config, apps, brain=None, listener=None, gui=None, jarvis=None):
        self.config = config
        self.apps = apps
        self.brain = brain
        self.listener = listener
        self.gui = gui
        self.jarvis = jarvis

        # Индексы — читаются один раз при старте.
        from jarvis.installed import scan_start_menu
        from jarvis.steam import scan_steam_games
        self.installed = scan_start_menu()
        self.steam_games = scan_steam_games()

        self.music_app = config.get("music_app", "яндекс музыка")
        self.music_wait = float(config.get("music_wait_sec", 6))
        self.last_file = None
        self.last_folder = None

        # Память — из config.
        self._memory_max = int(config.get("memory_max", 100))
        self._llm_context = int(config.get("llm_context_messages", 20))
        self.dialog = deque(maxlen=self._memory_max)
        for msg in memory.load(limit=self._memory_max):
            self.dialog.append(msg)

        # Состояние.
        self.last_was_chat = False
        self.mode = config.get("mode", "combo")
        self.active_packs = list(config.get("active_packs", []))
        self.last_macro = None
        self._reset_requested = False
        self._last_reply = ""
        self._pending_question = None
        self._pending_password = None

        # Диагностика.
        self._last_debug: dict = {}
        self._recent_phrases: deque = deque(maxlen=10)
        self._last_cmd: str = ""

        # Миграция пароля (plaintext → sha256).
        migrate_password_if_needed(config)

        # Custom-команды.
        self.custom = load_custom(config)
        self._config_custom_original = list(self.custom)

        # Реестр быстрых правил.
        self._fast_handlers_cache = build_registry(self)

        # Pipeline стадий.
        self._pipeline = build_pipeline(self)

        # Подписки.
        config.subscribe(self._on_config_change)
        profile.subscribe(self._on_profile_switch)

    # =================================================================
    # Публичный API
    # =================================================================

    def handle(self, cmd: str) -> Reply:
        """Возвращает Reply: либо text, либо stream."""
        self.last_was_chat = False

        cmd = normalize(cmd)
        actions_log.info("Команда: %r (режим: %s)", cmd, self.mode)
        self._recent_phrases.append(cmd)

        self._last_cmd = cmd

        result = self._handle_single(cmd)

        user_msg = {"role": "user", "content": cmd}
        self.dialog.append(user_msg)
        memory.append(user_msg)

        if result is None:
            result = "Не понял команду."

        if isinstance(result, str):
            assistant_msg = {"role": "assistant", "content": result}
            self.dialog.append(assistant_msg)
            memory.append(assistant_msg)
            actions_log.info("Ответ: %r", result[:120])
            self._last_reply = result
            return Reply(text=result)

        # result — генератор (chat_stream)
        return Reply(stream=result)

    def finalize_stream(self, full_text: str) -> None:
        if not full_text:
            return
        assistant_msg = {"role": "assistant", "content": full_text}
        self.dialog.append(assistant_msg)
        memory.append(assistant_msg)
        self._last_reply = full_text

    # =================================================================
    # Внутренняя оркестрация
    # =================================================================

    def _handle_single(self, cmd: str):
        """Пробегает pipeline стадий. Первая не-None — побеждает."""
        from jarvis.intents.context import Ctx

        ctx = Ctx(cmd=cmd, original_cmd=cmd, handler=self)
        for stage in self._pipeline:
            result = stage.handle(ctx)
            if result is not None:
                return result
        return None

    def _chat_stream(self, cmd: str):
        ctx = list(self.dialog)[-self._llm_context:] if self._llm_context else []
        return self.brain.chat_stream(cmd, ctx)

    def _ask_password(self, intent: dict) -> str:
        """Запрашивает пароль для опасного действия."""
        pending, msg = build_ask_password(intent)
        self._pending_password = pending
        return msg

    def _danger_password(self) -> str:
        return str(self.config.get("danger_password") or "").strip()

    # =================================================================
    # Подписки
    # =================================================================

    def _on_config_change(self, key: str, value) -> None:
        if key == "memory_max":
            try:
                new_max = int(value)
            except (TypeError, ValueError):
                return
            if new_max <= 0:
                return
            self._memory_max = new_max
            self.dialog = deque(self.dialog, maxlen=new_max)
            log.info("IntentHandler: memory_max = %d", new_max)
        elif key == "llm_context_messages":
            try:
                self._llm_context = int(value)
            except (TypeError, ValueError):
                return
            log.info("IntentHandler: llm_context_messages = %d", self._llm_context)

    def _on_profile_switch(self, old_name: str, new_name: str) -> None:
        """Перечитывает dialog при смене профиля."""
        if old_name == new_name:
            return
        self.dialog.clear()
        for msg in memory.load(limit=self._memory_max):
            self.dialog.append(msg)
        log.info(
            "Профиль сменился: %s → %s, диалог перечитан (%d сообщений)",
            old_name, new_name, len(self.dialog),
        )