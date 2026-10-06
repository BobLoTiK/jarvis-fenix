"""Разбор команды: быстрые правила + LLM."""

import datetime
import logging
import random
import re
import time
from collections import deque
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterator

from jarvis import APP_NAME, __version__, actions, files
from jarvis.apps import find_app
from jarvis.installed import find_installed, scan_start_menu
from jarvis.steam import find_game, scan_steam_games
from jarvis import modes
from jarvis import packs
from jarvis import memory
from jarvis import voices
from jarvis import timers
from jarvis import tasks
from jarvis import weather
from jarvis import profile
from jarvis import history
from jarvis import learning
from jarvis.reply import Reply


log = logging.getLogger("jarvis.intents")
actions_log = logging.getLogger("jarvis.actions")


def normalize(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


CANCEL = {"отмена", "стоп", "стой", "хватит", "замолчи", "ничего", "забудь", "отбой"}

BROWSER_WORDS = {"браузер", "браузере", "браузером", "хром", "хроме", "интернет", "интернете"}

SEARCH_VERBS = ("найди", "поищи", "ищи", "загугли", "погугли", "поиск")

SITES = {
    "ютуб": ("Ютуб", "https://www.youtube.com"),
    "гугл": ("Гугл", "https://www.google.com"),
    "яндекс": ("Яндекс", "https://ya.ru"),
    "гитхаб": ("Гитхаб", "https://github.com"),
    "вк": ("ВКонтакте", "https://vk.com"),
    "вконтакте": ("ВКонтакте", "https://vk.com"),
    "твич": ("Твич", "https://www.twitch.tv"),
    "кинопоиск": ("Кинопоиск", "https://www.kinopoisk.ru"),
    "википедия": ("Википедию", "https://ru.wikipedia.org"),
    "почта": ("Почту", "https://mail.google.com"),
}

MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня",
          "июля", "августа", "сентября", "октября", "ноября", "декабря"]

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]

_FOLDER_TITLES = {
    "Desktop": "на рабочем столе", "Downloads": "в загрузках",
    "Documents": "в документах", "Pictures": "в изображениях",
    "Music": "в музыке", "Videos": "в видео",
    "Screenshots": "в скриншотах",
}

_WEATHER_BAD_TARGET = (
    "курс", "доллар", "рубл", "евро", "юан", "валют",
    "цену", "цена", "поиск", "найди", "погод", "прогноз",
    "пожалуйста", "сколько", "стоит",
)

_NOT_A_CITY = (
    "открой", "закрой", "найди", "включи", "выключи",
    "как дела", "кто ты", "спасибо", "привет", "пока",
    "который час", "какое число", "сделай скриншот",
    "загугли", "поищи", "напечатай",
)

# Действия, требующие пароля (если danger_password задан)
_DANGER_ACTIONS = {
    "shutdown_pc", "reboot_pc", "kill_process",
    "clear_tasks", "cancel_timers", "delete_profile",
}


class IntentHandler:

    def __init__(self, config, apps, brain=None, listener=None):
        self.config = config
        self.apps = apps
        self.brain = brain
        self.listener = listener
        self.installed = scan_start_menu()
        self.steam_games = scan_steam_games()
        self.music_app = config.get("music_app", "яндекс музыка")
        self.music_wait = float(config.get("music_wait_sec", 6))
        self.last_file = None
        self.last_folder = None

        # Лимиты памяти — из config (не хардкод).
        self._memory_max = int(config.get("memory_max", 100))
        self._llm_context = int(config.get("llm_context_messages", 20))
        self.dialog = deque(maxlen=self._memory_max)
        for msg in memory.load(limit=self._memory_max):
            self.dialog.append(msg)

        self.last_was_chat = False
        self.mode = modes.get_mode(config)
        self.active_packs = list(config.get("active_packs", []))
        self.last_macro = None
        self._reset_requested = False
        self._last_reply = ""
        self._pending_question = None

        # Диагностика (Н2, Н3)
        self._last_debug: dict = {}
        self._recent_phrases: deque = deque(maxlen=10)

        # Последняя команда (для коррекции «это не то»)
        self._last_cmd: str = ""

        # Пароль (2.13)
        self._pending_password: dict | None = None

        self._config_custom_original = []
        for entry in config.get("custom_commands", []):
            phrases = [normalize(p) for p in entry.get("phrases", []) if p.strip()]
            action = entry.get("action", "").strip() or entry.get("steps")
            if phrases and action:
                self._config_custom_original.append(
                    (phrases, action, entry.get("reply", "Выполняю."))
                )
        self.custom = list(self._config_custom_original) + self._load_packs_as_custom(config)

        # Подписка на изменения memory_max / llm_context_messages
        config.subscribe(self._on_config_change)

        # Подписка на смену профиля — чтобы перечитать dialog
        profile.subscribe(self._on_profile_switch)

    def _on_config_change(self, key: str, value) -> None:
        """Реагирует на смену memory_max / llm_context_messages в рантайме."""
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
        """Перечитывает dialog при смене профиля.

        Без этого Феникс продолжает помнить диалог старого профиля
        и подсовывает его в LLM-контекст нового пользователя.
        """
        # Защита от повторного вызова при пустом old_name (init)
        if old_name == new_name:
            return

        self.dialog.clear()
        for msg in memory.load(limit=self._memory_max):
            self.dialog.append(msg)
        log.info(
            "Профиль сменился: %s → %s, диалог перечитан (%d сообщений)",
            old_name, new_name, len(self.dialog),
        )

    def handle(self, cmd: str) -> Reply:
        """Возвращает Reply: либо text, либо stream."""
        self.last_was_chat = False

        # Нормализация — единая точка входа.
        # Голосовой путь уже нормализует в Jarvis._process,
        # но GUI передаёт сырой текст. Нормализуем здесь,
        # чтобы все regex в _*_fast работали одинаково.
        cmd = normalize(cmd)

        actions_log.info("Команда: %r (режим: %s)", cmd, self.mode)

        # Диагностика: сохраняем последнюю команду
        self._recent_phrases.append(cmd)

        # Запоминаем ДО применения коррекции — чтобы «это не то»
        # знало, что именно было сказано (а не то, во что превратила коррекция).
        prev_cmd = self._last_cmd
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

    def finalize_stream(self, cmd: str, full_text: str) -> None:
        if not full_text:
            return
        assistant_msg = {"role": "assistant", "content": full_text}
        self.dialog.append(assistant_msg)
        memory.append(assistant_msg)
        self._last_reply = full_text

    def _chat_stream(self, cmd: str):
        """Отправляет в LLM только последние _llm_context сообщений."""
        ctx = list(self.dialog)[-self._llm_context:] if self._llm_context else []
        return self.brain.chat_stream(cmd, ctx)

    def _danger_password(self) -> str:
        return str(self.config.get("danger_password") or "").strip()

    def _handle_single(self, cmd: str) -> str | Iterator[str]:
        # === CANCEL — самый первый (фикс №6) ===
        # «стой», «отмена», «хватит» должны срабатывать ВСЕГДА, даже если
        # висит _pending_password / _pending_question.
        if cmd in CANCEL:
            self._pending_password = None
            self._pending_question = None
            self._reset_requested = True
            return "Жду обращение, сэр."

        # Применяем коррекцию, если есть
        corrected = learning.find_correction(cmd)
        if corrected and corrected != cmd:
            log.info("Применена коррекция: %r → %r", cmd, corrected)
            cmd = corrected

        # Пароль (2.13) — если ждём ввода
        if self._pending_password and time.time() < self._pending_password.get("expires_at", 0):
            return self._handle_password_answer(cmd)
        elif self._pending_password:
            self._pending_password = None

        # Удаление профиля — до tasks (иначе tasks перехватит «удали профиль X»)
        m = re.match(r"^удали\s+профиль\s+(\S+)$", cmd)
        if m:
            name = m.group(1)
            if self._danger_password():
                return self._ask_password({"action": "delete_profile", "target": name})
            if profile.delete(name):
                return f"Профиль {name} удалён."
            return f"Профиль {name} не найден или активен."

        # Память диалога — до всего остального
        mem_reply, clear_requested = memory.handle_memory_command(cmd, list(self.dialog))
        if mem_reply:
            if clear_requested:
                self.dialog.clear()
            return mem_reply

        if self._pending_question and time.time() < self._pending_question.get("expires_at", 0):
            return self._handle_pending_answer(cmd)
        else:
            self._pending_question = None

        # Буфер обмена
        if re.search(r"скопируй\s+(выделенное|выделенный|это\s+выделенное)", cmd) \
                or re.search(r"(выдели|выделенное)\s+(и\s+)?скопируй", cmd) \
                or cmd in {"скопируй выделенное", "скопируй это выделенное"}:
            return self._execute_intent({"action": "copy_selection"})

        if re.search(r"скопируй\s+(свой\s+)?(ответ|ответь|последнее|сказанное)", cmd) \
                or cmd in {"скопируй свой ответ", "скопируй ответ", "скопируй что ты сказал"}:
            return self._execute_intent({"action": "clipboard_copy_last"})

        if re.search(r"(что|чё)\s+(в\s+)?буфере", cmd) \
                or re.search(r"(покажи|прочитай|что)\s+буфер", cmd) \
                or cmd in {"что скопировано", "что в буфере"}:
            return self._execute_intent({"action": "clipboard_read"})

        if re.search(r"(очисти|сотри|удали)\s+буфер", cmd) \
                or cmd in {"очисти буфер", "сотри буфер"}:
            return self._execute_intent({"action": "clipboard_clear"})

        # Режимы
        if any(w in cmd for w in ("режим", "комбо", "комбинирован")):
            prev_mode = self.mode
            reply, new_mode = modes.handle_mode_command(cmd, self.mode, self.config)
            if reply:
                if new_mode != prev_mode:
                    history.push({
                        "action": "set_mode",
                        "prev_value": prev_mode,
                    })
                self.mode = new_mode
                return reply

        reply = self._match_custom(cmd)
        if reply:
            return reply

        reply = self._small_talk(cmd)
        if reply:
            return reply

        if re.search(r"скрин|снимок экрана", cmd):
            return self._take_screenshot(cmd)

        # --- Быстрые правила без LLM ---

        # Музыка — ДО _open_fast, иначе «включи музыку» откроет папку
        reply = self._music_fast(cmd)
        if reply:
            return reply

        reply = self._open_fast(cmd)
        if reply:
            return reply

        reply = voices.handle_voice_command(cmd, self.config)
        if reply:
            return reply

        reply, new_active = packs.handle_pack_command(cmd, self.active_packs, self.config)
        if reply:
            if new_active != self.active_packs:
                self.active_packs = new_active
                self._reload_packs()
            return reply

        reply = timers.handle_timer_command(cmd)
        if reply:
            return reply

        reply = tasks.handle_task_command(cmd)
        if reply:
            return reply

        reply = self._profile_fast(cmd)
        if reply:
            return reply

        reply = self._memory_fast(cmd)
        if reply:
            return reply

        reply = self._system_fast(cmd)
        if reply:
            return reply

        reply = self._debug_fast(cmd)
        if reply:
            return reply

        reply = self._correction_fast(cmd)
        if reply:
            return reply

        reply = self._undo_fast(cmd)
        if reply:
            return reply

        reply = self._weather_currency_fast(cmd)
        if reply:
            return reply

        if self.mode == "commands":
            self._last_debug = {
                "cmd": cmd, "reason": "режим commands",
                "mode": self.mode, "llm": False,
            }
            return "Я не понял команду. Скажите «режим ИИ» или добавьте фразу в конфиг."

        if self.brain is None or not self.brain.available:
            self._last_debug = {
                "cmd": cmd, "reason": "LLM недоступна",
                "mode": self.mode, "llm": False,
            }
            return "LLM недоступна. Скажите «режим команды»."

        intent = self.brain.parse(cmd)
        self._last_debug = {
            "cmd": cmd,
            "intent": intent,
            "mode": self.mode,
            "llm": True,
        }
        if intent and intent.get("action") not in ("answer", "none"):
            # Пароль на опасные (2.13)
            if self._is_danger(intent):
                return self._ask_password(intent)

            if intent.get("action") == "search" \
                    and not any(v in cmd for v in SEARCH_VERBS):
                return "Сэр, чтобы поискать, скажите «найди» и запрос. Например: «найди погоду»."
            if isinstance(intent.get("steps"), list):
                reply = self._execute_steps(intent["steps"])
            else:
                reply = self._execute_intent(intent)
            if reply:
                return reply

        if intent and intent.get("action") == "answer":
            gen = self._chat_stream(cmd)
            if gen is not None:
                self.last_was_chat = True
                return gen
            if intent.get("reply"):
                return str(intent["reply"])[:600]

        gen = self._chat_stream(cmd)
        if gen is not None:
            self.last_was_chat = True
            return gen
        return "Я не понял команду."

    def _is_danger(self, intent: dict) -> bool:
        """Проверяет, опасно ли действие (2.13)."""
        if not self._danger_password():
            return False
        action = intent.get("action")
        if action in _DANGER_ACTIONS:
            return True
        # open_app с target: выключение/перезагрузка (shutdown /s)
        if action == "open_app":
            target = str(intent.get("target") or "").lower()
            if "shutdown" in target or "выключ" in target or "перезагруз" in target:
                return True
        return False

    def _ask_password(self, intent: dict) -> str:
        """Запрашивает пароль для опасного действия."""
        self._pending_password = {
            "intent": intent,
            "expires_at": time.time() + 30,
        }
        action = intent.get("action")
        human = {
            "shutdown_pc": "выключение компьютера",
            "reboot_pc": "перезагрузку",
            "kill_process": "закрытие процесса",
            "clear_tasks": "очистку списка задач",
            "cancel_timers": "отмену напоминаний",
            "delete_profile": "удаление профиля",
            "open_app": "это действие",
        }.get(action, "это действие")
        return f"Для этого нужен пароль ({human}). Назовите пароль."

    def _handle_password_answer(self, cmd: str) -> str:
        """Проверяет пароль и выполняет отложенное действие."""
        pending = self._pending_password
        self._pending_password = None

        # Страховка: если проскочил CANCEL — отменяем действие.
        # (Основная проверка CANCEL уже в начале _handle_single, но
        #  пусть будет — на случай рефакторинга.)
        if cmd in CANCEL:
            return "Жду обращение, сэр."

        # Убираем «пароль», «код», лишние слова
        candidate = re.sub(r"^(?:пароль|код|пин)\s*", "", cmd).strip()

        if candidate != self._danger_password():
            log.warning("Пароль неверный: %r", candidate)
            return "Пароль неверный. Действие отменено."

        intent = pending.get("intent") or {}
        # Выполняем
        if isinstance(intent.get("steps"), list):
            result = self._execute_steps(intent["steps"])
        else:
            result = self._execute_intent(intent)
        return result or "Готово."

    def _music_fast(self, cmd: str) -> str | None:
        """Музыка — ДО _open_fast. Иначе «включи музыку» откроет папку.

        Ловит: включи/врубай/играй музыку, плей, пауза, следующий трек,
        предыдущий трек, стоп, громче, тише, без звука.
        """
        # «включи музыку» / «врубай музыку» / «играй музыку»
        if re.search(r"(включи|врубай|играй|поставь)\s+(музыку|музыка|плейлист)", cmd):
            actions.media_key("play")
            return "Включаю музыку."

        # «пауза», «плей», «играть/стоп»
        if cmd in {"пауза", "плей", "play", "pause"}:
            actions.media_key("play")
            return "Готово."
        if re.search(r"^(включи|врубай)\s+(плей|музыку)$", cmd):
            actions.media_key("play")
            return "Включаю."

        # «следующий трек», «дальше», «переключи трек»
        if re.search(r"(следующ|дальше|переключи|переключ)\w*\s*(трек|песн|музык)?", cmd):
            if any(w in cmd for w in ("трек", "песн", "музык", "дальше")):
                actions.media_key("next")
                return "Переключаю."

        # «предыдущий трек», «назад трек»
        if re.search(r"(предыдущ|назад)\w*\s*(трек|песн|музык)", cmd):
            actions.media_key("prev")
            return "Возвращаю."

        # «стоп музыка», «останови музыку»
        if re.search(r"(останови|стоп)\s+(музык|трек|песн)", cmd):
            actions.media_key("play")
            return "Останавливаю."

        return None


    def _open_fast(self, cmd: str) -> str | None:
        """Быстрое открытие приложений/сайтов/папок — без LLM."""
        m = re.match(r"^(?:открой|запусти|врубай|включи|открывай)\s+(.+)$", cmd)
        if not m:
            return None
        target = m.group(1).strip()
        if not target:
            return None
        return self._do_open(target)

    def _profile_fast(self, cmd: str) -> str | None:
        """Команды профиля: смена, список, факты."""
        log.info("_profile_fast: %r", cmd)
        m = re.match(r"^(?:я\s*[-—]?\s*|зови\s+меня\s+|переключись\s+на\s+|я\s+это\s+)([а-яёa-z][а-яёa-z\s\-]{0,40})$", cmd)
        if m:
            name = m.group(1).strip()
            if name and name not in _NOT_A_CITY:
                return profile.switch(name)

        if re.search(r"(кто|какой)\s+(сейчас\s+)?(активен|профиль|пользователь)", cmd) \
                or cmd in {"кто активен", "какой профиль", "текущий профиль"}:
            name = profile.get("name") or profile.current()
            return f"Сейчас профиль {name}."

        if re.search(r"(список|какие|покажи)\s+профил", cmd) \
                or cmd in {"список профилей", "какие профили"}:
            all_p = profile.list_all()
            if not all_p:
                return "Профилей нет."
            return f"Профили: {', '.join(all_p)}."

        m = re.match(r"^(?:запомни|запиши)\s*[,:]?\s*(?:что\s+)?(.+)$", cmd)
        if m:
            fact = m.group(1).strip(" ,.:!?")
            if not fact:
                return "Что запомнить?"
            sep = re.match(r"^(.+?)\s*[—\-=:]\s*(.+)$", fact)
            if sep:
                key, value = sep.group(1).strip(), sep.group(2).strip()
            else:
                key, value = fact, "да"
            ok = learning.add_fact(key, value)
            if ok:
                return f"Запомнил: {key} — {value}."
            return "Не удалось сохранить — проверь профиль (возможно, битый JSON)."

        if re.search(r"(что|чё)\s+ты\s+(обо\s+мне\s+)?знаешь", cmd) \
                or cmd in {"что ты обо мне знаешь", "что ты знаешь"}:
            facts = profile.all_facts()
            name = profile.get("name")
            parts = []
            if name:
                parts.append(f"Тебя зовут {name}")
            if facts:
                facts_str = "; ".join(f"{k} — {v}" for k, v in facts.items())
                parts.append(f"Знаю: {facts_str}")
            if not parts:
                return "Пока ничего о тебе не знаю."
            return ". ".join(parts) + "."

        m = re.match(r"^забудь\s+(?:факт\s+)?(.+)$", cmd)
        if m:
            key = m.group(1).strip(" ,.:!?")
            if profile.forget_fact(key):
                return f"Забыл: {key}."
            return f"Факта «{key}» не знаю."

        return None

    def _memory_fast(self, cmd: str) -> str | None:
        """Голосовые команды для управления памятью."""
        if re.search(r"(коротк|быстр)\w*\s+память", cmd):
            self.config.update({
                "memory_max": 40,
                "llm_context_messages": 10,
            })
            return "Память: короткая. 40 сообщений, контекст LLM — 10."

        if re.search(r"(обычн|стандартн|нормальн)\w*\s+память", cmd):
            self.config.update({
                "memory_max": 100,
                "llm_context_messages": 20,
            })
            return "Память: обычная. 100 сообщений, контекст LLM — 20."

        if re.search(r"(долг|глубок)\w*\s+память", cmd):
            self.config.update({
                "memory_max": 200,
                "llm_context_messages": 40,
            })
            return "Память: долгая. 200 сообщений, контекст LLM — 40."

        if re.search(r"(какая|текущ)\w*\s+память", cmd) \
                or cmd in {"какая память", "текущая память"}:
            mm = self.config.get("memory_max", 100)
            lc = self.config.get("llm_context_messages", 20)
            return f"Память: {mm} сообщений, контекст LLM — {lc}."

        return None

    def _system_fast(self, cmd: str) -> str | None:
        """Быстрые системные команды: раскладка, громкость, яркость."""

        # --- раскладка ---
        if re.search(r"раскладк", cmd):
            if re.search(r"(переключ|смени|поменяй|следующ)", cmd):
                ok = actions.switch_layout()
                if ok:
                    history.push({"action": "switch_layout"})
                return "Переключаю раскладку." if ok else "Не удалось переключить."
            if re.search(r"(русск|ru)", cmd):
                ok = actions.set_layout_ru()
                return "Русская раскладка." if ok else "Не удалось."
            if re.search(r"(англ|english|en)", cmd):
                ok = actions.set_layout_en()
                return "Английская раскладка." if ok else "Не удалось."
            if re.search(r"(какая|текущ|что)", cmd):
                layout = actions.get_layout()
                if layout == "ru":
                    return "Сейчас русская раскладка."
                if layout == "en":
                    return "Сейчас английская раскладка."
                return "Не смог определить раскладку."

        # --- громкость ---
        m = re.search(r"громкость\s+(?:на\s+)?(\d+)", cmd)
        if m:
            pct = int(m.group(1))
            prev = actions.get_volume()
            ok = actions.set_volume(pct)
            if ok:
                history.push({"action": "set_volume", "prev_value": prev})
            return f"Громкость: {pct}%." if ok else "Не удалось."

        if re.search(r"(какая|текущ|узнай)\s+громкость", cmd) \
                or cmd in {"какая громкость", "текущая громкость"}:
            vol = actions.get_volume()
            return f"Громкость: {vol}%." if vol is not None else "Не смог узнать."

        # --- яркость ---
        m = re.search(r"яркость\s+(?:на\s+)?(\d+)", cmd)
        if m:
            pct = int(m.group(1))
            prev = actions.get_brightness()
            ok = actions.set_brightness(pct)
            if ok:
                history.push({"action": "set_brightness", "prev_value": prev})
            return f"Яркость: {pct}%." if ok else "Не удалось."

        if re.search(r"(какая|текущ|узнай)\s+яркость", cmd) \
                or cmd in {"какая яркость", "текущая яркость"}:
            br = actions.get_brightness()
            return f"Яркость: {br}%." if br is not None else "Не смог узнать."

        return None

    def _debug_fast(self, cmd: str) -> str | None:
        """Команды диагностики: что слышал, почему не понял."""
        if re.search(r"(что|чё)\s+ты\s+слышал", cmd) \
                or cmd in {"что ты слышал", "что слышал", "история"}:
            # Берём из Listener — то, что услышал Vosk сырым.
            # Fallback на _recent_phrases — то, что дошло до handle().
            phrases = []
            if self.listener is not None and hasattr(self.listener, "recent_phrases"):
                phrases = list(self.listener.recent_phrases)
            if not phrases:
                phrases = list(self._recent_phrases)
            if not phrases:
                return "Пока ничего не слышал."
            lines = [f"{i+1}. {p}" for i, p in enumerate(phrases[-5:])]
            return "Последние фразы: " + "; ".join(lines) + "."

        if re.search(r"почему\s+(ты\s+)?не\s+понял", cmd) \
                or cmd in {"почему не понял", "почему не поняла"}:
            d = self._last_debug
            if not d:
                return "Пока нечего диагностировать."
            parts = [f"Фраза: «{d.get('cmd', '?')}»"]
            parts.append(f"Режим: {d.get('mode', '?')}")
            if d.get("llm"):
                intent = d.get("intent")
                if intent:
                    parts.append(f"LLM вернула: {intent.get('action', '?')}")
                else:
                    parts.append("LLM не разобрала")
            else:
                parts.append(f"LLM: {d.get('reason', 'выкл')}")
            return ". ".join(parts) + "."

        return None

    def _undo_fast(self, cmd: str) -> str | None:
        """Отмена последнего действия (Н1)."""
        if not re.search(r"(не\s+то|отмени|верни\s+как\s+было|откат)", cmd):
            return None

        item = history.pop()
        if not item:
            return "Нечего отменять."

        action = item.get("action")

        # macro → откатываем все шаги в обратном порядке
        if action == "macro":
            steps = item.get("steps") or []
            if not steps:
                return "Нечего отменять."
            results = []
            for step in reversed(steps):
                s_action = step.get("action")
                s_target = step.get("target")
                if s_action == "open_app" and s_target:
                    r = self._do_close(s_target)
                    results.append(r)
                # Добавлять другие типы шагов по мере надобности
            if results:
                return "Откатываю макрос: " + "; ".join(results)
            return "Макрос отменён."

        # open_app → close_app
        if action == "open_app":
            target = item.get("target") or ""
            if target:
                result = self._do_close(target)
                return f"Откатываю: {result}"

        # set_mode → вернуть предыдущий
        if action == "set_mode":
            prev = item.get("prev_value")
            if prev:
                reply = modes.set_mode(prev, self.config)
                self.mode = prev
                return f"Вернул режим: {reply}"

        # change_voice → вернуть предыдущий
        if action == "change_voice":
            prev = item.get("prev_value")
            if prev:
                reply = voices.switch(prev, self.config)
                return f"Вернул голос: {reply}"

        # set_volume → вернуть предыдущее
        if action == "set_volume":
            prev = item.get("prev_value")
            if prev is not None:
                actions.set_volume(int(prev))
                return f"Вернул громкость: {prev}%."

        # set_brightness → вернуть предыдущее
        if action == "set_brightness":
            prev = item.get("prev_value")
            if prev is not None:
                actions.set_brightness(int(prev))
                return f"Вернул яркость: {prev}%."

        # switch_layout → переключить обратно
        if action == "switch_layout":
            actions.switch_layout()
            return "Переключил раскладку обратно."

        return f"Действие «{action}» отменить нельзя."

    def _correction_fast(self, cmd: str) -> str | None:
        """Коррекция: «это не то, я сказал логи».

        Использует self._last_cmd — команду, которую пользователь
        сказал ПЕРЕД этой («это не то»).
        """
        m = re.match(
            r"^(?:это\s+)?не\s+то\s*,?\s*(?:я\s+сказал[а]?\s+)?(.+)$",
            cmd,
        )
        if m:
            right = m.group(1).strip(" ,.:!?")
            if not right:
                return None
            # self._last_cmd — это команда ДО текущей («это не то»).
            # Мы её сохранили в handle() в момент прихода.
            wrong = self._last_cmd
            if wrong and wrong != cmd:
                learning.add_correction(wrong, right)
                return f"Понял, запомнил. Повторяю: {right}."
            return "Что было не так?"

        return None

    def _weather_currency_fast(self, cmd: str) -> str | None:
        """Простые правила для погоды и курса — без LLM."""
        if re.search(r"\bкурс\b|\bвалют", cmd):
            code_map = {
                "доллар": "USD", "доллара": "USD", "бакс": "USD", "бакса": "USD",
                "евро": "EUR",
                "юан": "CNY", "юаня": "CNY",
                "фунт": "GBP", "фунта": "GBP",
                "йен": "JPY", "йены": "JPY",
                "лир": "TRY", "лиры": "TRY",
                "тенге": "KZT",
                "белорусск": "BYN", "бел рубл": "BYN",
                "гривн": "UAH",
            }
            code = ""
            for word, iso in code_map.items():
                if word in cmd:
                    code = iso
                    break
            r = weather.get_currency_rates()
            return weather.describe_currency(r, code=code)

        if re.search(r"\bпогод|\bпрогноз", cmd):
            day = "tomorrow" if "завтра" in cmd else "today"

            m = re.search(r"\bв\s+([а-яёa-z\-]+(?:\s+[а-яёa-z\-]+)?)", cmd)
            city = m.group(1).strip() if m else ""

            if not city:
                city = profile.get("default_city")
            if not city:
                self._pending_question = {
                    "type": "city_for_weather",
                    "day": day,
                    "expires_at": time.time() + 30,
                }
                return "В каком городе узнать погоду?"

            w = weather.get_weather(city, day=day)
            if not w:
                return None
            return weather.describe_weather(w)

        return None

    def _handle_pending_answer(self, cmd: str) -> str:
        pending = self._pending_question
        self._pending_question = None

        if pending.get("type") == "city_for_weather":
            city = cmd.strip()
            words = city.split()

            if not city or len(city) > 60 or len(words) > 3:
                return "Не расслышал город. Повторите, пожалуйста."

            if any(w in city for w in _NOT_A_CITY):
                log.info("pending_question: %r не похоже на город — обрабатываю как команду", city)
                result = self._handle_single(cmd)
                return result if isinstance(result, str) else "Не понял команду."

            profile.set("default_city", city)
            log.info("Запомнил город по умолчанию: %s", city)

            day = pending.get("day", "today")
            w = weather.get_weather(city, day=day)
            if w:
                return f"Запомнил. {weather.describe_weather(w)}"
            return f"Запомнил город «{city}», но погоду узнать не удалось."

        return "Не понял уточнение."

    def _execute_steps(self, steps: list) -> str | None:
        reply = None
        # Кладём макрос как ОДНУ запись в историю — иначе стек на 5
        # быстро забивается, и «отмени» откатит только последний шаг.
        history.push_macro(steps)

        for step in steps[:6]:
            if not isinstance(step, dict):
                continue
            action = step.get("action")
            if action == "wait":
                time.sleep(min(float(step.get("seconds", 1) or 1), 15))
                continue
            if action == "media_key":
                actions.media_key(str(step.get("key", "")), int(step.get("times", 1) or 1))
                continue
            r = self._execute_intent(step)
            if r:
                reply = r
        return reply

    def _execute_intent(self, intent: dict) -> str | None:
        action = intent.get("action")
        target = normalize(str(intent.get("target") or ""))
        query = str(intent.get("query") or "").strip()

        actions_log.info("Интент: %s (target=%r, query=%r)", action, target, query)

        if action == "open_app" and target:
            if intent.get("minimized"):
                hit = find_installed(self.installed, target)
                if hit:
                    actions.open_path(hit[1], minimized=True)
                    return f"Открываю {hit[0]}."
            running = actions.find_process(target, threshold=0.8)
            if running:
                from jarvis.actions import activate_window_by_title
                if activate_window_by_title(target):
                    return f"Переключаюсь на {target}."
            result = self._do_open(target)
            return result
        if action == "close_app" and target:
            return self._do_close(target)
        if action == "open_file":
            return self._open_last_file()

        if action == "open_site" and (target or query):
            site = target or query
            if "." in (intent.get("target") or ""):
                actions.open_url("https://" + str(intent["target"]).strip().lower())
                return f"Открываю {site}."
            return self._open_site(site)
        if action == "search" and (query or target):
            engine = intent.get("engine") if intent.get("engine") in ("google", "youtube", "wiki") else "google"
            q = query or target
            actions.open_search(engine, q)
            return f"Ищу: {q}."

        if action == "screenshot":
            path = actions.take_screenshot()
            self.last_file = path
            return f"Скриншот сохранён в папку {path.parent.name}."

        if action == "open_folder" and target:
            folder = files.resolve_folder(target, explicit=True)
            if folder:
                self.last_folder = folder
                files.open_folder(folder)
                return f"Открываю папку {folder.name}."
            return None
        if action == "list_folder":
            folder = files.resolve_folder(target, explicit=True) if target else self.last_folder
            if folder:
                self.last_folder = folder
                return files.describe_folder(folder)
            return None
        if action == "create_file":
            folder_name = str(intent.get("folder") or "").strip()
            folder = None
            if folder_name:
                folder = files.resolve_folder(folder_name, explicit=True)
                if folder is None:
                    return f"Папку «{folder_name}» не нашёл. Куда создать файл?"
            if folder is None:
                folder = Path.home() / "Desktop"
            path = files.create_file(folder, target or "новый файл")
            self.last_file = path
            return f"Создал {path.name} {self._folder_title(folder)}."

        if action == "type_text":
            text = str(intent.get("text") or intent.get("target") or "").strip()
            ok = actions.type_text(text)
            return f"Печатаю: {text}." if ok else "Не удалось напечатать."

        if action == "media_key":
            ok = actions.media_key(str(intent.get("key", "")),
                                   int(intent.get("times", 1) or 1))
            return "Готово." if ok else None
        if action == "play_pause":
            actions.media_key("play")
            return "Готово."
        if action == "next_track":
            actions.media_key("next")
            return "Переключаю."
        if action == "prev_track":
            actions.media_key("prev")
            return "Возвращаю."
        if action == "volume_up":
            actions.media_key("vol_up", 5)
            return "Громче."
        if action == "volume_down":
            actions.media_key("vol_down", 5)
            return "Тише."
        if action == "mute":
            actions.media_key("mute")
            return "Без звука."

        if action == "switch_layout":
            ok = actions.switch_layout()
            if ok:
                history.push({"action": "switch_layout"})
            return "Переключаю раскладку." if ok else None
        if action == "set_layout_ru":
            ok = actions.set_layout_ru()
            return "Русская раскладка." if ok else None
        if action == "set_layout_en":
            ok = actions.set_layout_en()
            return "Английская раскладка." if ok else None
        if action == "get_layout":
            layout = actions.get_layout()
            if layout == "ru":
                return "Русская раскладка."
            if layout == "en":
                return "Английская раскладка."
            return None

        if action == "set_volume":
            try:
                pct = int(intent.get("percent") or 50)
            except (TypeError, ValueError):
                pct = 50
            prev = actions.get_volume()
            ok = actions.set_volume(pct)
            if ok:
                history.push({"action": "set_volume", "prev_value": prev})
            return f"Громкость: {pct}%." if ok else None
        if action == "get_volume":
            vol = actions.get_volume()
            return f"Громкость: {vol}%." if vol is not None else None

        if action == "set_brightness":
            try:
                pct = int(intent.get("percent") or 50)
            except (TypeError, ValueError):
                pct = 50
            prev = actions.get_brightness()
            ok = actions.set_brightness(pct)
            if ok:
                history.push({"action": "set_brightness", "prev_value": prev})
            return f"Яркость: {pct}%." if ok else None
        if action == "get_brightness":
            br = actions.get_brightness()
            return f"Яркость: {br}%." if br is not None else None

        if action == "clipboard_read":
            text = actions.clipboard_read()
            if not text:
                return "Буфер обмена пуст."
            return f"В буфере: {text[:400]}"

        if action == "copy_selection":
            ok = actions.copy_selection()
            if not ok:
                return "Не удалось скопировать."
            time.sleep(0.15)
            text = actions.clipboard_read()
            if text:
                short = text[:200] + ("..." if len(text) > 200 else "")
                return f"Скопировал: {short}"
            return "Скопировал выделенное."

        if action == "clipboard_copy_last":
            last = self._last_reply
            if not last:
                return "Нечего копировать."
            ok = actions.clipboard_write(last)
            return "Скопировал свой ответ в буфер." if ok else "Не удалось скопировать."

        if action == "clipboard_clear":
            ok = actions.clipboard_clear()
            return "Буфер очищен." if ok else "Не удалось очистить буфер."

        if action == "minimize_all":
            actions.minimize_all()
            return "Сворачиваю всё."
        if action == "minimize_window" and target:
            ok = actions.minimize_window_by_title(target)
            return f"Сворачиваю {target}." if ok else f"Окно {target} не нашёл."
        if action == "maximize_window" and target:
            ok = actions.maximize_window_by_title(target)
            return f"Разворачиваю {target}." if ok else f"Окно {target} не нашёл."
        if action == "activate_window" and target:
            ok = actions.activate_window_by_title(target)
            return f"Переключаюсь на {target}." if ok else f"Окно {target} не нашёл."
        if action == "minimize_active":
            actions.minimize_active()
            return "Сворачиваю активное окно."
        if action == "maximize_active":
            actions.maximize_active()
            return "Разворачиваю активное окно."
        if action == "switch_window":
            actions.switch_window(back=bool(intent.get("back")))
            return "Переключаю окно."

        if action == "set_mode":
            prev_mode = self.mode
            mode = str(intent.get("mode") or "combo").lower()
            if mode not in ("commands", "llm", "combo"):
                mode = "combo"
            reply = modes.set_mode(mode, self.config)
            if mode != prev_mode:
                history.push({"action": "set_mode", "prev_value": prev_mode})
            self.mode = mode
            return reply

        if action == "load_pack":
            name = packs.normalize_name(str(intent.get("name") or ""))
            available = packs.list_available()
            if name not in available:
                return f"Пак '{name}' не найден. Доступны: {', '.join(available)}."
            if name in self.active_packs:
                return f"Пак '{name}' уже активен."
            self.active_packs.append(name)
            packs.save_active(self.active_packs, self.config)
            self._reload_packs()
            return f"Пак '{name}' загружен."
        if action == "unload_pack":
            name = packs.normalize_name(str(intent.get("name") or ""))
            if name not in self.active_packs:
                return f"Пак '{name}' и так не активен."
            self.active_packs.remove(name)
            packs.save_active(self.active_packs, self.config)
            self._reload_packs()
            return f"Пак '{name}' выгружен."
        if action == "list_packs":
            available = packs.list_available()
            active_str = ", ".join(self.active_packs) if self.active_packs else "нет"
            return f"Доступны: {', '.join(available)}. Активны: {active_str}."

        if action == "change_voice":
            prev = voices.current_voice(self.config)
            voice = str(intent.get("voice") or "").strip().lower()
            reply = voices.switch(voice, self.config)
            if voice in voices.PIPER_VOICES and voice != prev:
                history.push({"action": "change_voice", "prev_value": prev})
            return reply
        if action == "list_voices":
            return voices.handle_voice_command("список голосов", self.config)

        if action == "set_timer":
            text = str(intent.get("text") or "").strip()
            seconds = intent.get("seconds")
            time_str = intent.get("time")
            fire_at = None
            if seconds:
                try:
                    fire_at = time.time() + float(seconds)
                except (TypeError, ValueError):
                    fire_at = None
            elif time_str:
                try:
                    hh, mm = str(time_str).split(":")
                    now = datetime.datetime.now()
                    t = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
                    if t <= now:
                        t += datetime.timedelta(days=1)
                    fire_at = t.timestamp()
                except Exception:
                    fire_at = None
            if fire_at:
                timers.add(text, fire_at)
                when = datetime.datetime.fromtimestamp(fire_at).strftime("%H:%M")
                return f"Напомню в {when}: {text}." if text else f"Напомню в {when}."
            return "Не понял время напоминания."
        if action == "list_timers":
            return timers.format_list(timers.list_all())
        if action == "cancel_timers":
            n = timers.remove_all()
            return f"Отменено напоминаний: {n}." if n else "Напоминаний не было."

        if action == "add_task":
            text = str(intent.get("text") or intent.get("task") or "").strip()
            if not text:
                return "Что добавить?"
            task = tasks.add(text)
            return f"Добавил: {task['text']}."
        if action == "list_tasks":
            return tasks.format_list()
        if action == "done_task":
            q = str(intent.get("task") or "").strip()
            task = tasks.mark_done(q)
            return f"Отметил: {task['text']}." if task else f"Задачу «{q}» не нашёл."
        if action == "remove_task":
            q = str(intent.get("task") or "").strip()
            task = tasks.remove(q)
            return f"Убрал: {task['text']}." if task else f"Задачу «{q}» не нашёл."
        if action == "clear_tasks":
            n = tasks.clear_all()
            return f"Очищено задач: {n}." if n else "Список и так пуст."

        if action == "open_config":
            cfg_path = Path(__file__).resolve().parent.parent / "config.json"
            actions.open_path(cfg_path)
            return "Открываю конфиг."
        if action == "open_log":
            log_path = Path(__file__).resolve().parent.parent / "logs" / "jarvis.log"
            actions.open_path(log_path)
            return "Открываю журнал."

        if action == "get_weather":
            city = str(intent.get("target") or "").strip()
            day = "tomorrow" if intent.get("day") == "tomorrow" else "today"

            if any(w in city.lower() for w in _WEATHER_BAD_TARGET):
                log.warning("get_weather: LLM подсунула мусор target=%r — игнорирую", city)
                city = ""

            if not city:
                city = profile.get("default_city")
            if not city:
                self._pending_question = {
                    "type": "city_for_weather",
                    "day": day,
                    "expires_at": time.time() + 30,
                }
                return "В каком городе узнать погоду?"

            w = weather.get_weather(city, day=day)
            if not w:
                return f"Не удалось узнать погоду для «{city}». Проверь название или интернет."
            return weather.describe_weather(w)

        if action == "get_currency":
            code = str(intent.get("target") or "").strip().upper()
            r = weather.get_currency_rates()
            return weather.describe_currency(r, code=code)

        if action == "delete_profile":
            name = str(intent.get("target") or "").strip()
            if profile.delete(name):
                return f"Профиль {name} удалён."
            return f"Профиль {name} не найден или активен."

        if action == "answer" and intent.get("reply"):
            return str(intent["reply"])[:600]

        return None

    def _do_open(self, target: str) -> str:
        if not target:
            return "Что именно открыть?"
        if target in {"его", "ее", "это", "этот файл", "файл", "последний файл"}:
            return self._open_last_file()

        tokens = target.split()
        rest = [t for t in tokens if t not in BROWSER_WORDS]
        if len(rest) < len(tokens):
            if not rest:
                actions.open_browser()
                return "Открываю браузер."
            return self._open_site(" ".join(rest))

        app = find_app(self.apps, target)
        if app:
            spec = app.resolve_open()
            if spec is None:
                return f"{app.title} не найден на этом компьютере."
            actions.run_spec(spec)
            return f"Открываю {app.title}."

        for key, (title, url) in SITES.items():
            if key in target.split() or target == key:
                actions.open_url(url)
                return f"Открываю {title}."

        folder = files.resolve_folder(target, explicit="папк" in target)
        if folder:
            self.last_folder = folder
            files.open_folder(folder)
            return f"Открываю папку {folder.name}."

        game = find_game(self.steam_games, target)
        if game:
            title, appid = game
            actions.run_spec(("uri", f"steam://rungameid/{appid}"))
            return f"Запускаю {title}."

        hit = find_installed(self.installed, target)
        if hit:
            name, lnk = hit
            actions.open_path(lnk)
            return f"Открываю {name}."

        return self._open_site(target)

    def _open_site(self, name: str) -> str:
        if not name:
            return "Какой сайт открыть?"
        for key, (title, url) in SITES.items():
            if name == key or key in name.split():
                actions.open_url(url)
                return f"Открываю {title}."
        url = actions.spoken_domain(name) or actions.guess_site(name)
        if url:
            actions.open_url(url)
            return f"Открываю сайт {name}."
        return f"Сайт {name} не нашёл. Скажите «найди {name}», и я поищу."

    def _open_last_file(self) -> str:
        if self.last_file:
            actions.open_path(self.last_file)
            return "Открываю."
        return "Пока нечего открывать."

    def _do_close(self, target: str) -> str:
        if not target:
            return "Что именно закрыть?"
        if any(w in target for w in ("браузер", "интернет", "хром")):
            return "Закрываю браузер." if actions.close_browser() else "Браузер не запущен."
        app = find_app(self.apps, target)
        if app and app.procs:
            # Генератор, а не список: kill_process вызывается по одному,
            # при первом True — early exit. Не убиваем все процессы подряд.
            ok = any(actions.kill_process(p) for p in app.procs)
            if ok:
                return f"Закрываю {app.title}."
        exe = actions.find_process(target)
        if exe:
            actions.kill_process(exe)
            return f"Закрываю {exe.removesuffix('.exe')}."
        if app:
            return f"{app.title} сейчас не запущен."
        return f"Не нашёл запущенной программы {target}."

    def _match_custom(self, cmd: str) -> str | None:
        for phrases, action, reply in self.custom:
            for phrase in phrases:
                if cmd == phrase or SequenceMatcher(None, cmd, phrase).ratio() >= 0.85:
                    if isinstance(action, list):
                        return self._execute_steps(action) or reply
                    actions.run_spec(actions.spec_from_string(action))
                    return reply
        return None

    def _take_screenshot(self, cmd: str) -> str:
        if re.search(r"откр|покаж", cmd):
            if self.last_file:
                actions.open_path(self.last_file)
                return "Открываю."
            return "Пока нечего открывать."
        path = actions.take_screenshot()
        self.last_file = path
        return f"Скриншот сохранён в папку {path.parent.name}."

    def _load_packs_as_custom(self, config):
        result = []
        for entry in packs.load_active(config):
            phrases = [normalize(p) for p in entry.get("phrases", []) if p.strip()]
            action = entry.get("action", "").strip() or entry.get("steps")
            if phrases and action:
                result.append((phrases, action, entry.get("reply", "Выполняю.")))
        return result

    def _reload_packs(self):
        self.custom = list(self._config_custom_original) + self._load_packs_as_custom(self.config)

    def _folder_title(self, path: Path) -> str:
        return _FOLDER_TITLES.get(path.name, f"в папке {path.name}")

    def _small_talk(self, cmd: str) -> str | None:
        now = datetime.datetime.now()
        if any(p in cmd for p in ("который час", "сколько времени", "время")):
            return f"Сейчас {now.hour} {_hours(now.hour)} {now.minute} {_minutes(now.minute)}."
        if any(p in cmd for p in ("какое число", "какая дата", "какое сегодня число", "дата")):
            return f"Сегодня {now.day} {MONTHS[now.month - 1]} {now.year} года, {WEEKDAYS[now.weekday()]}."
        if "день недели" in cmd or cmd == "какой сегодня день":
            return f"Сегодня {WEEKDAYS[now.weekday()]}."
        if any(p in cmd for p in ("как дела", "как ты", "как настроение")):
            return random.choice([
                "Все системы функционируют нормально.",
                "Отлично, сэр. Готов к работе.",
                "В полном порядке, спасибо.",
                "Работаю в штатном режиме, сэр. А вы как?",
                "Не жалуюсь. Процессор холодный, настроение бодрое.",
                "Всё хорошо, сэр. Чем займёмся?",
                "Как у ассистента: без сбоев и скуки. Слушаю вас.",
            ])
        if any(p in cmd for p in ("кто ты", "ты кто", "представься", "как тебя зовут")):
            return f"Я {APP_NAME}, локальный голосовой ассистент, версия {__version__}."
        if any(p in cmd for p in ("что ты умеешь", "помощь", "что умеешь", "команды")):
            return ("Я умею открывать и закрывать приложения и сайты, делать скриншоты, "
                    "искать в интернете, печатать текст, управлять окнами, ставить "
                    "напоминания, вести списки задач, узнавать погоду и курс валют, "
                    "и отвечать на вопросы.")
        if any(p in cmd for p in ("спасибо", "благодарю")):
            return "Всегда пожалуйста."
        if any(p in cmd for p in ("привет", "здравствуй", "добрый день", "доброе утро", "добрый вечер")):
            name = profile.get("name")
            if name:
                return f"Привет, {name}! Чем могу помочь?"
            return "Привет! Чем могу помочь?"
        if any(p in cmd for p in ("пока", "до свидания", "спокойной ночи")):
            return "До связи."
        return None


def _hours(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "час"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "часа"
    return "часов"


def _minutes(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "минута"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "минуты"
    return "минут"