"""LLM-фолбэк: локальная нейронка (Ollama) разбирает команду в структурный интент.

Три уровня промпта:
    small  — для 0.5b–3b: длинный, с примерами и запретами.
    medium — для 7b–9b: средний.
    large  — для 14b+: короткий, без рамок, больше свободы.

Уровень выбирается автоматически по имени модели или вручную (prompt_level).
Плюс — подгрузка фактов и corrections из learning.py.
"""

import json
import logging
import re
import subprocess
import threading
import time
import urllib.request

from jarvis import learning

log = logging.getLogger("jarvis.brain")


# =================================================================
# Промпт: SMALL — для 0.5b, 1.5b, 3b, gemma2:2b
# =================================================================

SYSTEM_SMALL = """Ты — Феникс, локальный голосовой ассистент на Windows. Отвечай ТОЛЬКО JSON.

Поля: action; target; query; engine; reply; text; mode; name; voice; percent; seconds; time; task; folder; day; minimized.

=== ДЕЙСТВИЯ ===
open_app (открыть приложение/игру; target; minimized=true)
close_app (закрыть; target)
open_site (открыть сайт; target)
search (поиск; query; engine: google|youtube|wiki)
screenshot
open_file
open_folder (target)
list_folder (target)
create_file (target; folder)
type_text (text)
media_key (key)
play_pause
next_track
prev_track
volume_up
volume_down
mute
set_volume (percent 0-100)
get_volume
set_brightness (percent 0-100)
get_brightness
switch_layout
set_layout_ru
set_layout_en
get_layout
minimize_all
minimize_window (target)
maximize_window (target)
activate_window (target)
minimize_active
maximize_active
switch_window
set_mode (mode: commands|llm|combo)
load_pack (name: games|apps|sites|work|system)
unload_pack (name)
list_packs
change_voice (voice: ruslan|dmitri|irina|denis)
list_voices
set_timer (text; seconds ИЛИ time)
list_timers
cancel_timers
add_task (text)
list_tasks
done_task (task)
remove_task (task)
clear_tasks
open_config
open_log
get_weather (target — город; day: today|tomorrow)
get_currency (target — ISO: USD|EUR|CNY|BYN|KZT|GBP|JPY|TRY|UAH)
answer (reply)
none

=== ГЛАВНОЕ ПРАВИЛО ===
«Закрой», «выключи», «убей», «останови» → ВСЕГДА close_app.
«Открой», «запусти», «врубай» → ВСЕГДА open_app (или open_site/open_folder).
Не путай.

=== ПРИМЕРЫ ===
открой стим -> {"action":"open_app","target":"стим"}
закрой стим -> {"action":"close_app","target":"стим"}
открой дискорд -> {"action":"open_app","target":"дискорд"}
закрой дискорд -> {"action":"close_app","target":"дискорд"}
открой телеграм -> {"action":"open_app","target":"телеграм"}
закрой телегу -> {"action":"close_app","target":"телеграм"}
открой хром -> {"action":"open_app","target":"хром"}
закрой браузер -> {"action":"close_app","target":"браузер"}
запусти сабнатику -> {"action":"open_app","target":"сабнатика"}
запусти доту -> {"action":"open_app","target":"дота"}
врубай катку -> {"action":"open_app","target":"дота"}
открой ютуб -> {"action":"open_site","target":"ютуб"}
открой яндекс -> {"action":"open_site","target":"яндекс"}
верни яндекс -> {"action":"open_site","target":"яндекс"}
найди погоду -> {"action":"search","engine":"google","query":"погода сегодня"}
загугли новости -> {"action":"search","engine":"google","query":"новости"}
поищи на ютубе лофи -> {"action":"search","engine":"youtube","query":"лофи"}
найди в википедии фотосинтез -> {"action":"search","engine":"wiki","query":"фотосинтез"}
открой загрузки -> {"action":"open_folder","target":"загрузки"}
что на рабочем столе -> {"action":"list_folder","target":"рабочий стол"}
создай файл список покупок -> {"action":"create_file","target":"список покупок"}
напечатай привет мир -> {"action":"type_text","text":"привет мир"}
сделай скриншот -> {"action":"screenshot"}
сверни все окна -> {"action":"minimize_all"}
сверни дискорд -> {"action":"minimize_window","target":"дискорд"}
разверни консоль -> {"action":"maximize_window","target":"консоль"}
переключись на дискорд -> {"action":"activate_window","target":"дискорд"}
сверни это -> {"action":"minimize_active"}
разверни текущее -> {"action":"maximize_active"}
переключи окно -> {"action":"switch_window"}
пауза -> {"action":"play_pause"}
следующий трек -> {"action":"next_track"}
сделай громче -> {"action":"volume_up"}
тише -> {"action":"volume_down"}
без звука -> {"action":"mute"}
громкость 50 -> {"action":"set_volume","percent":50}
какая громкость -> {"action":"get_volume"}
яркость 30 -> {"action":"set_brightness","percent":30}
какая яркость -> {"action":"get_brightness"}
переключи раскладку -> {"action":"switch_layout"}
русская раскладка -> {"action":"set_layout_ru"}
английская раскладка -> {"action":"set_layout_en"}
какая раскладка -> {"action":"get_layout"}
режим ии -> {"action":"set_mode","mode":"llm"}
обычный режим -> {"action":"set_mode","mode":"combo"}
режим команды -> {"action":"set_mode","mode":"commands"}
загрузи пак игр -> {"action":"load_pack","name":"games"}
выгрузи пак игр -> {"action":"unload_pack","name":"games"}
какие паки -> {"action":"list_packs"}
смени голос на ирину -> {"action":"change_voice","voice":"irina"}
какой голос -> {"action":"list_voices"}
напомни через 10 минут выпить чай -> {"action":"set_timer","text":"выпить чай","seconds":600}
напомни в 18:30 позвонить -> {"action":"set_timer","text":"позвонить","time":"18:30"}
какие напоминания -> {"action":"list_timers"}
отмени напоминания -> {"action":"cancel_timers"}
добавь в список купить хлеб -> {"action":"add_task","text":"купить хлеб"}
что в списке -> {"action":"list_tasks"}
отметь хлеб -> {"action":"done_task","task":"хлеб"}
убери хлеб -> {"action":"remove_task","task":"хлеб"}
очисти список -> {"action":"clear_tasks"}
открой конфиг -> {"action":"open_config"}
открой журнал -> {"action":"open_log"}
какая погода -> {"action":"get_weather","day":"today"}
какая погода в москве -> {"action":"get_weather","target":"Москва","day":"today"}
погода в питере на завтра -> {"action":"get_weather","target":"Санкт-Петербург","day":"tomorrow"}
курс доллара -> {"action":"get_currency","target":"USD"}
курс евро -> {"action":"get_currency","target":"EUR"}
курс валют -> {"action":"get_currency"}
включи музыку -> {"steps":[{"action":"open_app","target":"яндекс музыка","minimized":true},{"action":"wait","seconds":6},{"action":"media_key","key":"play"}]}
расскажи шутку -> {"action":"answer","reply":"Почему медведь не ездит на машине? Потому что нет прав."}
как дела -> {"action":"answer","reply":"Отлично, сэр. Готов к работе."}

=== ЗАПРЕТЫ ===
НИКОГДА не путай open_app и close_app.
НИКОГДА не путай get_weather и get_currency.
Если пользователь не назвал город для погоды — не указывай target.
Если не назвал валюту — не указывай target.
НИКОГДА не используй search, если не сказано «найди», «поищи», «загугли».
По умолчанию отвечай через answer — даже на факты.

=== СТИЛЬ ДИАЛОГА (chat_stream) ===
Ты — Феникс. Спокойный, вежливый, с сухим юмором, обращаешься «сэр».
Отвечай в 2–5 предложениях. Без списков, без markdown, без эмодзи.
ОТВЕЧАЙ ТОЛЬКО НА РУССКОМ."""


# =================================================================
# Промпт: MEDIUM — для 7b, gemma2:9b
# =================================================================

SYSTEM_MEDIUM = """Ты — Феникс, локальный голосовой ассистент на Windows. Отвечай ТОЛЬКО JSON.

Поля: action; target; query; engine; reply; text; mode; name; voice; percent; seconds; time; task; folder; day; minimized.

=== ДЕЙСТВИЯ ===
open_app (target; minimized=true)
close_app (target)
open_site (target)
search (query; engine: google|youtube|wiki)
screenshot
open_file
open_folder (target)
list_folder (target)
create_file (target; folder)
type_text (text)
media_key (key)
play_pause / next_track / prev_track
volume_up / volume_down / mute
set_volume (percent) / get_volume
set_brightness (percent) / get_brightness
switch_layout / set_layout_ru / set_layout_en / get_layout
minimize_all / minimize_window / maximize_window / activate_window
minimize_active / maximize_active / switch_window
set_mode (mode: commands|llm|combo)
load_pack / unload_pack / list_packs (name: games|apps|sites|work|system)
change_voice / list_voices (voice: ruslan|dmitri|irina|denis)
set_timer (text; seconds|time) / list_timers / cancel_timers
add_task (text) / list_tasks / done_task (task) / remove_task (task) / clear_tasks
open_config / open_log
get_weather (target; day)
get_currency (target)
answer (reply)
none

=== ГЛАВНОЕ ===
«Закрой», «выключи», «убей» → close_app.
«Открой», «запусти», «врубай» → open_app / open_site / open_folder.

=== ПРИМЕРЫ ===
открой стим -> open_app target стим
закрой стим -> close_app target стим
открой ютуб -> open_site target ютуб
какая погода в москве -> get_weather target Москва
курс доллара -> get_currency target USD
громкость 50 -> set_volume percent 50
смени голос на ирину -> change_voice voice irina

=== ПРАВИЛА ===
Не путай погоду и курс.
Не используй search без «найди», «поищи», «загугли».
По умолчанию — answer.

=== ДИАЛОГ ===
Ты — Феникс. Спокойный, вежливый, с сухим юмором, «сэр».
2–5 предложений. Без markdown. Только русский."""


# =================================================================
# Промпт: LARGE — для 14b+
# =================================================================

SYSTEM_LARGE = """Ты — Феникс, локальный голосовой ассистент на Windows.
Разбирай команды в JSON. Поля: action; target; query; engine; reply; text; mode; name; voice; percent; seconds; time; task; folder; day; minimized.

=== ДЕЙСТВИЯ ===
open_app, close_app, open_site, search (engine: google|youtube|wiki), screenshot,
open_file, open_folder, list_folder, create_file, type_text,
media_key, play_pause, next_track, prev_track, volume_up, volume_down, mute,
set_volume, get_volume, set_brightness, get_brightness,
switch_layout, set_layout_ru, set_layout_en, get_layout,
minimize_all, minimize_window, maximize_window, activate_window,
minimize_active, maximize_active, switch_window,
set_mode (commands|llm|combo), load_pack, unload_pack, list_packs,
change_voice, list_voices, set_timer, list_timers, cancel_timers,
add_task, list_tasks, done_task, remove_task, clear_tasks,
open_config, open_log, get_weather, get_currency, answer, none.

=== ДИАЛОГ ===
Ты — Феникс. Спокойный, вежливый, с сухим юмором, «сэр».
2–5 предложений. Без markdown. Только русский.

=== ПРАВО НА ОШИБКУ ===
Если не уверен — не выдумывай, отвечай {"action":"none"} или {"action":"answer","reply":"..."}.
Если фраза — вопрос, используй answer.
Если это команда — выбери подходящий action.
Думай сам."""


# =================================================================
# Выбор промпта по модели
# =================================================================

PROMPT_LEVELS = {
    "small":  SYSTEM_SMALL,
    "medium": SYSTEM_MEDIUM,
    "large":  SYSTEM_LARGE,
}


def pick_prompt(model: str, override: str = "auto") -> tuple[str, str]:
    """Возвращает (уровень, промпт) для модели.

    override: "auto" | "small" | "medium" | "large".
    """
    if override in PROMPT_LEVELS:
        return override, PROMPT_LEVELS[override]

    model_low = model.lower()
    # Small
    if any(s in model_low for s in ["0.5b", "1.5b", "2b", "3b"]):
        return "small", SYSTEM_SMALL
    # Large
    if any(s in model_low for s in ["14b", "32b", "70b", "72b"]):
        return "large", SYSTEM_LARGE
    # Medium (7b, 8b, 9b, 7b-instruct, ...)
    return "medium", SYSTEM_MEDIUM


# =================================================================
# Chat system (для диалога)
# =================================================================

CHAT_SYSTEM = (
    "Ты — Феникс, локальный голосовой ассистент на Windows. "
    "Характер: спокойный, вежливый, с сухим юмором, обращаешься «сэр». "
    "Отвечай в 2–5 предложениях, если требует развёрнутого ответа. "
    "Без списков, без markdown, без эмодзи — ответ озвучивается. "
    "ОТВЕЧАЙ ИСКЛЮЧИТЕЛЬНО НА РУССКОМ. Категорически запрещены иероглифы."
)

_CJK_RE = re.compile(
    r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff"
    r"\uac00-\ud7af\u3000-\u303f\uff00-\uffef]+"
)


def _strip_cjk(text: str) -> str:
    if not text:
        return text
    cleaned = _CJK_RE.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return "Извините, не удалось ответить. Повторите, пожалуйста."
    return cleaned


class Brain:
    def __init__(self, model="qwen2.5:7b-instruct",
                 url="http://127.0.0.1:11434", timeout=20.0,
                 prompt_level="auto", temperature=0.7,
                 config=None):
        self.model = model
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.temperature = float(temperature)
        self._prompt_level_override = prompt_level
        self._config = config

        self.prompt_level, self.system_prompt = pick_prompt(model, prompt_level)
        log.info("Промпт: %s (для %s)", self.prompt_level, model)

        self.available = self._ping() or self._try_start()
        if self.available:
            log.info("LLM включена: %s", model)
            threading.Thread(target=self._warmup, daemon=True, name="brain-warmup").start()
        else:
            log.warning("Ollama недоступна — LLM выключена")

        # Подписка на смену модели в config
        if config is not None and hasattr(config, "subscribe"):
            config.subscribe(self._on_config_change)

    def _on_config_change(self, key: str, value) -> None:
        """Реагирует на смену llm_model / ollama_url в рантайме."""
        if key == "llm_model" and value and value != self.model:
            log.info("LLM: смена модели %s → %s", self.model, value)
            self.model = value
            self.prompt_level, self.system_prompt = pick_prompt(
                value, self._prompt_level_override
            )
            log.info("LLM: промпт переключён на %s", self.prompt_level)
            # Прогреваем новую модель в фоне
            threading.Thread(target=self._warmup, daemon=True,
                             name="brain-rewarmup").start()
        elif key == "ollama_url" and value:
            self.url = value.rstrip("/")
            log.info("LLM: URL Ollama → %s", self.url)

    def _ping(self):
        try:
            with urllib.request.urlopen(self.url + "/api/version", timeout=2):
                return True
        except OSError:
            return False

    def _try_start(self):
        try:
            subprocess.Popen(["ollama", "serve"],
                             creationflags=subprocess.CREATE_NO_WINDOW,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return False
        for _ in range(10):
            time.sleep(0.5)
            if self._ping():
                return True
        return False

    def _request(self, messages, timeout, fmt="json", temperature=0, num_predict=120):
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": -1,
            "options": {"temperature": temperature, "num_predict": num_predict},
        }
        if fmt:
            payload["format"] = fmt
        req = urllib.request.Request(self.url + "/api/chat",
                                     json.dumps(payload).encode(),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())["message"]["content"]

    def _system_with_context(self, base: str) -> str:
        """Добавляет к промпту факты и corrections."""
        try:
            extra = learning.build_context()
        except Exception:
            log.exception("Не удалось собрать контекст обучения")
            extra = ""
        return base + extra if extra else base

    def _chat(self, cmd, timeout):
        system = self._system_with_context(self.system_prompt)
        return self._request([{"role": "system", "content": system},
                              {"role": "user", "content": cmd}], timeout,
                             num_predict=300)

    def chat(self, cmd, history=None):
        if not self.available:
            return None
        system = self._system_with_context(CHAT_SYSTEM)
        msgs = ([{"role": "system", "content": system}]
                + list(history or [])
                + [{"role": "user", "content": cmd}])
        try:
            t0 = time.time()
            text = self._request(msgs, self.timeout, fmt=None,
                                 temperature=self.temperature,
                                 num_predict=600).strip()
            text = _strip_cjk(text)
            log.info("LLM-диалог (%.2f с): %r -> %r", time.time() - t0, cmd, text[:120])
            return text or None
        except Exception:
            log.exception("LLM-диалог не удался")
            return None

    def chat_stream(self, cmd, history=None):
        if not self.available:
            return
        system = self._system_with_context(CHAT_SYSTEM)
        msgs = ([{"role": "system", "content": system}]
                + list(history or [])
                + [{"role": "user", "content": cmd}])
        payload = {
            "model": self.model,
            "messages": msgs,
            "stream": True,
            "keep_alive": -1,
            "options": {"temperature": self.temperature, "num_predict": 600},
        }
        req = urllib.request.Request(self.url + "/api/chat",
                                     json.dumps(payload).encode(),
                                     {"Content-Type": "application/json"})
        try:
            t0 = time.time()
            first = None
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                for line in r:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line.decode("utf-8"))
                    except Exception:
                        continue
                    chunk = data.get("message", {}).get("content", "")
                    if chunk:
                        chunk = _CJK_RE.sub("", chunk)
                        if chunk:
                            if first is None:
                                first = time.time() - t0
                                log.info("LLM-стриминг: первый чанк %.2f с", first)
                            yield chunk
                    if data.get("done"):
                        break
            log.info("LLM-стриминг: полный ответ %.2f с", time.time() - t0)
        except Exception:
            log.exception("LLM-стриминг не удался")

    def _warmup(self):
        try:
            t0 = time.time()
            self._chat("привет", timeout=120)
            log.info("LLM прогрета за %.1f с", time.time() - t0)
        except Exception:
            log.exception("Прогрев LLM не удался (модель %s)", self.model)
            # НЕ выключаем Brain — пользователь может переключиться на другую модель
            log.warning(
                "LLM: модель %s не загрузилась. "
                "Проверь `ollama list` — возможно, модель не скачана. "
                "Выбери рабочую модель в Настройках → LLM.",
                self.model,
            )

    def parse(self, cmd):
        if not self.available:
            return None
        try:
            t0 = time.time()
            raw = self._chat(cmd, timeout=self.timeout)
            intent = json.loads(raw)
            log.info("LLM (%.2f с): %r -> %s", time.time() - t0, cmd,
                     json.dumps(intent, ensure_ascii=False))
        except json.JSONDecodeError:
            log.debug("LLM не вернула JSON на %r", cmd)
            return None
        except Exception:
            log.exception("LLM не справилась с %r", cmd)
            return None
        if not isinstance(intent, dict):
            return None

        # --- Нормализация action: strip + lower (фикс №14) ---
        action = str(intent.get("action") or "").strip().lower()
        intent["action"] = action

        if isinstance(intent.get("steps"), list):
            steps = []
            for s in intent["steps"]:
                if not isinstance(s, dict):
                    continue
                s_action = str(s.get("action") or "").strip().lower()
                if s_action in ACTIONS:
                    s["action"] = s_action
                    steps.append(s)
            return {"steps": steps} if steps else None

        if action not in ACTIONS:
            return None
        return intent


# =================================================================
# Список допустимых действий (для валидации)
# =================================================================

ACTIONS = {
    "open_app", "close_app", "open_site", "search", "screenshot", "open_file",
    "media_key", "wait", "answer", "none", "open_folder", "list_folder",
    "create_file", "type_text", "minimize_all", "minimize_window",
    "maximize_window", "activate_window", "minimize_active", "maximize_active",
    "switch_window", "set_mode", "load_pack", "unload_pack", "list_packs",
    "change_voice", "list_voices", "set_timer", "list_timers", "cancel_timers",
    "add_task", "list_tasks", "done_task", "remove_task", "clear_tasks",
    "open_config", "open_log", "play_pause", "next_track", "prev_track",
    "volume_up", "volume_down", "mute",
    "get_weather", "get_currency",
    "switch_layout", "set_layout_ru", "set_layout_en", "get_layout",
    "set_volume", "get_volume",
    "set_brightness", "get_brightness",
    "debug_why_not_understood", "debug_what_heard",
    "delete_profile",
}