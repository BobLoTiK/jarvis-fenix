"""LLM-фолбэк: локальная нейронка (Ollama) разбирает команду в структурный интент."""

import json
import logging
import subprocess
import threading
import time
import urllib.request

log = logging.getLogger("jarvis.brain")

SYSTEM = """Ты разбираешь команды голосового ассистента на Windows. Отвечай ТОЛЬКО JSON.
Действия: open_app (открыть программу; minimized=true — свёрнуто), close_app, open_site, search (поиск), screenshot, open_file, media_key (key: play|next|prev|vol_up|vol_down|mute), wait (seconds), answer, none, open_folder, list_folder, create_file, type_text (text), minimize_all (свернуть все окна), minimize_window (target), maximize_window (target), activate_window (target — переключиться на окно), minimize_active, maximize_active, switch_window (back=true — на предыдущее).
Поля: action; target; query; engine (google|youtube|wiki); reply; text.

ВАЖНО про паки: команды «активируй паки», «загрузи паки», «выгрузи паки», «какие паки» — НЕ трогай. Это команды системы паков, они обрабатываются отдельно. НИКОГДА не возвращай minimize_all, maximize_all или что-то с окнами в ответ на слова «паки», «активируй», «загрузи».

ВАЖНО про окна:
- «консоль», «терминал», «командная строка», «cmd» → target: "cmd"
- «браузер» → target: "браузер"
- «телега», «тг» → target: "telegram"
- «дс», «дискорд» → target: "discord"
- «проводник», «папка» → target: "проводник"
- «настройки», «параметры» → target: "настройки"

ВАЖНО про search vs answer:
По умолчанию отвечай САМ через answer — даже на вопросы о фактах, объяснения, мнения, советы, шутки, историю, погоду.
НИКОГДА не используй search, если пользователь явно не сказал: «найди», «поищи», «ищи», «загугли», «погугли», «поиск», «найди в интернете», «найди на ютубе», «найди в википедии».
Свежесть данных (погода, курс, новости) — НЕ повод для search, если глагола поиска нет. В этом случае либо ответь тем, что знаешь, либо скажи: «Скажите "найди ...", и я посмотрю в интернете».

Примеры:
открой стим -> {"action":"open_app","target":"стим"}
запусти сабнатику -> {"action":"open_app","target":"сабнатика"}
что такое чёрная дыра -> {"action":"answer","reply":"Это область пространства, откуда не может вырваться даже свет."}
сколько будет два плюс два -> {"action":"answer","reply":"Четыре"}
расскажи шутку -> {"action":"answer","reply":"Почему медведь не ездит на машине? Потому что у него нет водительских прав."}
как дела -> {"action":"answer","reply":"Отлично, сэр. Готов к работе."}
какая погода -> {"action":"answer","reply":"Без доступа к сети я не знаю текущую погоду, сэр. Скажите «найди погоду», и я посмотрю в интернете."}
найди погоду -> {"action":"search","engine":"google","query":"погода сегодня"}
загугли новости -> {"action":"search","engine":"google","query":"новости сегодня"}
поищи на ютубе лофи -> {"action":"search","engine":"youtube","query":"лофи"}
найди в википедии фотосинтез -> {"action":"search","engine":"wiki","query":"фотосинтез"}
объясни что такое фотосинтез -> {"action":"answer","reply":"Это процесс, которым растения превращают свет в энергию."}
посоветуй фильм -> {"action":"answer","reply":"Попробуйте «Пятый элемент» — классика, сэр."}
напечатай привет мир -> {"action":"type_text","text":"привет мир"}
сверни все окна -> {"action":"minimize_all"}
сверни это -> {"action":"minimize_active"}
разверни текущее -> {"action":"maximize_active"}
переключи окно -> {"action":"switch_window"}
предыдущее окно -> {"action":"switch_window","back":true}
сверни дискорд -> {"action":"minimize_window","target":"discord"}
разверни консоль -> {"action":"maximize_window","target":"cmd"}
разверни терминал -> {"action":"maximize_window","target":"cmd"}
разверни командную строку -> {"action":"maximize_window","target":"cmd"}
сверни браузер -> {"action":"minimize_window","target":"браузер"}
разверни браузер -> {"action":"maximize_window","target":"браузер"}
разверни телегу -> {"action":"maximize_window","target":"telegram"}
сверни проводник -> {"action":"minimize_window","target":"проводник"}
переключись на дискорд -> {"action":"activate_window","target":"discord"}
перейди в консоль -> {"action":"activate_window","target":"cmd"}
открой загрузки -> {"action":"open_folder","target":"загрузки"}
включи музыку -> {"steps":[{"action":"open_app","target":"яндекс музыка","minimized":true},{"action":"wait","seconds":6},{"action":"media_key","key":"play"}]}
сделай скриншот и открой его -> {"steps":[{"action":"screenshot"},{"action":"open_file"}]}"""

ACTIONS = {"open_app", "close_app", "open_site", "search", "screenshot",
           "open_file", "media_key", "wait", "answer", "none",
           "open_folder", "list_folder", "create_file",
           "type_text", "minimize_all", "minimize_window", "maximize_window",
           "activate_window", "minimize_active", "maximize_active", "switch_window"}

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
    "Без списков, без markdown, без эмодзи — твой ответ озвучивается вслух."
)


class Brain:
    def __init__(self, model: str = "qwen2.5:1.5b-instruct",
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
                              {"role": "user", "content": cmd}], timeout)

    def chat(self, cmd: str, history: list | None = None) -> str | None:
        if not self.available:
            return None
        msgs = ([{"role": "system", "content": CHAT_SYSTEM}]
                + list(history or [])[-40:]
                + [{"role": "user", "content": cmd}])
        try:
            t0 = time.time()
            text = self._request(msgs, self.timeout, fmt=None,
                                 temperature=0.7, num_predict=600).strip()
            log.info("LLM-диалог (%.2f с): %r -> %r", time.time() - t0, cmd, text)
            return text or None
        except Exception:
            log.exception("LLM-диалог не удался")
            return None

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