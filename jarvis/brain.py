"""LLM-фолбэк: локальная нейронка (Ollama) разбирает команду в структурный интент.
"""

import json
import logging
import re
import subprocess
import threading
import time
import urllib.request

log = logging.getLogger("jarvis.brain")

SYSTEM = """Ты разбираешь команды голосового ассистента на Windows. Отвечай ТОЛЬКО JSON.
Поля: action; target; query; engine (google|youtube|wiki); reply; text; mode; name; voice; seconds; time; task; folder; minimized; day (today|tomorrow).

Действия:
open_app (открыть программу/игру; target; minimized=true — свёрнуто)
close_app (закрыть; target)
open_site (открыть сайт; target — домен или название)
search (поиск; query; engine)
screenshot (скриншот)
open_file (открыть последний файл)
open_folder (открыть папку; target)
list_folder (что в папке; target)
create_file (создать файл; target — имя; folder — папка)
type_text (напечатать; text)
media_key (key: play|next|prev|vol_up|vol_down|mute)
play_pause (пауза/плей)
next_track (следующий трек)
prev_track (предыдущий трек)
volume_up (громче)
volume_down (тише)
mute (без звука)
switch_layout (переключить раскладку)
set_layout_ru (русская раскладка)
set_layout_en (английская раскладка)
get_layout (какая раскладка)
set_volume (громкость в процентах; percent — число 0-100)
get_volume (какая громкость)
set_brightness (яркость в процентах; percent — число 0-100)
get_brightness (какая яркость)
debug_what_heard (что ты слышал — история распознавания)
debug_why_not_understood (почему не понял — диагностика)
minimize_all (свернуть все окна)
minimize_window (свернуть окно; target)
maximize_window (развернуть окно; target)
activate_window (переключиться на окно; target)
minimize_active (свернуть активное)
maximize_active (развернуть активное)
switch_window (переключить окно; back=true — на предыдущее)
set_mode (режим; mode: commands|llm|combo)
load_pack (загрузить пак; name: games|apps|sites|work|system)
unload_pack (выгрузить пак; name)
list_packs (список паков)
change_voice (сменить голос; voice: ruslan|dmitri|irina|denis)
list_voices (список голосов)
set_timer (напоминание; text; seconds ИЛИ time="HH:MM")
list_timers (список напоминаний)
cancel_timers (отменить все напоминания)
add_task (добавить задачу; text)
list_tasks (список задач)
done_task (отметить задачу; task)
remove_task (удалить задачу; task)
clear_tasks (очистить список)
open_config (открыть конфиг)
open_log (открыть лог)
get_weather (погода; target — ТОЛЬКО город в ИМЕНИТЕЛЬНОМ падеже; day: today|tomorrow)
get_currency (курс валют ЦБ РФ; target — ISO-код валюты или пусто)
answer (ответ на вопрос; reply)
none (бессмыслица)

=== ГЛАВНОЕ ПРАВИЛО ===
ЕСЛИ в фразе есть «закрой», «выключи», «убей», «останови» → это ВСЕГДА close_app, НИКОГДА open_app.
ЕСЛИ в фразе есть «открой», «запусти», «врубай» → это open_app (или open_site / open_folder — см. примеры).
Это правило важнее всех остальных. Не путай их.

=== ЗАКРЫТИЕ ПРИЛОЖЕНИЙ (close_app) ===
Используй ТОЛЬКО когда пользователь хочет ЗАКРЫТЬ приложение.
target — название приложения (без .exe).

Примеры:
закрой дискорд -> {"action":"close_app","target":"дискорд"}
закрой стим -> {"action":"close_app","target":"стим"}
закрой телеграм -> {"action":"close_app","target":"телеграм"}
закрой телегу -> {"action":"close_app","target":"телеграм"}
закрой браузер -> {"action":"close_app","target":"браузер"}
закрой хром -> {"action":"close_app","target":"хром"}
закрой игру -> {"action":"close_app","target":"игра"}
закрой калькулятор -> {"action":"close_app","target":"калькулятор"}
закрой блокнот -> {"action":"close_app","target":"блокнот"}
выключи музыку -> {"action":"close_app","target":"музыка"}
останови обс -> {"action":"close_app","target":"обс"}
убей стим -> {"action":"close_app","target":"стим"}
закрой проводник -> {"action":"close_app","target":"проводник"}

=== ОТКРЫТИЕ ПРИЛОЖЕНИЙ (open_app) ===
Используй ТОЛЬКО когда пользователь хочет ОТКРЫТЬ приложение или игру.

Примеры:
открой стим -> {"action":"open_app","target":"стим"}
открой дискорд -> {"action":"open_app","target":"дискорд"}
открой телеграм -> {"action":"open_app","target":"телеграм"}
открой хром -> {"action":"open_app","target":"хром"}
запусти сабнатику -> {"action":"open_app","target":"сабнатика"}
запусти доту -> {"action":"open_app","target":"дота"}
врубай катку -> {"action":"open_app","target":"дота"}
открой блокнот -> {"action":"open_app","target":"блокнот"}
открой калькулятор -> {"action":"open_app","target":"калькулятор"}
верни стим -> {"action":"open_app","target":"стим"}

=== ВАЖНО про set_mode ===
Используй set_mode ТОЛЬКО если пользователь явно говорит:
«режим», «переключись на режим», «включи режим», «смени режим».
НИКОГДА не используй set_mode для слов: «верни», «открой», «покажи», «запусти».

=== ВАЖНО про search vs answer ===
По умолчанию отвечай САМ через answer — даже на вопросы о фактах, объяснения, мнения, советы, шутки.
НИКОГДА не используй search, если пользователь явно не сказал: «найди», «поищи», «загугли», «погугли».
Свежесть данных — НЕ повод для search.

=== ПОГОДА (get_weather) ===
target — ТОЛЬКО НАЗВАНИЕ ГОРОДА в именительном падеже. Если пользователь не назвал город — target НЕ УКАЗЫВАЙ.
Погода — это НЕ search. Даже «найди погоду» → get_weather.

Примеры:
какая погода -> {"action":"get_weather","day":"today"}
какая погода в нижнем новгороде -> {"action":"get_weather","target":"Нижний Новгород","day":"today"}
какая погода в питере -> {"action":"get_weather","target":"Санкт-Петербург","day":"today"}
какая погода в мск -> {"action":"get_weather","target":"Москва","day":"today"}
погода в москве на завтра -> {"action":"get_weather","target":"Москва","day":"tomorrow"}
что по погоде в казани -> {"action":"get_weather","target":"Казань","day":"today"}
погода -> {"action":"get_weather","day":"today"}

=== КУРС ВАЛЮТ (get_currency) ===
target — ISO-код валюты: USD, EUR, CNY, BYN, KZT, GBP, JPY, TRY, UAH.
Если пользователь не назвал валюту — target НЕ УКАЗЫВАЙ.

Примеры:
курс валют -> {"action":"get_currency"}
курс доллара -> {"action":"get_currency","target":"USD"}
курс евро -> {"action":"get_currency","target":"EUR"}
курс юаня -> {"action":"get_currency","target":"CNY"}
курс белорусского рубля -> {"action":"get_currency","target":"BYN"}
курс тенге -> {"action":"get_currency","target":"KZT"}
курс фунта -> {"action":"get_currency","target":"GBP"}
а белорусский рубль -> {"action":"get_currency","target":"BYN"}
сколько стоит доллар -> {"action":"get_currency","target":"USD"}

=== КАТЕГОРИЧЕСКИ ВАЖНО ===
НИКОГДА не путай get_weather и get_currency.
Если пользователь не назвал валюту — target не указывай.
Если пользователь не назвал город — target не указывай.
НИКОГДА не подставляй «курс доллара» в target от get_weather.

=== ВАЖНО про окна ===
- «консоль», «терминал», «cmd» → target: "cmd"
- «браузер» → target: "браузер"
- «телега», «тг» → target: "telegram"
- «дс», «дискорд» → target: "discord"
- «проводник», «папка» → target: "проводник"

=== ВАЖНО про load_pack / unload_pack ===
name — ЛАТИНСКОЕ имя пака: games, apps, sites, work, system.
НЕ ПИШИ «игр» или «игры» — пиши «games».

Примеры:
загрузи пак игр -> {"action":"load_pack","name":"games"}
выгрузи пак игр -> {"action":"unload_pack","name":"games"}
загрузи пак сайтов -> {"action":"load_pack","name":"sites"}
выгрузи пак приложений -> {"action":"unload_pack","name":"apps"}
какие паки -> {"action":"list_packs"}

=== ПРОЧИЕ ПРИМЕРЫ ===
открой ютуб -> {"action":"open_site","target":"ютуб"}
открой яндекс -> {"action":"open_site","target":"яндекс"}
верни яндекс -> {"action":"open_site","target":"яндекс"}
найди погоду -> {"action":"search","engine":"google","query":"погода сегодня"}
загугли новости -> {"action":"search","engine":"google","query":"новости сегодня"}
поищи на ютубе лофи -> {"action":"search","engine":"youtube","query":"лофи"}
найди в википедии фотосинтез -> {"action":"search","engine":"wiki","query":"фотосинтез"}
открой загрузки -> {"action":"open_folder","target":"загрузки"}
что на рабочем столе -> {"action":"list_folder","target":"рабочий стол"}
создай файл список покупок в документах -> {"action":"create_file","target":"список покупок","folder":"документы"}
напечатай привет мир -> {"action":"type_text","text":"привет мир"}
ВАЖНО: «напечатай историю», «напечатай шутку», «напиши стих» — это answer, НЕ type_text.
сделай скриншот -> {"action":"screenshot"}
сверни все окна -> {"action":"minimize_all"}
сверни дискорд -> {"action":"minimize_window","target":"discord"}
разверни консоль -> {"action":"maximize_window","target":"cmd"}
переключись на дискорд -> {"action":"activate_window","target":"discord"}
сверни это -> {"action":"minimize_active"}
разверни текущее -> {"action":"maximize_active"}
переключи окно -> {"action":"switch_window"}
пауза -> {"action":"play_pause"}
следующий трек -> {"action":"next_track"}
сделай громче -> {"action":"volume_up"}
без звука -> {"action":"mute"}
включи музыку -> {"steps":[{"action":"open_app","target":"яндекс музыка","minimized":true},{"action":"wait","seconds":6},{"action":"media_key","key":"play"}]}
переключись на режим команды -> {"action":"set_mode","mode":"commands"}
включи режим ИИ -> {"action":"set_mode","mode":"llm"}
обычный режим -> {"action":"set_mode","mode":"combo"}
смени голос на ирину -> {"action":"change_voice","voice":"irina"}
какой голос -> {"action":"list_voices"}
напомни через 10 минут выпить чай -> {"action":"set_timer","text":"выпить чай","seconds":600}
добавь в список купить хлеб -> {"action":"add_task","text":"купить хлеб"}
что в списке -> {"action":"list_tasks"}
открой конфиг -> {"action":"open_config"}
открой журнал -> {"action":"open_log"}
расскажи шутку -> {"action":"answer","reply":"Почему медведь не ездит на машине? Потому что у него нет водительских прав."}
как дела -> {"action":"answer","reply":"Отлично, сэр. Готов к работе."}
сколько будет два плюс два -> {"action":"answer","reply":"Четыре"}"""

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
}

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
                 url="http://127.0.0.1:11434", timeout=20.0):
        self.model = model
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.available = self._ping() or self._try_start()
        if self.available:
            log.info("LLM-фолбэк включён: %s через Ollama", model)
            threading.Thread(target=self._warmup, daemon=True, name="brain-warmup").start()
        else:
            log.warning("Ollama недоступна — LLM-фолбэк выключен")

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

    def _chat(self, cmd, timeout):
        return self._request([{"role": "system", "content": SYSTEM},
                              {"role": "user", "content": cmd}], timeout,
                             num_predict=300)

    def chat(self, cmd, history=None):
        if not self.available:
            return None
        msgs = ([{"role": "system", "content": CHAT_SYSTEM}]
                + list(history or [])
                + [{"role": "user", "content": cmd}])
        try:
            t0 = time.time()
            text = self._request(msgs, self.timeout, fmt=None,
                                 temperature=0.7, num_predict=600).strip()
            text = _strip_cjk(text)
            log.info("LLM-диалог (%.2f с): %r -> %r", time.time() - t0, cmd, text[:120])
            return text or None
        except Exception:
            log.exception("LLM-диалог не удался")
            return None

    def chat_stream(self, cmd, history=None):
        if not self.available:
            return
        msgs = ([{"role": "system", "content": CHAT_SYSTEM}]
                + list(history or [])
                + [{"role": "user", "content": cmd}])
        payload = {
            "model": self.model,
            "messages": msgs,
            "stream": True,
            "keep_alive": -1,
            "options": {"temperature": 0.7, "num_predict": 600},
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
            log.exception("Прогрев LLM не удался")
            self.available = False

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
        if isinstance(intent.get("steps"), list):
            steps = [s for s in intent["steps"]
                     if isinstance(s, dict) and s.get("action") in ACTIONS]
            return {"steps": steps} if steps else None
        if intent.get("action") not in ACTIONS:
            return None
        return intent