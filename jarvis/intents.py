"""Разбор команды: быстрые правила + LLM.

Архитектура LLM-first:
    1. CANCEL — мгновенно.
    2. Быстрая проверка режимов — до LLM.
    3. custom_commands — точное совпадение.
    4. small_talk — время, дата, «как дела».
    5. скриншот — быстро.
    6. Всё остальное — LLM: parse() → интент → _execute_intent().
    7. Если не команда — chat_stream() → диалог (со историей).
"""

import datetime
import logging
import random
import re
import time
from collections import deque
from difflib import SequenceMatcher
from pathlib import Path

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

log = logging.getLogger("jarvis.intents")


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


class IntentHandler:

    def __init__(self, config: dict, apps: list, brain=None):
        self.apps = apps
        self.brain = brain
        self.installed = scan_start_menu()
        self.steam_games = scan_steam_games()
        self.music_app = config.get("music_app", "яндекс музыка")
        self.music_wait = float(config.get("music_wait_sec", 6))
        self.last_file = None
        self.last_folder = None
        self.dialog = deque(maxlen=40)
        for msg in memory.load()[-40:]:
            self.dialog.append(msg)
        self.last_was_chat = False
        self.mode = modes.get_mode(config)
        self.active_packs = list(config.get("active_packs", []))
        self.last_macro = None
        self._reset_requested = False

        self._config_custom_original = []
        for entry in config.get("custom_commands", []):
            phrases = [normalize(p) for p in entry.get("phrases", []) if p.strip()]
            action = entry.get("action", "").strip() or entry.get("steps")
            if phrases and action:
                self._config_custom_original.append(
                    (phrases, action, entry.get("reply", "Выполняю."))
                )
        self.custom = list(self._config_custom_original) + self._load_packs_as_custom(config)

    def handle(self, cmd: str):
        self.last_was_chat = False
        reply = self._handle_single(cmd)

        if hasattr(reply, "__iter__") and not isinstance(reply, str):
            self.dialog.append({"role": "user", "content": cmd})
            return reply

        self.dialog.append({"role": "user", "content": cmd})
        self.dialog.append({"role": "assistant", "content": reply})
        memory.save(list(self.dialog))
        return reply

    def finalize_stream(self, cmd: str, full_text: str) -> None:
        self.dialog.append({"role": "assistant", "content": full_text})
        memory.save(list(self.dialog))

    def _handle_single(self, cmd: str):
        # 1. CANCEL
        if cmd in CANCEL:
            self._reset_requested = True
            return "Жду обращение, сэр."

        # 2. Быстрая проверка режимов — ДО LLM
        if any(w in cmd for w in ("режим", "комбо", "комбинирован")):
            reply, new_mode = modes.handle_mode_command(cmd, self.mode)
            if reply:
                self.mode = new_mode
                return reply

        # 3. Свои команды
        reply = self._match_custom(cmd)
        if reply:
            return reply

        # 4. Small talk
        reply = self._small_talk(cmd)
        if reply:
            return reply

        # 5. Скриншот
        if re.search(r"скрин|снимок экрана", cmd):
            return self._take_screenshot(cmd)

        # 6. Режим «только команды»
        if self.mode == "commands":
            return "Я не понял команду. Скажите «режим ИИ» или добавьте фразу в конфиг."

        # 7. LLM недоступна
        if self.brain is None or not self.brain.available:
            return "LLM недоступна. Скажите «режим команды»."

        # 8. LLM parse → интент
        intent = self.brain.parse(cmd)
        if intent and intent.get("action") not in ("answer", "none"):
            if intent.get("action") == "search" \
                    and not any(v in cmd for v in SEARCH_VERBS):
                return "Сэр, чтобы поискать, скажите «найди» и запрос. Например: «найди погоду»."
            if isinstance(intent.get("steps"), list):
                reply = self._execute_steps(intent["steps"])
            else:
                reply = self._execute_intent(intent)
            if reply:
                return reply

        # 9. LLM вернула answer — но отвечаем через chat_stream (в контексте!)
        if intent and intent.get("action") == "answer":
            gen = self.brain.chat_stream(cmd, list(self.dialog))
            if gen is not None:
                self.last_was_chat = True
                return gen
            if intent.get("reply"):
                return str(intent["reply"])[:600]

        # 10. Диалог (стриминг)
        gen = self.brain.chat_stream(cmd, list(self.dialog))
        if gen is not None:
            self.last_was_chat = True
            return gen
        return "Я не понял команду."

    def _execute_steps(self, steps: list) -> str | None:
        reply = None
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
            return self._do_open(target)
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
            mode = str(intent.get("mode") or "combo").lower()
            if mode not in ("commands", "llm", "combo"):
                mode = "combo"
            reply = modes.set_mode(mode)
            self.mode = mode
            return reply

        if action == "load_pack":
            name = str(intent.get("name") or "").strip().lower()
            available = packs.list_available()
            if name not in available:
                return f"Пак '{name}' не найден. Доступны: {', '.join(available)}."
            if name in self.active_packs:
                return f"Пак '{name}' уже активен."
            self.active_packs.append(name)
            packs.save_active(self.active_packs)
            self._reload_packs()
            return f"Пак '{name}' загружен."
        if action == "unload_pack":
            name = str(intent.get("name") or "").strip().lower()
            if name not in self.active_packs:
                return f"Пак '{name}' и так не активен."
            self.active_packs.remove(name)
            packs.save_active(self.active_packs)
            self._reload_packs()
            return f"Пак '{name}' выгружен."
        if action == "list_packs":
            available = packs.list_available()
            active_str = ", ".join(self.active_packs) if self.active_packs else "нет"
            return f"Доступны: {', '.join(available)}. Активны: {active_str}."

        if action == "change_voice":
            voice = str(intent.get("voice") or "").strip().lower()
            return voices.switch(voice)
        if action == "list_voices":
            return voices.handle_voice_command("список голосов")

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
            log_path = Path(__file__).resolve().parent.parent / "jarvis.log"
            actions.open_path(log_path)
            return "Открываю журнал."

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
            ok = any([actions.kill_process(p) for p in app.procs])
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
        config_copy = {"active_packs": self.active_packs, "custom_commands": []}
        self.custom = list(self._config_custom_original) + self._load_packs_as_custom(config_copy)

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
                    "напоминания, вести списки задач и отвечать на вопросы.")
        if any(p in cmd for p in ("спасибо", "благодарю")):
            return "Всегда пожалуйста."
        if any(p in cmd for p in ("привет", "здравствуй", "добрый день", "доброе утро", "добрый вечер")):
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