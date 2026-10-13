# Как контрибьютить в Феникс

Документ для себя-будущего и для LLM, которая помогает с проектом.

## 🎯 Главное правило

**Не добавляй костыли.** Если решение «работает, но выглядит грязно» —
это не решение. Лучше потратить час сейчас, чем три — через месяц.

## 📁 Структура

```
jarvis/             — пакет
  reply.py          — тип Reply (text | stream)
  intents/          — пакет: handler, context, verbs, password, sites,
                      execute + stages/ (11 стадий) + fast/ (19 правил)
  main.py           — точка входа, Jarvis, barge-in, cmd_lock
  brain.py          — Ollama: parse() и chat_stream()
  config.py         — Config в памяти + подписки
  config_manager.py — атомарная запись (FileLock per-path)
  paths.py          — PROGRAM_DIR / USER_DIR
  text_utils.py     — normalize, strip_cjk, prepare_text
  tts.py            — фасад над tts_engines + per-call token
  tts_engines/      — BaseEngine + Silero / Piper / WinRT / SAPI
  stt.py            — Vosk + Whisper + ring buffer
  vad.py            — Silero VAD ONNX + SpeechHangover
  prosody.py        — эмоции из голоса (RMS + pitch + ZCR)
  gui.py            — Flet GUI + PALETTES + fireworks
  celebrations.py   — поздравление с ДР
  ...

tests/                  — pytest-тесты
tests/test_intents.py   — интент-тесты (без микрофона)
tests/stress_intents.py — стресс-тест (100 ситуаций)
tests/manual/           — ручные прогоны (микрофон, UIA, ONNX)
check_all.bat           — всё сразу: 4 шага + компактный итог
check_syntax.py         — синтаксис всех .py
snapshot.py             — сборка SNAPSHOT.md

PROJECT.md          — ИСТОЧНИК ПРАВДЫ: инварианты, правила,
                      история ошибок, контракт проверки

packs/              — JSON-паки команд
scripts/            — утилиты (make_icon, build_exe, mics, ...)
.github/workflows/  — CI
```

## 📝 Правила кода

1. **Не читай `config.json` напрямую** — `config.get()` из объекта `Config`.
2. **Не пиши в `config.json` напрямую** — только `Config.set()` или `config_manager.save()`.
3. **Не плоди глобальное состояние** — кроме `Config._GLOBAL`.
4. **Нормализация (города, валюты, паков) — задача LLM.**
5. **Логи в `actions.log`** — главный инструмент отладки.
6. **`check_all.bat`** — первое, что запускаешь после правки `intents/`, `brain.py`, `actions.py` (4 шага, компактный итог).
7. **`normalize(cmd)` в `IntentHandler.handle()`** — единая точка.
8. **Per-call stop-token в `tts.py`.**
9. **`PALETTES` в `gui.py`** — две палитры, `_detect_system_theme()` для системной.
10. **`ft.Button`** вместо `ft.ElevatedButton` / `ft.TextButton` (в Flet 1.x их удалили).
11. **`weather_cache_ttl_sec`** — читается **на каждый вызов**.
12. **`snapshot.py`** — исключать `.venv311` и `profiles/`.
13. **Пути — только через `jarvis/paths.py`.**
14. **Модели Vosk/Whisper — ВСЕГДА в `PROGRAM_DIR` (ASCII).**
15. **`HF_HOME` для Whisper — временно.**
16. **Vosk API — только из listener-потока.**
17. **Pack-команды с аргументами — `_looks_like_cmd` + `shlex`.**
18. **Атомарная запись везде — `mkstemp` + `os.replace`.**
19. **Zip Slip защита при распаковке.**
20. **`cmd_lock` в Jarvis — сериализация GUI↔голос.**
21. **`_say_lock` в Jarvis** — `say()` зовут ещё таймеры, `mic_watchdog`
    и `celebrations`. Без него они режут текущую речь через `speaker.stop()`.
22. **`PROJECT.md` — источник правды.** Поменялось поведение, инвариант
    или добавилась грабля — правь **его**, а не пять доков сразу.

## 🔒 Правила безопасности

**Никогда не упоминай в публичных файлах** (`README.md`, `PLAN.md`,
`CHANGELOG.md`, `ARCHITECTURE.md`, `PROMPT.md`, `CONTRIBUTING.md`,
`config.example.json`):

- Имя пользователя.
- Город.
- Модель CPU / GPU.
- ОС.

**Всё личное — только в:**
- `config.json`.
- `profiles/`.
- `system_caps.json`.

**И они — в `.gitignore`.**

**Не удаляй attribution `jsays12`** из `LICENSE`, `README.md`, `CHANGELOG.md`.

## 🚀 Рабочий процесс

### 1. Правка

Правь файлы в `jarvis/`. **Один патч — одна задача.**

### 2. Проверка синтаксиса

```bat
python check_syntax.py
```

### 3. Тесты

```bat
check_all.bat                     :: всё сразу (синтаксис + pytest + интенты + стресс)
python -m pytest tests/ -q
python tests/test_intents.py
python tests/stress_intents.py
```

### 4. Обновление SNAPSHOT

```bat
python snapshot.py
```

### 5. Коммит

```bat
commit.bat "fix: краткое описание"
```

**`commit.bat`** сам:
1. Активирует `.venv311`.
2. Запустит `snapshot.py`.
3. `git add .` → `git commit` → `git push`.

## 🎨 Стиль

### Комментарии

**Хорошо:**
```python
# Per-call stop-token: каждый вызов создаёт свой Event.
# Иначе старый поток не завершится, и будет 2-3 голоса одновременно.
```

**Плохо:**
```python
# создаём токен
token = threading.Event()
```

### Имена

- **Переменные:** `snake_case`.
- **Классы:** `PascalCase`.
- **Константы:** `UPPER_SNAKE`.
- **Приватные методы:** `_method`.

### Логи

**Хорошо:**
```python
log.info("Custom (точно): %r → %r, action=%r", cmd, phrase, action)
```

**Плохо:**
```python
print("custom matched")
```

## 🧪 Тесты

### Что писать

- **Новые интенты** — сценарий в `tests/test_intents.py` (или ситуация в `tests/stress_intents.py`).
- **Новые функции** с логикой — `pytest`.
- **Погода/курс** — с моками `_http_get_json`.

### Чего не делать

- **Не тестируй GUI** — Flet требует окно.
- **Не тестируй звук** — в CI нет звуковой карты.
- **Не тестируй сеть** — если тест требует интернет, добавь флаг `--network`.

## ⚠️ Частые ошибки

1. **Читать `config.json` руками** — используй `config.get()`.
2. **Писать в `config.json` руками** — `Config.set()`.
3. **Использовать общий `_stop_flag` в TTS** — per-call токен.
4. **Коммитить `.venv311`** — `.gitignore`.
5. **Коммитить `config.json`, `profiles/`, `system_caps.json`** — личное.
6. **Коммитить `SNAPSHOT.md` > 1 МБ** — исключай `.venv311`.
7. **Использовать Python 3.13/3.14** — Vosk падает. Только 3.10–3.12.
8. **Запускать Flet не в главном потоке** — `signal.signal` не работает.
9. **`ElevatedButton`/`TextButton` в Flet 1.x** — используй `ft.Button`.
10. **Хардкодить пути** — через `jarvis/paths.py`.
11. **Хардкодить модели в `USER_DIR`** — Vosk сломается, только `PROGRAM_DIR`.
12. **Ставить `HF_HOME` глобально** — сломает Piper, ставить временно.
13. **Дёргать Vosk API из главного потока** — только listener-поток.
14. **`prevent_close` + `on_event`** — в Flet 1.0.3 не работает.
15. **Zip Slip** — всегда проверяй `is_relative_to` при распаковке.
16. **`Global\` мьютекс** — требует админа. Используй `Local\`.
17. **Pack-команды с аргументами** — через `_looks_like_cmd` + `shlex`.
18. **Открывать файлы с кириллицей в пути через Vosk** — модель только в ASCII.
19. **Писать `timers.json` / `tasks.json` в `BASE_DIR`** — только `USER_DIR`.
20. **Забывать `cmd_lock`** — GUI и голос должны сериализоваться.

## 📦 Как добавить новый интент

### 1. Быстрое правило (без LLM)

**Добавь функцию** `my_handler(handler, cmd) -> str | None` в модуль
`jarvis/intents/fast/<name>.py`:

```python
def my_handler(handler, cmd: str) -> str | None:
    if "моя команда" not in cmd:
        return None
    return "Готово."
```

**Зарегистрируй** её в реестре — `jarvis/intents/fast/__init__.py` →
`build_registry()`:

```python
def build_registry(handler) -> list:
    return [
        ...,
        ("my_handler", lambda cmd: my_handler(handler, cmd)),
    ]
```

**Порядок важен.** Специфичные — выше общих.

### 2. Через LLM

В `jarvis/brain.py`, в `ACTIONS` — добавь action:

```python
ACTIONS = {
    ...,
    "my_new_action",
}
```

В `SYSTEM_SMALL` / `SYSTEM_MEDIUM` / `SYSTEM_LARGE` — добавь описание и пример.

В `jarvis/intents/execute.py` — добавь обработчик `_do_*` и зарегистрируй его
в `_DISPATCH` (в конце файла):

```python
def _do_my_new_action(handler, intent, target, query):
    ...
    return "Готово."

_DISPATCH = {
    ...,
    "my_new_action": _do_my_new_action,
}
```

## 📦 Как добавить новый пак

1. Создай `packs/my_pack.json`:

```json
[
  {"phrases": ["моя команда"], "action": "open_app:discord", "reply": "Открываю."}
]
```

2. В `config.json`:

```json
"active_packs": ["apps", "games", "sites", "system", "work", "my_pack"]
```

3. **Проверь:** «какие паки» → должен появиться `my_pack`.

## 📦 Как добавить свою фразу

1. В `%APPDATA%\Phoenix\config.json` → `custom_commands`:

```json
{
  "phrases": ["открой мой сайт"],
  "action": "https://example.com",
  "reply": "Открываю."
}
```

2. **Проверь:** скажи «открой мой сайт» → откроется `example.com`.

## 📦 Как добавить новый TTS-голос

Голоса задаются в **классе движка** (`jarvis/tts_engines/`). Например Piper —
`jarvis/tts_engines/piper.py` → `PiperEngine.voices`:

```python
class PiperEngine:
    voices = {
        ...,
        "my_voice": "Мой голос — описание",
    }
```

Для Silero (`tts_engines/silero.py`) и WinRT (`tts_engines/winrt.py`) — так же,
в `voices` соответствующего класса.

2. Скачай модель с HuggingFace: `rhasspy/piper-voices` → `ru/ru_RU/my_voice/medium/`
   (для Silero голоса уже внутри `snakers4/silero-models`).

3. (Опционально) алиас русского имени — `jarvis/voices.py` → `_VOICE_ALIASES`.

4. **Проверь:** «смени голос на мой голос» → должен переключиться.

## 🚨 Если что-то сломалось

1. **Посмотри `%APPDATA%\Phoenix\logs\errors.log`** — там трейсбек.
2. **Посмотри `%APPDATA%\Phoenix\logs\actions.log`** — там команды и интенты.
3. **Посмотри `%APPDATA%\Phoenix\logs\launcher.log`** — если проблема с запуском.
4. **Проверь Event Viewer** — `eventvwr.msc` → Application / System.
5. **Запусти `check_all.bat`** — синтаксис, pytest, интенты, стресс: сразу видно, что упало.
6. **Сузь поиск** — `python tests/test_intents.py -k <фраза>` или `python tests/stress_intents.py -k <имя>`.
7. **Откати коммит** — если совсем плохо:

```bat
git reset --hard HEAD~1
```

## 📋 Чек-лист перед коммитом

- [ ] `check_all.bat` — «ВСЁ ОТЛИЧНО» (синтаксис + pytest + интенты + стресс).
- [ ] `python -m pytest tests/ -q` — все тесты зелёные.
- [ ] `python tests/test_intents.py` + `python tests/stress_intents.py` — интенты и 100 ситуаций проходят.
- [ ] **Не коммичу** `.venv311`, `config.json`, `profiles/`, `system_caps.json`, `timers.json`, `tasks.json`, `models/`, `voices/`, `dist/`, `build/`.
- [ ] **Проверил** `git status` — нет лишних файлов.
- [ ] **Личные данные** не попали в публичные файлы.
- [ ] **Attribution `jsays12`** на месте.
- [ ] **Сообщение коммита** — понятное.

## 🤝 Как задавать вопросы

**Хорошо:**

> Брат, `_open_fast` не срабатывает для «открой спотифай». Вот лог: `...`.
> Где копать?

**Плохо:**

> Ничего не работает, помоги!

**Хорошо:**

> Брат, вот скриншот лога. Вижу `match_score: 0.46` для Spotify. Что делаем?

**Плохо:**

> Посмотри логи.

## 🎯 Философия

1. **Стабильность важнее фич.** Сначала багфиксы, потом новые возможности.
2. **Логи — источник истины.** Если в логе нет — значит не было.
3. **Тесты — страховка.** Не пиши код без тестов, если он трогает интенты.
4. **Простота — залог долговечности.** Если решение сложное — упрости.
5. **Один патч — одна задача.** Не смешивай фикс бага и новую фичу.
6. **Пути — через `paths.py`.** Никаких `Path.home()` в коде.
7. **Модели — в ASCII.** Vosk не переваривает кириллицу в пути.
8. **Тесты и CI — святое.** Красный CI — стоп всему.
9. **Attribution — не трогать.** Мы форк, и указываем источник.
10. **Один `cmd_lock`.** GUI и голос — не параллельно.

---

**Погнали, брат.** 🚀