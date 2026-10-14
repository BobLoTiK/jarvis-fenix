# AGENTS.md — шпаргалка для AI-агентов

> **Начинай с ЭТОГО файла.** `README.md` (967 стр), `PLAN.md` (1005),
> `ARCHITECTURE.md` (919), `CHANGELOG.md` (916), `PROJECT.md` (219) и особенно
> `SNAPSHOT.md` (≈1 МБ, ≈28 тыс. стр) — **не читать целиком**: всё прочитанное висит
> в контексте и переотправляется на каждом следующем шаге.
> Нужен факт — искать `grep`/`search_codebase`, затем читать 20–40 строк вокруг.
> Источник правды по инвариантам и правилам кода — `PROJECT.md` (по разделам, не целиком).

## Проект

Феникс — локальный голосовой ассистент для Windows, форк `jsys12/jarvis`.
GUI — Flet, STT — Vosk/Whisper, TTS — несколько движков, LLM — Ollama (локально),
семантика/интенты — собственный пакет `jarvis/intents/`.

- Python **3.11.9**, окружение — **`.venv311`** (только оно).
- Корень проекта: `c:\jarvis`, пакет — `jarvis/` (40 модулей + `intents/`, `sounds/`, `tts_engines/`).
- `jarvis/intents/` — 39 модулей: `handler.py` (IntentHandler), `execute.py`
  (исполнитель команд), `stages/`, `fast/` (быстрые обработчики).

## Команды (PowerShell, из `c:\jarvis`)

```powershell
.\.venv311\Scripts\python.exe check_all.py            # 4 шага + компактный итог (лучший вариант)
.\.venv311\Scripts\python.exe -m pytest tests/ -q     # юнит-тесты: 349
.\.venv311\Scripts\python.exe tests/test_intents.py   # интент-тесты: 39 кейсов (7 — только с --llm/--network)
.\.venv311\Scripts\python.exe tests/stress_intents.py # стресс: 100 ситуаций
.\.venv311\Scripts\python.exe check_syntax.py         # синтаксис всех .py (131 файл)
.\.venv311\Scripts\python.exe snapshot.py             # пересобрать SNAPSHOT.md
.\.venv311\Scripts\python.exe snapshot.py --check     # проверка актуальности снимка
.\.venv311\Scripts\python.exe launcher.py             # автозапуск приложения
```

CI (`.github/workflows/test.yml`): `check_syntax.py` → `snapshot.py --check` →
`pytest -q` → `test_intents.py` → `stress_intents.py`. Снимок устарел — CI
красный: локально `python snapshot.py`. В `requirements-ci.txt` есть `flet`
(иначе `tests/test_gui_wiring.py` скипается и ~500 строк GUI-проверок не бегут).

Ожидаемые длины вывода в консоль обрезать: `| Select-Object -Last 15`.

## Правила чтения (главная экономия)

| Не читать целиком | Чем заменить |
|---|---|
| `SNAPSHOT.md` (1 МБ) | ничем — он в `.clineignore`, все ключевые факты есть здесь |
| `CHANGELOG.md`, `PLAN.md`, `ARCHITECTURE.md`, `CI.md` | `search_codebase` → чтение диапазона строк |
| `README.md`, `PROJECT.md`, `PROMPT.md`, `CONTRIBUTING.md` | только `start_line`/`end_line` |
| любой `.py` длиннее 400 строк | сначала поиск, потом один диапазон |
| `logs/*` (≈1 МБ) | `Select-String` / `Get-Content -Tail 20` |

Порядок всегда один: **поиск → точный диапазон**. Не «прочитаю файл, чтобы понять».
Перед правкой файла — прочитать только тот участок, который меняется.

## Конвенции кода

- Файлы — **UTF-8 без BOM, CRLF**. Правки не должны менять ни то, ни другое.
- Пути — **только через `jarvis/paths.py`**: `USER_DIR` (настройки, логи, профили —
  кириллица допустима), `PROGRAM_DIR` (**только ASCII** — там модели Vosk/Whisper,
  Vosk падает на не-ASCII пути).
- Запись файлов — **атомарная**; данные пользователя — в `USER_DIR`, не в папку кода.
- **Никаких новых зависимостей** без явной просьбы (CI ставит `requirements*.txt`).
- Flet 1.x: кнопка — **`ft.Button`** (`ElevatedButton`/`TextButton` удалены).
- Атрибуция: оригинальный код — собственность `jsys12` (см. `LICENSE`, `PROJECT.md`).
- Личные данные (`config.json`, `profiles/`, `dialog.json`) — не в git и не в контекст.

## Карта кода

| Файл | Строк | О чём |
|---|---|---|
| `jarvis/main.py` | 779 | точка входа: конфиг → GUI → голосовой цикл |
| `jarvis/gui.py` | 2196 | Flet GUI, палитры, вкладки, анимации |
| `jarvis/actions.py` | 1160 | низкоуровневые действия ОС (запуск, окна, звук) |
| `jarvis/intents/` | 253+877 | `handler.py` — `IntentHandler`, `execute.py` — исполнитель, `stages/`, `fast/` |
| `jarvis/uia.py` | 969 | UI Automation: окна, вкладки браузеров |
| `jarvis/brain.py` | 831 | LLM (Ollama) + системные промпты |
| `jarvis/safety.py` | 197 | постфильтр ответов LLM («красная черта») перед TTS |
| `jarvis/stt.py` / `vad.py` / `tts.py` / `tts_engines/` | 651 / 567 / 367 | распознавание, VAD, синтез |
| `jarvis/profile.py` / `config.py` / `paths.py` | 451 / 257 / 216 | данные, настройки, пути |
| `jarvis/installed.py` / `steam.py` / `apps.py` | 51 / 67 / 114 | индексы «Пуска» и Steam |
| `jarvis/mood.py` / `prosody.py` / `persona.py` / `observer.py` | 388 / 152 / 219 / 201 | «личность» и эмоции; observer по умолчанию ВЫКЛ |
| `jarvis/timers.py` / `tasks.py` / `weather.py` / `tray.py` | 340 / 236 / 394 / 176 | таймеры, задачи, погода, трей |
| `launcher.py` / `snapshot.py` / `check_all.py` | 693 / 698 / 170 | автозапуск / снимок / проверки |
| `tests/` | — | `test_*.py` (pytest, 349 тестов), `test_intents.py`, `stress_intents.py`, `manual/` |

## Ключевые API

- `from jarvis.intents import IntentHandler`; `IntentHandler(config, apps, jarvis)`.
- `handler.handle(cmd)` → `Reply`; если `reply.is_stream` — собрать поток и вызвать
  `handler.finalize_stream(text)`.
- `handler.installed` — dict «имя → путь к .exe», `handler.steam_games` — list.
  Оба — **ленивые свойства**: индекс собирается в фоновом потоке при старте
  (`jarvis/intents/handler.py`, `_warm_indexes`), первый доступ дожидается потока.
- `jarvis/packs.py` + `jarvis/packs/*.json` — паки команд (apps, games, sites, system, work).
- `jarvis/config.py` — `load_config()`, `subscribe()` (дефолты — через `jarvis/paths.py`).
- `jarvis/safety.py` — `check_response(text)` → `(ok, reason)`, `guard_stream(chunks, state)`;
  вызывается из `Jarvis._say_text` / `_say_stream`: заблокированное не озвучивается.

## Экономия (обязательно к исполнению)

Полный список — в `.clinerules`. Коротко: **батчить** независимые вызовы в один ответ,
читать **диапазонами**, выводить **итоговыми строками**, не перечитывать файл после правки
(вместо этого `git --no-pager diff -- <файл>`), ответ — **до 5 строк**.

