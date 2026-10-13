# AGENTS.md — шпаргалка для AI-агентов

> **Начинай с ЭТОГО файла.** `README.md` (732 стр), `PLAN.md` (706),
> `ARCHITECTURE.md` (728), `CHANGELOG.md` (777), `PROJECT.md` (350) и особенно
> `SNAPSHOT.md` (1 МБ, 22 650 стр) — **не читать целиком**: всё прочитанное висит
> в контексте и переотправляется на каждом следующем шаге.
> Нужен факт — искать `grep`/`search_codebase`, затем читать 20–40 строк вокруг.
> Источник правды по инвариантам и правилам кода — `PROJECT.md` (по разделам, не целиком).

## Проект

Феникс — локальный голосовой ассистент для Windows, форк `jsys12/jarvis`.
GUI — Flet, STT — Vosk/Whisper, TTS — несколько движков, LLM — Ollama (локально),
семантика/интенты — собственный пакет `jarvis/intents/`.

- Python **3.11.9**, окружение — **`.venv311`** (только оно).
- Корень проекта: `c:\jarvis`, пакет — `jarvis/` (39 модулей + `intents/`, `sounds/`, `tts_engines/`).
- `jarvis/intents/` — 39 модулей: `handler.py` (IntentHandler), `execute.py`
  (исполнитель команд), `stages/`, `fast/` (быстрые обработчики).

## Команды (PowerShell, из `c:\jarvis`)

```powershell
.\.venv311\Scripts\python.exe check_all.py            # 4 шага + компактный итог (лучший вариант)
.\.venv311\Scripts\python.exe -m pytest tests/ -q     # юнит-тесты: 317
.\.venv311\Scripts\python.exe tests/test_intents.py   # интент-тесты: 39 кейсов (7 — только с --llm/--network)
.\.venv311\Scripts\python.exe tests/stress_intents.py # стресс: 100 ситуаций
.\.venv311\Scripts\python.exe check_syntax.py         # синтаксис всех .py (129 файлов)
.\.venv311\Scripts\python.exe snapshot.py             # пересобрать SNAPSHOT.md
.\.venv311\Scripts\python.exe snapshot.py --check     # проверка актуальности снимка
.\.venv311\Scripts\python.exe launcher.py             # автозапуск приложения
```

CI (`.github/workflows/test.yml`): `check_syntax.py` → `pytest -q` →
`test_intents.py` → `stress_intents.py`. `snapshot.py --check` в CI **не** гоняется,
но: добавил/удалил файл или поменял код — **пересобери `SNAPSHOT.md`**
(`python snapshot.py`), на него смотрят люди и `CONTRIBUTING.md`.

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
| `jarvis/main.py` | 631 | точка входа: конфиг → GUI → голосовой цикл |
| `jarvis/gui.py` | 1886 | Flet GUI, палитры, вкладки, анимации |
| `jarvis/actions.py` | 973 | низкоуровневые действия ОС (запуск, окна, звук) |
| `jarvis/intents/` | пакет | `handler.py` — `IntentHandler`, `execute.py` — исполнитель, `stages/`, `fast/` |
| `jarvis/uia.py` | 800 | UI Automation: окна, вкладки браузеров |
| `jarvis/brain.py` | 742 | LLM (Ollama) + системные промпты |
| `jarvis/stt.py` / `vad.py` / `tts.py` / `tts_engines/` | 573 / 465 / 313 | распознавание, VAD, синтез |
| `jarvis/profile.py` / `config.py` / `paths.py` | 360 / 207 / 168 | данные, настройки, пути |
| `jarvis/installed.py` / `steam.py` / `apps.py` | 42 / 56 / 98 | индексы «Пуска» и Steam |
| `jarvis/mood.py` / `prosody.py` / `persona.py` / `observer.py` | 306 / 119 / 174 / 165 | «личность» и эмоции |
| `jarvis/timers.py` / `tasks.py` / `weather.py` / `tray.py` | 283 / 194 / 330 / 145 | таймеры, задачи, погода, трей |
| `launcher.py` / `snapshot.py` / `check_all.py` | 693 / 698 | автозапуск / снимок / проверки |
| `tests/` | — | `test_*.py` (pytest), `test_intents.py`, `stress_intents.py`, `manual/` |

## Ключевые API

- `from jarvis.intents import IntentHandler`; `IntentHandler(config, apps, jarvis)`.
- `handler.handle(cmd)` → `Reply`; если `reply.is_stream` — собрать поток и вызвать
  `handler.finalize_stream(text)`.
- `handler.installed` — dict «имя → путь к .exe», `handler.steam_games` — list.
  Оба — **ленивые свойства**: индекс собирается в фоновом потоке при старте
  (`jarvis/intents/handler.py`, `_warm_indexes`), первый доступ дожидается потока.
- `jarvis/packs.py` + `jarvis/packs/*.json` — паки команд (apps, games, sites, system, work).
- `jarvis/config.py` — `load_config()`, `subscribe()` (дефолты — через `jarvis/paths.py`).

## Экономия (обязательно к исполнению)

Полный список — в `.clinerules`. Коротко: **батчить** независимые вызовы в один ответ,
читать **диапазонами**, выводить **итоговыми строками**, не перечитывать файл после правки
(вместо этого `git --no-pager diff -- <файл>`), ответ — **до 5 строк**.

