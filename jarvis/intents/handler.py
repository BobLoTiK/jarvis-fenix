"""IntentHandler — оркестрация.

Единственный класс. Собирает pipeline стадий и реестр быстрых
обработчиков, ведёт диалог, подписки на config / profile.

Вся бизнес-логика — в `stages/`, `fast/`, `execute.py`.
"""

import logging
import threading
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

        # Индексы приложений («Пуск», Steam) собираются 1-3 с, поэтому уходят
        # в фоновый поток: старт не ждёт, а первый запрос дождётся его сам.
        self._installed: dict | None = None
        self._steam_games: list | None = None
        self._index_lock = threading.Lock()
        threading.Thread(
            target=self._warm_indexes, daemon=True, name="app-index"
        ).start()

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
        self._raw_cmd: str = ""

        # Миграция пароля (plaintext → sha256).
        migrate_password_if_needed(config)

        # Custom-команды.
        from jarvis.intents.fast.custom import reload_custom
        reload_custom(self)

        # Реестр быстрых правил.
        self._fast_handlers_cache = build_registry(self)

        # Pipeline стадий.
        self._pipeline = build_pipeline(self)

        # Подписки.
        config.subscribe(self._on_config_change)
        profile.subscribe(self._on_profile_switch)

    # =================================================================
    # Индексы приложений
    # =================================================================

    def _warm_indexes(self) -> None:
        """Прогревает индексы в фоне — старт не должен ждать 1-3 с."""
        started = time.monotonic()
        self.installed
        self.steam_games
        log.info(
            "Индексы приложений готовы за %.2f с (Пуск: %d, Steam: %d)",
            time.monotonic() - started,
            len(self._installed or {}),
            len(self._steam_games or []),
        )

    def _scan_installed(self) -> dict:
        from jarvis.installed import scan_start_menu

        try:
            return scan_start_menu()
        except Exception:
            log.exception("scan_start_menu упал — индекс «Пуск» пуст")
            return {}

    def _scan_steam(self) -> list:
        from jarvis.steam import scan_steam_games

        try:
            return scan_steam_games()
        except Exception:
            log.exception("scan_steam_games упал — список игр пуст")
            return []

    @property
    def installed(self) -> dict:
        """Индекс «Пуск» → путь к .exe. Собирается лениво и ровно один раз."""
        if self._installed is None:
            with self._index_lock:
                if self._installed is None:
                    self._installed = self._scan_installed()
        return self._installed

    @property
    def steam_games(self) -> list:
        """Список Steam-игр (name, appid). Собирается лениво и ровно один раз."""
        if self._steam_games is None:
            with self._index_lock:
                if self._steam_games is None:
                    self._steam_games = self._scan_steam()
        return self._steam_games

    # =================================================================
    # Публичный API
    # =================================================================

    def handle(self, cmd: str) -> Reply:
        """Один ход; метрики содержат только длительности, не текст команды."""
        started = time.perf_counter()
        self._previous_timings = getattr(self, "_last_timings", {})
        self._last_timings = {"stages_ms": {}}
        try:
            return self._handle_command(cmd)
        finally:
            self._last_timings["handler_ms"] = round(
                (time.perf_counter() - started) * 1000, 3
            )

    def _handle_command(self, cmd: str) -> Reply:
        """Возвращает Reply: либо text, либо stream."""
        self.last_was_chat = False

        # Ответ на пароль не проходит через коррекции, историю или логи.
        if self._pending_password:
            from jarvis.intents.context import Ctx
            from jarvis.intents.stages.password import PasswordStage

            self._raw_cmd = ""
            try:
                result = PasswordStage().handle(
                    Ctx(cmd=normalize(cmd), original_cmd=cmd, handler=self)
                )
                self._last_reply = result or "Действие отменено."
                return Reply(text=self._last_reply)
            finally:
                self._raw_cmd = ""

        self._raw_cmd = cmd
        from jarvis.language import analyze_command
        analysis = analyze_command(cmd)
        self._number_analysis = analysis
        if analysis.issue:
            return Reply(text=analysis.issue)
        cmd = normalize(analysis.command)
        actions_log.info("Команда: %r (режим: %s)", cmd, self.mode)
        self._recent_phrases.append(cmd)

        result = self._handle_single(cmd)

        # Запоминаем ПОСЛЕ разбора: correction_fast читает _last_cmd как
        # «предыдущую» команду. Раньше запись стояла до pipeline, и фраза
        # «это не то, я сказал X» сравнивалась сама с собой — коррекция
        # никогда не сохранялась.
        self._last_cmd = cmd

        # Mood: реагируем на эмоциональный окрас фразы.
        # Делается ДО сохранения user_msg, чтобы mood был актуален
        # для уже сформированного ответа. Это осознанный tradeoff:
        # ответ сгенерирован со старым mood, но следующий уже учтёт.
        try:
            from jarvis import mood
            mood.apply_from_text(cmd)
        except Exception:
            log.exception("mood.apply_from_text упал на %r", cmd)

        user_msg = {"role": "user", "content": self._raw_cmd}
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
            return Reply(text=result, allow_nonverbal=self.last_was_chat)

        # result — генератор (chat_stream)
        return Reply(stream=result, allow_nonverbal=self.last_was_chat)

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
            started = time.perf_counter()
            try:
                result = stage.handle(ctx)
            finally:
                timings = getattr(self, "_last_timings", {}).get("stages_ms")
                if timings is not None:
                    timings[stage.name] = timings.get(stage.name, 0.0) + round(
                        (time.perf_counter() - started) * 1000, 3
                    )
            if result is not None:
                return result
        return None

    def _chat_stream(self, cmd: str):
        ctx = list(self.dialog)[-self._llm_context:] if self._llm_context else []
        return self.brain.chat_stream(cmd, ctx)

    def _ask_password(self, intent: dict) -> str:
        """Запрашивает пароль для опасного действия."""
        pending, msg = build_ask_password(intent)
        self._pending_question = None
        self._pending_password = pending
        return msg

    def _danger_password(self) -> str:
        return str(self.config.get("danger_password") or "").strip()

    # =================================================================
    # Подписки
    # =================================================================

    def _on_config_change(self, key: str, value) -> None:
        if key in ("custom_commands", "active_packs"):
            from jarvis.intents.fast.custom import reload_custom
            reload_custom(self)
            self.active_packs = list(self.config.get("active_packs", []))
        elif key == "memory_max":
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
        self._pending_question = None
        self._pending_password = None
        self._last_cmd = ""
        self.dialog.clear()
        for msg in memory.load(limit=self._memory_max):
            self.dialog.append(msg)
        log.info(
            "Профиль сменился: %s → %s, диалог перечитан (%d сообщений)",
            old_name, new_name, len(self.dialog),
        )