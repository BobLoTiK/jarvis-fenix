"""Автотест Феникса без микрофона.

Прогоняет список команд через IntentHandler, проверяет ответы
по ожидаемым подстрокам, пишет всё в logs/test_intents.log.

Запуск:
    python test_intents.py              # все тесты, без озвучки
    python test_intents.py --voice      # с озвучкой
    python test_intents.py -k weather   # только тесты со словом 'weather'
"""

import argparse
import logging
import re
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)
LOG_FILE = LOGS_DIR / "test_intents.log"

log = logging.getLogger("jarvis.test")
log.setLevel(logging.INFO)

_fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

_fh = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
_fh.setFormatter(_fmt)
log.addHandler(_fh)

_ch = logging.StreamHandler()
_ch.setFormatter(_fmt)
log.addHandler(_ch)


TESTS = [
    # === Режимы ===
    ("mode_set_llm",       "режим ии",                  ["Режим", "ИИ"]),
    ("mode_query",         "какой режим",               ["Сейчас режим"]),
    ("mode_set_combo",     "обычный режим",             ["комбинированный"]),
    ("mode_set_commands",  "режим команды",             ["только команды"]),
    ("mode_restore",       "обычный режим",             ["комбинированный"]),

    # === Голоса ===
    ("voice_list",         "какой голос",               ["голос"]),
    ("voice_switch_irina", "смени голос на ирину",      ["Irina", "ирина"]),
    ("voice_switch_ruslan","смени голос на руслан",     ["Ruslan", "руслан"]),

    # === Паки (ожидания ослаблены) ===
    ("packs_list",         "какие паки",                ["Доступны"]),
    ("packs_unload",       "выгрузи пак игр",           ["выгружен", "уже", "не активен", "загружен"]),
    ("packs_load",         "загрузи пак игр",           ["загружен", "уже", "не найден"]),

    # === Буфер ===
    ("clipboard_read",     "что в буфере",              ["буфере", "пуст"]),
    ("clipboard_clear",    "очисти буфер",              ["Буфер"]),

    # === Погода ===
    ("weather_ask_city",   "какая погода",              ["городе", "Погода"]),
    ("weather_answer_city","Казань",                    ["Запомнил", "Погода"]),
    ("weather_default",    "какая погода",              ["Погода", "Казань"]),
    ("weather_other_city", "погода в нижнем новгороде", ["Погода", "Новгород"]),
    ("weather_tomorrow",   "погода в питере на завтра", ["Погода", "Петербург"]),

    # === Курс ===
    ("currency_usd",       "курс доллара",              ["Доллар"]),
    ("currency_byn",       "курс белорусского рубля",   ["рубл"]),
    ("currency_all",       "курс валют",                ["ЦБ", "Доллар"]),

    # === Small talk ===
    ("small_talk_how",     "как дела",                  []),  # любой непустой
    ("small_talk_time",    "который час",               ["Сейчас"]),
    ("small_talk_date",    "какое сегодня число",       ["Сегодня"]),
    ("small_talk_who",     "кто ты",                    ["Феникс"]),

    # === Скриншот, сайт ===
    ("screenshot",         "сделай скриншот",           ["Скриншот"]),
    ("open_site",          "открой ютуб",               ["Ютуб", "youtube"]),
]


class Result:
    def __init__(self, name, cmd, reply, expected, elapsed):
        self.name = name
        self.cmd = cmd
        self.reply = reply
        self.expected = expected
        self.elapsed = elapsed
        self.passed = self._check()
        self.error = None

    def _check(self):
        if not self.reply:
            return False
        if not self.expected:
            return True
        text = str(self.reply).lower()
        return any(e.lower() in text for e in self.expected)

    def __str__(self):
        mark = "OK  " if self.passed else "FAIL"
        return f"[{mark}] {self.name:24s} ({self.elapsed:5.2f} с) «{self.cmd}»"


def build_handler(with_voice=False):
    from jarvis.config import load_config
    from jarvis.apps import build_apps
    from jarvis.intents import IntentHandler

    log.info("Загрузка конфига...")
    config = load_config(BASE_DIR)

    brain = None
    if config.get("use_llm", True):
        from jarvis.brain import Brain
        model = config.get("llm_model", "qwen2.5:7b-instruct")
        url = config.get("ollama_url", "http://127.0.0.1:11434")
        log.info("Инициализация LLM: %s", model)
        brain = Brain(model, url)
        if not brain.available:
            log.warning("LLM недоступна — работаем только с правилами")
            brain = None
        else:
            log.info("Ждём прогрева LLM (10 с)...")
            time.sleep(10)

    speaker = None
    if with_voice:
        try:
            from jarvis.tts import Speaker
            speaker = Speaker(config)
        except Exception:
            log.exception("Speaker не завёлся — без озвучки")

    log.info("Сборка IntentHandler...")
    handler = IntentHandler(config, build_apps(config), brain)
    return handler, speaker


def run_one(handler, speaker, name, cmd, expected):
    log.info("─" * 70)
    log.info("ТЕСТ: %s | команда: %r", name, cmd)

    t0 = time.time()
    try:
        reply = handler.handle(cmd)
        if hasattr(reply, "__iter__") and not isinstance(reply, str):
            reply = "".join(reply)
    except Exception as e:
        log.exception("Исключение в тесте %s", name)
        r = Result(name, cmd, f"<EXCEPTION: {e}>", expected, time.time() - t0)
        r.error = str(e)
        return r

    elapsed = time.time() - t0

    if speaker is not None:
        try:
            speaker.speak(reply)
        except Exception:
            log.exception("Ошибка озвучки")

    r = Result(name, cmd, reply, expected, elapsed)
    log.info("Ответ: %s", str(reply)[:200])
    log.info("Результат: %s", "OK" if r.passed else f"FAIL (ожидалось: {expected})")
    return r


def main():
    parser = argparse.ArgumentParser(description="Автотест Феникса")
    parser.add_argument("--voice", action="store_true")
    parser.add_argument("-k", "--filter")
    args = parser.parse_args()

    log.info("=" * 70)
    log.info("АВТОТЕСТ ФЕНИКСА")
    log.info("Лог: %s", LOG_FILE)
    log.info("=" * 70)

    handler, speaker = build_handler(with_voice=args.voice)

    tests = TESTS
    if args.filter:
        f = args.filter.lower()
        tests = [t for t in tests if f in t[0].lower()]
        log.info("Фильтр %r: %d тестов", args.filter, len(tests))

    results = []
    t_start = time.time()
    for name, cmd, expected in tests:
        r = run_one(handler, speaker, name, cmd, expected)
        results.append(r)

    total = time.time() - t_start
    passed = [r for r in results if r.passed]
    failed = [r for r in results if not r.passed]

    log.info("")
    log.info("=" * 70)
    log.info("ИТОГ: %d / %d пройдено за %.1f с", len(passed), len(results), total)
    log.info("=" * 70)

    for r in results:
        log.info(str(r))

    if failed:
        log.info("")
        log.info("ПРОВАЛЫ:")
        for r in failed:
            log.info("  %s", r.name)
            log.info("    команда: %r", r.cmd)
            log.info("    ответ:   %s", str(r.reply)[:200])
            log.info("    ждали:   %s", r.expected)
            if r.error:
                log.info("    ошибка:  %s", r.error)

    log.info("")
    log.info("Полный лог: %s", LOG_FILE)
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()