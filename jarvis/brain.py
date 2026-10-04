"""LLM-фолбэк: локальная нейронка (Ollama) разбирает команду в структурный интент.

Плюс streaming: chat_stream() отдаёт ответ по кускам (для streaming TTS).
"""

import json
import logging
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
get_weather (узнать погоду; target — название города В ИМЕНИТЕЛЬНОМ ПАДЕЖЕ; day: today|tomorrow)
get_currency (курс валют ЦБ РФ; target — ISO-код валюты или пусто)
answer (ответ на вопрос; reply)
none (бессмыслица)

ВАЖНО про set_mode:
Используй set_mode ТОЛЬКО если пользователь явно говорит:
«режим», «переключись на режим», «включи режим», «смени режим», «переключись на комбинированный».
НИКОГДА не используй set_mode для слов: «верни», «открой», «покажи», «запусти», «включи музыку».

ВАЖНО про search vs answer:
По умолчанию отвечай САМ через answer — даже на вопросы о фактах, объяснения, мнения, советы, шутки, историю.
НИКОГДА не используй search, если пользователь явно не сказал: «найди», «поищи», «ищи», «загугли», «погугли», «поиск».
Свежесть данных — НЕ повод для search, если глагола поиска нет.

ВАЖНО про погоду:
Для погоды используй get_weather, НЕ search. Даже если пользователь говорит «найди погоду» — это get_weather.
target — название города в ИМЕНИТЕЛЬНОМ падеже (как в справочнике).
Примеры нормализации:
  «в нижнем новгороде» → target: "Нижний Новгород"
  «в питере» → target: "Санкт-Петербург"
  «в мск» → target: "Москва"
  «в екб» → target: "Екатеринбург"
  «в нижнем» (если контекст понятен) → target: "Нижний Новгород"
Если город не назван — не указывай target. Ассистент сам спросит или возьмёт из профиля.
Если day не указан — оставь today. «на завтра» → day: tomorrow.

ВАЖНО про курс валют:
Для курса используй get_currency, НЕ search.
target — это ISO-код валюты (USD, EUR, CNY, BYN, KZT, UAH, GBP, JPY, TRY, ...).
Примеры нормализации:
  «курс доллара» → target: "USD"
  «курс евро» → target: "EUR"
  «курс юаня» → target: "CNY"
  «курс белорусского рубля» → target: "BYN"
  «курс тенге» → target: "KZT"
  «курс фунта» → target: "GBP"
  «курс лиры» → target: "TRY"
  «курс валют» (без конкретной) → target не указывай.
Если пользователь называет валюту — ОБЯЗАТЕЛЬНО ставь target с ISO-кодом.
Если не уверен в коде — не указывай target.

ВАЖНО про окна:
- «консоль», «терминал», «командная строка», «cmd» → target: "cmd"
- «браузер» → target: "браузер"
- «телега», «тг» → target: "telegram"
- «дс», «дискорд» → target: "discord"
- «проводник», «папка» → target: "проводник"
- «настройки», «параметры» → target: "настройки"

Примеры:
открой стим -> {"action":"open_app","target":"стим"}
открой стимул -> {"action":"open_app","target":"steam"}
запусти сабнатику -> {"action":"open_app","target":"сабнатика"}
закрой дискорд -> {"action":"close_app","target":"дискорд"}
открой ютуб -> {"action":"open_site","target":"ютуб"}
открой яндекс -> {"action":"open_site","target":"яндекс"}
открой хабр точка ру -> {"action":"open_site","target":"habr.ru"}
верни яндекс -> {"action":"open_site","target":"яндекс"}
верни ютуб -> {"action":"open_site","target":"ютуб"}
верни стим -> {"action":"open_app","target":"стим"}
верни вк -> {"action":"open_site","target":"вк"}
найди погоду -> {"action":"search","engine":"google","query":"погода сегодня"}
загугли новости -> {"action":"search","engine":"google","query":"новости сегодня"}
поищи на ютубе лофи -> {"action":"search","engine":"youtube","query":"лофи"}
найди в википедии фотосинтез -> {"action":"search","engine":"wiki","query":"фотосинтез"}
открой загрузки -> {"action":"open_folder","target":"загрузки"}
что на рабочем столе -> {"action":"list_folder","target":"рабочий стол"}
создай файл список покупок в документах -> {"action":"create_file","target":"список покупок","folder":"документы"}
напечатай привет мир -> {"action":"type_text","text":"привет мир"}
ВАЖНО: «напечатай историю», «напечатай шутку», «напиши стих», «напечатай факт» — это answer, НЕ type_text. Пользователь хочет, чтобы ты СОЧИНИЛ текст. type_text — только когда пользователь ДИКТУЕТ конкретный текст: «напечатай привет мир», «напиши яблоко».
сделай скриншот -> {"action":"screenshot"}
сделай скриншот и открой его -> {"steps":[{"action":"screenshot"},{"action":"open_file"}]}
сверни все окна -> {"action":"minimize_all"}
сверни дискорд -> {"action":"minimize_window","target":"discord"}
разверни консоль -> {"action":"maximize_window","target":"cmd"}
переключись на дискорд -> {"action":"activate_window","target":"discord"}
сверни это -> {"action":"minimize_active"}
разверни текущее -> {"action":"maximize_active"}
переключи окно -> {"action":"switch_window"}
предыдущее окно -> {"action":"switch_window","back":true}
пауза -> {"action":"play_pause"}
продолжи -> {"action":"play_pause"}
следующий трек -> {"action":"next_track"}
предыдущий трек -> {"action":"prev_track"}
сделай громче -> {"action":"volume_up"}
сделай тише -> {"action":"volume_down"}
без звука -> {"action":"mute"}
включи музыку -> {"steps":[{"action":"open_app","target":"яндекс музыка","minimized":true},{"action":"wait","seconds":6},{"action":"media_key","key":"play"}]}
переключись на режим команды -> {"action":"set_mode","mode":"commands"}
переключись на комбинированный -> {"action":"set_mode","mode":"combo"}
включи режим ИИ -> {"action":"set_mode","mode":"llm"}
загрузи пак игр -> {"action":"load_pack","name":"games"}
выгрузи пак игр -> {"action":"unload_pack","name":"games"}
какие паки -> {"action":"list_packs"}
смени голос на ирину -> {"action":"change_voice","voice":"irina"}
какой голос -> {"action":"list_voices"}
напомни через 10 минут выпить чай -> {"action":"set_timer","text":"выпить чай","seconds":600}
напомни в 18:30 позвонить -> {"action":"set_timer","text":"позвонить","time":"18:30"}
какие напоминания -> {"action":"list_timers"}
отмени все напоминания -> {"action":"cancel_timers"}
добавь в список купить хлеб -> {"action":"add_task","text":"купить хлеб"}
что в списке -> {"action":"list_tasks"}
отметь хлеб выполненным -> {"action":"done_task","task":"хлеб"}
убери хлеб из списка -> {"action":"remove_task","task":"хлеб"}
очисти список -> {"action":"clear_tasks"}
открой конфиг -> {"action":"open_config"}
открой журнал -> {"action":"open_log"}
какая погода -> {"action":"get_weather","day":"today"}
какая погода в нижнем новгороде -> {"action":"get_weather","target":"Нижний Новгород","day":"today"}
какая погода в питере -> {"action":"get_weather","target":"Санкт-Петербург","day":"today"}
какая погода в мск -> {"action":"get_weather","target":"Москва","day":"today"}
погода в москве на завтра -> {"action":"get_weather","target":"Москва","day":"tomorrow"}
что по погоде в казани -> {"action":"get_weather","target":"Казань","day":"today"}
курс валют -> {"action":"get_currency"}
курс доллара -> {"action":"get_currency","target":"USD"}
курс евро -> {"action":"get_currency","target":"EUR"}
курс юаня -> {"action":"get_currency","target":"CNY"}
курс белорусского рубля -> {"action":"get_currency","target":"BYN"}
курс тенге -> {"action":"get_currency","target":"KZT"}
курс фунта -> {"action":"get_currency","target":"GBP"}
сколько стоит доллар -> {"action":"get_currency","target":"USD"}
а белорусский рубль -> {"action":"get_currency","target":"BYN"}
расскажи шутку -> {"action":"answer","reply":"Почему медведь не ездит на машине? Потому что у него нет водительских прав."}
что такое чёрная дыра -> {"action":"answer","reply":"Это область пространства, откуда не может вырваться даже свет."}
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
}

CHAT_SYSTEM = (
    "Ты — Феникс, локальный голосовой ассистент на Windows. Ты живой собеседник, "
    "а не справочная и не служба безопасности. Характер: спокойный, вежливый, "
    "с сухим ироничным юмором, обращаешься к пользователю «сэр». "
    "Говори разговорным языком, как умный человек в беседе. "
    "Отвечай в 2–5 предложениях, если вопрос требует развёрнутого ответа. "
    "Ты МОЖЕШЬ и ДОЛЖЕН отвечать на любые безобидные просьбы: рассказать шутку, "
    "анекдот, историю, факт, объяснить, дать совет, высказать мнение, сочинить. "
    "Никогда не пиши «я не могу помочь», «извините», «как ИИ я не могу». "
    "Помни предыдущие реплики диалога и ссылайся на них, если уместно. "
    "Без списков, без markdown, без эмодзи — твой ответ озвучивается вслух. "
    "ЯЗЫК: ОТВЕЧАЙ ИСКЛЮЧИТЕЛЬНО НА РУССКОМ. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО "
    "использовать китайские иероглифы (漢字), японские (かな), корейские (한글), "
    "арабские, иврит или любые другие не-русские символы. Если не знаешь "
    "русского слова — опиши его простыми русскими словами. Если сомневаешься "
    "в языке — пиши по-русски."
)


class Brain:
    def __init__(self, model: str = "qwen2.5:7b-instruct",
                 url: str = "http://127.0.0.1:11434", timeout: float = 20.0):
        self.model = model
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.available = self._ping() or self._try_start()
        if self.available:
            log.info("LLM-фолбэк включён: %s через Ollama", model)
            threading.Thread(target=self._warmup, daemon=True, name="brain-warmup").start()
        else:
            log.warning("Ollama недоступна — LLM-фолбэк выключен")

    def _ping(self) -> bool:
        try:
            with urllib.request.urlopen(self.url + "/api/version", timeout=2):
                return True
        except OSError:
            return False

    def _try_start(self) -> bool:
        try:
            subprocess.Popen(["ollama", "serve"], creationflags=subprocess.CREATE_NO_WINDOW,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return False
        for _ in range(10):
            time.sleep(0.5)
            if self._ping():
                return True
        return False

    def _request(self, messages: list, timeout: float, fmt: str | None = "json",
                 temperature: float = 0, num_predict: int = 120) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": -1,
            "options": {"temperature": temperature, "num_predict": num_predict},
        }
        if fmt:
            payload["format"] = fmt
        req = urllib.request.Request(self.url + "/api/chat", json.dumps(payload).encode(),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())["message"]["content"]

    def _chat(self, cmd: str, timeout: float):
        return self._request([{"role": "system", "content": SYSTEM},
                              {"role": "user", "content": cmd}], timeout,
                             num_predict=300)

    def chat(self, cmd: str, history: list | None = None) -> str | None:
        if not self.available:
            return None
        msgs = ([{"role": "system", "content": CHAT_SYSTEM}]
                + list(history or [])[-40:]
                + [{"role": "user", "content": cmd}])
        try:
            t0 = time.time()
            text = self._request(msgs, self.timeout, fmt=None,
                                 temperature=0.4, num_predict=600).strip()
            log.info("LLM-диалог (%.2f с): %r -> %r", time.time() - t0, cmd, text)
            return text or None
        except Exception:
            log.exception("LLM-диалог не удался")
            return None

    def chat_stream(self, cmd: str, history: list | None = None):
        if not self.available:
            return
        msgs = ([{"role": "system", "content": CHAT_SYSTEM}]
                + list(history or [])[-40:]
                + [{"role": "user", "content": cmd}])
        payload = {
            "model": self.model,
            "messages": msgs,
            "stream": True,
            "keep_alive": -1,
            "options": {"temperature": 0.4, "num_predict": 600},
        }
        req = urllib.request.Request(self.url + "/api/chat",
                                     json.dumps(payload).encode(),
                                     {"Content-Type": "application/json"})
        try:
            t0 = time.time()
            first_chunk_time = None
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
                        if first_chunk_time is None:
                            first_chunk_time = time.time() - t0
                            log.info("LLM-стриминг: первый чанк за %.2f с", first_chunk_time)
                        yield chunk
                    if data.get("done"):
                        break
            log.info("LLM-стриминг: полный ответ за %.2f с", time.time() - t0)
        except Exception:
            log.exception("LLM-стриминг не удался")

    def _warmup(self) -> None:
        try:
            t0 = time.time()
            self._chat("привет", timeout=120)
            log.info("LLM прогрета за %.1f с", time.time() - t0)
        except Exception:
            log.exception("Прогрев LLM не удался")
            self.available = False

    def parse(self, cmd: str) -> dict | None:
        if not self.available:
            return None
        try:
            t0 = time.time()
            raw = self._chat(cmd, timeout=self.timeout)
            intent = json.loads(raw)
            log.info("LLM (%.2f с): %r -> %s", time.time() - t0, cmd,
                     json.dumps(intent, ensure_ascii=False))
        except json.JSONDecodeError:
            log.debug("LLM не вернула JSON на %r — уходим в диалог", cmd)
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