"""Разбор команды (уже без wake-слова) и выбор действия.

ОГЛАВЛЕНИЕ (поиск по Ctrl+F в блокноте):

    # ==== ИМПОРТЫ ====
    # ==== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====
        _is_open_verb / _is_close_verb     — определение глаголов «открой», «закрой»
        _engine_in                         — поисковый движок из фразы
        parse_search                       — «найди X» → (движок, X)
        parse_engine_tail                  — «найди на ютубе X» → (youtube, X)
        normalize                          — нижний регистр, чистка знаков

    # ==== КОНСТАНТЫ ====
        FILLER, BROWSER_WORDS, CANCEL
        SITES     — известные сайты
        MONTHS, WEEKDAYS
        ENGINES   — поисковые движки

    # ==== КЛАСС IntentHandler ====
        __init__                — инициализация
        handle                  — точка входа (разбор цепочек)
        _handle_single          — разбор одной команды
        _execute_steps          — выполнение цепочек шагов
        _execute_intent         — выполнение интента от LLM

    # ==== БЛОКИ ОБРАБОТКИ (внутри класса) ====
        _match_custom           — свои команды из config.json
        _media                  — музыка, громкость, треки
        _music_on               — запуск плеера
        _files                  — создание файлов и папок, содержимое
        _do_open                — открытие приложений/сайтов/папок
        _open_site              — открытие конкретного сайта
        _do_close               — закрытие приложений
        _open_last_file         — «открой его» → последний файл
        _small_talk             — время, дата, «как дела», «привет»

    # ==== ФУНКЦИИ-ХЕЛПЕРЫ (вне класса) ====
        _hours, _minutes        — падежи для «час/часа/часов»
"""

# ============================================================
# ==== ИМПОРТЫ ====
# ============================================================

import datetime
import logging
import random
import re
import threading
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
from jarvis import recorder

log = logging.getLogger("jarvis.intents")


# ============================================================
# ==== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====
# ============================================================

OPEN_STEMS = ("откр", "запус", "включ", "вруб")
CLOSE_STEMS = ("закр", "выключ", "выруб", "заверш", "убей")


def _is_open_verb(tok: str) -> bool:
    """Токен похож на «открой/запусти/включи/вруби»."""
    return any(tok.startswith(s) for s in OPEN_STEMS)


def _is_close_verb(tok: str) -> bool:
    """Токен похож на «закрой/выключи/убей»."""
    return any(tok.startswith(s) for s in CLOSE_STEMS)


def _engine_in(text: str):
    """Возвращает (ключ_движка, как_сказать) или None, если движок не упомянут."""
    for stem, val in ENGINES.items():
        if stem in text:
            return val
    return None


# ============================================================
# ==== КОНСТАНТЫ ====
# ============================================================

FILLER = {"пожалуйста", "мне", "ка", "давай", "быстро", "срочно", "будь", "добр",
          "в", "на", "и", "а", "но", "ну", "от", "до", "же", "бы", "то", "это", "там",
          "игру", "игра", "приложение", "программу", "программа"}

BROWSER_WORDS = {"браузер", "браузере", "браузером", "хром", "хроме", "интернет", "интернете"}

CANCEL = {"отмена", "стоп", "стой", "хватит", "замолчи", "ничего", "забудь", "отбой"}

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

ENGINES = {
    "ютуб": ("youtube", "на Ютубе"),
    "youtube": ("youtube", "на Ютубе"),
    "википеди": ("wiki", "в Википедии"),
    "вики": ("wiki", "в Википедии"),
    "гугл": ("google", "в Гугле"),
    "интернет": ("google", "в интернете"),
}


# ============================================================
# ==== ПОИСК: «найди X», «найди на ютубе X» ====
# ============================================================

def parse_search(cmd: str):
    """Понимает: «найди X», «поищи на ютубе X», «загугли X».

    Возвращает (движок, 'где_сказать', запрос) или None.
    """
    m = re.search(r"\bпоиск\w*\s+(.+)$", cmd)
    if m:
        engine = _engine_in(cmd[:m.start()]) or ENGINES["гугл"]
        return (*engine, m.group(1).strip())

    m = re.match(r"^(?:найди|поищи|ищи|загугли|погугли)\s+(.+)$", cmd)
    if not m:
        return None
    rest = m.group(1).strip()
    m2 = re.match(r"^(?:в|на)\s+(\S+)\s+(.+)$", rest)
    if m2 and _engine_in(m2.group(1)):
        return (*_engine_in(m2.group(1)), m2.group(2).strip())
    m3 = re.match(r"^(.+?)\s+(?:в|на)\s+(\S+)$", rest)
    if m3 and _engine_in(m3.group(2)):
        return (*_engine_in(m3.group(2)), m3.group(1).strip())
    return (*ENGINES["гугл"], rest)


def parse_engine_tail(cmd: str):
    """Движок с запросом в любом порядке: «открой на ютубе видео котиков»."""
    tokens = cmd.split()
    for i, tok in enumerate(tokens):
        engine = _engine_in(tok)
        if not engine:
            continue
        query = " ".join(t for t in tokens[i + 1:] if t not in FILLER)
        if query:
            return (*engine, query)
        query = " ".join(
            t for t in tokens[:i]
            if t not in FILLER and not _is_open_verb(t) and not _is_close_verb(t)
        )
        if query:
            return (*engine, query)
    return None


def normalize(text: str) -> str:
    """Нижний регистр, ё→е, чистка знаков, схлопывание пробелов."""
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ============================================================
# ==== КЛАСС IntentHandler ====
# ============================================================

class IntentHandler:

    # --------------------------------------------------------
    # Инициализация
    # --------------------------------------------------------

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
        # подгружаем память с диска
        for msg in memory.load()[-40:]:
            self.dialog.append(msg)
        self.last_was_chat = False
        self.mode = modes.get_mode(config)
        self.active_packs = list(config.get("active_packs", []))
        self.last_macro = None
        self._reset_requested = False
        self.custom = []
        self.custom.extend(self._load_packs_as_custom(config))
        for entry in config.get("custom_commands", []):
            phrases = [normalize(p) for p in entry.get("phrases", []) if p.strip()]
            action = entry.get("action", "").strip() or entry.get("steps")
            if phrases and action:
                self.custom.append((phrases, action, entry.get("reply", "Выполняю.")))

    # --------------------------------------------------------
    # Разбор цепочек: «сделай скриншот и открой его»
    # --------------------------------------------------------

    _CHAIN_SEP = re.compile(r"\s+(?:а\s+)?(?:и|потом|затем|после этого)\s+")
    _CHAIN_STARTERS = {"сделай", "сними", "найди", "поищи", "загугли", "погугли",
                       "скажи", "поставь", "переключи", "покажи", "создай", "посмотри"}
    _CHAIN_SINGLES = {"пауза", "плей", "стоп", "скриншот", "громче", "тише",
                      "погромче", "потише", "дальше"}

    def _split_chain(self, cmd: str) -> list[str]:
        """Делит «сделай X и сделай Y» на шаги. Если не похоже — возвращает [cmd]."""
        parts = [p.strip() for p in self._CHAIN_SEP.split(cmd) if p.strip()]
        if len(parts) < 2:
            return [cmd]
        for part in parts:
            if len(part.split()) == 1 and part not in self._CHAIN_SINGLES:
                return [cmd]
        for part in parts[1:]:
            first = part.split()[0]
            if not (_is_open_verb(first) or _is_close_verb(first)
                    or first in self._CHAIN_STARTERS
                    or part in self._CHAIN_SINGLES or "скрин" in first):
                return [cmd]
        return parts

    # --------------------------------------------------------
    # Точка входа: разбирает фразу, возвращает ответ
    # --------------------------------------------------------

    def handle(self, cmd: str):
        """Возвращает строку (обычная команда) или генератор (стриминг LLM).

        Память диалога сохраняется:
        - для строки — здесь, сразу;
        - для генератора — в main.py, после speak_stream.
        """
        self.last_was_chat = False
        parts = self._split_chain(cmd)
        if len(parts) > 1:
            log.info("Цепочка из %d шагов: %s", len(parts), parts)
            replies = [self._handle_single(p) for p in parts]
            reply = " ".join(r for r in replies if r)
        else:
            reply = self._handle_single(cmd)

        # если это генератор (стриминг) — память сохранит main.py
        if hasattr(reply, "__iter__") and not isinstance(reply, str):
            self.dialog.append({"role": "user", "content": cmd})
            # ответ допишет main.py после стриминга
            return reply

        # обычная строка — сохраняем память здесь
        self.dialog.append({"role": "user", "content": cmd})
        self.dialog.append({"role": "assistant", "content": reply})
        memory.save(list(self.dialog))
        return reply

    def finalize_stream(self, cmd: str, full_text: str) -> None:
        """Вызывается main.py после speak_stream: дописывает ответ в память."""
        self.dialog.append({"role": "assistant", "content": full_text})
        memory.save(list(self.dialog))

    # --------------------------------------------------------
    # Разбор одной команды (главный диспетчер)
    # --------------------------------------------------------

    def _handle_single(self, cmd: str) -> str:
        if cmd in CANCEL:
            # сигнал main.py: закрыть окно диалога
            self._reset_requested = True
            return "Жду обращение, сэр."

        # --- режимы работы ---
        reply, new_mode = modes.handle_mode_command(cmd, self.mode)
        if reply:
            self.mode = new_mode
            return reply

        # --- паки ---
        reply, new_active = packs.handle_pack_command(cmd, self.active_packs)
        if reply:
            self.active_packs = new_active
            config_copy = {"active_packs": new_active, "custom_commands": []}
            self.custom = [c for c in self.custom if c not in self._load_packs_as_custom({"active_packs": [], "custom_commands": []})]
            self.custom.extend(self._load_packs_as_custom(config_copy))
            return reply

        # --- память диалога ---
        reply, clear_flag = memory.handle_memory_command(cmd, list(self.dialog))
        if reply:
            if clear_flag:
                self.dialog.clear()
            return reply

        # --- голоса ---
        reply = voices.handle_voice_command(cmd)
        if reply:
            return reply

        # --- запись действий ---
        if re.search(r"(запиши|начни запись)\s*(действие|действий|макрос)?", cmd):
            if recorder.start():
                return "Записываю. Скажите «стоп запись», когда закончите."
            return "Не удалось начать запись. Проверьте права администратора."

        if re.search(r"(стоп|останови|закончи|прекрати)\s*(запись|действие|макрос)", cmd):
            if recorder.is_recording():
                macro = recorder.stop()
                if macro:
                    self.last_macro = macro
                    return "Запись остановлена. " + recorder.describe(macro)
                return "Запись была пустой."

        if re.search(r"(повтори|воспроизведи)\s*(последн|это|макрос)", cmd) \
                or cmd in {"повтори", "повтори последнее", "воспроизведи"}:
            if self.last_macro:
                if recorder.play(self.last_macro):
                    return "Воспроизвожу макрос."
                return "Не удалось воспроизвести."
            return "Нет сохранённого макроса."

        # --- режим «только LLM»: пропускаем правила, кроме скриншота ---
        if self.mode == "llm":
            if re.search(r"скрин|снимок экрана", cmd):
                path = actions.take_screenshot()
                self.last_file = path
                return f"Скриншот сохранён в папку {path.parent.name}."
            if self.brain is not None and self.brain.available:
                intent = self.brain.parse(cmd)
                if intent and intent.get("action") not in ("answer", "none"):
                    if isinstance(intent.get("steps"), list):
                        r = self._execute_steps(intent["steps"])
                    else:
                        r = self._execute_intent(intent)
                    if r:
                        return r
                text = self.brain.chat(cmd, list(self.dialog))
                if text:
                    self.last_was_chat = True
                    return text
            return "LLM недоступна. Скажите «режим команды»."

        # --- свои команды из config.json ---
        reply = self._match_custom(cmd)
        if reply:
            return reply

        # --- медиа ---
        reply = self._media(cmd)
        if reply:
            return reply

        # --- файлы ---
        reply = self._files(cmd)
        if reply:
            return reply

        # --- печать в активное окно ---
        m = re.match(r"^(?:напечатай|напиши|введи|набери)\s+(.+)$", cmd)
        if m:
            text = m.group(1).strip()
            actions.type_text(text)
            return f"Печатаю: {text}."

        # --- свернуть ВСЁ (проверять ДО именованных окон) ---
        if re.search(r"(сверни|свернуть|убери)\s+(вс[её]|все окна|рабочий стол)", cmd) \
                or cmd in {"покажи рабочий стол", "сверни все окна", "сверни всё", "сверни все"}:
            actions.minimize_all()
            return "Сворачиваю всё."

        # --- относительные окна: активное ---
        if re.search(r"^сверни\s+(это|текущ|активн)", cmd) or cmd in {"сверни окно", "сверни"}:
            actions.minimize_active()
            return "Сворачиваю активное окно."

        if re.search(r"^(разверни|развернуть)\s+(это|текущ|активн)", cmd) \
                or cmd in {"разверни окно", "разверни"}:
            actions.maximize_active()
            return "Разворачиваю активное окно."

        # --- переключение окон ---
        if re.search(r"^(переключи|смени|следующ\w*)\s+(окно|вкладк)", cmd) \
                or cmd in {"переключи окно", "следующее окно", "дальше окно"}:
            actions.switch_window(back=False)
            return "Переключаю окно."

        if re.search(r"^(предыдущ\w*|назад)\s+(окно|вкладк)", cmd) \
                or cmd in {"предыдущее окно", "назад окно"}:
            actions.switch_window(back=True)
            return "Возвращаю окно."

        # --- свернуть/развернуть именованное окно ---
        # Если не нашли — не возвращаем ошибку, падаем в LLM ниже.
        m = re.match(r"^(сверни|разверни|развернуть|свернуть)\s+(.+)$", cmd)
        if m:
            verb, name = m.group(1), m.group(2).strip()
            if verb.startswith("сверн"):
                if actions.minimize_window_by_title(name):
                    return f"Сворачиваю {name}."
            else:
                if actions.maximize_window_by_title(name):
                    return f"Разворачиваю {name}."

        # --- переключиться на окно ---
        m = re.match(r"^(переключись|перейди)\s+(?:на\s+)?(.+)$", cmd)
        if m:
            name = m.group(2).strip()
            if actions.activate_window_by_title(name):
                return f"Переключаюсь на {name}."

        # --- скриншот ---
        if re.search(r"скрин|снимок экрана", cmd):
            tokens_ = cmd.split()
            has_open = any(_is_open_verb(t) or t == "покажи" for t in tokens_)
            has_make = any(t.startswith(("сдела", "сним", "щелк")) for t in tokens_)
            if has_open and not has_make:
                return self._open_last_file()
            path = actions.take_screenshot()
            self.last_file = path
            if has_open:
                self._open_last_file()
                return "Скриншот сделан, открываю."
            return f"Скриншот сохранён в папку {path.parent.name}."

        # --- поиск в интернете (только по явному «найди»/«загугли») ---
        search = parse_search(cmd) or parse_engine_tail(cmd)
        if search:
            engine, where, query = search
            actions.open_search(engine, query)
            return f"Ищу {where}: {query}."

        # --- открыть/закрыть ---
        tokens = [t for t in cmd.split() if t not in FILLER]
        verb_open = any(_is_open_verb(t) for t in tokens)
        verb_close = any(_is_close_verb(t) for t in tokens)
        target = " ".join(t for t in tokens if not _is_open_verb(t) and not _is_close_verb(t))

        if verb_open:
            return self._do_open(target)
        if verb_close:
            return self._do_close(target)

        # --- простые вопросы (время, дата, «как дела») ---
        reply = self._small_talk(cmd)
        if reply:
            return reply

        # --- режим «только команды»: LLM не вызываем ---
        if self.mode == "commands":
            return "Я не понял команду. Скажите, например: открой стим."

                # --- LLM ---
        if self.brain is not None and self.brain.available:
            intent = self.brain.parse(cmd)
            if intent and intent.get("action") not in ("answer", "none"):
                if isinstance(intent.get("steps"), list):
                    reply = self._execute_steps(intent["steps"])
                else:
                    reply = self._execute_intent(intent)
                if reply:
                    return reply
            # СТРИМИНГ: возвращаем генератор, main.py его озвучит через speak_stream
            gen = self.brain.chat_stream(cmd, list(self.dialog))
            if gen is not None:
                self.last_was_chat = True
                return gen  # ← генератор, не строка
        return "Я не понял команду. Скажите, например: открой стим."

    # --------------------------------------------------------
    # Выполнение цепочек и интентов от LLM
    # --------------------------------------------------------

    def _execute_steps(self, steps: list) -> str | None:
        """Выполняет цепочку шагов (от LLM или из custom_commands)."""
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
        """Выполняет интент от LLM средствами обычного пайплайна."""
        action = intent.get("action")
        target = normalize(str(intent.get("target") or ""))
        query = str(intent.get("query") or "").strip()

        if action == "open_app" and target:
            if intent.get("minimized"):
                hit = find_installed(self.installed, target)
                if hit:
                    actions.open_path(hit[1], minimized=True)
                    return f"Открываю {hit[0]}."
            return self._do_open(target)
        if action == "open_file":
            return self._open_last_file()
        if action == "media_key":
            ok = actions.media_key(str(intent.get("key", "")),
                                   int(intent.get("times", 1) or 1))
            return "Готово." if ok else None
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
            folder = files.resolve_folder(str(intent.get("folder") or ""), explicit=True) \
                or Path.home() / "Desktop"
            path = files.create_file(folder, target or "новый файл")
            self.last_file = path
            return f"Создал {path.name} {self._folder_title(folder)}."
        if action == "close_app" and target:
            return self._do_close(target)
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
        if action == "answer" and intent.get("reply"):
            return str(intent["reply"])[:600]
        if action == "type_text":
            text = str(intent.get("text") or intent.get("target") or "").strip()
            ok = actions.type_text(text)
            return f"Печатаю: {text}." if ok else "Не удалось напечатать."
        if action == "minimize_all":
            ok = actions.minimize_all()
            return "Сворачиваю всё." if ok else None
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
        return None

    # ========================================================
    # БЛОК: СВОИ КОМАНДЫ ИЗ CONFIG.JSON
    # ========================================================

    def _match_custom(self, cmd: str) -> str | None:
        """Ищет совпадение в custom_commands (точное или ≥0.85 по ratio)."""
        for phrases, action, reply in self.custom:
            for phrase in phrases:
                if cmd == phrase or SequenceMatcher(None, cmd, phrase).ratio() >= 0.85:
                    if isinstance(action, list):
                        return self._execute_steps(action) or reply
                    actions.run_spec(actions.spec_from_string(action))
                    return reply
        return None

    # ========================================================
    # БЛОК: МЕДИА (музыка, громкость, треки)
    # ========================================================

    def _media(self, cmd: str) -> str | None:
        """Музыка, пауза, треки, громкость. Возвращает ответ или None."""
        musicy = re.search(r"музык|трек|песн|волн", cmd) is not None
        if "пауз" in cmd or (musicy and re.search(r"выключ|выруб|останов|стоп", cmd)):
            actions.media_key("play")
            return "Пауза."
        if cmd in {"продолжи", "продолжить", "плей", "играй", "стоп"}:
            actions.media_key("play")
            return "Готово."
        if musicy and re.search(r"включ|вруб|постав|запуст|играй|сыграй", cmd):
            return self._music_on()
        if re.search(r"следующ|некст", cmd) and musicy or cmd == "дальше":
            actions.media_key("next")
            return "Переключаю."
        if re.search(r"предыдущ", cmd) and musicy:
            actions.media_key("prev")
            return "Возвращаю."
        if re.search(r"^(сделай\s+)?(по)?громче$", cmd) or "громкость выше" in cmd:
            actions.media_key("vol_up", 5)
            return "Громче."
        if re.search(r"^(сделай\s+)?(по)?тише$", cmd) or "громкость ниже" in cmd:
            actions.media_key("vol_down", 5)
            return "Тише."
        if re.search(r"без звука|отключи звук|мьют", cmd):
            actions.media_key("mute")
            return "Без звука."
        return None

    def _music_on(self) -> str:
        """Запускает плеер и жмёт play (или открывает веб-версию)."""
        if actions.find_process(self.music_app, threshold=0.8):
            actions.ensure_music_playing()
            return "Включаю."
        hit = find_installed(self.installed, self.music_app)
        if hit:
            name, lnk = hit
            actions.open_path(lnk)
            threading.Timer(self.music_wait, actions.ensure_music_playing).start()
            threading.Timer(self.music_wait + 3,
                            actions.minimize_window, args=(name,)).start()
            return "Включаю музыку."
        actions.open_url("https://music.yandex.ru/personal/my-wave")
        return "Плеер не найден, открываю Мою волну в браузере."

    # ========================================================
    # БЛОК: ФАЙЛЫ И ПАПКИ
    # ========================================================

    _FOLDER_TITLES = {"Desktop": "на рабочем столе", "Downloads": "в загрузках",
                      "Documents": "в документах", "Pictures": "в изображениях",
                      "Music": "в музыке", "Videos": "в видео",
                      "Screenshots": "в скриншотах"}

    def _folder_title(self, path: Path) -> str:
        """«на рабочем столе», «в документах» и т.п. для озвучки."""
        return self._FOLDER_TITLES.get(path.name, f"в папке {path.name}")

    def _files(self, cmd: str) -> str | None:
        """Создание файлов/папок и «что лежит в …»."""
        m = re.match(r"^созда\w*\s+(файл|папку|документ|заметку)\s*(.*)$", cmd)
        if m:
            kind, rest = m.group(1), m.group(2)
            folder = files.resolve_folder(rest, explicit=True) or Path.home() / "Desktop"
            ext = ".txt"
            name_tokens = []
            for t in rest.split():
                if t in {"в", "на", "папке", "папку", "моем", "новый", "новую"}:
                    continue
                if files.resolve_folder(t, explicit=True):
                    continue
                hit_ext = next((e for s, e in files._EXT_WORDS.items() if t.startswith(s)), None)
                if hit_ext and kind in ("файл", "документ"):
                    ext = hit_ext
                    continue
                name_tokens.append(t)
            name = " ".join(name_tokens)
            if kind == "папку":
                path = files.create_folder(folder, name or "новая папка")
                self.last_folder = path
            else:
                if kind == "заметку":
                    name = name or "заметка"
                path = files.create_file(folder, name or "новый файл", ext)
                self.last_file = path
            return f"Создал {path.name} {self._folder_title(folder)}."

        if re.match(r"^(что|чего)\s+(лежит\s+|есть\s+|находится\s+)?(в|на|внутри|там)", cmd) \
                or "содержимое" in cmd:
            if re.search(r"в ней|в нем|там|внутри$", cmd) and self.last_folder:
                return files.describe_folder(self.last_folder)
            folder = files.resolve_folder(cmd, explicit=True)
            if folder:
                self.last_folder = folder
                return files.describe_folder(folder)
            return "Какую папку посмотреть?"
        return None

    # ========================================================
    # БЛОК: ОТКРЫТИЕ (приложения, сайты, папки)
    # ========================================================

    def _open_last_file(self) -> str:
        """«Открой его» → последний созданный/скриншотный файл."""
        if self.last_file:
            actions.open_path(self.last_file)
            return "Открываю."
        return "Пока нечего открывать."

    def _do_open(self, target: str) -> str:
        """Открывает приложение, игру, сайт или папку по названию."""
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

        site_only = bool(re.match(r"^(сайт|ссылк|страниц)", target))
        site_target = re.sub(r"^(сайт\w*|ссылку|ссылка|страницу)\s*(на)?\s*", "", target).strip() or target
        if site_only:
            return self._open_site(site_target)

        # 1. Встроенный каталог приложений
        app = find_app(self.apps, target)
        if app:
            spec = app.resolve_open()
            if spec is None:
                return f"{app.title} не найден на этом компьютере. Укажите путь в конфиге."
            actions.run_spec(spec)
            return f"Открываю {app.title}."

        # 2. Известные сайты
        for key, (title, url) in SITES.items():
            if key in target.split() or target == key:
                actions.open_url(url)
                return f"Открываю {title}."

        # 3. Папки пользователя
        folder = files.resolve_folder(target, explicit="папк" in target)
        if folder:
            self.last_folder = folder
            files.open_folder(folder)
            return f"Открываю папку {folder.name}."

        # 4. Игры Steam
        game = find_game(self.steam_games, target)
        if game:
            title, appid = game
            actions.run_spec(("uri", f"steam://rungameid/{appid}"))
            return f"Запускаю {title}."

        # 5. Любая установленная программа из меню «Пуск»
        hit = find_installed(self.installed, target)
        if hit:
            name, lnk = hit
            actions.open_path(lnk)
            return f"Открываю {name}."

        # 6. Не нашли — пробуем как сайт
        return self._open_site(target)

    def _open_site(self, name: str) -> str:
        """Открывает сайт: из известных, по домену, или говорит «не нашёл»."""
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

    # ========================================================
    # БЛОК: ЗАКРЫТИЕ
    # ========================================================

    def _do_close(self, target: str) -> str:
        """Закрывает приложение или браузер по названию."""
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

    # ========================================================
    # БЛОК: SMALL TALK (время, дата, «как дела»)
    # ========================================================

    def _load_packs_as_custom(self, config):
        """Загружает активные паки в формате custom_commands."""
        result = []
        for entry in packs.load_active(config):
            phrases = [normalize(p) for p in entry.get("phrases", []) if p.strip()]
            action = entry.get("action", "").strip() or entry.get("steps")
            if phrases and action:
                result.append((phrases, action, entry.get("reply", "Выполняю.")))
        return result

    def _small_talk(self, cmd: str) -> str | None:
        """Простые вопросы: время, дата, «как дела», «привет»."""
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
                    "искать в интернете, печатать текст, управлять окнами и отвечать "
                    "на вопросы. Свои команды можно добавить в конфиг.")
        if any(p in cmd for p in ("спасибо", "благодарю")):
            return "Всегда пожалуйста."
        if any(p in cmd for p in ("привет", "здравствуй", "добрый день", "доброе утро", "добрый вечер")):
            return "Привет! Чем могу помочь?"
        if any(p in cmd for p in ("пока", "до свидания", "спокойной ночи")):
            return "До связи."
        return None


# ============================================================
# ==== ФУНКЦИИ-ХЕЛПЕРЫ (вне класса) ====
# ============================================================

def _hours(n: int) -> str:
    """Падеж для часов: 1 час, 2 часа, 5 часов."""
    if n % 10 == 1 and n % 100 != 11:
        return "час"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "часа"
    return "часов"


def _minutes(n: int) -> str:
    """Падеж для минут: 1 минута, 2 минуты, 5 минут."""
    if n % 10 == 1 and n % 100 != 11:
        return "минута"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "минуты"
    return "минут"