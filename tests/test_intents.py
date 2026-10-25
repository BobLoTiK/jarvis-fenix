"""Автотест Феникса без микрофона.

Прогоняет список команд через IntentHandler, проверяет ответы
по ожидаемым подстрокам, пишет всё в logs/test_intents.log.

По умолчанию:
    - Без LLM (Brain не создаётся). Хочешь с LLM — флаг --llm.
    - Без озвучки. Хочешь озвучку — флаг --voice.
    - Без сети (тесты погоды/курса пропускаются). Хочешь сеть — флаг --network.
    - Без настоящего браузера: «открой ютуб» проверяет разбор команды,
      а не открывает вкладку (иначе каждый прогон плодит вкладки, а на CI
      браузера нет вовсе). Нужен настоящий браузер — --real-browser.

Запуск:
    python tests/test_intents.py                  # правила, без LLM, без сети, без озвучки
    python tests/test_intents.py --llm            # + LLM (нужна Ollama)
    python tests/test_intents.py --network        # + тесты погоды/курса (нужна сеть)
    python tests/test_intents.py --llm --network  # всё вместе
    python tests/test_intents.py --voice          # с озвучкой
    python tests/test_intents.py --real-browser   # сайты открываются по-настоящему
    python tests/test_intents.py -k weather       # только тесты со словом 'weather'

ВНИМАНИЕ: это НЕ pytest-тест, а скрипт-раннер. pytest его не собирает
(см. `tests/conftest.py`, collect_ignore) — запускать только напрямую
или через `check_all.bat`.
"""

import argparse
import logging
import sys
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path

# Принудительно UTF-8 для stdout/stderr — иначе на CI (Windows, cp1252)
# падает UnicodeEncodeError при печати русских букв.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Скрипт лежит в tests/, а корень проекта — на уровень выше.
# BASE_DIR = корень нужен, чтобы лог остался в logs/ проекта (как в docs),
# а sys.path — чтобы `python tests/test_intents.py` видел пакет jarvis
# (иначе sys.path[0] = tests/ и `import jarvis` падает).
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)
LOG_FILE = LOGS_DIR / "test_intents.log"

log = logging.getLogger("jarvis.test")
log.setLevel(logging.INFO)

_fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")


def setup_logging() -> None:
    """Вешает хендлеры лениво — только при реальном запуске скрипта.

    Иначе импорт модуля (stress_intents.py берёт отсюда build_handler)
    открывал бы logs/test_intents.log на запись и обрезал чужой лог.
    """
    if log.handlers:
        return
    fh = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
    fh.setFormatter(_fmt)
    log.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setFormatter(_fmt)
    log.addHandler(ch)


# =================================================================
# Setup / teardown для тестов, которым нужно особое окружение.
# Возвращают (setup, teardown), либо None.
#
# ВАЖНО: работаем с config._data напрямую (в памяти), НЕ через config.set().
# Иначе пароль пользователя уйдёт на диск — если тест упадёт между
# setup и teardown, пароль потеряется.
# =================================================================

def _no_password_setup(handler):
    """Временно выставить danger_password = "" в памяти."""
    handler._saved_password = handler.config._data.get("danger_password", "")
    handler.config._data["danger_password"] = ""


def _no_password_teardown(handler):
    """Вернуть пароль как было — в памяти, без записи на диск."""
    saved = getattr(handler, "_saved_password", "")
    handler.config._data["danger_password"] = saved
    handler._saved_password = ""


def _with_password_setup(handler):
    """Временно выставить danger_password = 'test_password_123' в памяти."""
    handler._saved_password = handler.config._data.get("danger_password", "")
    handler.config._data["danger_password"] = "test_password_123"


def _add_note_setup(handler):
    """Заводит факт, ключ которого не совпадает со словами команды.

    Иначе «забудь про заметку» сработало бы точным совпадением ключа
    и не проверило поиск по смыслу.
    """
    from jarvis import learning
    learning.add_fact("тестовая заметка", "проверка 12345")


def _add_note_teardown(handler):
    """Если команда не сработала — факт не должен остаться в профиле."""
    from jarvis import learning
    learning.forget_fact("тестовая заметка")


def _correction_setup(handler):
    """Запоминает коррекции до теста — teardown уберёт только новые."""
    from jarvis import learning
    handler._corrections_before = dict(learning.all_corrections())


def _correction_teardown(handler):
    """Убирает коррекции, созданные тестом.

    После фикса correction_fast «это не то, я сказал X» реально сохраняет
    пару, и без уборки она подменяла команды в следующих прогонах
    (например, стресс-кейс «что ты обо мне помнишь»).
    """
    from jarvis import learning
    before = getattr(handler, "_corrections_before", {})
    for wrong in list(learning.all_corrections()):
        if wrong not in before:
            learning.forget_correction(wrong)


# teardown — тот же, что у _no_password_teardown


# (name, cmd, expected, requires_llm, requires_network, hooks)
# hooks: None или (setup_fn, teardown_fn).
TESTS = [
    # === Режимы (без LLM, без сети) ===
    ("mode_set_llm",        "режим ии",                   ["Режим", "ИИ"],          False, False, None),
    ("mode_query",          "какой режим",                ["Сейчас режим"],         False, False, None),
    ("mode_set_combo",      "обычный режим",              ["комбинированный"],      False, False, None),
    ("mode_set_commands",   "режим команды",              ["только команды"],       False, False, None),
    ("mode_restore",        "обычный режим",              ["комбинированный"],      False, False, None),

    # === Голоса (быстрые правила, без LLM) ===
    ("voice_list",          "какой голос",                ["голос"],                False, False, None),
    ("voice_switch_irina",  "смени голос на ирину",       ["Irina", "ирина"],       False, False, None),
    ("voice_switch_ruslan", "смени голос на руслан",      ["Ruslan", "руслан"],     False, False, None),

    # === Паки (быстрые правила, без LLM) ===
    ("packs_list",          "какие паки",                 ["Доступны"],             False, False, None),
    ("packs_unload",        "выгрузи пак игр",            ["выгружен", "уже", "не активен", "загружен"], False, False, None),
    ("packs_load",          "загрузи пак игр",            ["загружен", "уже", "не найден"], False, False, None),

    # === Буфер (без LLM, без сети) ===
    ("clipboard_read",      "что в буфере",               ["буфере", "пуст"],       False, False, None),
    ("clipboard_clear",     "очисти буфер",               ["Буфер"],                False, False, None),

    # === Погода ===
    ("weather_ask_city",    "какая погода",               ["городе"],               False, False, None),
    ("weather_answer_city", "Казань",                     ["Запомнил"],             False, True,  None),
    ("weather_default",     "какая погода",               ["Погода", "Казань"],     False, True,  None),
    ("weather_other_city",  "погода в нижнем новгороде",  ["Погода", "Новгород"],   True,  True,  None),
    ("weather_tomorrow",    "погода в питере на завтра",  ["Погода", "Петербург"],  True,  True,  None),

    # === Курс (требует сеть) ===
    ("currency_usd",        "курс доллара",               ["Доллар"],               False, True,  None),
    ("currency_byn",        "курс белорусского рубля",    ["рубл"],                 False, True,  None),
    ("currency_all",        "курс валют",                 ["ЦБ", "Доллар"],         False, True,  None),

    # === Small talk (без LLM, без сети) ===
    ("small_talk_how",      "как дела",                   [],                       False, False, None),
    ("small_talk_time",     "который час",                ["Сейчас"],               False, False, None),
    ("small_talk_date",     "какое сегодня число",        ["Сегодня"],              False, False, None),
    ("small_talk_who",      "кто ты",                     ["Феникс"],               False, False, None),

    # === Скриншот, сайт (без сети — только открытие URL, не загрузка) ===
    ("screenshot",          "сделай скриншот",            ["Скриншот"],             False, False, None),
    ("open_site",           "открой ютуб",                ["Ютуб", "youtube"],      False, False, None),

    # === Системные (раскладка, громкость, яркость) ===
    # На CI нет звуковой карты/монитора → «Не смог узнать». Локально → значение.
    ("layout_query",        "какая раскладка",            ["раскладк", "Не смог"],  False, False, None),
    ("volume_query",        "какая громкость",            ["Громкость", "Не смог"], False, False, None),
    ("brightness_query",    "какая яркость",              ["Яркость", "Не смог"],   False, False, None),

    # === Диагностика (Н2 + Н3) ===
    ("debug_what_heard",    "что ты слышал",              ["фразы", "слышал", "Пока ничего"], False, False, None),
    ("debug_why_not",       "почему не понял",            ["Фраза", "нечего", "диагност"],    False, False, None),

    # === Отмена (Н1) ===
    ("undo_ne_to",          "не то",                      ["Нечего", "Откатываю", "Вернул", "Переключил", "Действие"], False, False, None),
    ("undo_otmeni",         "отмени",                     ["Нечего", "Откатываю", "Вернул", "Переключил", "Действие"], False, False, None),

    # === Пароль (2.13) ===
    # danger_no_password: setup ставит пароль пустым — удаление профиля
    # необратимо, поэтому раньше оно стирало профиль сразу. Теперь ответ —
    # безопасный отказ: без пароля необратимые действия не выполняются.
    ("danger_no_password",  "удали профиль тест",
     ["не выполняются", "пароль"],
     False, False, (_no_password_setup, _no_password_teardown)),

    # danger_with_password: setup ставит пароль — команда уходит в _ask_password.
    ("danger_with_password", "удали профиль тест",
     ["пароль"],
     False, False, (_with_password_setup, _no_password_teardown)),

    # === Learning (5.3) ===
    ("learn_fact",          "запомни: мой город Казань",  ["Запомнил"],              False, False, None),
    ("learn_fact_query",    "что ты обо мне знаешь",      ["Казань", "Знаю"],        False, False, None),
    ("learn_fact_remember", "что ты обо мне помнишь",     ["Казань", "Знаю"],        False, False, None),
    ("learn_correction",    "это не то, я сказал логи",   ["Понял", "запомнил", "Что было"], False, False, (_correction_setup, _correction_teardown)),
    # «забудь про X» — не по ключу, а по смыслу (векторная память, без неё — слова)
    ("forget_by_meaning",   "забудь про заметку",         ["Забыл"],
     False, False, (_add_note_setup, _add_note_teardown)),
]


class Result:
    def __init__(self, name, cmd, reply_text, expected, elapsed):
        self.name = name
        self.cmd = cmd
        self.reply_text = reply_text
        self.expected = expected
        self.elapsed = elapsed
        # error инициализируем ДО _check(): иначе тест с исключением
        # не отличить от обычного, а _check() читает self.error.
        self.error = None
        self.passed = self._check()

    def _check(self):
        # Тест с исключением не может быть «пройден», даже если ожиданий нет.
        # Иначе small_talk_how с expected=[] молча съедал TypeError
        # из finalize_stream и харнес рапортовал зелёный.
        if self.error is not None:
            return False
        if not self.reply_text:
            return False
        if not self.expected:
            return True
        text = str(self.reply_text).lower()
        return any(e.lower() in text for e in self.expected)

    def __str__(self):
        mark = "OK  " if self.passed else "FAIL"
        return f"[{mark}] {self.name:24s} ({self.elapsed:5.2f} с) «{self.cmd}»"


def build_handler(use_llm=False, reset_profile=True):
    """Собирает IntentHandler.

    use_llm=False (по умолчанию) — brain=None, только правила.
    reset_profile=True — сбрасывает default_city, чтобы тесты были
                         детерминированными (не зависели от прошлых прогонов).
    """
    from jarvis.config import load_config
    from jarvis.apps import build_apps
    from jarvis.intents import IntentHandler

    log.info("Загрузка конфига...")
    config = load_config(BASE_DIR)

    # В тестах — только Piper. Silero требует torch, грузит модель 2-3 сек,
    # а голоса у него другие (aidar/baya/...). Тесты ожидают Piper-голоса
    # (ruslan, irina, dmitri, denis).
    if config.get("tts_backend", "auto") != "piper":
        log.info("Тесты: tts_backend принудительно → piper")
        config._data["tts_backend"] = "piper"

    if reset_profile:
        from jarvis import profile
        if profile.forget("default_city"):
            log.info("Профиль: default_city сброшен для чистого прогона")
        else:
            log.info("Профиль: default_city уже отсутствовал")

    brain = None
    if use_llm:
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

    log.info("Сборка IntentHandler...")
    return IntentHandler(config, build_apps(config), brain)


# =================================================================
# Тесты не должны открывать настоящий браузер
# =================================================================
# «открой ютуб» — проверка разбора команды, а не повод открыть вкладку.
# Локально каждый прогон добавлял вкладку (а прогонов много), в CI браузера
# нет вовсе. Подменяем только действия-открывашки: разбор фразы, ответ и
# проверка ожиданий остаются настоящими.

_OPEN_ACTIONS = ("open_url", "open_browser", "open_search", "open_site_lucky")


@contextmanager
def no_real_browser():
    """Открытие сайтов/браузера → заглушка «открыл» (True)."""
    from unittest.mock import patch

    from jarvis import actions

    with ExitStack() as stack:
        for name in _OPEN_ACTIONS:
            stack.enter_context(patch.object(actions, name, return_value=True))
        yield


def reset_handler_state(handler):
    """Сбрасывает stateful-состояние между тестами.

    ВАЖНО: сбрасываем ТОЛЬКО разовые вещи — пароль и флаг reset.
    Не трогаем _pending_question, _last_cmd, dialog, _recent_phrases:
    тесты weather_ask_city → weather_answer_city → weather_default
    построены как цепочка и специально зависят от состояния
    предыдущего шага.
    """
    handler._pending_password = None
    handler._reset_requested = False


def run_one(handler, speaker, name, cmd, expected, hooks=None):
    log.info("─" * 70)
    log.info("ТЕСТ: %s | команда: %r", name, cmd)

    # Чистое состояние перед каждым тестом
    reset_handler_state(handler)

    setup, teardown = hooks if hooks else (None, None)
    if setup:
        try:
            setup(handler)
        except Exception:
            log.exception("setup не удался для %s", name)

    t0 = time.time()
    try:
        reply = handler.handle(cmd)
        if reply.is_stream:
            reply_text = "".join(reply.stream)
            handler.finalize_stream(reply_text)
        else:
            reply_text = reply.text
    except Exception as e:
        log.exception("Исключение в тесте %s", name)
        r = Result(name, cmd, f"<EXCEPTION: {e}>", expected, time.time() - t0)
        r.error = str(e)
        if teardown:
            try:
                teardown(handler)
            except Exception:
                log.exception("teardown не удался для %s", name)
        return r

    elapsed = time.time() - t0

    if teardown:
        try:
            teardown(handler)
        except Exception:
            log.exception("teardown не удался для %s", name)

    if speaker is not None and reply_text:
        try:
            speaker.speak(reply_text)
        except Exception:
            log.exception("Ошибка озвучки")

    r = Result(name, cmd, reply_text, expected, elapsed)
    log.info("Ответ: %s", str(reply_text)[:200])
    log.info("Результат: %s", "OK" if r.passed else f"FAIL (ожидалось: {expected})")
    return r


def main():
    parser = argparse.ArgumentParser(description="Автотест Феникса")
    parser.add_argument("--llm", action="store_true",
                        help="Использовать LLM (нужна Ollama)")
    parser.add_argument("--voice", action="store_true",
                        help="Озвучивать ответы")
    parser.add_argument("--network", action="store_true",
                        help="Запускать тесты, требующие сеть (погода, курс)")
    parser.add_argument("--real-browser", action="store_true",
                        help="Открывать сайты по-настоящему (по умолчанию — заглушка)")
    parser.add_argument("-k", "--filter",
                        help="Фильтр по имени теста")
    args = parser.parse_args()

    setup_logging()

    log.info("=" * 70)
    log.info("АВТОТЕСТ ФЕНИКСА")
    log.info("LLM: %s | Сеть: %s | Озвучка: %s | Браузер: %s",
             "вкл" if args.llm else "выкл",
             "вкл" if args.network else "выкл",
             "вкл" if args.voice else "выкл",
             "настоящий" if args.real_browser else "заглушка")
    log.info("Лог: %s", LOG_FILE)
    log.info("=" * 70)

    handler = build_handler(use_llm=args.llm)

    speaker = None
    if args.voice:
        try:
            from jarvis.tts import Speaker
            speaker = Speaker(handler.config)
        except Exception:
            log.exception("Speaker не завёлся — без озвучки")

    tests = TESTS
    if args.filter:
        f = args.filter.lower()
        tests = [t for t in tests if f in t[0].lower()]
        log.info("Фильтр %r: %d тестов", args.filter, len(tests))

    results = []
    skipped = []
    t_start = time.time()
    # Сайты по умолчанию не открываем по-настоящему — иначе тесты плодят
    # вкладки в браузере (см. no_real_browser). Нужен настоящий — --real-browser.
    with ExitStack() as stack:
        if not args.real_browser:
            stack.enter_context(no_real_browser())
        for entry in tests:
            # entry — 6 полей: (name, cmd, expected, requires_llm, requires_network, hooks)
            name, cmd, expected, requires_llm, requires_network, hooks = entry
            if requires_llm and not args.llm:
                log.info("ПРОПУСК %s (требует --llm)", name)
                skipped.append(f"{name} (--llm)")
                continue
            if requires_network and not args.network:
                log.info("ПРОПУСК %s (требует --network)", name)
                skipped.append(f"{name} (--network)")
                continue
            r = run_one(handler, speaker, name, cmd, expected, hooks)
            results.append(r)

    total = time.time() - t_start
    passed = [r for r in results if r.passed]
    failed = [r for r in results if not r.passed]

    log.info("")
    log.info("=" * 70)
    log.info("ИТОГ: %d / %d пройдено за %.1f с", len(passed), len(results), total)
    if skipped:
        log.info("Пропущено: %d — %s", len(skipped), ", ".join(skipped))
    log.info("=" * 70)

    for r in results:
        log.info(str(r))

    if failed:
        log.info("")
        log.info("ПРОВАЛЫ:")
        for r in failed:
            log.info("  %s", r.name)
            log.info("    команда: %r", r.cmd)
            log.info("    ответ:   %s", str(r.reply_text)[:200])
            log.info("    ждали:   %s", r.expected)
            if r.error:
                log.info("    ошибка:  %s", r.error)

    log.info("")
    log.info("Полный лог: %s", LOG_FILE)
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()