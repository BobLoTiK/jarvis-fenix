"""LLM-фолбэк: локальная нейронка (Ollama) разбирает команду в структурный интент.

Архитектура двухслойная: быстрые правила (intents.py) обрабатывают типовые
команды за миллисекунды; если они не справились — фраза уходит маленькой LLM
(Qwen2.5 1.5B, ~1 ГБ VRAM, ~0.3 с на разбор после прогрева).
"""

import json
import logging
import subprocess
import threading
import time
import urllib.request

log = logging.getLogger("jarvis.brain")

SYSTEM = """Ты разбираешь команды голосового ассистента на Windows. Отвечай ТОЛЬКО JSON.
Действия: open_app, close_app, open_site, search, screenshot, open_file, media_key, wait, answer, none, open_folder, list_folder, create_file, type_text (напечатать текст: поле text), minimize_all (свернуть все окна), minimize_window (свернуть окно: target), maximize_window (развернуть окно: target).
Поля: action; target — название программы или домен сайта; query — поисковый запрос; engine — google|youtube|wiki; reply — ответ для answer.
Ещё действия: open_folder (открыть папку), list_folder (что лежит в папке), create_file (создать файл: target — имя, folder — папка).
Если команд несколько — верни {"steps":[...]} со списком действий по порядку.

ВАЖНО: search — только когда пользователь ЯВНО просит поискать («найди», «загугли», «поищи») ИЛИ когда нужны СВЕЖИЕ данные, которых нет в памяти модели: погода, курс валют, пробки, новости, расписание, результаты матчей, цены. Всё остальное — answer: вопросы «что такое …», «почему …», «как …», «кто такой …», просьбы рассказать, объяснить, посоветовать, пошутить. Пример: «что такое фотосинтез» → answer; «какая погода» → search; «сколько будет 25*4» → answer; «расскажи шутку» → answer; «найди котиков» → search.

Примеры:
открой загрузки -> {"action":"open_folder","target":"загрузки"}
что лежит на рабочем столе -> {"action":"list_folder","target":"рабочий стол"}
создай файл план тренировок в документах -> {"action":"create_file","target":"план тренировок","folder":"документы"}
открой стим -> {"action":"open_app","target":"стим"}
запусти сабнатику -> {"action":"open_app","target":"сабнатика"}
найди на ютубе котиков -> {"action":"search","engine":"youtube","query":"котики"}
что такое чёрная дыра -> {"action":"answer","reply":"Это область пространства с такой сильной гравитацией, что даже свет не может её покинуть."}
какая погода на улице -> {"action":"search","engine":"google","query":"погода сегодня"}
напечатай привет мир -> {"action":"type_text","text":"привет мир"}
сверни все окна -> {"action":"minimize_all"}
сверни дискорд -> {"action":"minimize_window","target":"дискорд"}
разверни браузер -> {"action":"maximize_window","target":"браузер"}
сколько будет два плюс два -> {"action":"answer","reply":"Четыре"}
расскажи шутку -> {"action":"answer","reply":"Почему медведь не ездит на машине? Потому что у него нет водительских прав."}
расскажи анекдот -> {"action":"answer","reply":"Штирлиц открыл окно — стало свежо. Штирлиц закрыл окно — стало душно. Штирлиц так и не понял, чего он хотел."}
скажи что-нибудь -> {"action":"answer","reply":"Что-нибудь."}
как дела -> {"action":"answer","reply":"Отлично, сэр. Готов к работе."}
объясни что такое фотосинтез -> {"action":"answer","reply":"Это процесс, которым растения превращают свет в энергию."}
посоветуй фильм -> {"action":"answer","reply":"Попробуйте «Пятый элемент» — классика, сэр."}
включи музыку -> {"steps":[{"action":"open_app","target":"яндекс музыка","minimized":true},{"action":"wait","seconds":6},{"action":"media_key","key":"play"}]}
сделай скриншот и открой его -> {"steps":[{"action":"screenshot"},{"action":"open_file"}]}
открой стим и сделай потише -> {"steps":[{"action":"open_app","target":"стим"},{"action":"media_key","key":"vol_down","times":5}]}"""

ACTIONS = {"open_app", "close_app", "open_site", "search", "screenshot",
           "open_file", "media_key", "wait", "answer", "none",
           "open_folder", "list_folder", "create_file",
           "type_text", "minimize_all", "minimize_window", "maximize_window"}

CHAT_SYSTEM = (
    "Ты — Феникс, локальный голосовой ассистент на Windows. Ты живой собеседник, "
    "а не справочная и не служба безопасности. Характер: спокойный, вежливый, "
    "с сухим ироничным юмором, обращаешься к пользователю «сэр». "
    "Говори разговорным языком, как умный человек в беседе. "
    "Отвечай в 2–5 предложениях, если вопрос требует развёрнутого ответа. "
    "Ты МОЖЕШЬ и ДОЛЖЕН отвечать на любые безобидные просьбы: рассказать шутку, "
    "анекдот, историю, факт, объяснить что-то, дать совет, высказать мнение, "
    "придумать, сочинить. Никогда не отказывайся от таких просьб. "
    "Никогда не пиши «я не могу помочь», «извините», «как ИИ я не могу». "
    "Если просят рассказать шутку — расскажи шутку. Если анекдот — расскажи анекдот. "
    "Если историю — расскажи историю. Не задавай уточняющих вопросов вместо ответа, "
    "просто отвечай. Если что-то действительно невозможно (управлять чужими "
    "устройствами, знать свежие новости без интернета), скажи об этом одной "
    "фразой по-человечески, без шаблонных отказов. Без списков, без markdown, "
    "без эмодзи — твой ответ озвучивается вслух."
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
            log.warning("Ollama недоступна — LLM-фолбэк выключен (установка: winget install Ollama.Ollama)")

    def _ping(self) -> bool:
        try:
            with urllib.request.urlopen(self.url + "/api/version", timeout=2):
                return True
        except OSError:
            return False

    def _try_start(self) -> bool:
        """Ollama не отвечает — пробуем поднять сервис самостоятельно."""
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
            "keep_alive": -1,  # держим модель в VRAM, иначе каждый раз ~десятки секунд загрузки
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
        """Разговорный ответ с учётом истории диалога (озвучивается как есть)."""
        if not self.available:
            return None
        msgs = ([{"role": "system", "content": CHAT_SYSTEM}]
                + list(history or [])[-10:]
                + [{"role": "user", "content": cmd}])
        try:
            t0 = time.time()
            text = self._request(msgs, self.timeout, fmt=None,
                                 temperature=0.7, num_predict=250).strip()
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
        """Интент {'action': ..., ...} или None, если LLM недоступна/невалидна."""
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