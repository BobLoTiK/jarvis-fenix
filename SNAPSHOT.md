# SNAPSHOT проекта «Феникс»

_Автоматически сгенерировано `snapshot.py`. Обновляется при `git push`._
_Файлов в снимке: 73_

---

## 📁 Структура проекта

```
jarvis/
├── .github/
│   ├── workflows/
│   │   ├── README.md
│   │   ├── test.yml
├── cmds/
│   ├── open_terminal.bat
│   ├── show_ip.bat
├── jarvis/
│   ├── __init__.py
│   ├── __main__.py
│   ├── actions.py
│   ├── apps.py
│   ├── brain.py
│   ├── config.py
│   ├── config_manager.py
│   ├── files.py
│   ├── gui.py
│   ├── history.py
│   ├── installed.py
│   ├── intents.py
│   ├── learning.py
│   ├── main.py
│   ├── matching.py
│   ├── memory.py
│   ├── model.py
│   ├── modes.py
│   ├── packs.py
│   ├── profile.py
│   ├── recorder.py
│   ├── reply.py
│   ├── steam.py
│   ├── stt.py
│   ├── tasks.py
│   ├── timers.py
│   ├── tray.py
│   ├── tts.py
│   ├── voices.py
│   ├── weather.py
├── packs/
│   ├── apps.json
│   ├── games.json
│   ├── sites.json
│   ├── system.json
│   ├── work.json
├── profiles/
│   ├── maksim/
│   │   ├── profile.json
├── scripts/
│   ├── __init__.py
│   ├── build_exe.py
│   ├── check_caps.py
│   ├── mics.py
│   ├── selftest.py
│   ├── set_llm_model.py
│   ├── voicedemo.py
│   ├── wakebench.py
├── tests/
│   ├── test_caps.py
│   ├── test_config_manager.py
│   ├── test_weather.py
├── ARCHITECTURE.md
├── CHANGELOG.md
├── check_all.bat
├── check_syntax.bat
├── check_syntax.py
├── CI.md
├── config.example.json
├── CONTRIBUTING.md
├── install.bat
├── launcher.py
├── PLAN.md
├── PROMPT.md
├── README.md
├── requirements-ci.txt
├── requirements-dev.txt
├── requirements.txt
├── snapshot.py
├── start_fenix.bat
├── start_fenix_debug.bat
├── system_caps.json
├── test_intents.py
├── вкладка
```

---

## 📄 Содержимое файлов

### `.github\workflows\README.md`

```markdown
# Workflows

## test.yml

Основной CI. Запускается при `push` и `pull_request` в `main` / `master`.

**Что делает:**
1. Windows-виртуалка, Python 3.11, кэш pip.
2. `pip install -r requirements-ci.txt`.
3. `python check_syntax.py`.
4. `python -m pytest tests/ -q`.
5. `python test_intents.py` (без флагов).

**Env:**
- `PYTHONUTF8=1` — UTF-8 mode интерпретатора.
- `PYTHONIOENCODING=utf-8` — для stdout/stderr.

**Timeout:** 15 минут.

**Если упало** — см. `CI.md` в корне репозитория.

## Как добавить новый workflow

Создай файл `.github/workflows/<name>.yml`:

```yaml
name: my-workflow
on: [push]
jobs:
  my-job:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: python my_script.py
```
```

### `.github\workflows\test.yml`

```yaml
# ============================================================
# GitHub Actions: автоматическая проверка при каждом push.
#
# Что делает:
#   1. Поднимает виртуалку с Windows.
#   2. Ставит Python 3.11.
#   3. Ставит лёгкие зависимости (requirements-ci.txt).
#   4. Проверяет синтаксис (check_syntax.py).
#   5. Гоняет pytest (tests/).
#   6. Гоняет test_intents.py (без LLM, без сети, без озвучки).
#
# Где смотреть результат:
#   На GitHub → вкладка "Actions" → последний запуск.
#
# Файл лежит в: .github/workflows/test.yml
# ============================================================

name: tests

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

jobs:
  test:
    runs-on: windows-latest
    timeout-minutes: 15

    # PYTHONUTF8=1 — включает UTF-8 mode интерпретатора.
    # Страховка от UnicodeEncodeError в cp1252-консоли GitHub Actions.
    # В коде тоже есть reconfigure — здесь глобально на весь job.
    env:
      PYTHONUTF8: "1"
      PYTHONIOENCODING: "utf-8"

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install dependencies
        run: pip install -r requirements-ci.txt

      - name: Check syntax
        run: python check_syntax.py

      - name: Unit tests (pytest)
        run: python -m pytest tests/ -q

      - name: Intent tests (без LLM, без сети, без озвучки)
        run: python test_intents.py
```

### `ARCHITECTURE.md`

```markdown
# 🏗 Архитектура «Феникс»

Документ описывает модули проекта, их роль и связи.
Помогает быстро вникнуть в проект — человеку или LLM.

---

## Карта модулей

```text
jarvis/
├── main.py           — точка входа, класс Jarvis, barge-in цикл
├── config.py         — объект Config в памяти + подписки
├── config_manager.py — атомарная запись config.json (один FileLock)
├── brain.py          — LLM (Ollama): parse() и chat_stream()
├── intents.py        — IntentHandler: правила + LLM + _fast_handlers()
├── reply.py          — тип Reply (text | stream)
├── gui.py            — Flet GUI + PALETTES + _detect_system_theme()
├── history.py        — стек отмены («стоп, не то»)
├── stt.py            — Vosk (wake) + Whisper, ring buffer
├── tts.py            — Piper / XTTS / WinRT / SAPI, Streaming TTS, per-call token
├── modes.py          — режимы commands / llm / combo
├── voices.py         — смена голоса Piper
├── packs.py          — загрузка/выгрузка паков
├── profile.py        — profiles/<user>/profile.json + subscribe
├── memory.py         — profiles/<user>/dialog.json
├── learning.py       — факты + коррекции
├── weather.py        — погода (open-meteo) и курс (ЦБ РФ) + настраиваемый TTL
├── timers.py         — напоминания
├── tasks.py          — списки задач
├── actions.py        — окна, медиа, печать, буфер, громкость, яркость, раскладка,
│                       open_in_editor, _activate_window_hard
├── files.py          — папки (Desktop, Downloads, ...)
├── apps.py           — каталог приложений
├── installed.py      — индекс меню «Пуск»
├── steam.py          — индекс игр Steam
├── matching.py       — нечёткое сравнение + транслитерация
├── model.py          — загрузка Vosk-модели
├── recorder.py       — запись макросов
└── tray.py           — иконка в трее
```

---

## Поток обработки фразы

```text
Микрофон
   ↓
stt.Listener (Vosk) — ловит wake-слово
   ↓
stt.WhisperTranscriber — уточняет расшифровку
   ↓
main.Jarvis._process → извлекает команду (без wake-слова)
   ↓
intents.IntentHandler.handle(cmd)   ← normalize(cmd)
   ├── CANCEL («стой», «хватит», ...)
   ├── Коррекции (learning.find_correction)
   ├── Пароль (pending_password)
   ├── Удаление профиля
   ├── Память диалога (memory.handle_memory_command)
   ├── pending_question (уточнения)
   ├── Буфер обмена (4 проверки)
   ├── Режимы (modes)
   ├── Custom / small_talk / скриншот
   ├── _split_compound (многослойные)
   ├── ⚡ РЕЕСТР _fast_handlers()  ← здесь ВСЕ быстрые правила
   │   ├── custom, small_talk, music, open_profile
   │   ├── open, voices, packs, timers, tasks
   │   └── profile, memory, system, debug, correction,
   │       undo, weather_currency
   ├── brain.parse(cmd) → intent → _execute_intent
   └── brain.chat_stream() → генератор
   ↓
main.Jarvis.say(reply)
   ├── если text → speaker.play_async()
   └── если stream → speaker.speak_stream() + tee → gui.add_stream_chunk()
   ↓
tts.Speaker → Piper / XTTS / WinRT / SAPI
```

---

## Реестр быстрых обработчиков

`IntentHandler._fast_handlers()` — **список `(имя, функция)`**. Порядок = приоритет.

Каждый обработчик: `(cmd: str) -> str | None`. Если вернул строку — команда обработана. Если `None` — идём к следующему.

**Правило:** специфичные — **выше** общих. Например, `open_profile` — **выше** `open` (иначе `_open_fast` съест «открой профиль»).

**Сейчас:**

```python
[
    ("custom", self._match_custom),
    ("small_talk", self._small_talk),
    ("music", self._music_fast),
    ("open_profile", self._open_profile_fast),   # ВЫШЕ open
    ("open", self._open_fast),
    ("voices", lambda cmd: voices.handle_voice_command(cmd, self.config)),
    ("packs", self._packs_handler),              # side-effect: active_packs
    ("timers", timers.handle_timer_command),
    ("tasks", tasks.handle_task_command),
    ("profile", self._profile_fast),
    ("memory", self._memory_fast),
    ("system", self._system_fast),
    ("debug", self._debug_fast),
    ("correction", self._correction_fast),
    ("undo", self._undo_fast),
    ("weather_currency", self._weather_currency_fast),
]
```

**Добавить новый обработчик** — **одна строка** в список, **не искать место в 22 if**.

**Обработчики со side-effect** (например, `packs`, меняющий `self.active_packs`) — **обёртки** с методом (`_packs_handler`).

**Исключения** в обработчике **логируются** через `log.exception`, но **не роняют** команду — идём к следующему.

---

## Универсальный профиль (set_profile / get_profile)

**Раньше:** куча `re.match` под каждую фразу — «мой город X», «меня зовут Y», «поменяй город Z», ... **Костыли.**

**Сейчас:** LLM **сама разбирает**, что нужно:

```
Пользователь: «меня зовут Максим»
LLM: {"action": "set_profile", "key": "name", "value": "Максим"}

Пользователь: «какой город»
LLM: {"action": "get_profile", "key": "default_city"}
```

**В `brain.py`** — `set_profile` и `get_profile` **в `ACTIONS`** + **примеры в промптах**.

**В `intents._execute_intent`** — обработка:

```python
if action == "set_profile":
    key = intent.get("key")
    value = intent.get("value")
    key_map = {"имя": "name", "город": "default_city", ...}
    key = key_map.get(key.lower(), key.lower())
    ...
    ok = profile.set(key, value)
    return f"Имя изменено на {value}." if key == "name" else ...
```

**Никаких костылей** — **любая фраза** через LLM.

---

## GUI (Flet 1.0.3)

```text
Flet Main Thread
   ├── NavigationRail (слева): Главная / Микрофон / Настройки
   ├── Контент-область (кеш _tabs):
   │   ├── Главная: статус-сфера, контролы, чат, ввод
   │   ├── Микрофон: прогресс-бар уровня + кнопка теста + dropdown
   │   └── Настройки: LLM / TTS / тема
   ├── page.run_task(_process_queue) — читает очередь
   └── page.run_task(_mic_level_loop) — уровень микрофона + смена темы

Jarvis Thread
   ├── listener.phrases() → _process(cmd)
   ├── handler.handle(cmd) → Reply
   └── say(reply):
       ├── text → gui.add_message("assistant", text)
       └── stream → tee → gui.add_stream_chunk(chunk)
```

**Связь:** `queue.Queue()` → `gui._queue`. `Jarvis` пишет, GUI читает в `_process_queue`.

**Важно:** Flet запускается в **главном потоке** (`gui.run_main()`), потому что ставит `signal.signal(SIGINT, ...)`. Jarvis — **в фоне**.

### Режим запуска (launch_mode)

**`config.json`:**

```json
"launch_mode": "gui"
```

- **`"gui"`** — окно Flet **видимо** при старте (по умолчанию).
- **`"tray"`** — окно **скрыто** (`page.window.visible = False`). Flet **всё равно запущен** — `show_window()` из трея показывает окно.

**Защита:** если `launch_mode="tray"`, но `tray_enabled=false` — автоматически переключается на `"gui"`.

**Трей:**
- **Двойной клик** по иконке → `on_show_window` (`default=True`).
- **Правый клик** → «Открыть окно», «Настройки», «Слушать микрофон», «Сделать скриншот», «Открыть конфиг», «Открыть журнал», «Выход».

### Темы GUI

```text
PALETTES = {
    "dark":  { bg_main, bg_card, bg_bubble_user, bg_bubble_ai, accent, text, text_dim, ... },
    "light": { bg_main, bg_card, bg_bubble_user, bg_bubble_ai, accent, text, text_dim, ... },
}

_apply_palette(name) — подменяет глобальные BG_DARK, TEXT, ACCENT.

_detect_system_theme() — читает HKCU\...\Themes\Personalize\AppsUseLightTheme.
    0 = dark, 1 = light.

_on_theme_change → _apply_palette + _rebuild_ui_for_theme.
_mic_level_loop  → раз в 2 сек проверяет тему Windows (если gui_theme = "Системная").
_rebuild_ui_for_theme → сохраняет историю чата (_history_list.controls) перед пересборкой.
```

### Вкладка «Микрофон»

- `Listener.current_rms` — текущий RMS, обновляется в `_callback`.
- `Listener.peak` — пик за сессию.
- `Listener.utterances` — сколько фраз распознано.
- `Listener.reset_stats()` — сброс для кнопки «Проверить».
- `_on_mic_test` — 3 сек, показывает результат (≥500 ✅, ≥100 ⚠️, <100 ❌).
- `_update_mic_level` — обновляет прогресс-бар.
- `mic_watchdog` → `("open_mic_tab", None)` в очередь GUI.

---

## Мультипрофиль

```text
profiles/
├── <user1>/
│   ├── profile.json    ← name, default_city, facts, tts_voice,
│   │                     persona (в планах), onboarding_done (в планах)
│   └── dialog.json     ← история диалога
├── <user2>/
│   ├── profile.json
│   └── dialog.json
└── ...
```

- **Активный профиль** — по имени Windows-юзера (`getpass.getuser()`).
- **`profile.switch(name)`** — переключение («я — Маша»). **Один `RLock`** — гонка исключена.
- **`profile.subscribe(callback)`** — подписка на смену (old_name, new_name).
- **`IntentHandler._on_profile_switch`** — перечитывает `dialog`.
- **`FenixGUI._on_profile_switch`** — `rebuild_ui` (пересборка вкладок с **сохранением истории**).
- **Миграция** из старого `user_profile.json` при первом запуске.
- **`.gitignore`:** `profiles/`.

### Универсальные команды профиля

- «меня зовут X» → `set_profile` → `name`.
- «мой город Y» → `set_profile` → `default_city`.
- «поменяй город на Z» → `set_profile` → `default_city` + `prev_city`.
- «как меня зовут» → `get_profile` → `name`.
- «какой город» → `get_profile` → `default_city`.
- «открой профиль» → `open_profile` → Notepad++ / VS Code / системный.
- «что ты обо мне знаешь» → `_profile_fast` → name, default_city, facts.

---

## Поток конфига

```text
config.json → Config.__init__ → config_manager.load() (один раз)
   ↓
Config._data (в памяти) — источник истины
   ↓
config.get("key") / config.set("key", value)
   ├── config_manager.save() — атомарно
   └── Оповещение подписчиков:
       ├── "tts_voice" → speaker.set_voice()
       ├── "voice_rate" → speaker.set_rate()
       ├── "mode" → handler.mode
       ├── "barge_enabled" → jarvis.barge_enabled
       ├── "memory_max" → handler._memory_max + deque
       ├── "llm_context_messages" → handler._llm_context
       └── "gui_theme" → PALETTES + _rebuild_ui_for_theme
```

**Подписки:**
- `Config.subscribe(callback)` — добавить.
- `Config.unsubscribe(callback)` — удалить.

---

## Погода и курс валют

```text
weather.py
   ├── _CACHE: dict = {}          ← (key, timestamp, data)
   ├── _CACHE_LOCK: threading.Lock
   ├── _config = None             ← ссылка на Config (через set_config)
   │
   ├── set_config(config)          ← вызывается из main.py
   ├── _current_ttl() → int        ← читает weather_cache_ttl_sec каждый раз
   └── _cached(key, fetcher)       ← TTL применяется на каждый вызов
```

**TTL:** `weather_cache_ttl_sec` — по умолчанию `600` (10 мин), для Local — `86400` (24 ч).

**Ключи кэша:**
- `("geo", "москва")` — геокодинг.
- `("weather", "москва", "today")` / `("weather", "москва", "tomorrow")` — погода.
- `("currency", "cbr")` — курс ЦБ.

---

## Открытие файлов в редакторе

```text
actions.open_in_editor(path, prefer="auto")
   ├── prefer="notepad++" → _find_notepadpp()
   ├── prefer="vscode"    → _find_vscode()
   ├── prefer="system"    → os.startfile()
   └── prefer="auto"      → [_find_notepadpp, _find_vscode] → os.startfile()

_find_notepadpp():
   C:\Program Files\Notepad++\notepad++.exe
   C:\Program Files (x86)\Notepad++\notepad++.exe
   %LOCALAPPDATA%\Notepad++\notepad++.exe
   shutil.which("notepad++")

_find_vscode():
   %LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe
   C:\Program Files\Microsoft VS Code\Code.exe
   shutil.which("code")
```

**Активация окна** — `_activate_window_hard(title_part)`:

- `win32gui.EnumWindows` — поиск по заголовку.
- `AttachThreadInput` — **трюк**, чтобы Windows разрешила `SetForegroundWindow`.
- `SetForegroundWindow` + `BringWindowToTop` — окно **всплывает**.

**Вызов из `_open_profile_fast`:**

```python
prof_path = profile.profile_path()
ok = actions.open_in_editor(prof_path, prefer=prefer)
```

**Редактор** — по фразе:
- «открой профиль» → auto.
- «открой профиль в вс код» → vscode.
- «открой профиль в блокноте» → system.

---

## Ключевые объекты

| Объект | Модуль | Роль |
|---|---|---|
| `Config` | `config.py` | Конфиг в памяти + подписки |
| `IntentHandler` | `intents.py` | Разбор команд, `_fast_handlers()` — реестр |
| `Brain` | `brain.py` | LLM: `parse()` и `chat_stream()` |
| `Speaker` | `tts.py` | Синтез + воспроизведение, per-call token |
| `Listener` | `stt.py` | Микрофон, Vosk, ring buffer, current_rms |
| `WhisperTranscriber` | `stt.py` | Точная расшифровка |
| `Jarvis` | `main.py` | Связка всего, wake-логика, mic_watchdog |
| `FenixGUI` | `gui.py` | Flet GUI, PALETTES, mic_level_loop |
| `Reply` | `reply.py` | `text` \| `stream` |
| `history` | `history.py` | Стек отмены |

---

## Файлы данных (не в гит)

| Файл | Что хранит |
|---|---|
| `config.json` | Настройки |
| `profiles/<user>/profile.json` | Имя, город, факты, persona |
| `profiles/<user>/dialog.json` | История диалога |
| `profiles/<user>/custom_commands.json` | Мои команды (в планах) |
| `timers.json` | Напоминания |
| `tasks.json` | Задачи |
| `system_caps.json` | Возможности системы (volume/brightness/layout/cpu) |
| `logs/` | Логи |
| `config.json.lock` | FileLock |

**Все эти файлы — в `.gitignore`.**

---

## Внешние зависимости

| Сервис | URL | Зачем |
|---|---|---|
| Ollama | `http://127.0.0.1:11434` | LLM |
| open-meteo.com | `geocoding-api.open-meteo.com` | Геокодинг |
| open-meteo.com | `api.open-meteo.com` | Погода |
| cbr-xml-daily.ru | `www.cbr-xml-daily.ru` | Курс ЦБ |
| HuggingFace | `rhasspy/piper-voices` | Голоса Piper |
| HuggingFace | `coriollon/whisper-large-v3-turbo-russian` | Whisper (в планах) |
| HuggingFace | `deepdml/faster-whisper-large-v3-turbo-ct2` | Whisper (текущая) |
| alphacephei.com | `vosk-model-small-ru-0.22` | Vosk |

**Облачные (в планах):**

| Сервис | URL | Зачем |
|---|---|---|
| Groq | `api.groq.com` | LLM (Llama 3.3 70B), STT (Whisper) |
| Microsoft Edge | `edge-tts` | TTS |

---

## Тесты

- **`test_intents.py`** — 40 сценариев (30 базовых + 2 danger + learning).
- **`tests/test_config_manager.py`** — параллельная запись.
- **`tests/test_weather.py`** — погода/курс с моками.
- **`tests/test_caps.py`** — структура `system_caps.json`.

---

## Инфраструктура

### `.venv311`

**Python 3.11** в **отдельном venv** — обход падения Vosk на Python 3.13/3.14.

- `.gitignore` — `.venv311/`.
- `snapshot.py` — `EXCLUDE_DIRS` содержит `.venv311`.
- `commit.bat`, `check_all.bat`, `check_syntax.bat` — активируют venv.

### Git

- **`.gitignore`:** `.venv311/`, `*.bak`, `config.json`, `profiles/`, `logs/`, `system_caps.json`, `models/`, `voices/`.
- **`SNAPSHOT.md`** — 520 КБ, обновляется при `commit.bat`.
- **`git filter-repo`** — `.venv311` вырезан из истории (`.git` = 12 МБ).

### `commit.bat`

Автокоммит:
1. Активирует `.venv311`.
2. Запускает `snapshot.py`.
3. `git add .`.
4. `git commit -m "%~1"`.
5. `git push`.

---

## Что важно помнить при доработке

1. **Не добавляй `_atomic_write`** — используй `config_manager.save()` или `Config.set()`.
2. **Не читай `config.json` напрямую** — `config.get()`.
3. **Не плоди глобальное состояние** — кроме `Config._GLOBAL`.
4. **Нормализация (города, валюты, паков) — задача LLM.**
5. **Логи в `actions.log`** — главный инструмент отладки.
6. **`test_intents.py`** — первое, что запускаешь после правок.
7. **GUI Flet — только в главном потоке.** Jarvis — в фоне.
8. **Связь GUI ↔ Jarvis — через `queue.Queue()`, не напрямую.**
9. **`normalize(cmd)` в `IntentHandler.handle()`** — единая точка.
10. **Per-call stop-token в `tts.py`** — не общий `_stop_flag`.
11. **`PALETTES` в `gui.py`** — две темы, `_detect_system_theme()` для системной.
12. **`ft.Button`** вместо `ElevatedButton`/`TextButton` в Flet 1.x.
13. **`ft.BoxShadow`** — без `blur_style` (в Flet 1.0.3 нет `ShadowBlurStyle`).
14. **Личные данные — только в `config.json`, `profiles/`, `system_caps.json`** (в `.gitignore`).
15. **`weather_cache_ttl_sec`** — настраиваемый TTL кэша погоды (600 по умолчанию, 86400 для Local).
16. **Python 3.10–3.12** — Vosk не работает на 3.13/3.14. Только `.venv311`.
17. **`snapshot.py`** — исключать `.venv311` (иначе `SNAPSHOT.md` = 52 МБ).
18. **Реестр `_fast_handlers()`** — новые быстрые правила добавляй **туда**, а не в 22 if.
19. **`open_profile` — выше `open`** в реестре (иначе `_open_fast` съест).
20. **`set_profile` / `get_profile`** — через LLM, без `re.match`-костылей.
21. **Активация окон — через `win32gui` + `AttachThreadInput`** (`pygetwindow` не работает).
```

### `CHANGELOG.md`

```markdown
# Changelog

Все значимые изменения проекта.
Формат: [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версии: [Semantic Versioning](https://semver.org/lang/ru/).

## [Unreleased] — 0.3.0

### Добавлено (сессия 06.10.2026, вечерняя)

- **`set_profile` / `get_profile`** — универсальные action'ы для LLM. Теперь «меня зовут X», «поменяй город на Y», «как меня зовут», «какой город» — **работают через LLM**, без костылей-`re.match`.
- **`open_profile`** — «открой профиль» → Notepad++ → VS Code → системный. Активация окна через `win32gui` + `AttachThreadInput`.
- **Реестр `_fast_handlers()`** в `intents.py` — вместо 22 `if reply: return reply`. Порядок = приоритет, легко добавить новый обработчик.
- **`launch_mode`** в config — `"gui"` (окно) или `"tray"` (только трей, окно скрыто).
- **Трей: «Открыть окно»** — двойной клик по иконке, `default=True`.
- **`_activate_window_hard`** в `actions.py` — надёжная активация через `win32gui`.

### Исправлено (сессия 06.10.2026, вечерняя)

- **№67** — «открой стим и запусти доту» — теперь **обе части**.
- **№68** — «открой ютуб и сделай громче» — не мусорный URL.
- **№69** — «сделай на 10 потише» — работает.
- **№70** — «аааааааа» — «Не расслышал».
- **№71** — `scripts/__init__.py` создан.
- **№72** — `speaker.wait_end` → `bool`.
- **№73** — стрим-пузырь не зависает.
- **№74** — TTS не накладывается.
- **№76** — `profile.switch` — один `RLock`.
- **№80** — Groq в README помечен «🚧 в планах».
- **№84** — `launch_mode` + защита от конфликта `tray_enabled`.
- **№88** — `launcher.py` мьютекс держит HANDLE.
- **№89** — `close_browser` убивает все браузеры.
- **№90** — `pystray.SystemExit` ловится.
- **№91** — `profiles/` убран из git.
- **№92** — `_tabs` не теряют историю чата при смене профиля.
- **№93** — `chat_stream` не теряет последний чанк.
- **№94** — `wake_score` — 4 явных сравнения.
- **№95** — `Config.unsubscribe`.
- **№96** — `SITES` из `packs/sites.json`.
- **№97** — `build_context` / `_profile_fast` без дублей.
- **№98** — `check_syntax.bat` — `%~dp0`.
- **№22** — падежи погоды.
- **№23** — LLM видит `name` / `default_city`.

### Исправлено (сессия 06.10.2026)

- **№26** — «открой стим» → «Открываю Spotify» (`_match_custom` ловил нечётко «стим» на «споти»).
- **№28** — «мой город казань» в фактах вместо `default_city`.
- **№29** — «мой город X» сохранялся как факт, а не `default_city`.
- **№31** — `_match_custom`: нечёткий матч только для фраз ≥ 12 символов.
- **№32** — **Vosk падает с access violation на Python 3.14** → переход на Python 3.11 через `.venv311`.
- **№34** — `.bat` и doskey: активация venv, `chcp 65001`, проверка `errorlevel`.
- **№35** — `.venv311` попал в git → `.gitignore`.
- **№36** — `SNAPSHOT.md` 52 МБ → 520 КБ (исключён `.venv311` из `snapshot.py`).
- **№37** — `.git` 110 МБ → 12 МБ (`git filter-repo`).
- **О9** — TTL кэша погоды: `weather_cache_ttl_sec` в config.
- **№39** — README: требование Python 3.10–3.12.

### Добавлено (сессия 06.10.2026)

- **`weather_cache_ttl_sec`** в config — настраиваемый TTL кэша погоды (по умолчанию 600 сек = 10 мин).
- **Специальные шаблоны в `_profile_fast`:**
  - «запомни: мой город X» / «мой город X» → `default_city`
  - «запомни: меня зовут X» / «меня зовут X» → `name`
  - «запомни: я живу в X» / «я живу в X» → `default_city`
- **Глобальный `threading.excepthook`** — падения в фоновых потоках логируются в `errors.log`.
- **`try/except SystemExit`** вокруг трея — pystray не роняет процесс.
- **`commit.bat`** — автокоммит с обновлением `SNAPSHOT.md` (активация venv + `chcp 65001`).

### Добавлено

- **Flet GUI** (`jarvis/gui.py`):
  - Окно 1100×760, тёмная тема.
  - NavigationRail — разделы: Главная, Микрофон, Настройки.
  - **Статус-сфера** с анимацией (смена цвета и размера).
  - **Чат-пузыри** с аватарами (👤 / 🦅), тенями, fade-in.
  - Поле ввода + кнопки Send / Mic.
  - **Настройки:** модель LLM, Ollama URL, TTS бэкенд, скорость речи (слайдер), тема.
  - **Смена темы на лету** (Тёмная / Светлая / Системная) — `PALETTES` + `_rebuild_ui_for_theme`.
  - **Системная тема** — автоопределение через реестр Windows (`_detect_system_theme`).
  - **Подхват смены темы Windows** — раз в 2 сек в `_mic_level_loop`.
  - **Стриминг в GUI** через tee-генератор в `main._say_stream`.
  - **Кеш разделов** — история чата не теряется при переключении.
  - **Микрофон:** выбор устройства + сохранение в config.
  - **Вкладка «Микрофон»:**
    - Прогресс-бар уровня сигнала в реальном времени.
    - Кнопка «🎙 Проверить микрофон (3 сек)».
    - Статус: ✅ Работает / ⚠️ Тихий / ⏸ Ожидание.
    - Автооткрытие по сигналу `mic_watchdog`.

- **Системные команды:**
  - **Раскладка RU/EN:** `switch_layout`, `set_layout_ru`, `set_layout_en`, `get_layout`. Через `SendInput`.
  - **Громкость в %:** `get_volume` / `set_volume` через `pycaw`.
  - **Яркость в %:** `get_brightness` / `set_brightness` через `screen-brightness-control`.

- **Диагностика:**
  - «Что ты слышал?» — ring buffer последних 10 фраз в `stt.Listener`.
  - «Почему не понял?» — `_last_debug` в `IntentHandler`.

- **Отмена действий (Н1):**
  - `jarvis/history.py` — стек последних 5 действий.
  - «Стоп, не то» / «отмени» — откат.
  - Отмена: `open_app` → `close_app`, `set_mode`, `change_voice`, `set_volume`, `set_brightness`, `switch_layout`.

- **Пароль на опасные (2.13):**
  - `danger_password` в config.
  - «Выключи компьютер» → запрос пароля.

- **Мультипрофиль:**
  - `profiles/<user>/profile.json` + `profiles/<user>/dialog.json`.
  - `profile.init()` — инициализация + миграция.
  - `profile.switch()`, `profile.delete()`, `profile.list_all()`.
  - `profile.subscribe()` — уведомление подписчиков при смене профиля.
  - Голосовые: «я — Маша», «кто активен», «список профилей», «запомни: …».

- **Память:** `memory.append(limit)`, `memory.load(limit)`, `memory.clear()`.
- **Лимиты в config:** `memory_max`, `llm_context_messages`, `danger_password`, `gui_enabled`, `gui_theme`, `gui_x`, `gui_y`, `tray_enabled`, `mic_watchdog_enabled`, `weather_cache_ttl_sec`.
- **CI:** `.github/workflows/test.yml` на `windows-latest`.

- **`mic_watchdog`:**
  - Одно предупреждение за сессию (не спамит).
  - Порог пика ≥ 50 (микрофон живой).
  - Автооткрытие вкладки «Микрофон» в GUI.
  - Опция `mic_watchdog_enabled` в config.

### Изменено

- `IntentHandler.handle()` → **`cmd = normalize(cmd)`** в начале (единая точка нормализации для GUI и голоса).
- `Jarvis.say()` → принимает `Reply`.
- `brain.chat_stream()` → без `[-40:]` (лимит у вызывающего).
- `_execute_steps` → сохранение `history` для отмены.
- `main.py` → **Jarvis в фоне**, **Flet в главном** (`gui.run_main()`).
- `requirements.txt` → `flet>=1.0.3`.
- **`tts.py`:** per-call stop-token вместо общего `_stop_flag`.
- **`gui.py`:** `PALETTES` (две темы), `_detect_system_theme()`, `_rebuild_ui_for_theme()`, `_mic_level_loop()`.
- **`profile.py`:** `_current_lock`, `_listeners`, `subscribe()`, `_on_profile_switch`.

### Исправлено

- **№1** — `profile._current` гонка. `threading.Lock`.
- **№2** — Маша видит диалог Максима. `profile.subscribe()` + `_on_profile_switch`.
- **№3** — `_awaiting_until` после `say()`. Перенесено **до** `say()`.
- **№6** — `CANCEL` не первым. В начало `_handle_single`.
- **№8** — `any([...])` в `_do_close`. Генератор + early exit.
- **№14** — `brain.parse` без `.strip()`. `.strip().lower()`.
- **№20** — TTS накладывается (2–3 голоса). Per-call stop-token.
- **№21** — `_profile_fast` не матчит из GUI. `normalize(cmd)` в `handle()`.
- **№24** — Светлая тема ломала GUI. `PALETTES` + пересборка.
- **№24.5** — Системная тема не автоопределялась. `_detect_system_theme()`.
- **№25** — `mic_watchdog` спамил. Одно предупреждение за сессию.
- **№25.5** — Микрофон не проверить из GUI. Вкладка + прогресс-бар + кнопка.
- **Flet 1.x API** — `ft.ElevatedButton` → `ft.Button`.
- **Раскладка:** `SendInput` вместо `keybd_event` — работает второй раз.
- **Стриминг в GUI:** tee-генератор — чанки и в TTS, и в GUI.
- **История чата** не теряется при переключении разделов (кеш `_tabs`).
- **`signal only works in main thread`** — Flet в главном потоке.
- `open_site` без LLM через `_open_fast`.
- `small_talk_how` — не перехватывается `pending_question`.
- `UnicodeEncodeError` на CI — `reconfigure` + `PYTHONUTF8`.
- **`удали профиль`** обрабатывается **до** `tasks.handle_task_command`.

### Обновления технологий

- ✅ **О1** — `vosk 0.3.45`, `faster-whisper 1.2.1`, `ctranslate2 4.8.2`, `piper-tts 1.8.0`.
- ✅ **О2** — `whisper_model: deepdml/faster-whisper-large-v3-turbo-ct2`.
- ✅ **О3** — `check_cpu()` в `check_caps.py` + `system_caps.json`.
- ✅ **О4** — `tts_voice_quality` в config.
- ✅ **О5** — `_init_piper` quality + fallback.
- ✅ **О9** — настраиваемый TTL кэша погоды.
- ❌ О6 — GUI RadioGroup «Качество голоса».
- ❌ О7 — README + `config.example.json` (синхронизированы).

### В планах

- **Ф1–Ф13** — облачные провайдеры (Groq, Edge TTS).
- **З1–З7** — знакомство (persona).
- **С1–С3** — стресс-тест (20 фраз).
- **М1–М9** — мои команды голосом.
- **Ф14–Ф19** — платные провайдеры (OpenAI, Fish Audio).
- **№5, №7, №9–№13, №15–№19, №22, №23** — открытые баги.

---

## [0.2.2] — 2026-10-05

### Добавлено

- Этап 0 (рефакторинг): `config_manager`, `Config` в памяти, barge-in, CJK-фильтр, few-shot промпт.
- Этап 1: голосовые режимы, паки, макросы, память, голоса Piper.
- Этап 2: streaming TTS, barge-in, логи, буфер обмена, погода и курс.
- `test_intents.py` + `pytest tests/`.

### Исправлено

- `actions.run_spec` — `kind == "cmd"`.
- `matching.match_score` — короткие слова.
- `tts.Speaker.stop()` — barge-in через sounddevice.
- `stt._enable_cuda_dlls` — флаг.
- `brain.py` — `close_app` в отдельный блок.

## [0.2.1] и раньше

См. коммиты в репозитории до июня 2026 — от оригинала
[jsays12/jarvis](https://github.com/jsays12/jarvis).
```

### `check_all.bat`

```batch
@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title Проверка Феникса

echo ============================================================
echo   Проверка проекта Феникс
echo ============================================================
echo.

cd /d "%~dp0"
call .venv311\Scripts\activate.bat

set FAILED=0

REM =====================================================================
REM 1. Синтаксис
REM =====================================================================
echo [1/3] Проверка синтаксиса...
echo.
python check_syntax.py
if errorlevel 1 (
    echo.
    echo   [!!] Синтаксис сломан
    set FAILED=1
) else (
    echo.
    echo   [OK] Синтаксис в порядке
)
echo.
echo ------------------------------------------------------------
echo.

REM =====================================================================
REM 2. pytest
REM =====================================================================
echo [2/3] Юнит-тесты (pytest)...
echo.
python -m pytest tests/ -q
if errorlevel 1 (
    echo.
    echo   [!!] Тесты упали
    set FAILED=1
) else (
    echo.
    echo   [OK] Тесты прошли
)
echo.
echo ------------------------------------------------------------
echo.

REM =====================================================================
REM 3. test_intents
REM =====================================================================
echo [3/3] Интент-тесты (test_intents.py)...
echo   Это может занять до 30 секунд.
echo.
python test_intents.py
if errorlevel 1 (
    echo.
    echo   [!!] Интент-тесты упали — смотри logs\test_intents.log
    set FAILED=1
) else (
    echo.
    echo   [OK] Интент-тесты прошли
)
echo.

REM =====================================================================
REM Итог
REM =====================================================================
echo ============================================================
if "!FAILED!"=="1" (
    echo   ЕСТЬ ОШИБКИ
    echo ============================================================
    echo.
    echo   Что смотреть:
    echo     1. Выше — какой шаг упал
    echo     2. logs\errors.log
    echo     3. logs\test_intents.log
    echo.
) else (
    echo   ВСЁ РАБОТАЕТ
    echo ============================================================
    echo.
)

pause
```

### `check_syntax.bat`

```batch
@echo off
rem №98: cd /d "%~dp0" вместо хардкода C:\jarvis.
rem Теперь скрипт работает, даже если проект перемещён.
cd /d "%~dp0"
call .venv311\Scripts\activate.bat
python check_syntax.py
pause
```

### `check_syntax.py`

```python
"""Проверяет синтаксис всех .py файлов в проекте."""
import ast
import sys
from pathlib import Path

# Принудительно UTF-8 для stdout/stderr — иначе на CI (Windows, cp1252)
# падает UnicodeEncodeError при печати русских букв.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parent

# Папки, где ищем .py
TARGETS = [
    BASE / "jarvis",
    BASE / "scripts",
    BASE,  # корень: launcher.py, check_syntax.py
]

# Исключения
SKIP_DIRS = {"__pycache__", ".venv", "venv", ".git", "models", "voices", "logs"}
SKIP_FILES = set()

files = []
for t in TARGETS:
    if not t.exists():
        continue
    if t == BASE:
        # В корне — только файлы верхнего уровня
        files.extend(f for f in t.glob("*.py") if f.name not in SKIP_FILES)
    else:
        for f in t.rglob("*.py"):
            if any(part in SKIP_DIRS for part in f.parts):
                continue
            if f.name in SKIP_FILES:
                continue
            files.append(f)

files = sorted(set(files))

failed = 0
for f in files:
    try:
        ast.parse(f.read_text(encoding="utf-8"))
        rel = f.relative_to(BASE)
        print(f"OK   {rel}")
    except SyntaxError as e:
        failed += 1
        rel = f.relative_to(BASE) if f.is_relative_to(BASE) else f
        print(f"FAIL {rel}: {e}")

print()
if failed:
    print(f"Ошибок: {failed}")
    sys.exit(1)
else:
    print(f"Все {len(files)} файлов в порядке.")
```

### `CI.md`

```markdown
# CI — что это и как с ним жить

## 🎯 Что такое CI

CI = Continuous Integration = автоматическая проверка кода при каждом push.

GitHub Actions запускает виртуалку с Windows, ставит Python, зависимости,
прогоняет тесты. Через ~40 секунд ты видишь: ✅ или ❌.

**Зачем:** ловит регрессии, пока ты спишь. Не нужно помнить про тесты —
GitHub запускает их сам.

## 📁 Где лежит

`.github/workflows/test.yml` — инструкция для GitHub.

## 🔍 Что делает

1. Checkout — скачивает код.
2. Setup Python 3.11 + кэш pip.
3. `pip install -r requirements-ci.txt` — облегчённые зависимости.
4. `python check_syntax.py` — синтаксис.
5. `python -m pytest tests/ -q` — юнит-тесты.
6. `python test_intents.py` — интент-тесты без флагов.

`PYTHONUTF8=1` — глобально на весь job, страховка от cp1252.

## 🚀 Как смотреть результат

1. Открой репозиторий на GitHub.
2. Вкладка **Actions** (сверху).
3. Последний запуск — ✅ или ❌.
4. Кликни → увидишь шаги и логи.

## 🔧 Если упало

**Шаг `Check syntax`** — синтаксис где-то сломан. Открой лог, найди файл и строку.

**Шаг `pytest`** — юнит-тест упал. Лог покажет какой.

**Шаг `Intent tests`** — интент-тест упал. Логи в артефактах Actions или
локально `logs/test_intents.log`.

**Общая ошибка `UnicodeEncodeError`** — Windows-консоль в cp1252 не может
напечатать русский. Уже пофикшено (`reconfigure` + `PYTHONUTF8=1`). Если
повторится — проверь, что эти правки на месте.

## 📦 requirements-ci.txt

Отдельный файл — **только то, что нужно для CI**:

- `filelock`, `num2words`, `psutil`, `pyperclip`, `Pillow`
- `pytest`, `pytest-asyncio`

**Чего нет:**
- `piper-tts`, `faster-whisper`, `sounddevice`, `vosk`, `winrt-*` — на сервере нет звука
- `pycaw`, `screen-brightness-control` — Windows-специфичные, тяжёлые
- `pyautogui`, `pygetwindow`, `keyboard`, `mouse` — GUI

**Почему:** CI ускоряется с ~5 мин до ~40 сек. И не падает на «нет звука».

## ➕ Как добавить шаг

В `.github/workflows/test.yml`:

```yaml
      - name: Мой новый шаг
        run: python my_script.py
```

Пуш → GitHub сам подхватит.

## 🎨 Бейдж в README

```markdown
[![tests](https://github.com/USER/REPO/actions/workflows/test.yml/badge.svg)](https://github.com/USER/REPO/actions/workflows/test.yml)
```

Замени `USER/REPO` на свой. Вставь в начало README.
```

### `cmds\open_terminal.bat`

```batch
@echo off
cd /d C:\jarvis
cmd
```

### `cmds\show_ip.bat`

```batch
@echo off
ipconfig
pause
```

### `config.example.json`

```json
{
  "wake_words": [
    "феникс",
    "финикс",
    "феникса",
    "fenix",
    "phoenix",
    "джарвис",
    "jarvis"
  ],
  "tts_backend": "auto",
  "xtts_ref": "voices/jarvis.wav",
  "tts_voice": "ruslan",
  "tts_voice_quality": "medium",
  "voice_rate": 1.15,
  "voice": "Pavel",
  "music_app": "яндекс музыка",
  "music_wait_sec": 6,
  "dialog_window_sec": 20,
  "sample_rate": 16000,
  "input_device": null,
  "mic_check_sec": 20,
  "mic_watchdog_enabled": true,
  "command_window_sec": 9,
  "mode": "combo",
  "barge_enabled": true,
  "active_packs": [],
  "timers_file": "timers.json",
  "tasks_file": "tasks.json",
  "memory_file": "dialog.json",
  "memory_max": 100,
  "llm_context_messages": 20,
  "weather_cache_ttl_sec": 600,
  "danger_password": "",
  "gui_enabled": true,
  "gui_theme": "Системная",
  "gui_x": null,
  "gui_y": null,
  "tray_enabled": true,
  "launch_mode": "gui",
  "use_whisper": true,
  "whisper_model": "deepdml/faster-whisper-large-v3-turbo-ct2",
  "whisper_device": "auto",
  "use_llm": true,
  "llm_model": "qwen2.5:7b-instruct",
  "ollama_url": "http://127.0.0.1:11434",
  "prompt_level": "auto",
  "llm_temperature": 0.7,
  "app_paths": {},
  "custom_commands": []
}
```

### `CONTRIBUTING.md`

```markdown
# Как контрибьютить в Феникс

Документ для себя-будущего и для LLM, которая помогает с проектом.

## 🎯 Главное правило

**Не добавляй костыли.** Если решение «работает, но выглядит грязно» —
это не решение. Лучше потратить час сейчас, чем три — через месяц.

## 📁 Структура

```
jarvis/             — пакет
  reply.py          — тип Reply (text | stream)
  intents.py        — разбор команд, быстрые правила + LLM
  main.py           — точка входа, Jarvis, barge-in
  brain.py          — Ollama: parse() и chat_stream()
  config.py         — Config в памяти + подписки
  config_manager.py — атомарная запись
  tts.py            — Piper / XTTS / WinRT / SAPI + per-call token
  stt.py            — Vosk + Whisper + ring buffer
  gui.py            — Flet GUI + PALETTES + _detect_system_theme()
  ...

tests/              — pytest-тесты
test_intents.py     — интент-тесты (без микрофона)
check_syntax.py     — синтаксис всех .py
snapshot.py         — сборка SNAPSHOT.md

packs/              — JSON-паки команд
scripts/            — утилиты (mics, wakebench, build_exe)
.github/workflows/  — CI
```

## 📝 Правила кода

1. **Не читай `config.json` напрямую** — используй `config.get()` из объекта `Config`.
2. **Не пиши в `config.json` напрямую** — только `Config.set()` или `config_manager.save()`.
3. **Не плоди глобальное состояние** — кроме `Config._GLOBAL`.
4. **Нормализация (города, валюты, паков) — задача LLM.** Не добавляй словари синонимов в код без нужды.
5. **Логи в `actions.log`** — главный инструмент отладки.
6. **Не выбрасывай ошибки в `errors.log`** — это сигнал, что что-то сломалось, разбирайся.
7. **`test_intents.py`** — первое, что запускаешь после правки `intents.py`, `brain.py`, `actions.py`.
8. **`normalize(cmd)` в `IntentHandler.handle()`** — единая точка нормализации для GUI и голоса.
9. **Per-call stop-token в `tts.py`** — не используй общий `_stop_flag`. Каждый вызов `play_async` / `speak_stream` создаёт свой токен.
10. **`PALETTES` в `gui.py`** — две палитры (dark/light), `_detect_system_theme()` для системной темы через реестр Windows.
11. **`ft.Button`** вместо `ft.ElevatedButton` / `ft.TextButton` — в Flet 1.x их удалили.
12. **`weather_cache_ttl_sec`** — читается **на каждый вызов** через `weather._current_ttl()`, не кэшируй TTL.
13. **`snapshot.py`** — исключай `.venv311` из `EXCLUDE_DIRS` (иначе `SNAPSHOT.md` = 52 МБ).

## 🔒 Правила безопасности

**Никогда не упоминай в публичных файлах** (`README.md`, `PLAN.md`, `CHANGELOG.md`, `ARCHITECTURE.md`, `PROMPT.md`, `CONTRIBUTING.md`, `config.example.json`):

- Имя пользователя.
- Город.
- Модель CPU / GPU.
- ОС.

**Всё личное — только в:**
- `config.json`.
- `profiles/`.
- `system_caps.json`.

**И они — в `.gitignore`.**

## 🚀 Рабочий процесс

### 1. Правка

Правь файлы в `jarvis/`. **Один патч — одна задача.**

### 2. Проверка синтаксиса

```bat
python check_syntax.py
```

### 3. Тесты

```bat
python -m pytest tests/ -q
python test_intents.py
```

### 4. Обновление SNAPSHOT

```bat
python snapshot.py
```

### 5. Коммит

```bat
commit "fix: краткое описание"
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

- **Новые интенты** — сценарий в `test_intents.py`.
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
6. **Коммитить `SNAPSHOT.md` > 1 МБ** — исключай `.venv311` в `snapshot.py`.
7. **Использовать Python 3.13/3.14** — Vosk падает. Только 3.10–3.12.
8. **Запускать Flet не в главном потоке** — `signal.signal` не работает.
9. **`ElevatedButton`/`TextButton` в Flet 1.x** — используй `ft.Button`.
10. **Хардкодить пути** — через `BASE_DIR` и `Path.home()`.

## 📦 Как добавить новый интент

### 1. Быстрое правило (без LLM)

В `jarvis/intents.py`, в `_handle_single` — **до** `brain.parse()`:

```python
if cmd == "привет феникс":
    return "Привет!"
```

**Где вставлять:** после `_match_custom`, до `_open_fast`.

### 2. Через LLM

В `jarvis/brain.py`, в `ACTIONS` — добавь action:

```python
ACTIONS = {
    ...,
    "my_new_action",
}
```

В `SYSTEM_SMALL` / `SYSTEM_MEDIUM` / `SYSTEM_LARGE` — добавь описание и пример.

В `IntentHandler._execute_intent` — обработай:

```python
if action == "my_new_action":
    ...
    return "Готово."
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

1. В `config.json` → `custom_commands`:

```json
{
  "phrases": ["открой мой сайт"],
  "action": "https://example.com",
  "reply": "Открываю."
}
```

2. **Проверь:** скажи «открой мой сайт» → откроется `example.com`.

## 📦 Как добавить новый TTS-голос

1. В `jarvis/voices.py` → `PIPER_VOICES`:

```python
PIPER_VOICES = {
    ...,
    "my_voice": "Мой голос — описание",
}
```

2. Скачай модели с HuggingFace: `rhasspy/piper-voices` → `ru/ru_RU/my_voice/medium/`.

3. **Проверь:** «смени голос на мой голос» → должен переключиться.

## 🚨 Если что-то сломалось

1. **Посмотри `logs/errors.log`** — там трейсбек.
2. **Посмотри `logs/actions.log`** — там команды и интенты.
3. **Запусти `check_syntax.py`** — может, опечатка.
4. **Запусти `test_intents.py`** — может, регрессия.
5. **Откати коммит** — если совсем плохо:

```bat
git reset --hard HEAD~1
```

## 📋 Чек-лист перед коммитом

- [ ] `python check_syntax.py` — без ошибок.
- [ ] `python -m pytest tests/ -q` — все тесты зелёные.
- [ ] `python test_intents.py` — все интенты проходят.
- [ ] **Не коммичу** `.venv311`, `config.json`, `profiles/`, `system_caps.json`.
- [ ] **Проверил** `git status` — нет лишних файлов.
- [ ] **Личные данные** не попали в публичные файлы.
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

---

**Погнали, брат.** 🚀
```

### `install.bat`

```batch
@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title Установка Феникса

echo ============================================================
echo   Феникс — установка
echo ============================================================
echo.

cd /d "%~dp0"

REM =====================================================================
REM 1. Проверка Python 3.10-3.12
REM =====================================================================
echo [1/11] Проверка Python — нужен 3.10-3.12...

where py >nul 2>nul
if errorlevel 1 (
    echo.
    echo   Python Launcher py.exe не найден.
    echo.
    echo   Установи Python 3.11.9:
    echo     https://www.python.org/downloads/release/python-3119/
    echo   При установке отметь:
    echo     - Add python.exe to PATH
    echo     - Install launcher for all users
    echo.
    pause
    exit /b 1
)

py -3.11 --version >nul 2>nul
if errorlevel 1 (
    echo.
    echo   Python 3.11 не найден.
    echo.
    echo   Установи Python 3.11.9:
    echo     https://www.python.org/downloads/release/python-3119/
    echo.
    echo   ВАЖНО: Python 3.13/3.14 НЕ подходит.
    echo   Vosk 0.3.45 падает с access violation в libvosk.dll.
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('py -3.11 --version 2^>^&1') do set PYVER=%%v
echo   Найден Python %PYVER% через py -3.11
echo.

REM =====================================================================
REM 2. Создание .venv311
REM =====================================================================
echo [2/11] Создание виртуального окружения .venv311...

if exist ".venv311\Scripts\python.exe" (
    echo   .venv311 уже существует, использую его.
) else (
    echo   Создаю .venv311...
    py -3.11 -m venv .venv311
    if errorlevel 1 (
        echo   ОШИБКА: не удалось создать .venv311.
        pause
        exit /b 1
    )
    echo   .venv311 создан.
)
echo.

REM =====================================================================
REM 3. Активация venv
REM =====================================================================
echo [3/11] Активация .venv311...
call .venv311\Scripts\activate.bat
if errorlevel 1 (
    echo   ОШИБКА: не удалось активировать .venv311.
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set VENVVER=%%v
echo   Активен Python %VENVVER% из .venv311
echo.

REM =====================================================================
REM 4. Обновление pip
REM =====================================================================
echo [4/11] Обновление pip...
python -m pip install --upgrade pip
if errorlevel 1 (
    echo   ОШИБКА: не удалось обновить pip.
    pause
    exit /b 1
)
echo   pip обновлён.
echo.

REM =====================================================================
REM 5. Python-зависимости из requirements.txt
REM =====================================================================
echo [5/11] Установка зависимостей из requirements.txt...
echo   Это может занять 5-15 минут.
echo.
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo   ОШИБКА: не удалось установить зависимости.
    echo   Проверь requirements.txt или скинь лог автору.
    pause
    exit /b 1
)
echo.
echo   Зависимости установлены.
echo.

REM =====================================================================
REM 6. eSpeak NG
REM =====================================================================
echo [6/11] Проверка eSpeak NG — нужен для Piper TTS...
where espeak-ng >nul 2>nul
if errorlevel 1 (
    if exist "C:\Program Files\eSpeak NG\espeak-ng.exe" (
        echo   eSpeak NG найден в C:\Program Files\eSpeak NG
    ) else (
        echo.
        echo   eSpeak NG не найден. Без него Piper не заведётся.
        echo.
        set /p INSTALL_ESPEAK="Установить eSpeak NG сейчас? y/n: "
        if /i "!INSTALL_ESPEAK!"=="y" (
            echo   Устанавливаю через winget...
            winget install --id eSpeak-NG.eSpeak-NG -e --accept-source-agreements --accept-package-agreements
            if errorlevel 1 (
                echo.
                echo   Не удалось установить автоматически.
                echo   Скачай вручную: https://github.com/espeak-ng/espeak-ng/releases
                start https://github.com/espeak-ng/espeak-ng/releases
                pause
            ) else (
                echo   eSpeak NG установлен.
            )
        ) else (
            echo   Пропускаю. Поставишь позже.
        )
    )
) else (
    echo   eSpeak NG найден.
)
echo.

REM =====================================================================
REM 7. Ollama
REM =====================================================================
echo [7/11] Проверка Ollama — для LLM-диалога...
where ollama >nul 2>nul
if errorlevel 1 (
    echo.
    echo   Ollama не установлена.
    echo   Без неё Феникс работает только на правилах.
    echo.
    set /p INSTALL_OLLAMA="Установить Ollama сейчас? y/n: "
    if /i "!INSTALL_OLLAMA!"=="y" (
        echo   Устанавливаю через winget...
        winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
        if errorlevel 1 (
            echo   Не удалось. Скачай вручную: https://ollama.com/download
            pause
        )
    ) else (
        echo   Пропускаю. Поставишь позже: winget install Ollama.Ollama
    )
) else (
    echo   Ollama найдена.
)
echo.

REM =====================================================================
REM 8. Выбор модели LLM
REM =====================================================================
where ollama >nul 2>nul
if errorlevel 1 (
    echo [8/11] Ollama не установлена — пропускаю выбор модели.
    echo.
    goto skip_model
)

echo [8/11] Выбор модели для LLM.
echo.
echo   ============================================================
echo    Слабые ПК, встроенная графика, 4-8 ГБ RAM, без GPU
echo   ============================================================
echo     1) qwen2.5:0.5b    ~0.5 ГБ RAM   Очень слабо, только тест
echo     2) qwen2.5:1.5b    ~1.5 ГБ RAM   Базовое, для теста
echo     3) qwen2.5:3b      ~3 ГБ RAM     Заметно лучше
echo.
echo   ============================================================
echo    Ноутбуки с дискретной GPU, 8-16 ГБ VRAM
echo   ============================================================
echo     4) qwen2.5:7b      ~5-6 ГБ VRAM  Отличное, рекомендуется
echo     5) qwen2.5:14b     ~10 ГБ VRAM   Максимум для 12 ГБ
echo.
echo   ============================================================
echo    Мощные ПК и серверы, 16+ ГБ VRAM
echo   ============================================================
echo     6) qwen2.5:32b     ~20 ГБ VRAM   Профессиональное
echo     7) qwen2.5:72b     ~40 ГБ VRAM   Только для топовых GPU
echo.
echo   ============================================================
echo    Альтернативные семейства, для русского тоже ок
echo   ============================================================
echo     8) gemma2:2b       ~1.5 ГБ RAM   Быстрая, для слабых ПК
echo     9) gemma2:9b       ~6 ГБ VRAM    Хорошо держит русский
echo    10) llama3.1:8b     ~5 ГБ VRAM    Популярная, многоязычная
echo    11) mistral:7b      ~5 ГБ VRAM    Быстрая, живая
echo.
echo   ============================================================
echo    12) Пропустить — модель уже скачана или не нужна
echo   ============================================================
echo.
echo   Если не знаешь свою видеокарту:
echo     Win+R -> dxdiag -> Enter -> вкладка "Экран"
echo     Смотри "Видеопамять VRAM".
echo.

set /p LLM_CHOICE="Выбери модель 1-12, по умолчанию 4: "
if "!LLM_CHOICE!"=="" set LLM_CHOICE=4

if "!LLM_CHOICE!"=="1"  set LLM_MODEL=qwen2.5:0.5b
if "!LLM_CHOICE!"=="2"  set LLM_MODEL=qwen2.5:1.5b-instruct
if "!LLM_CHOICE!"=="3"  set LLM_MODEL=qwen2.5:3b-instruct
if "!LLM_CHOICE!"=="4"  set LLM_MODEL=qwen2.5:7b-instruct
if "!LLM_CHOICE!"=="5"  set LLM_MODEL=qwen2.5:14b-instruct
if "!LLM_CHOICE!"=="6"  set LLM_MODEL=qwen2.5:32b-instruct
if "!LLM_CHOICE!"=="7"  set LLM_MODEL=qwen2.5:72b-instruct
if "!LLM_CHOICE!"=="8"  set LLM_MODEL=gemma2:2b
if "!LLM_CHOICE!"=="9"  set LLM_MODEL=gemma2:9b
if "!LLM_CHOICE!"=="10" set LLM_MODEL=llama3.1:8b
if "!LLM_CHOICE!"=="11" set LLM_MODEL=mistral:7b
if "!LLM_CHOICE!"=="12" goto skip_model

if not defined LLM_MODEL (
    echo   Некорректный выбор. Ставлю по умолчанию qwen2.5:7b-instruct.
    set LLM_MODEL=qwen2.5:7b-instruct
)

echo.
echo   Проверяю, скачана ли !LLM_MODEL!...
set ALREADY=
for /f "tokens=*" %%m in ('ollama list 2^>nul ^| findstr /C:"!LLM_MODEL!"') do set ALREADY=1
if defined ALREADY (
    echo   Модель уже скачана. Пропускаю.
) else (
    echo   Скачиваю !LLM_MODEL! ... это займёт несколько минут.
    ollama pull !LLM_MODEL!
    if errorlevel 1 (
        echo   Не удалось скачать модель. Попробуй позже: ollama pull !LLM_MODEL!
    ) else (
        echo   Модель !LLM_MODEL! скачана.
    )
)

echo   Обновляю config.json — устанавливаю llm_model = !LLM_MODEL! ...
python scripts\set_llm_model.py "!LLM_MODEL!"
if errorlevel 1 (
    echo   ВНИМАНИЕ: не удалось обновить config.json
)
echo.

goto after_model

:skip_model
echo   Пропускаю скачивание модели.
echo.

:after_model

REM =====================================================================
REM 9. Конфиг, папки
REM =====================================================================
echo [9/11] Настройка конфига и папок...

if not exist "config.json" (
    if exist "config.example.json" (
        copy config.example.json config.json >nul
        echo   Создан config.json из config.example.json
    ) else (
        echo   ВНИМАНИЕ: config.example.json не найден.
    )
) else (
    echo   config.json уже существует, оставляю как есть.
)

if not exist "logs" mkdir logs
if not exist "models" mkdir models
echo   Папки logs/ и models/ готовы.
echo.

REM =====================================================================
REM 10. Проверка возможностей системы
REM =====================================================================
echo [10/11] Проверка возможностей системы.
echo.
python scripts\check_caps.py
echo.

REM =====================================================================
REM 11. Проверка работоспособности
REM =====================================================================
echo [11/11] Проверка работоспособности Феникса.
echo.
echo   Сейчас прогонятся:
echo     - Проверка синтаксиса check_syntax.py
echo     - Юнит-тесты pytest tests/
echo     - Интент-тесты test_intents.py
echo.

set /p RUN_CHECKS="Запустить проверку сейчас? y/n: "
if /i "%RUN_CHECKS%"=="n" goto skip_checks

set CHECK_FAILED=0

REM --- Проверка синтаксиса ---
echo.
echo   --- Проверка синтаксиса ---
python check_syntax.py
if errorlevel 1 (
    echo   ОШИБКА: синтаксис сломан
    set CHECK_FAILED=1
) else (
    echo   OK: синтаксис в порядке
)

REM --- pytest ---
echo.
echo   --- Юнит-тесты pytest ---
python -m pytest tests/ -q
if errorlevel 1 (
    echo   ОШИБКА: тесты упали
    set CHECK_FAILED=1
) else (
    echo   OK: тесты прошли
)

REM --- test_intents ---
echo.
echo   --- Интент-тесты test_intents.py ---
echo   Это может занять до 30 секунд.
python test_intents.py
if errorlevel 1 (
    echo   ОШИБКА: интент-тесты упали — смотри logs\test_intents.log
    set CHECK_FAILED=1
) else (
    echo   OK: интент-тесты прошли
)

echo.
if "!CHECK_FAILED!"=="1" (
    echo ============================================================
    echo   ЕСТЬ ОШИБКИ — смотри выше
    echo ============================================================
    echo.
    echo   Что делать:
    echo     1. Проверь logs\errors.log
    echo     2. Проверь logs\test_intents.log
    echo     3. Скинь эти логи автору
    echo.
) else (
    echo ============================================================
    echo   ВСЁ РАБОТАЕТ
    echo ============================================================
    echo.
)
goto checks_done

:skip_checks
echo   Пропускаю проверку. Запустишь позже вручную:
echo     check_syntax.bat
echo     python -m pytest tests/ -q
echo     python test_intents.py
echo.

:checks_done

REM =====================================================================
REM Финальный экран
REM =====================================================================
echo ============================================================
echo   Установка завершена!
echo ============================================================
echo.
echo   Что дальше:
echo.
echo   1. Проверь микрофон:
echo        .venv311\Scripts\activate.bat
echo        python scripts\mics.py
echo.
echo   2. Запусти Феникса:
echo        start_fenix_311.bat        — Python 3.11 venv, без консоли
echo        start_fenix_311_debug.bat  — с логами в консоли
echo.
echo   3. Говори "Феникс ..." — и он ответит.
echo.

set /p RUN_MICS="Запустить проверку микрофона сейчас? y/n: "
if /i "%RUN_MICS%"=="y" (
    python scripts\mics.py
)

echo.
pause
```

### `jarvis\__init__.py`

```python
"""Феникс — локальный голосовой ассистент для Windows.

Ассистент: Vosk (wake) + Whisper (расшифровка) + Ollama (LLM) + Piper (TTS).
Ключевые модули: jarvis.main, jarvis.intents, jarvis.brain, jarvis.tts, jarvis.stt.
"""

__version__ = "1.0.0"
APP_NAME = "Феникс"
```

### `jarvis\__main__.py`

```python
from jarvis.main import main

if __name__ == "__main__":
    main()
```

### `jarvis\actions.py`

```python
"""Действия: запуск приложений, открытие сайтов, скриншоты, медиа, печать, окна."""

import json
import logging
import os
import re
import shutil
import subprocess
import time
import urllib.parse
from pathlib import Path

log = logging.getLogger("jarvis.actions")

BASE_DIR = Path(__file__).resolve().parent.parent
_CAPS_FILE = BASE_DIR / "system_caps.json"
_CAPS: dict = {}


def _load_caps() -> dict:
    """Читает system_caps.json. Кэширует. Если файла нет — возвращает {}."""
    global _CAPS
    if _CAPS:
        return _CAPS
    if _CAPS_FILE.exists():
        try:
            _CAPS = json.loads(_CAPS_FILE.read_text(encoding="utf-8"))
            log.info("system_caps.json загружен")
        except Exception:
            log.exception("Не удалось прочитать system_caps.json")
            _CAPS = {}
    return _CAPS


def _caps_available(name: str) -> bool:
    """Проверяет, доступна ли возможность."""
    return _load_caps().get(name, {}).get("available", False)


def _caps_method(name: str) -> str:
    return _load_caps().get(name, {}).get("method", "none")


# --- запуск приложений и файлов -------------------------------------------

def spec_from_string(s: str):
    s = s.strip()
    if s.startswith("open_app:"):
        return ("open_app", s[len("open_app:"):])
    if s.startswith(("http://", "https://")):
        return ("url", s)
    if s.startswith("steam://"):
        return ("uri", s)
    if s.lower().endswith((".bat", ".cmd")):
        return ("path", s)
    if s.lower() in ("browser", "браузер"):
        return ("browser", None)
    if os.path.exists(s):
        return ("path", s)
    return ("path", s)


def run_spec(spec) -> bool:
    if not spec:
        return False
    kind, value = spec
    log.info("Запуск: %s %s", kind, value)
    try:
        if kind == "open_app":
            from jarvis.installed import scan_start_menu, find_installed
            apps = scan_start_menu()
            hit = find_installed(apps, value)
            if hit:
                os.startfile(str(hit[1]))
                _schedule_activation(value, hit[0])
                return True
            log.warning("Приложение '%s' не найдено в меню Пуск", value)
            return False
        if kind == "browser":
            open_browser()
            return True
        if kind == "url":
            open_url(value)
            return True
        if kind == "uri":
            os.startfile(value)
            return True
        if kind == "cmd":
            args = value if isinstance(value, list) else [value]
            subprocess.Popen(args, creationflags=subprocess.CREATE_NO_WINDOW)
            return True
        if kind in ("path", "exe"):
            os.startfile(value)
            return True
    except Exception:
        log.exception("run_spec не удался: %s", spec)
    return False


def _schedule_activation(name: str, app_title: str | None = None) -> None:
    """Через 2 сек после запуска пытается активировать окно приложения."""
    import threading
    targets = [name]
    if app_title and app_title.lower() != name.lower():
        targets.append(app_title)

    def _run():
        time.sleep(2.0)
        try:
            import pygetwindow as gw
            for t in targets:
                t_low = t.lower()
                for w in gw.getAllWindows():
                    if not w.title:
                        continue
                    if t_low in w.title.lower():
                        try:
                            if getattr(w, "isMinimized", False):
                                w.restore()
                                time.sleep(0.1)
                            w.activate()
                            log.info("Активировал окно: %s", w.title)
                        except Exception:
                            pass
                        return
        except Exception:
            log.exception("Не удалось активировать окно %r", name)

    threading.Thread(target=_run, daemon=True, name=f"activate-{name}").start()


def open_path(path, minimized: bool = False) -> bool:
    log.info("Открываю путь: %s (minimized=%s)", path, minimized)
    try:
        if minimized and str(path).lower().endswith(".lnk"):
            subprocess.Popen(["cmd", "/c", "start", "/min", "", str(path)],
                             creationflags=subprocess.CREATE_NO_WINDOW)
            return True
        os.startfile(str(path))
        return True
    except Exception:
        log.exception("open_path не удался: %s", path)
        return False

def _activate_window_hard(title_part: str) -> bool:
    """Активирует окно по части заголовка — надёжно, через win32gui.

    Windows блокирует SetForegroundWindow от не-активного окна.
    Трюк: AttachThreadInput — присоединяемся к потоку целевого окна,
    тогда система разрешает смену фокуса.

    Возвращает True, если окно найдено и активировано.
    """
    if not title_part:
        return False
    try:
        import win32gui
        import win32con
        import win32process
        import win32api
    except ImportError:
        log.warning("pywin32 не установлен — активация через win32gui недоступна")
        return False

    target_hwnd = [None]

    def _enum_cb(hwnd, _):
        if target_hwnd[0] is not None:
            return
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd) or ""
        if title_part.lower() in title.lower():
            target_hwnd[0] = hwnd

    win32gui.EnumWindows(_enum_cb, None)

    hwnd = target_hwnd[0]
    if not hwnd:
        log.info("_activate_window_hard: окно %r не найдено", title_part)
        return False

    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

        # Трюк AttachThreadInput
        fg_hwnd = win32gui.GetForegroundWindow()
        fg_thread = win32process.GetWindowThreadProcessId(fg_hwnd)[0]
        target_thread = win32process.GetWindowThreadProcessId(hwnd)[0]
        cur_thread = win32api.GetCurrentThreadId()

        attached_fg = False
        attached_target = False
        try:
            if fg_thread != cur_thread:
                win32process.AttachThreadInput(fg_thread, cur_thread, True)
                attached_fg = True
            if target_thread != cur_thread:
                win32process.AttachThreadInput(target_thread, cur_thread, True)
                attached_target = True

            win32gui.SetForegroundWindow(hwnd)
            win32gui.BringWindowToTop(hwnd)
        finally:
            if attached_fg:
                win32process.AttachThreadInput(fg_thread, cur_thread, False)
            if attached_target:
                win32process.AttachThreadInput(target_thread, cur_thread, False)

        log.info("_activate_window_hard: активировал %r", title_part)
        return True
    except Exception:
        log.exception("_activate_window_hard: не удалось активировать %r", title_part)
        return False

def open_in_editor(path, prefer: str = "auto") -> bool:
    """Открывает файл в редакторе.

    prefer:
        "auto"       — Notepad++ → VS Code → системный редактор (по умолчанию).
        "notepad++"  — только Notepad++.
        "vscode"     — только VS Code.
        "system"     — системный редактор (os.startfile).

    Возвращает True, если удалось открыть.
    """
    path = Path(path)
    if not path.exists():
        log.warning("open_in_editor: файла нет: %s", path)
        return False

    # Порядок редакторов для auto
    editors = []

    if prefer == "notepad++":
        editors = [_find_notepadpp]
    elif prefer == "vscode":
        editors = [_find_vscode]
    elif prefer == "system":
        editors = []
    else:  # auto
        editors = [_find_notepadpp, _find_vscode]

    for finder in editors:
        exe = finder()
        if exe:
            try:
                subprocess.Popen([exe, str(path)],
                                 creationflags=subprocess.CREATE_NO_WINDOW)
                log.info("open_in_editor: %s → %s", path, exe)

                # Активируем окно редактора через 0.5 сек —
                # иначе Notepad++ открывается за другими окнами.
                import threading
                editor_name = Path(exe).stem.lower()

                def _activate():
                    time.sleep(0.6)
                    # Ищем окно по имени редактора
                    if "notepad" in editor_name:
                        _activate_window_hard("notepad++")
                    elif "code" in editor_name:
                        _activate_window_hard("visual studio code")

                threading.Thread(target=_activate, daemon=True,
                                 name="editor-activate").start()
                return True
            except Exception:
                log.exception("open_in_editor: не удалось запустить %s", exe)
                continue

    # Fallback: системный редактор
    try:
        os.startfile(str(path))
        log.info("open_in_editor: %s → системный редактор", path)
        return True
    except Exception:
        log.exception("open_in_editor: не удалось открыть %s", path)
        return False


def _find_notepadpp() -> str | None:
    """Ищет notepad++.exe в типичных местах."""
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Notepad++" / "notepad++.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Notepad++" / "notepad++.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Notepad++" / "notepad++.exe",
    ]
    for c in candidates:
        if c and c.exists():
            return str(c)
    # В PATH?
    exe = shutil.which("notepad++") or shutil.which("notepad++.exe")
    return exe


def _find_vscode() -> str | None:
    """Ищет code.exe (VS Code) в типичных местах."""
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft VS Code" / "Code.exe",
    ]
    for c in candidates:
        if c and c.exists():
            return str(c)
    exe = shutil.which("code") or shutil.which("code.exe")
    return exe

def open_url(url: str) -> bool:
    log.info("Открываю URL: %s", url)
    try:
        os.startfile(url)
        return True
    except Exception:
        log.exception("open_url не удался: %s", url)
        return False


def open_browser() -> bool:
    log.info("Открываю браузер")
    try:
        os.startfile("https://www.google.com")
        return True
    except Exception:
        log.exception("open_browser не удался")
        return False


# --- поиск и сайты ---------------------------------------------------------

def open_search(engine: str, query: str) -> bool:
    log.info("Поиск: %s, запрос=%r", engine, query)
    q = urllib.parse.quote(query)
    if engine == "youtube":
        url = f"https://www.youtube.com/results?search_query={q}"
    elif engine == "wiki":
        url = f"https://ru.wikipedia.org/w/index.php?search={q}"
    else:
        url = f"https://www.google.com/search?q={q}"
    return open_url(url)


def google_search(query: str) -> bool:
    return open_search("google", query)


def open_site_lucky(name: str) -> bool:
    q = urllib.parse.quote(name)
    return open_url(f"https://duckduckgo.com/?q=!ducky+{q}")


def spoken_domain(name: str):
    text = name.lower().replace("точка", ".").replace(" точка ", ".").strip()
    text = re.sub(r"\s+", "", text)
    if "." in text and " " not in text:
        return "https://" + text
    return None


def guess_site(name: str):
    slug = re.sub(r"[^a-z0-9]", "", name.lower())
    if not slug:
        return None
    return f"https://{slug}.ru"


# --- скриншоты -------------------------------------------------------------

def take_screenshot():
    try:
        from PIL import ImageGrab
        folder = Path.home() / "Pictures" / "Screenshots"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"screenshot_{time.strftime('%Y-%m-%d_%H-%M-%S')}.png"
        img = ImageGrab.grab()
        img.save(path)
        log.info("Скриншот: %s", path)
        return path
    except Exception:
        log.exception("take_screenshot не удался")
        raise


# --- медиа -----------------------------------------------------------------

def media_key(key: str, times: int = 1) -> bool:
    log.info("Медиа-клавиша: %s x%d", key, times)
    try:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Manager,
        )
    except ImportError:
        log.warning("WinRT Media Control недоступен")
        return False
    try:
        import asyncio

        async def _press():
            mgr = await Manager.request_async()
            session = mgr.get_current_session()
            if not session:
                return False
            for _ in range(max(1, times)):
                if key == "play":
                    await session.try_toggle_play_pause_async()
                elif key == "next":
                    await session.try_skip_next_async()
                elif key == "prev":
                    await session.try_skip_previous_async()
                elif key == "vol_up":
                    _volume_up()
                elif key == "vol_down":
                    _volume_down()
                elif key == "mute":
                    _volume_mute()
                time.sleep(0.05)
            return True

        return asyncio.run(_press())
    except Exception:
        log.exception("media_key не удался: %s", key)
        return False


def _volume_up():
    import ctypes
    for _ in range(2):
        ctypes.windll.user32.keybd_event(0xAF, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0xAF, 0, 2, 0)


def _volume_down():
    import ctypes
    for _ in range(2):
        ctypes.windll.user32.keybd_event(0xAE, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0xAE, 0, 2, 0)


def _volume_mute():
    import ctypes
    ctypes.windll.user32.keybd_event(0xAD, 0, 0, 0)
    ctypes.windll.user32.keybd_event(0xAD, 0, 2, 0)


def ensure_music_playing() -> bool:
    return media_key("play")


# --- примитивы для сценариев (К2) -----------------------------------------

def key_press(key: str) -> bool:
    """Нажимает одну клавишу.

    key: "enter", "escape", "tab", "space", "pagedown", "pageup",
         "up", "down", "left", "right", "f1".."f12",
         "a".."z", "0".."9".
    Для сценариев: «нажми Enter» → key_press("enter").
    """
    if not key:
        return False
    log.info("key_press: %s", key)
    try:
        import pyautogui
        pyautogui.press(key)
        return True
    except Exception:
        log.exception("key_press не удался: %s", key)
        return False


def hotkey(keys) -> bool:
    """Нажимает сочетание клавиш одновременно.

    keys: список строк, например ["ctrl", "k"] или ["ctrl", "shift", "n"].
    Для сценариев: «нажми Ctrl+K» → hotkey(["ctrl", "k"]).

    Модификаторы: ctrl, alt, shift, win.
    """
    if not keys:
        return False
    if isinstance(keys, str):
        keys = [k.strip() for k in keys.replace("+", " ").split() if k.strip()]
    if not keys:
        return False
    log.info("hotkey: %s", keys)
    try:
        import pyautogui
        pyautogui.hotkey(*keys)
        return True
    except Exception:
        log.exception("hotkey не удался: %s", keys)
        return False


def scroll(direction: str, amount: int = 3) -> bool:
    """Листает вверх или вниз.

    direction: "up" | "down".
    amount: сколько «щелчков» колеса (по умолчанию 3).
    Для сценариев: «листни ниже» → scroll("down").
    """
    if direction not in ("up", "down"):
        log.warning("scroll: неизвестное направление %r", direction)
        return False
    log.info("scroll: %s x%d", direction, amount)
    try:
        import pyautogui
        clicks = amount if direction == "up" else -amount
        pyautogui.scroll(clicks)
        return True
    except Exception:
        log.exception("scroll не удался: %s", direction)
        return False


def click_at(x: int, y: int, button: str = "left") -> bool:
    """Кликает в координаты на экране.

    x, y: пиксели.
    button: "left" | "right" | "middle".
    Для сценариев: «кликни в 500 300» → click_at(500, 300).
    """
    log.info("click_at: (%d, %d) %s", x, y, button)
    try:
        import pyautogui
        pyautogui.click(x, y, button=button)
        return True
    except Exception:
        log.exception("click_at не удался: (%d, %d)", x, y)
        return False


# --- раскладка клавиатуры --------------------------------------------------

def switch_layout() -> bool:
    """Переключает раскладку через Alt+Shift (SendInput)."""
    log.info("Переключаю раскладку (Alt+Shift)")
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class INPUT(ctypes.Structure):
            _fields_ = [
                ("type", wintypes.DWORD),
                ("ki", KEYBDINPUT),
                ("padding", ctypes.c_ubyte * 8),
            ]

        VK_MENU = 0x12
        VK_SHIFT = 0x10
        KEYEVENTF_KEYUP = 0x0002
        INPUT_KEYBOARD = 1

        def _key(vk, up=False):
            inp = INPUT()
            inp.type = INPUT_KEYBOARD
            inp.ki.wVk = vk
            inp.ki.wScan = 0
            inp.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
            inp.ki.time = 0
            inp.ki.dwExtraInfo = None
            user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

        _key(VK_MENU)
        import time as _t
        _t.sleep(0.05)
        _key(VK_SHIFT)
        _t.sleep(0.05)
        _key(VK_SHIFT, up=True)
        _t.sleep(0.05)
        _key(VK_MENU, up=True)
        return True
    except Exception:
        log.exception("switch_layout не удался")
        return False


def _set_layout_hkl(hkl_hex: str) -> bool:
    """Устанавливает раскладку по HKL через PostMessage с фокусом."""
    log.info("Установка раскладки: %s", hkl_hex)
    try:
        import ctypes
        user32 = ctypes.windll.user32

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            log.warning("Нет foreground-окна")
            return False

        user32.SetForegroundWindow(hwnd)
        hkl = user32.LoadKeyboardLayoutW(hkl_hex, 1)
        user32.PostMessageW(hwnd, 0x50, 0, hkl)
        return True
    except Exception:
        log.exception("_set_layout_hkl не удался: %s", hkl_hex)
        return False


def set_layout_ru() -> bool:
    """Переключает на русскую раскладку."""
    return _set_layout_hkl("00000419")


def set_layout_en() -> bool:
    """Переключает на английскую раскладку."""
    return _set_layout_hkl("00000409")


def get_layout() -> str | None:
    """Возвращает 'ru', 'en' или None."""
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        thread_id = ctypes.windll.user32.GetWindowThreadProcessId(hwnd, None)
        hkl = ctypes.windll.user32.GetKeyboardLayout(thread_id)
        lang_id = hkl & 0xFFFF
        return {0x0419: "ru", 0x0409: "en"}.get(lang_id)
    except Exception:
        log.exception("get_layout не удался")
        return None


# --- громкость -------------------------------------------------------------

def get_volume() -> int | None:
    """Возвращает громкость в процентах (0..100)."""
    if not _caps_available("volume"):
        log.warning("Громкость недоступна (см. system_caps.json)")
        return None

    method = _caps_method("volume")
    try:
        from pycaw.pycaw import AudioUtilities
        device = AudioUtilities.GetSpeakers()

        if method == "volume_percent":
            return int(device.volume_percent)
        if method == "endpoint_volume":
            return round(device.EndpointVolume.GetMasterVolumeLevelScalar() * 100)
        if method == "activate":
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import IAudioEndpointVolume
            interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            vol = cast(interface, POINTER(IAudioEndpointVolume))
            return round(vol.GetMasterVolumeLevelScalar() * 100)
    except Exception:
        log.exception("get_volume не удался (method=%s)", method)
    return None


def set_volume(percent: int) -> bool:
    """Ставит громкость в процентах (0..100)."""
    if not _caps_available("volume"):
        log.warning("Громкость недоступна (см. system_caps.json)")
        return False

    percent = max(0, min(100, int(percent)))
    log.info("Громкость: %d%% (method=%s)", percent, _caps_method("volume"))

    method = _caps_method("volume")
    try:
        from pycaw.pycaw import AudioUtilities
        device = AudioUtilities.GetSpeakers()

        if method == "volume_percent":
            device.volume_percent = percent
            return True
        if method == "endpoint_volume":
            device.EndpointVolume.SetMasterVolumeLevelScalar(percent / 100.0, None)
            return True
        if method == "activate":
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import IAudioEndpointVolume
            interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            vol = cast(interface, POINTER(IAudioEndpointVolume))
            vol.SetMasterVolumeLevelScalar(percent / 100.0, None)
            return True
    except Exception:
        log.exception("set_volume не удался (method=%s)", method)
    return False


# --- яркость ---------------------------------------------------------------

def get_brightness() -> int | None:
    """Возвращает яркость в процентах (0..100)."""
    if not _caps_available("brightness"):
        log.warning("Яркость недоступна (см. system_caps.json)")
        return None
    try:
        import screen_brightness_control as sbc
        values = sbc.get_brightness()
        if values:
            return int(values[0])
        return None
    except Exception:
        log.exception("get_brightness не удался")
        return None


def set_brightness(percent: int) -> bool:
    """Ставит яркость в процентах (0..100)."""
    if not _caps_available("brightness"):
        log.warning("Яркость недоступна (см. system_caps.json)")
        return False
    percent = max(0, min(100, int(percent)))
    log.info("Яркость: %d%%", percent)
    try:
        import screen_brightness_control as sbc
        sbc.set_brightness(percent)
        return True
    except Exception:
        log.exception("set_brightness не удался")
        return False


# --- процессы --------------------------------------------------------------

def find_process(name: str, threshold: float = 0.7):
    """Находит имя процесса по неточному имени."""
    try:
        import psutil
    except ImportError:
        return None
    from jarvis.matching import match_score
    name_low = name.lower()
    best_name, best_score = None, 0.0
    for proc in psutil.process_iter(["name"]):
        pname = (proc.info.get("name") or "").lower()
        if not pname:
            continue
        base = pname.removesuffix(".exe")
        if name_low in base or base in name_low:
            return proc.info["name"]
        score = match_score(name_low, base)
        if score > best_score:
            best_name, best_score = proc.info["name"], score
    if best_name and best_score >= threshold:
        log.info("Процесс %r -> %s (score %.2f)", name, best_name, best_score)
        return best_name
    log.info("Процесс для %r не найден (лучший score %.2f)", name, best_score)
    return None


def kill_process(name: str) -> bool:
    protected = {"system", "svchost.exe", "csrss.exe", "wininit.exe",
                 "services.exe", "lsass.exe", "explorer.exe"}
    if name.lower() in protected:
        log.warning("Запрещено убивать защищённый процесс: %s", name)
        return False
    log.info("Убиваю процесс: %s", name)
    try:
        import psutil
        killed = False
        for proc in psutil.process_iter(["name"]):
            if (proc.info.get("name") or "").lower() == name.lower():
                proc.kill()
                killed = True
        return killed
    except Exception:
        log.exception("kill_process не удался: %s", name)
        return False


def close_browser() -> bool:
    """Закрывает ВСЕ известные браузеры.

    №89: раньше был early exit — при открытых Chrome + Firefox + Edge
    закрывался только первый. Теперь проходим по всем и убиваем всё,
    что нашли. Возвращаем True, если хоть один процесс убит.
    """
    any_killed = False
    for name in ("chrome.exe", "firefox.exe", "msedge.exe",
                 "opera.exe", "brave.exe", "yandex.exe"):
        base = name.removesuffix(".exe")
        if find_process(base) and kill_process(name):
            any_killed = True
    if any_killed:
        log.info("close_browser: закрыл все найденные браузеры")
    return any_killed


def minimize_window(name: str) -> bool:
    return minimize_window_by_title(name)


# --- печать и окна ---------------------------------------------------------

def type_text(text: str) -> bool:
    if not text:
        return False
    log.info("Печатаю: %r", text)
    try:
        import pyautogui
        try:
            import pyperclip
            old = pyperclip.paste()
            pyperclip.copy(text)
            time.sleep(0.05)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.15)
            pyperclip.copy(old)
            return True
        except Exception:
            log.debug("pyperclip не сработал, пробую pyautogui.typewrite")
        pyautogui.typewrite(text, interval=0.02)
        return True
    except Exception:
        log.exception("type_text не удался")
        return False


def minimize_all() -> bool:
    try:
        import pygetwindow as gw
        count = 0
        for w in gw.getAllWindows():
            try:
                if w.title and w.visible and not w.isMinimized:
                    w.minimize()
                    count += 1
            except Exception:
                pass
        log.info("Свёрнуто окон: %d", count)
        return True
    except Exception:
        try:
            import pyautogui
            pyautogui.hotkey("win", "d")
            return True
        except Exception:
            log.exception("minimize_all не удался")
            return False


_WINDOW_SYNONYMS = {
    "консоль": ["cmd.exe", "powershell", "command prompt", "c:\\users\\", "c:\\windows\\", "c:\\jarvis"],
    "терминал": ["cmd.exe", "powershell", "command prompt", "c:\\users\\", "c:\\windows\\", "c:\\jarvis"],
    "командную строку": ["cmd.exe", "command prompt", "c:\\users\\", "c:\\windows\\"],
    "командная строка": ["cmd.exe", "command prompt", "c:\\users\\", "c:\\windows\\"],
    "cmd": ["cmd.exe", "command prompt", "c:\\users\\", "c:\\windows\\"],
    "браузер": ["chrome", "firefox", "яндекс", "yandex", "edge", "opera", "brave"],
    "хром": ["chrome"],
    "яндекс браузер": ["яндекс", "yandex"],
    "firefox": ["firefox"],
    "файрфокс": ["firefox"],
    "edge": ["edge"],
    "эдж": ["edge"],
    "телега": ["telegram"],
    "телеграм": ["telegram"],
    "тг": ["telegram"],
    "дискорд": ["discord"],
    "дс": ["discord"],
    "стим": ["steam"],
    "steam": ["steam"],
    "проводник": ["проводник", "explorer"],
    "explorer": ["проводник", "explorer"],
    "папку": ["проводник", "explorer"],
    "настройки": ["настройки", "settings", "параметры"],
    "параметры": ["параметры", "settings", "настройки"],
    "оллама": ["ollama"],
    "ollama": ["ollama"],
    "радмин": ["radmin"],
    "radmin": ["radmin"],
    "овервульф": ["overwolf"],
    "overwolf": ["overwolf"],
}


def _find_window(name: str):
    try:
        import pygetwindow as gw
    except ImportError:
        return None

    windows = [w for w in gw.getAllWindows() if w.title]
    name_low = name.lower().strip()

    for noise in (" музыка", " browser", " браузер"):
        if name_low.endswith(noise):
            name_low = name_low[: -len(noise)].strip()

    direct = [w for w in windows if name_low in w.title.lower()]
    if direct:
        for w in direct:
            try:
                if w.visible and not w.isMinimized:
                    return w
            except Exception:
                pass
        return direct[0]

    subs = None
    for key, values in _WINDOW_SYNONYMS.items():
        if key == name_low or key in name_low or name_low in key:
            subs = values
            break
    if subs:
        for sub in subs:
            sub_low = sub.lower()
            for w in windows:
                if sub_low in w.title.lower():
                    try:
                        if w.visible and not w.isMinimized:
                            return w
                    except Exception:
                        pass
        for sub in subs:
            sub_low = sub.lower()
            for w in windows:
                if sub_low in w.title.lower():
                    return w

    from jarvis.matching import match_score
    best = None
    best_score = 0.6
    for w in windows:
        title = w.title.lower()
        score = match_score(name_low, title[:40])
        if score > best_score:
            best_score, best = score, w
    if best:
        log.info("Окно %r -> %s (score %.2f)", name, best.title, best_score)
    return best


def minimize_window_by_title(name: str) -> bool:
    w = _find_window(name)
    if not w:
        log.warning("Окно не найдено для сворачивания: %s", name)
        return False
    try:
        w.minimize()
        log.info("Свернул окно: %s", w.title)
        return True
    except Exception:
        log.exception("minimize_window_by_title не удался")
        return False


def maximize_window_by_title(name: str) -> bool:
    w = _find_window(name)
    if not w:
        log.warning("Окно не найдено для разворачивания: %s", name)
        return False
    try:
        if getattr(w, "isMinimized", False):
            w.restore()
            time.sleep(0.15)
        w.maximize()
        try:
            w.activate()
        except Exception:
            pass
        log.info("Развернул окно: %s", w.title)
        return True
    except Exception:
        log.exception("maximize_window_by_title не удался")
        return False


def activate_window_by_title(name: str) -> bool:
    w = _find_window(name)
    if not w:
        log.warning("Окно не найдено для активации: %s", name)
        return False
    try:
        if getattr(w, "isMinimized", False):
            w.restore()
            time.sleep(0.15)
        w.activate()
        log.info("Активировал окно: %s", w.title)
        return True
    except Exception:
        log.exception("activate_window_by_title не удался")
        return False


def minimize_active() -> bool:
    try:
        import pyautogui
        pyautogui.hotkey("win", "down")
        log.info("Свернул активное окно")
        return True
    except Exception:
        log.exception("minimize_active не удался")
        return False


def maximize_active() -> bool:
    try:
        import pyautogui
        pyautogui.hotkey("win", "up")
        log.info("Развернул активное окно")
        return True
    except Exception:
        log.exception("maximize_active не удался")
        return False


def switch_window(back: bool = False) -> bool:
    try:
        import pyautogui
        if back:
            pyautogui.hotkey("alt", "shift", "tab")
            log.info("Переключил окно назад")
        else:
            pyautogui.hotkey("alt", "tab")
            log.info("Переключил окно")
        return True
    except Exception:
        log.exception("switch_window не удался")
        return False


# --- папки пользователя ----------------------------------------------------

_USER_FOLDERS = {
    "загрузки": Path.home() / "Downloads",
    "скачанное": Path.home() / "Downloads",
    "документы": Path.home() / "Documents",
    "рабочий стол": Path.home() / "Desktop",
    "изображения": Path.home() / "Pictures",
    "картинки": Path.home() / "Pictures",
    "музыка": Path.home() / "Music",
    "видео": Path.home() / "Videos",
    "скриншоты": Path.home() / "Pictures" / "Screenshots",
}


def resolve_user_folder(name: str):
    name = name.lower().strip()
    for key, path in _USER_FOLDERS.items():
        if key in name:
            return path
    return None


# --- буфер обмена -----------------------------------------------------------

def copy_selection() -> bool:
    """Нажимает Ctrl+C, чтобы скопировать выделенное в активном окне."""
    log.info("Копирую выделенное (Ctrl+C)")
    try:
        import pyautogui
        pyautogui.hotkey("ctrl", "c")
        return True
    except Exception:
        log.exception("copy_selection не удался")
        return False


def clipboard_read() -> str:
    log.info("Читаю буфер обмена")
    try:
        import pyperclip
        text = pyperclip.paste() or ""
        log.info("Буфер обмена: %r", text[:80])
        return text
    except Exception:
        log.exception("clipboard_read не удался")
        return ""


def clipboard_write(text: str) -> bool:
    log.info("Пишу в буфер обмена: %r", text[:80])
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception:
        log.exception("clipboard_write не удался")
        return False


def clipboard_clear() -> bool:
    log.info("Очищаю буфер обмена")
    return clipboard_write("")
```

### `jarvis\apps.py`

```python
"""Каталог известных приложений: как их зовут голосом, как открыть и как закрыть."""

import logging
import os
import winreg
from dataclasses import dataclass, field
from pathlib import Path

from jarvis.matching import match_score

log = logging.getLogger("jarvis.apps")


@dataclass
class App:
    key: str
    title: str          # как назвать в ответе («Открываю Дискорд»)
    aliases: list       # как пользователь может назвать приложение
    open_specs: list    # кандидаты ("uri"|"exe"|"cmd", значение) — берётся первый рабочий
    procs: list = field(default_factory=list)  # имена процессов для «закрой»

    def resolve_open(self):
        for kind, value in self.open_specs:
            if kind == "exe":
                if Path(value).exists():
                    return ("exe", value)
            else:
                return (kind, value)
        return None


def _steam_exe() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            return winreg.QueryValueEx(k, "SteamExe")[0]
    except OSError:
        return None


def _expand(p: str) -> str:
    return os.path.expandvars(p)


def build_apps(config: dict) -> list[App]:
    steam = _steam_exe() or r"C:\Program Files (x86)\Steam\steam.exe"
    discord_updater = _expand(r"%LOCALAPPDATA%\Discord\Update.exe")

    apps = [
        App(
            "discord", "Дискорд",
            ["дискорд", "дис", "дс", "дэ эс", "discord"],
            [("cmd", [discord_updater, "--processStart", "Discord.exe"])],
            ["Discord.exe"],
        ),
        App(
            "telegram", "Телеграм",
            ["телеграм", "телеграмм", "телега", "тг", "тэ гэ", "telegram"],
            [("exe", _expand(r"%APPDATA%\Telegram Desktop\Telegram.exe"))],
            ["Telegram.exe"],
        ),
        App(
            "steam", "Стим",
            ["стим", "steam"],
            [("exe", steam)],
            ["steam.exe"],
        ),
        App(
            "dota2", "Дота два",
            ["дота", "дота два", "доту", "дотан", "dota"],
            [("uri", "steam://rungameid/570")],
            ["dota2.exe"],
        ),
        App(
            "claude", "Клод Десктоп",
            ["клод", "клауд", "клод десктоп", "клауд десктоп", "claude"],
            [("exe", _expand(r"%LOCALAPPDATA%\AnthropicClaude\claude.exe"))],
            ["claude.exe"],
        ),
        App(
            "vscode", "Вэ Эс Код",
            ["вс код", "вэ эс код", "в эс код", "вес код", "vs code", "vscode", "вс-код"],
            [("exe", _expand(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"))],
            ["Code.exe"],
        ),
        App("calc", "Калькулятор", ["калькулятор"], [("uri", "calc:")], ["CalculatorApp.exe", "Calculator.exe"]),
        App("notepad", "Блокнот", ["блокнот"], [("cmd", ["notepad.exe"])], ["notepad.exe", "Notepad.exe"]),
        App("explorer", "Проводник", ["проводник", "папку", "файлы"], [("cmd", ["explorer.exe"])]),
        App("paint", "Пэйнт", ["пэйнт", "паинт", "пейнт", "рисовалку"], [("cmd", ["mspaint.exe"])], ["mspaint.exe"]),
        App("taskmgr", "Диспетчер задач", ["диспетчер задач", "диспетчер"], [("cmd", ["taskmgr.exe"])], ["Taskmgr.exe"]),
    ]

    # Переопределение путей из config.json: "app_paths": {"discord": "C:\\...\\Discord.exe"}
    overrides = config.get("app_paths") or {}
    for app in apps:
        if app.key in overrides:
            app.open_specs = [("exe", _expand(overrides[app.key]))]
    return apps


def find_app(apps: list[App], target: str) -> App | None:
    """Лучшее совпадение цели с псевдонимами приложений (точное/вхождение/нечёткое)."""
    best, best_score = None, 0.0
    for app in apps:
        for alias in app.aliases:
            if target == alias:
                return app
            score = match_score(target, alias)
            if score > best_score:
                best, best_score = app, score
    if best_score >= 0.75:
        log.info("Цель %r -> %s (score %.2f)", target, best.key, best_score)
        return best
    log.info("Цель %r не сопоставлена (лучший score %.2f)", target, best_score)
    return None
```

### `jarvis\brain.py`

```python
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

Поля: action; target; query; engine; reply; text; mode; name; voice; percent; seconds; time; task; folder; day; minimized; key; value.

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
open_profile (открыть profile.json в редакторе)
get_weather (target — город; day: today|tomorrow)
get_currency (target — ISO: USD|EUR|CNY|BYN|KZT|GBP|JPY|TRY|UAH)
set_profile (key: name|default_city, value — сохранить в профиль)
get_profile (key: name|default_city — прочитать из профиля)
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
открой профиль -> {"action":"open_profile"}
открой профиль в вс код -> {"action":"open_profile","editor":"vscode"}
какая погода -> {"action":"get_weather","day":"today"}
какая погода в москве -> {"action":"get_weather","target":"Москва","day":"today"}
погода в питере на завтра -> {"action":"get_weather","target":"Санкт-Петербург","day":"tomorrow"}
курс доллара -> {"action":"get_currency","target":"USD"}
курс евро -> {"action":"get_currency","target":"EUR"}
курс валют -> {"action":"get_currency"}
меня зовут Максим -> {"action":"set_profile","key":"name","value":"Максим"}
мой город Казань -> {"action":"set_profile","key":"default_city","value":"Казань"}
как меня зовут -> {"action":"get_profile","key":"name"}
какой город -> {"action":"get_profile","key":"default_city"}
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

Поля: action; target; query; engine; reply; text; mode; name; voice; percent; seconds; time; task; folder; day; minimized; key; value.

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
open_config / open_log / open_profile
get_weather (target; day) / get_currency (target)
set_profile (key: name|default_city, value) / get_profile (key: name|default_city)
answer (reply)
none

=== ГЛАВНОЕ ===
«Закрой», «выключи», «убей» → close_app.
«Открой», «запусти», «врубай» → open_app / open_site / open_folder.

=== ПРИМЕРЫ ===
открой стим -> open_app target стим
закрой стим -> close_app target стим
открой ютуб -> open_site target ютуб
открой профиль -> open_profile
какая погода в москве -> get_weather target Москва
курс доллара -> get_currency target USD
громкость 50 -> set_volume percent 50
смени голос на ирину -> change_voice voice irina
меня зовут Максим -> set_profile key=name value=Максим
какой город -> get_profile key=default_city

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
Разбирай команды в JSON. Поля: action; target; query; engine; reply; text; mode; name; voice; percent; seconds; time; task; folder; day; minimized; key; value.

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
open_config, open_log, open_profile, get_weather, get_currency, answer, none,
set_profile (key: name|default_city, value — сохранить в профиль),
get_profile (key: name|default_city — прочитать из профиля).

=== ПРОФИЛЬ ===
Пользователь просит запомнить/поменять → set_profile.
    «меня зовут Максим» → {"action":"set_profile","key":"name","value":"Максим"}
    «мой город Казань» → {"action":"set_profile","key":"default_city","value":"Казань"}
    «поменяй город на Москву» → {"action":"set_profile","key":"default_city","value":"Москва"}
    «запомни: мой город X» → {"action":"set_profile","key":"default_city","value":"X"}

Пользователь спрашивает про себя → get_profile.
    «как меня зовут» → {"action":"get_profile","key":"name"}
    «какой мой город» → {"action":"get_profile","key":"default_city"}
    «какой город» → {"action":"get_profile","key":"default_city"}

=== ФАЙЛЫ ===
    «открой профиль» → {"action":"open_profile"}
    «открой профиль в вс код» → {"action":"open_profile","editor":"vscode"}
    «открой профиль в блокноте» → {"action":"open_profile","editor":"system"}
    «открой конфиг» → {"action":"open_config"}
    «открой журнал» → {"action":"open_log"}

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
        # Для JSON-разбора команды — БЕЗ контекста обучения.
        # Факты и коррекции нужны в диалоге (chat / chat_stream),
        # но в parse() они только путают модель.
        return self._request([{"role": "system", "content": self.system_prompt},
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
    "set_profile", "get_profile",
    "open_profile",
}
```

### `jarvis\config.py`

```python
"""Загрузка конфигурации и объект Config в памяти.

Раньше: каждый модуль читал config.json с диска.
Сейчас: Config живёт в памяти, читается один раз, изменения рассылаются подписчикам.

Запись — через config_manager (единый FileLock).

Совместимость: Config поддерживает config["key"] и config.get("key").
"""

import logging
from pathlib import Path
from typing import Any, Callable

from jarvis import config_manager

log = logging.getLogger("jarvis.config")

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_CONFIG = {
    "wake_words": ["феникс", "финикс", "феникса", "fenix", "phoenix",
                   "джарвис", "jarvis"],
    "tts_backend": "auto",
    "xtts_ref": "voices/jarvis.wav",
    "tts_voice": "ruslan",
    "tts_voice_quality": "medium",
    "voice_rate": 1.15,
    "voice": "Pavel",
    "sample_rate": 16000,
    "input_device": None,
    "mic_check_sec": 20,
    "mic_watchdog_enabled": True,
    "command_window_sec": 8,
    "dialog_window_sec": 20,
    "use_whisper": True,
    "whisper_model": "coriollon/whisper-large-v3-turbo-russian",
    "whisper_device": "auto",
    "mode": "combo",
    "barge_enabled": True,
    "use_llm": True,
    "llm_model": "qwen2.5:7b-instruct",
    "ollama_url": "http://127.0.0.1:11434",
    "prompt_level": "auto",
    "llm_temperature": 0.7,
    "music_app": "яндекс музыка",
    "music_wait_sec": 6,
    "active_packs": [],
    "app_paths": {},
    "custom_commands": [],
    "timers_file": "timers.json",
    "tasks_file": "tasks.json",
    "memory_file": "dialog.json",
    "memory_max": 100,
    "llm_context_messages": 20,
    "weather_cache_ttl_sec": 600,
    "danger_password": "",
    "gui_enabled": True,
    "gui_theme": "dark-blue",
    "gui_x": None,
    "gui_y": None,
    "tray_enabled": True,
    "launch_mode": "gui",
}


class Config:
    """Конфиг в памяти с подписками на изменения."""

    def __init__(self, path: Path | None = None):
        self.path = path or (BASE_DIR / "config.json")
        self._data: dict = {}
        self._listeners: list[Callable[[str, Any], None]] = []
        self.reload()

    def reload(self) -> None:
        """Перечитывает config.json с диска. Вызывается при старте."""
        raw = config_manager.load(path=self.path)
        if not self.path.exists():
            merged = dict(DEFAULT_CONFIG)
            config_manager.save(merged, path=self.path)
            log.info("Создан конфиг по умолчанию: %s", self.path)
        else:
            merged = dict(DEFAULT_CONFIG)
            merged.update(raw)
            log.info("Конфиг загружен: %d ключей из %s", len(merged), self.path.name)
        self._data = merged

    # --- чтение ----------------------------------------------------------

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def all_data(self) -> dict:
        return dict(self._data)

    # --- запись ----------------------------------------------------------

    def set(self, key: str, value) -> bool:
        """Ставит значение, сохраняет на диск, оповещает подписчиков."""
        if self._data.get(key) == value:
            return True
        self._data[key] = value
        ok = config_manager.save(self._data, path=self.path)

        if not ok:
            log.error("Config.set: save не удался на ключе %s", key)
            return False

        for cb in list(self._listeners):
            try:
                cb(key, value)
            except Exception:
                log.exception("Подписчик Config упал на ключе %s", key)
        return True

    def update(self, data: dict) -> bool:
        """Массовое обновление. Оповещает по каждому ключу."""
        changed = {k: v for k, v in data.items() if self._data.get(k) != v}
        if not changed:
            return True
        self._data.update(changed)
        ok = config_manager.save(self._data, path=self.path)

        if not ok:
            log.error(
                "Config.update: save не удался, подписчики не уведомлены (%d ключей)",
                len(changed),
            )
            return False

        for key, value in changed.items():
            for cb in list(self._listeners):
                try:
                    cb(key, value)
                except Exception:
                    log.exception("Подписчик Config упал на ключе %s", key)
        return True

    def subscribe(self, callback: Callable[[str, Any], None]) -> None:
        """Регистрирует callback(key, value), вызываемый при set/update."""
        if callback in self._listeners:
            return
        self._listeners.append(callback)

    def unsubscribe(self, callback: Callable[[str, Any], None]) -> None:
        """№95: удаляет подписку. Без этого Brain при пересоздании
        оставался в списке — утечка."""
        try:
            self._listeners.remove(callback)
            log.info("Config: подписка удалена (%s)", callback)
        except ValueError:
            log.debug("Config: подписки %s не было", callback)

    # --- совместимость с dict --------------------------------------------

    def __getitem__(self, key):
        return self._data[key]

    def __contains__(self, key):
        return key in self._data

    def __repr__(self):
        return f"Config({len(self._data)} keys)"


_GLOBAL: Config | None = None


def load_config(base_dir: Path | None = None) -> Config:
    """Создаёт глобальный Config."""
    global _GLOBAL
    if _GLOBAL is None:
        path = (base_dir / "config.json") if base_dir else None
        _GLOBAL = Config(path)
    return _GLOBAL


def get_global() -> Config:
    if _GLOBAL is None:
        raise RuntimeError("Config не создан. Вызови load_config() при старте.")
    return _GLOBAL
```

### `jarvis\config_manager.py`

```python
"""Единый менеджер записи в config.json.

Зачем:
    Раньше _atomic_write был продублирован в modes.py, voices.py, packs.py.
    Три лока, три .tmp, гонка между модулями.
    Плюс path.with_suffix(".tmp") давал общий временный файл.

Как работает:
    - Один FileLock на весь проект (работает и между процессами).
    - Уникальный .tmp через tempfile.mkstemp.
    - os.replace для атомарной подмены.
    - Логи: сколько ключей прочитано / записано.
"""

import json
import logging
import os
import tempfile
from pathlib import Path

from filelock import FileLock

log = logging.getLogger("jarvis.config_manager")

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"
_LOCK_PATH = BASE_DIR / "config.json.lock"
_lock = FileLock(str(_LOCK_PATH))


def load(path: Path | None = None) -> dict:
    """Читает JSON. Если файла нет или он битый — возвращает {}."""
    p = Path(path) if path else CONFIG_PATH
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            log.warning("Файл %s не словарь (%s) — возвращаю {}", p.name, type(data).__name__)
            return {}
        return data
    except Exception:
        log.exception("Не удалось прочитать %s", p)
        return {}


def save(data: dict, path: Path | None = None) -> bool:
    """Атомарно записывает JSON. Возвращает True при успехе."""
    p = Path(path) if path else CONFIG_PATH
    if not isinstance(data, dict):
        log.error("save: data не словарь (%s) — отказ", type(data).__name__)
        return False
    try:
        with _lock:
            log.info("save: пишу %d ключей → %s", len(data), p.name)
            fd, tmp_name = tempfile.mkstemp(
                dir=str(p.parent), suffix=".tmp", prefix=p.stem + "."
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_name, p)
                return True
            except Exception:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
    except Exception:
        log.exception("Не удалось записать %s", p)
        return False


def update(key: str, value, path: Path | None = None) -> bool:
    """Читает, меняет одно поле, записывает. Всё под одним локом."""
    p = Path(path) if path else CONFIG_PATH
    try:
        with _lock:
            data = load(p)
            log.info("update: key=%r, до=%d ключей, файл=%s", key, len(data), p.name)
            data[key] = value
            fd, tmp_name = tempfile.mkstemp(
                dir=str(p.parent), suffix=".tmp", prefix=p.stem + "."
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_name, p)
                return True
            except Exception:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
    except Exception:
        log.exception("Не удалось обновить %s", p)
        return False
```

### `jarvis\files.py`

```python
"""Файлы и папки: открыть, посмотреть содержимое, создать."""

import logging
import re
import subprocess
from pathlib import Path

log = logging.getLogger("jarvis.files")

# Основа слова -> папка пользователя. У «музыки» и «видео» намеренно нет
# коротких основ: «открой музыку» — это про плеер, папка только со словом «папка».
_FOLDER_STEMS = {
    "рабоч": "Desktop", "стол": "Desktop",
    "загрузк": "Downloads", "скачанн": "Downloads", "скачк": "Downloads",
    "документ": "Documents",
    "изображен": "Pictures", "картин": "Pictures", "фотограф": "Pictures", "фотк": "Pictures",
    "скриншот": Path("Pictures") / "Screenshots", "скрин": Path("Pictures") / "Screenshots",
}
_FOLDER_STEMS_EXPLICIT = {  # только при явном слове «папка»
    "музык": "Music", "видео": "Videos", "загруз": "Downloads",
}

_EXT_WORDS = {"текст": ".txt", "заметк": ".txt", "маркдаун": ".md",
              "питон": ".py", "джейсон": ".json"}


def resolve_folder(spoken: str, explicit: bool = False) -> Path | None:
    """«загрузки», «рабочем столе» -> реальная папка пользователя."""
    stems = dict(_FOLDER_STEMS)
    if explicit:
        stems.update(_FOLDER_STEMS_EXPLICIT)
    for word in spoken.split():
        for stem, sub in stems.items():
            if word.startswith(stem):
                path = Path.home() / sub
                if path.exists():
                    return path
    return None


def open_folder(path: Path) -> None:
    log.info("Открываю папку: %s", path)
    subprocess.Popen(["explorer", str(path)])


def describe_folder(path: Path, limit: int = 5) -> str:
    """Человеческое описание содержимого папки для озвучки."""
    try:
        entries = list(path.iterdir())
    except OSError:
        return f"Не могу заглянуть в папку {path.name}."
    files = [e for e in entries if e.is_file()]
    dirs = [e for e in entries if e.is_dir()]
    if not entries:
        return f"Папка {path.name} пуста."
    recent = sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)[:limit]
    names = ", ".join(f.stem for f in recent)
    parts = []
    if files:
        parts.append(f"{len(files)} {_plural(len(files), 'файл', 'файла', 'файлов')}")
    if dirs:
        parts.append(f"{len(dirs)} {_plural(len(dirs), 'папка', 'папки', 'папок')}")
    reply = f"Здесь {' и '.join(parts)}."
    if names:
        reply += f" Последние: {names}."
    return reply


def create_file(folder: Path, name: str, ext: str = ".txt") -> Path:
    name = re.sub(r'[<>:"/\\|?*]', "", name).strip() or "новый файл"
    if not Path(name).suffix:
        name += ext
    path = folder / name
    n = 1
    while path.exists():
        n += 1
        path = folder / f"{Path(name).stem} {n}{Path(name).suffix}"
    path.touch()
    log.info("Создан файл: %s", path)
    return path


def create_folder(folder: Path, name: str) -> Path:
    name = re.sub(r'[<>:"/\\|?*]', "", name).strip() or "новая папка"
    path = folder / name
    n = 1
    while path.exists():
        n += 1
        path = folder / f"{name} {n}"
    path.mkdir(parents=True)
    log.info("Создана папка: %s", path)
    return path


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many
```

### `jarvis\gui.py`

```python
"""GUI Феникса — интерактивное окно на Flet 1.0.3.

Архитектура:
    Jarvis → очередь (queue.Queue) → Flet worker (page.run_task) → обновление UI.
    Обратно: UI → callback → Jarvis.

Связь с Jarvis:
    GUI → Jarvis: callbacks (on_mode_change, on_voice_change, ...)
    Jarvis → GUI: gui.add_message(...), gui.set_state(...), gui.add_stream_chunk(...)

Профиль:
    Подписка на profile.subscribe — при смене профиля пересобираем _tabs.

launch_mode=tray:
    GUI запускается всегда (Flet в главном потоке), но окно скрыто.
    show_window() / open_settings_tab() — вызываются из трея.
"""

import asyncio
import logging
import os
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

import flet as ft

log = logging.getLogger("jarvis.gui")

PALETTES = {
    "dark": {
        "bg_main": "#0e1116",
        "bg_card": "#161b22",
        "bg_bubble_user": "#1f6feb",
        "bg_bubble_ai": "#21262d",
        "accent": "#58a6ff",
        "text": "#e6edf3",
        "text_dim": "#8b949e",
        "border": "#30363d",
        "error": "#f85149",
        "success": "#3fb950",
        "warning": "#d29922",
    },
    "light": {
        "bg_main": "#f6f8fa",
        "bg_card": "#ffffff",
        "bg_bubble_user": "#0969da",
        "bg_bubble_ai": "#eaeef2",
        "accent": "#0969da",
        "text": "#1f2328",
        "text_dim": "#656d76",
        "border": "#d0d7de",
        "error": "#cf222e",
        "success": "#1a7f37",
        "warning": "#9a6700",
    },
}


def _detect_system_theme() -> str:
    """Определяет тему Windows: 'dark' или 'light'."""
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if value == 1 else "dark"
    except Exception:
        log.exception("Не удалось определить тему Windows — беру тёмную")
        return "dark"


class _Palette:
    def __init__(self):
        self._data = PALETTES["dark"]

    def set(self, name: str):
        self._data = PALETTES.get(name, PALETTES["dark"])

    def __getattr__(self, key):
        return self._data.get(key, "")


P = _Palette()

BG_DARK = "#0e1116"
BG_CARD = "#161b22"
BG_BUBBLE_USER = "#1f6feb"
BG_BUBBLE_AI = "#21262d"
ACCENT = "#58a6ff"
TEXT = "#e6edf3"
TEXT_DIM = "#8b949e"


def _apply_palette(name: str) -> None:
    global BG_DARK, BG_CARD, BG_BUBBLE_USER, BG_BUBBLE_AI, ACCENT, TEXT, TEXT_DIM
    P.set(name)
    BG_DARK = P.bg_main
    BG_CARD = P.bg_card
    BG_BUBBLE_USER = P.bg_bubble_user
    BG_BUBBLE_AI = P.bg_bubble_ai
    ACCENT = P.accent
    TEXT = P.text
    TEXT_DIM = P.text_dim


STATES = {
    "idle":      ("#484f58", "Спит",   "Жду «Феникс»"),
    "listening": ("#d29922", "Слушаю", "Слушаю команду"),
    "speaking":  ("#3fb950", "Говорю", "Отвечаю"),
    "error":     ("#f85149", "Ошибка", "Проверь логи"),
}

THEMES = {
    "Системная": ft.ThemeMode.SYSTEM,
    "Тёмная": ft.ThemeMode.DARK,
    "Светлая": ft.ThemeMode.LIGHT,
}

LLM_MODELS = [
    "qwen2.5:0.5b", "qwen2.5:1.5b-instruct", "qwen2.5:3b-instruct",
    "qwen2.5:7b-instruct", "qwen2.5:14b-instruct", "qwen2.5:32b-instruct",
    "gemma2:2b", "gemma2:9b", "llama3.1:8b", "mistral:7b",
]

TTS_BACKENDS = ["auto", "piper", "xtts", "winrt", "sapi"]


class FenixGUI:
    """Окно Феникса на Flet."""

    def __init__(self, jarvis, config):
        self.jarvis = jarvis
        self.config = config
        self._queue = queue.Queue()
        self._thread = None
        self._running = False

        # launch_mode=tray — окно скрыто при старте
        self.start_hidden = False

        # Состояние
        self._state = "idle"
        self._stream_bubble = None
        self._stream_text = ""
        self._stream_label = None

        # Ссылки на контролы
        self._status_circle = None
        self._status_text = None
        self._status_sub = None
        self._history_list = None
        self._input_field = None
        self._mic_btn = None
        self._content_area = None
        self._rail = None
        self._tabs = {}

        # Контролы вкладки «Микрофон»
        self._mic_dropdown = None
        self._mic_level_bar = None
        self._mic_level_text = None
        self._mic_status_text = None
        self._mic_peak_text = None
        self._mic_utt_text = None
        self._mic_test_result = None

        self._page = None

        # №92: подписка на смену профиля
        try:
            from jarvis import profile as _profile
            _profile.subscribe(self._on_profile_switch)
        except Exception:
            log.exception("Не удалось подписаться на смену профиля в GUI")

    def _on_profile_switch(self, old_name: str, new_name: str) -> None:
        """№92: при смене профиля просим UI пересобраться."""
        if old_name == new_name:
            return
        log.info("GUI: профиль сменился %s → %s — пересобираю вкладки",
                 old_name, new_name)
        self._queue.put(("rebuild_ui", None))

    # ---------------------------------------------------------------
    # Публичный API
    # ---------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="gui")
        self._thread.start()
        log.info("GUI (Flet) запущен в потоке")

    def run_main(self) -> None:
        """Запускает Flet в ТЕКУЩЕМ (главном) потоке."""
        if self._running:
            return
        self._running = True
        try:
            ft.run(self._main)
        except Exception:
            log.exception("GUI (Flet) упал")
        finally:
            self._running = False

    def stop(self) -> None:
        self._running = False
        self._queue.put(("stop", None))

    def show_window(self) -> None:
        """Показать окно (для launch_mode=tray)."""
        self._queue.put(("show_window", None))

    def open_settings_tab(self) -> None:
        """Открыть GUI на вкладке «Настройки»."""
        self._queue.put(("open_settings_tab", None))

    def add_message(self, role: str, text: str) -> None:
        self._queue.put(("message", (role, text)))

    def add_stream_chunk(self, chunk: str) -> None:
        self._queue.put(("stream_chunk", chunk))

    def end_stream(self) -> None:
        self._queue.put(("stream_end", None))

    def set_state(self, state: str) -> None:
        self._queue.put(("state", state))

    # ---------------------------------------------------------------
    # Flet
    # ---------------------------------------------------------------

    def _run(self) -> None:
        try:
            ft.run(self._main)
        except Exception:
            log.exception("GUI (Flet) упал")
        finally:
            self._running = False

    def _main(self, page: ft.Page) -> None:
        self._page = page

        theme_name = self.config.get("gui_theme", "Системная")
        if theme_name not in THEMES:
            theme_name = "Системная"
        theme_mode = THEMES[theme_name]

        if theme_mode == ft.ThemeMode.SYSTEM:
            palette_name = _detect_system_theme()
            log.info("Системная тема: %s", palette_name)
            _apply_palette(palette_name)
        elif theme_mode == ft.ThemeMode.LIGHT:
            _apply_palette("light")
        else:
            _apply_palette("dark")

        page.title = "Феникс"
        page.window.width = 1100
        page.window.height = 760
        page.window.min_width = 900
        page.window.min_height = 600
        page.padding = 0
        page.spacing = 0
        page.bgcolor = BG_DARK
        page.theme_mode = theme_mode
        page.theme = ft.Theme(
            color_scheme_seed=ACCENT,
            font_family="Segoe UI",
        )

        x = self.config.get("gui_x")
        y = self.config.get("gui_y")
        if x is not None and y is not None:
            page.window.left = x
            page.window.top = y

        # launch_mode=tray — окно скрыто
        if self.start_hidden:
            page.window.visible = False
            log.info("GUI: окно скрыто при старте (launch_mode=tray)")

        self._build_ui(page)
        page.run_task(self._process_queue)
        page.run_task(self._mic_level_loop)

    def _build_ui(self, page: ft.Page) -> None:
        self._rail = ft.NavigationRail(
            selected_index=0,
            label_type=ft.NavigationRailLabelType.ALL,
            min_width=90,
            min_extended_width=200,
            bgcolor=BG_CARD,
            indicator_color=ACCENT,
            group_alignment=-1.0,
            destinations=[
                ft.NavigationRailDestination(
                    icon=ft.Icons.HOME_OUTLINED,
                    selected_icon=ft.Icons.HOME,
                    label="Главная",
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.MIC_NONE,
                    selected_icon=ft.Icons.MIC,
                    label="Микрофон",
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.SETTINGS_OUTLINED,
                    selected_icon=ft.Icons.SETTINGS,
                    label="Настройки",
                ),
            ],
            on_change=self._on_nav_change,
        )

        self._tabs = {
            0: self._build_main_tab(),
            1: self._build_mic_tab(),
            2: self._build_settings_tab(),
        }

        self._content_area = ft.Container(
            content=self._tabs[0],
            expand=True,
            padding=0,
            bgcolor=BG_DARK,
        )

        page.add(
            ft.Row(
                controls=[
                    self._rail,
                    self._content_area,
                ],
                expand=True,
                spacing=0,
            )
        )

    def _build_main_tab(self) -> ft.Control:
        self._status_circle = ft.Container(
            width=80,
            height=80,
            border_radius=40,
            bgcolor="#484f58",
            animate=ft.Animation(300, ft.AnimationCurve.EASE_IN_OUT),
            shadow=ft.BoxShadow(
                blur_radius=24,
                color="#484f58",
                spread_radius=2,
            ),
        )

        self._status_text = ft.Text(
            "Спит", size=24, weight=ft.FontWeight.BOLD, color=TEXT,
        )
        self._status_sub = ft.Text(
            "Жду «Феникс»", size=13, color=TEXT_DIM,
        )

        status_bar = ft.Container(
            content=ft.Row(
                controls=[
                    self._status_circle,
                    ft.Column(
                        controls=[self._status_text, self._status_sub],
                        spacing=2,
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                ],
                spacing=20,
            ),
            padding=ft.Padding(left=30, top=25, right=30, bottom=20),
        )

        controls_bar = self._build_controls()

        self._history_list = ft.ListView(
            spacing=12,
            auto_scroll=True,
            expand=True,
        )
        history_container = ft.Container(
            content=self._history_list,
            expand=True,
            padding=ft.Padding(left=30, right=30, top=10, bottom=10),
        )

        input_bar = self._build_input()

        return ft.Column(
            controls=[
                status_bar,
                controls_bar,
                history_container,
                input_bar,
            ],
            spacing=0,
            expand=True,
        )

    def _build_controls(self) -> ft.Container:
        def _label(text):
            return ft.Text(text, width=80, color=TEXT_DIM, size=13)

        mode_row = ft.Row(
            controls=[
                _label("Режим:"),
                ft.RadioGroup(
                    value=self.config.get("mode", "combo"),
                    on_change=self._on_mode_change,
                    content=ft.Row(
                        controls=[
                            ft.Radio(value="commands", label="Команды", active_color=ACCENT),
                            ft.Radio(value="llm", label="ИИ", active_color=ACCENT),
                            ft.Radio(value="combo", label="Комбо", active_color=ACCENT),
                        ],
                        spacing=10,
                    ),
                ),
            ],
            spacing=10,
        )

        voice_row = ft.Row(
            controls=[
                _label("Голос:"),
                ft.Dropdown(
                    value=self.config.get("tts_voice", "ruslan"),
                    options=[
                        ft.dropdown.Option("ruslan"),
                        ft.dropdown.Option("dmitri"),
                        ft.dropdown.Option("irina"),
                        ft.dropdown.Option("denis"),
                    ],
                    width=160,
                    border_color="#30363d",
                    focused_border_color=ACCENT,
                    text_size=13,
                    on_select=self._on_voice_change,
                ),
            ],
            spacing=10,
        )

        mm = self.config.get("memory_max", 100)
        mem_value = {40: "short", 100: "normal", 200: "long"}.get(mm, "normal")
        mem_row = ft.Row(
            controls=[
                _label("Память:"),
                ft.RadioGroup(
                    value=mem_value,
                    on_change=self._on_memory_change,
                    content=ft.Row(
                        controls=[
                            ft.Radio(value="short", label="Короткая", active_color=ACCENT),
                            ft.Radio(value="normal", label="Обычная", active_color=ACCENT),
                            ft.Radio(value="long", label="Долгая", active_color=ACCENT),
                        ],
                        spacing=10,
                    ),
                ),
            ],
            spacing=10,
        )

        return ft.Container(
            content=ft.Column(
                controls=[mode_row, voice_row, mem_row],
                spacing=12,
            ),
            padding=ft.Padding(left=30, right=30, top=10, bottom=15),
        )

    def _build_input(self) -> ft.Container:
        self._input_field = ft.TextField(
            hint_text="Напишите команду...",
            expand=True,
            border_radius=24,
            border_color="#30363d",
            focused_border_color=ACCENT,
            bgcolor=BG_CARD,
            text_size=14,
            content_padding=ft.Padding(left=20, right=20, top=14, bottom=14),
            on_submit=self._on_send,
        )

        self._mic_btn = ft.IconButton(
            icon=ft.Icons.MIC,
            icon_color=TEXT_DIM,
            icon_size=24,
            tooltip="Пауза/возобновить микрофон",
            on_click=self._on_mic_toggle,
        )

        return ft.Container(
            content=ft.Row(
                controls=[
                    self._input_field,
                    ft.IconButton(
                        icon=ft.Icons.SEND,
                        icon_color=ACCENT,
                        icon_size=24,
                        tooltip="Отправить",
                        on_click=self._on_send,
                    ),
                    self._mic_btn,
                ],
                spacing=10,
            ),
            padding=ft.Padding(left=30, right=30, top=10, bottom=25),
        )

    def _build_mic_tab(self) -> ft.Control:
        name = "—"
        if self.jarvis and self.jarvis.listener:
            name = self.jarvis.listener.device_name

        devices = ["по умолчанию"]
        try:
            import sounddevice as sd
            for d in sd.query_devices():
                if d["max_input_channels"] > 0:
                    n = d["name"][:50]
                    if n not in devices:
                        devices.append(n)
        except Exception:
            log.exception("Не удалось получить список устройств")

        current = self.config.get("input_device") or "по умолчанию"
        if current not in devices:
            devices.append(current)

        self._mic_dropdown = ft.Dropdown(
            value=current,
            options=[ft.dropdown.Option(d) for d in devices],
            width=400,
            border_color="#30363d",
            focused_border_color=ACCENT,
            on_select=self._on_mic_change,
        )

        self._mic_level_bar = ft.ProgressBar(
            value=0.0,
            width=400,
            color=ACCENT,
            bgcolor="#21262d",
        )
        self._mic_level_text = ft.Text("Уровень сигнала: —", size=13, color=TEXT_DIM)
        self._mic_status_text = ft.Text("Статус: ожидание проверки", size=13, color=TEXT_DIM)
        self._mic_peak_text = ft.Text("Пик за сессию: 0", size=13, color=TEXT_DIM)
        self._mic_utt_text = ft.Text("Распознано фраз: 0", size=13, color=TEXT_DIM)
        self._mic_test_result = ft.Text("", size=13, color=TEXT_DIM)

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("Микрофон", size=26, weight=ft.FontWeight.BOLD, color=TEXT),
                    ft.Container(height=25),
                    ft.Text(f"Текущее устройство: {name}", size=14, color=TEXT),
                    ft.Container(height=20),
                    ft.Container(
                        content=ft.Column(
                            controls=[
                                self._mic_level_text,
                                self._mic_level_bar,
                                ft.Container(height=8),
                                self._mic_peak_text,
                                self._mic_utt_text,
                                self._mic_status_text,
                                self._mic_test_result,
                            ],
                            spacing=6,
                        ),
                        padding=16,
                        bgcolor=BG_CARD,
                        border_radius=12,
                    ),
                    ft.Container(height=15),
                    ft.Button(
                        content=ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.MIC, color=BG_DARK),
                                ft.Text("Проверить микрофон (3 сек)", color=BG_DARK),
                            ],
                            spacing=8,
                            alignment=ft.MainAxisAlignment.CENTER,
                        ),
                        on_click=self._on_mic_test,
                        style=ft.ButtonStyle(
                            bgcolor=ACCENT,
                            shape=ft.RoundedRectangleBorder(radius=10),
                            padding=ft.Padding(left=20, right=20, top=12, bottom=12),
                        ),
                    ),
                    ft.Container(height=20),
                    ft.Text("Выбрать устройство:", size=13, color=TEXT_DIM),
                    self._mic_dropdown,
                    ft.Container(height=15),
                    ft.Container(
                        content=ft.Text(
                            "После смены устройства перезапусти Феникса",
                            size=12,
                            color="#d29922",
                        ),
                        padding=12,
                        bgcolor="#2d2210",
                        border_radius=8,
                    ),
                ],
                spacing=5,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=ft.Padding(left=40, top=40, right=40, bottom=40),
            expand=True,
        )

    def _on_mic_change(self, e) -> None:
        value = e.control.value
        if value == "по умолчанию":
            value = None
        self.config.set("input_device", value)
        log.info("Микрофон сохранён: %r (перезапусти Феникса)", value)

    def _on_mic_test(self, e) -> None:
        if self.jarvis is None or self.jarvis.listener is None:
            self._mic_test_result.value = "Listener не запущен"
            self._mic_test_result.color = "#f85149"
            try:
                self._page.update()
            except Exception:
                pass
            return

        def _run():
            listener = self.jarvis.listener
            listener.reset_stats()
            self._mic_test_result.value = "Слушаю 3 секунды... говори!"
            self._mic_test_result.color = ACCENT
            try:
                self._page.update()
            except Exception:
                pass

            time.sleep(3.0)
            peak = listener.peak
            if peak >= 500:
                self._mic_test_result.value = f"Микрофон работает (пик {peak})"
                self._mic_test_result.color = "#3fb950"
            elif peak >= 100:
                self._mic_test_result.value = f"Микрофон очень тихий (пик {peak})."
                self._mic_test_result.color = "#d29922"
            else:
                self._mic_test_result.value = f"Микрофон молчит (пик {peak})."
                self._mic_test_result.color = "#f85149"

            try:
                self._page.update()
            except Exception:
                pass

        threading.Thread(target=_run, daemon=True, name="mic-test").start()

    def _update_mic_level(self) -> None:
        if self.jarvis is None or self.jarvis.listener is None:
            return
        listener = self.jarvis.listener
        rms = listener.current_rms
        level = min(1.0, rms / 2000.0)

        try:
            if self._mic_level_bar is not None:
                self._mic_level_bar.value = level
            if self._mic_level_text is not None:
                pct = int(level * 100)
                self._mic_level_text.value = f"Уровень сигнала: {pct}%"
            if self._mic_peak_text is not None:
                self._mic_peak_text.value = f"Пик за сессию: {listener.peak}"
            if self._mic_utt_text is not None:
                self._mic_utt_text.value = f"Распознано фраз: {listener.utterances}"
            if self._mic_status_text is not None:
                if listener.peak >= 500:
                    self._mic_status_text.value = "Статус: Работает"
                    self._mic_status_text.color = "#3fb950"
                elif listener.peak >= 100:
                    self._mic_status_text.value = "Статус: Тихий сигнал"
                    self._mic_status_text.color = "#d29922"
                else:
                    self._mic_status_text.value = "Статус: Ожидание звука"
                    self._mic_status_text.color = TEXT_DIM
        except Exception:
            log.exception("_update_mic_level упал")

    def _build_settings_tab(self) -> ft.Control:
        llm_dropdown = ft.Dropdown(
            value=self.config.get("llm_model", "qwen2.5:7b-instruct"),
            options=[ft.dropdown.Option(m) for m in LLM_MODELS],
            width=350,
            border_color="#30363d",
            focused_border_color=ACCENT,
            on_select=self._on_llm_change,
        )

        ollama_field = ft.TextField(
            value=self.config.get("ollama_url", "http://127.0.0.1:11434"),
            width=400,
            border_color="#30363d",
            focused_border_color=ACCENT,
            on_submit=self._on_ollama_change,
        )

        tts_dropdown = ft.Dropdown(
            value=self.config.get("tts_backend", "auto"),
            options=[ft.dropdown.Option(b) for b in TTS_BACKENDS],
            width=250,
            border_color="#30363d",
            focused_border_color=ACCENT,
            on_select=self._on_tts_change,
        )

        rate_slider = ft.Slider(
            min=0.5,
            max=2.0,
            divisions=30,
            value=float(self.config.get("voice_rate", 1.15)),
            label="{value}",
            active_color=ACCENT,
            on_change_end=self._on_rate_change,
        )

        theme_dropdown = ft.Dropdown(
            value=self.config.get("gui_theme", "Системная"),
            options=[ft.dropdown.Option(t) for t in THEMES.keys()],
            width=250,
            border_color="#30363d",
            focused_border_color=ACCENT,
            on_select=self._on_theme_change,
        )

        def _section(title):
            return ft.Text(title, size=16, weight=ft.FontWeight.BOLD, color=ACCENT)

        def _label(text):
            return ft.Text(text, size=13, color=TEXT_DIM)

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("Настройки", size=26, weight=ft.FontWeight.BOLD, color=TEXT),
                    ft.Container(height=20),
                    _section("LLM"),
                    _label("Модель:"),
                    llm_dropdown,
                    ft.Container(height=8),
                    _label("Ollama URL:"),
                    ollama_field,
                    ft.Container(height=25),
                    _section("TTS"),
                    _label("Бэкенд:"),
                    tts_dropdown,
                    ft.Container(height=8),
                    _label("Качество голоса:"),
                    self._build_voice_quality_row(),
                    ft.Container(height=8),
                    _label("Скорость речи:"),
                    rate_slider,
                    ft.Container(height=25),
                    _section("Внешний вид"),
                    _label("Тема:"),
                    theme_dropdown,
                ],
                spacing=6,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=ft.Padding(left=40, top=40, right=40, bottom=40),
            expand=True,
        )

    def _build_voice_quality_row(self) -> ft.Control:
        current = self.config.get("tts_voice_quality", "medium")
        recommended = "medium"
        try:
            import json
            caps_path = Path(__file__).resolve().parent.parent / "system_caps.json"
            if caps_path.exists():
                caps = json.loads(caps_path.read_text(encoding="utf-8"))
                recommended = caps.get("cpu", {}).get("recommended_piper", "medium")
        except Exception:
            log.exception("Не удалось прочитать рекомендацию Piper")

        radio = ft.RadioGroup(
            value=current,
            on_change=self._on_voice_quality_change,
            content=ft.Row(
                controls=[
                    ft.Radio(value="medium", label="medium (быстрее)", active_color=ACCENT),
                    ft.Radio(value="high", label="high (лучше)", active_color=ACCENT),
                ],
                spacing=15,
            ),
        )

        hint = ft.Text(
            f"Рекомендация по CPU: {recommended}. "
            f"Для русских голосов high пока недоступен — используется medium.",
            size=11,
            color=TEXT_DIM,
        )

        return ft.Column(controls=[radio, hint], spacing=4)

    # ---------------------------------------------------------------
    # Очередь
    # ---------------------------------------------------------------

    async def _process_queue(self) -> None:
        while self._running:
            try:
                try:
                    kind, value = self._queue.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.05)
                    continue

                if kind == "stop":
                    break
                elif kind == "state":
                    self._apply_state(value)
                elif kind == "message":
                    self._apply_message(*value)
                elif kind == "stream_chunk":
                    self._apply_stream_chunk(value)
                elif kind == "stream_end":
                    self._apply_stream_end()
                elif kind == "open_mic_tab":
                    self._open_mic_tab()
                elif kind == "open_settings_tab":
                    self._open_settings_tab()
                elif kind == "show_window":
                    self._show_window_now()
                elif kind == "mic_level":
                    self._update_mic_level()
                elif kind == "rebuild_theme":
                    self._rebuild_ui_for_theme()
                elif kind == "rebuild_ui":
                    self._rebuild_ui_for_theme()

                try:
                    self._page.update()
                except Exception:
                    pass
            except Exception:
                log.exception("Ошибка в _process_queue")

    async def _mic_level_loop(self) -> None:
        last_system_theme = _detect_system_theme()
        counter = 0

        while self._running:
            try:
                if self._rail and self._rail.selected_index == 1:
                    self._queue.put(("mic_level", None))

                counter += 1
                if counter >= 10:
                    counter = 0
                    if self.config.get("gui_theme") == "Системная":
                        current = _detect_system_theme()
                        if current != last_system_theme:
                            log.info("Системная тема Windows изменилась: %s → %s",
                                     last_system_theme, current)
                            last_system_theme = current
                            _apply_palette(current)
                            self._queue.put(("rebuild_theme", current))

                await asyncio.sleep(0.2)
            except Exception:
                log.exception("_mic_level_loop упал")
                await asyncio.sleep(1.0)

    def _apply_state(self, state: str) -> None:
        if state not in STATES:
            return
        self._state = state
        color, text, sub = STATES[state]

        size = {"idle": 80, "listening": 90, "speaking": 95, "error": 85}.get(state, 80)

        try:
            if self._status_circle:
                self._status_circle.bgcolor = color
                self._status_circle.width = size
                self._status_circle.height = size
                self._status_circle.border_radius = size // 2
                self._status_circle.shadow = ft.BoxShadow(
                    blur_radius=32, color=color, spread_radius=3,
                )
            if self._status_text:
                self._status_text.value = text
            if self._status_sub:
                self._status_sub.value = sub
        except Exception:
            log.exception("Ошибка в _apply_state")

    def _avatar(self, is_user: bool) -> ft.Container:
        if is_user:
            bg = BG_BUBBLE_USER
            icon = ft.Icons.PERSON
            icon_color = "#ffffff"
        else:
            bg = BG_CARD
            icon = ft.Icons.SMART_TOY
            icon_color = ACCENT

        return ft.Container(
            content=ft.Icon(icon, size=20, color=icon_color),
            width=40,
            height=40,
            border_radius=20,
            bgcolor=bg,
            alignment=ft.Alignment.CENTER,
        )

    def _apply_message(self, role: str, text: str) -> None:
        try:
            ts = datetime.now().strftime("%H:%M")
            is_user = (role == "user")
            avatar = self._avatar(is_user)

            text_col = ft.Column(
                controls=[
                    ft.Text(
                        f"{'Вы' if is_user else 'Феникс'} • {ts}",
                        size=11, color=TEXT_DIM,
                    ),
                    ft.Text(text, size=14,
                            color="#ffffff" if is_user else TEXT,
                            selectable=True),
                ],
                spacing=2, expand=True,
            )

            bubble = ft.Container(
                content=ft.Row(
                    controls=[avatar, text_col] if not is_user else [text_col, avatar],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                bgcolor=BG_BUBBLE_USER if is_user else BG_BUBBLE_AI,
                padding=ft.Padding(left=14, right=14, top=10, bottom=10),
                border_radius=14,
                shadow=ft.BoxShadow(
                    blur_radius=10, color="#000000",
                    offset=ft.Offset(0, 2),
                ),
                animate_opacity=ft.Animation(300, ft.AnimationCurve.EASE_IN),
                opacity=1.0,
            )

            wrapper = ft.Container(
                content=bubble,
                alignment=ft.Alignment.CENTER_RIGHT if is_user else ft.Alignment.CENTER_LEFT,
                margin=ft.Margin(
                    left=80 if is_user else 0,
                    right=0 if is_user else 80,
                    top=0, bottom=0,
                ),
            )

            self._history_list.controls.append(wrapper)
        except Exception:
            log.exception("Ошибка в _apply_message")

    def _apply_stream_chunk(self, chunk: str) -> None:
        try:
            if self._stream_bubble is None:
                ts = datetime.now().strftime("%H:%M")
                self._stream_text = ""
                self._stream_label = ft.Text("", size=14, color=TEXT, selectable=True)

                avatar = self._avatar(is_user=False)

                text_col = ft.Column(
                    controls=[
                        ft.Text(f"Феникс • {ts}", size=11, color=TEXT_DIM),
                        self._stream_label,
                    ],
                    spacing=2, expand=True,
                )

                bubble = ft.Container(
                    content=ft.Row(
                        controls=[avatar, text_col],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                    bgcolor=BG_BUBBLE_AI,
                    padding=ft.Padding(left=14, right=14, top=10, bottom=10),
                    border_radius=14,
                    shadow=ft.BoxShadow(
                        blur_radius=10, color="#000000",
                        offset=ft.Offset(0, 2),
                    ),
                )

                wrapper = ft.Container(
                    content=bubble,
                    alignment=ft.Alignment.CENTER_LEFT,
                    margin=ft.Margin(left=0, right=80, top=0, bottom=0),
                )

                self._stream_bubble = wrapper
                self._history_list.controls.append(wrapper)

            self._stream_text += chunk
            self._stream_label.value = self._stream_text
        except Exception:
            log.exception("Ошибка в _apply_stream_chunk")

    def _apply_stream_end(self) -> None:
        self._stream_bubble = None
        self._stream_label = None
        self._stream_text = ""

    def _open_mic_tab(self) -> None:
        try:
            self._rail.selected_index = 1
            self._content_area.content = self._tabs[1]
            log.info("GUI: открыл вкладку «Микрофон»")
        except Exception:
            log.exception("Не удалось открыть вкладку «Микрофон»")

    def _open_settings_tab(self) -> None:
        try:
            self._rail.selected_index = 2
            self._content_area.content = self._tabs[2]
            log.info("GUI: открыл вкладку «Настройки»")
        except Exception:
            log.exception("Не удалось открыть вкладку «Настройки»")

    def _show_window_now(self) -> None:
        """Показывает окно — для launch_mode=tray."""
        try:
            if self._page is not None:
                self._page.window.visible = True
                self._page.window.minimized = False
                self._page.update()
                log.info("GUI: окно показано")
        except Exception:
            log.exception("Не удалось показать окно")

    # ---------------------------------------------------------------
    # Действия
    # ---------------------------------------------------------------

    def _on_nav_change(self, e) -> None:
        idx = e.control.selected_index
        log.info("Навигация: %d", idx)
        if idx in self._tabs:
            self._content_area.content = self._tabs[idx]
        try:
            self._page.update()
        except Exception:
            pass

    def _on_mode_change(self, e) -> None:
        mode = e.control.value
        self.config.set("mode", mode)
        if self.jarvis is not None:
            self.jarvis.handler.mode = mode

    def _on_voice_change(self, e) -> None:
        self.config.set("tts_voice", e.control.value)

    def _on_memory_change(self, e) -> None:
        mem = e.control.value
        preset = {"short": (40, 10), "normal": (100, 20), "long": (200, 40)}.get(mem, (100, 20))
        self.config.update({
            "memory_max": preset[0],
            "llm_context_messages": preset[1],
        })

    def _on_llm_change(self, e) -> None:
        self.config.set("llm_model", e.control.value)

    def _on_ollama_change(self, e) -> None:
        self.config.set("ollama_url", e.control.value)

    def _on_tts_change(self, e) -> None:
        self.config.set("tts_backend", e.control.value)

    def _on_voice_quality_change(self, e) -> None:
        quality = e.control.value
        if quality not in ("medium", "high"):
            quality = "medium"

        self.config.set("tts_voice_quality", quality)

        if self.jarvis is not None and self.jarvis.speaker is not None:
            voice = self.config.get("tts_voice", "ruslan")
            try:
                self.jarvis.speaker._init_piper(voice)
                actual = getattr(self.jarvis.speaker, "_piper_quality", quality)
                if actual != quality:
                    log.warning("Piper: %s/%s не найден, использован %s/%s",
                                voice, quality, voice, actual)
                log.info("Piper переключён на %s/%s", voice, actual)
            except Exception:
                log.exception("Не удалось переключить качество голоса")

    def _on_rate_change(self, e) -> None:
        self.config.set("voice_rate", round(float(e.control.value), 2))

    def _on_theme_change(self, e) -> None:
        theme_name = e.control.value
        if theme_name not in THEMES:
            theme_name = "Системная"
        mode = THEMES[theme_name]
        self.config.set("gui_theme", theme_name)

        if mode == ft.ThemeMode.SYSTEM:
            palette_name = _detect_system_theme()
            log.info("Системная тема: %s", palette_name)
            _apply_palette(palette_name)
        elif mode == ft.ThemeMode.LIGHT:
            _apply_palette("light")
        else:
            _apply_palette("dark")

        try:
            self._page.theme_mode = mode
            self._page.bgcolor = BG_DARK
            self._rebuild_ui_for_theme()
            self._page.update()
        except Exception:
            log.exception("Ошибка в _on_theme_change")

    def _rebuild_ui_for_theme(self) -> None:
        """Пересобирает UI с новой палитрой.

        Вызывается при смене темы И при смене профиля (№92).

        №92-fix: сохраняем историю чата перед пересборкой, чтобы
        не терять сообщения при смене темы/профиля.
        """
        current_index = self._rail.selected_index if self._rail else 0

        # Сохранить историю чата перед пересборкой
        saved_history = []
        if self._history_list is not None:
            saved_history = list(self._history_list.controls)

        self._tabs = {
            0: self._build_main_tab(),
            1: self._build_mic_tab(),
            2: self._build_settings_tab(),
        }

        # Восстановить историю в новый _history_list
        if saved_history and self._history_list is not None:
            self._history_list.controls = saved_history

        if self._content_area is not None:
            self._content_area.bgcolor = BG_DARK
            self._content_area.content = self._tabs.get(current_index, self._tabs[0])

        if self._rail is not None:
            self._rail.bgcolor = BG_CARD
            self._rail.indicator_color = ACCENT

        log.info("UI пересобран (тема/профиль), история сохранена: %d",
                 len(saved_history))

    def _on_send(self, e) -> None:
        text = self._input_field.value.strip()
        if not text:
            return
        self._input_field.value = ""
        self._run_command(text)

    def _on_mic_toggle(self, e) -> None:
        if self.jarvis is None:
            return
        self.jarvis.listening_enabled = not self.jarvis.listening_enabled
        self._mic_btn.icon = ft.Icons.MIC if self.jarvis.listening_enabled else ft.Icons.MIC_OFF
        self._mic_btn.icon_color = ACCENT if self.jarvis.listening_enabled else "#f85149"
        try:
            self._page.update()
        except Exception:
            pass

    def _run_command(self, cmd: str) -> None:
        if self.jarvis is None:
            return

        def _run():
            try:
                self.set_state("listening")
                self.add_message("user", cmd)
                self.jarvis.speaker.stop()
                self.jarvis.speaker.wait_end(timeout=1.0)
                reply = self.jarvis.handler.handle(cmd)
                if not reply.is_stream:
                    self.add_message("assistant", reply.text or "")
                self.jarvis.say(reply)
            except Exception:
                log.exception("Ошибка команды %r", cmd)
                self.set_state("error")

        threading.Thread(target=_run, daemon=True, name="gui-cmd").start()
```

### `jarvis\history.py`

```python
"""История последних действий для отмены («стоп, не то»).

Стек на 5 действий. Каждое — dict с полем `action` и данными для отката.

Пример:
    history.push({
        "action": "open_app",
        "target": "дискорд",
        "prev_value": None,
    })

При откате:
    item = history.pop()
    if item["action"] == "open_app":
        actions.kill_process(...)
"""

import logging
import threading
from collections import deque

log = logging.getLogger("jarvis.history")

_MAX = 5
_stack: deque = deque(maxlen=_MAX)
_lock = threading.Lock()


def push(item: dict) -> None:
    """Кладёт действие в стек. Отбрасывает лишнее."""
    if not isinstance(item, dict) or "action" not in item:
        return
    with _lock:
        _stack.append(item)
    log.info("История: +%s (всего %d)", item.get("action"), len(_stack))
    
def push_macro(steps: list) -> None:
    """Кладёт макрос как ОДНУ запись в историю.

    steps — список dict с action/target (то же, что _execute_steps принимает).
    """
    if not isinstance(steps, list) or not steps:
        return
    # Отбрасываем steps с action="wait" — их откатывать нечего
    real_steps = [s for s in steps
                  if isinstance(s, dict) and s.get("action") not in ("wait",)]
    if not real_steps:
        return
    push({"action": "macro", "steps": real_steps})


def pop() -> dict | None:
    """Достаёт последнее действие. Возвращает None, если пусто."""
    with _lock:
        if not _stack:
            return None
        return _stack.pop()


def peek() -> dict | None:
    """Смотрит последнее действие без удаления."""
    with _lock:
        if not _stack:
            return None
        return _stack[-1]


def clear() -> None:
    with _lock:
        _stack.clear()


def size() -> int:
    with _lock:
        return len(_stack)
```

### `jarvis\installed.py`

```python
"""Индекс установленных программ по ярлыкам меню «Пуск».

Позволяет открывать голосом программы, которые не заложены в каталоге apps.py:
«открой обс» -> OBS Studio.lnk.
"""

import logging
import os
from pathlib import Path

from jarvis.matching import match_score

log = logging.getLogger("jarvis.installed")

# Служебные ярлыки, которые не надо предлагать к запуску
_EXCLUDE = ("uninstall", "удал", "help", "справк", "readme", "manual",
            "website", "веб-сайт", "документ", "update", "repair", "license")


def scan_start_menu() -> dict[str, Path]:
    """Имя программы (нижний регистр) -> путь к .lnk."""
    roots = [
        Path(os.path.expandvars(r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs")),
        Path(os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs")),
    ]
    index: dict[str, Path] = {}
    for root in roots:
        if not root.exists():
            continue
        for lnk in root.rglob("*.lnk"):
            name = lnk.stem.strip().lower()
            if not name or any(x in name for x in _EXCLUDE):
                continue
            index.setdefault(name, lnk)
    log.info("Меню «Пуск»: проиндексировано %d программ", len(index))
    return index


def find_installed(index: dict[str, Path], spoken: str,
                   threshold: float = 0.75) -> tuple[str, Path] | None:
    best_name, best_path, best_score = None, None, 0.0
    for name, path in index.items():
        score = match_score(spoken, name)
        if score > best_score:
            best_name, best_path, best_score = name, path, score
    if best_score >= threshold:
        log.info("Установленная программа: %r -> %r (score %.2f)", spoken, best_name, best_score)
        return best_name, best_path
    log.info("В меню «Пуск» не найдено: %r (лучший score %.2f, %r)",
             spoken, best_score, best_name)
    return None
```

### `jarvis\intents.py`

```python
"""Разбор команды: быстрые правила + LLM."""

import datetime
import hashlib
import logging
import random
import re
import time
from collections import deque
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterator

from jarvis import APP_NAME, __version__, actions, files
from jarvis.apps import find_app
from jarvis.installed import find_installed, scan_start_menu
from jarvis.steam import find_game, scan_steam_games
from jarvis import modes
from jarvis import packs
from jarvis import memory
from jarvis import voices
from jarvis import timers
from jarvis import tasks
from jarvis import weather
from jarvis import profile
from jarvis import history
from jarvis import learning
from jarvis.reply import Reply


log = logging.getLogger("jarvis.intents")
actions_log = logging.getLogger("jarvis.actions")


# =================================================================
# Хеширование пароля (№81)
# =================================================================

_PASSWORD_PREFIX = "sha256:"


def _hash_password(password: str) -> str:
    """SHA-256 с префиксом. Префикс нужен, чтобы отличать
    уже захешированный пароль от старого (plaintext)."""
    digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return f"{_PASSWORD_PREFIX}{digest}"


def _is_hashed(value: str) -> bool:
    return bool(value) and value.startswith(_PASSWORD_PREFIX)


def _verify_password(candidate: str, stored: str) -> bool:
    """Сравнивает введённый пароль с сохранённым.

    Если stored ещё старый (plaintext) — сравнивает напрямую
    и возвращает True. Миграция произойдёт при следующем set.
    """
    if not stored:
        return False
    if _is_hashed(stored):
        return _hash_password(candidate) == stored
    # legacy plaintext — сравнение напрямую
    return candidate == stored


# =================================================================
# Нормализация
# =================================================================

def normalize(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


CANCEL = {"отмена", "стоп", "стой", "хватит", "замолчи", "ничего", "забудь", "отбой"}

BROWSER_WORDS = {"браузер", "браузере", "браузером", "хром", "хроме", "интернет", "интернете"}

SEARCH_VERBS = ("найди", "поищи", "ищи", "загугли", "погугли", "поиск")


# =================================================================
# SITES — fallback на хардкод, если packs/sites.json недоступен (№96)
# =================================================================

_SITES_FALLBACK = {
    "ютуб": ("Ютуб", "https://www.youtube.com"),
    "гугл": ("Гугл", "https://www.google.com"),
    "яндекс": ("Яндекс", "https://ya.ru"),
    "гитхаб": ("Гитхаб", "https://github.com"),
    "вк": ("ВКонтакте", "https://vk.com"),
    "вконтакте": ("ВКонтакте", "https://vk.com"),
    "твич": ("Твич", "https://www.twitch.tv"),
    "кинопоиск": ("Кинопоиск", "https://www.kinopoisk.ru"),
    "википедия": ("Википедию", "https://ru.wikipedia.org"),
    "почта": ("Почту", "https://mail.google.com"),
}


def _load_sites() -> dict:
    """Загружает sites.json из packs/. Fallback — хардкод.

    Формат packs/sites.json — список:
        [{"phrases": ["открой ютуб"], "action": "https://...", "reply": "..."}]
    Превращаем в {ключ: (title, url)}.
    """
    sites = dict(_SITES_FALLBACK)
    try:
        from jarvis.packs import PACKS_DIR
        import json
        path = PACKS_DIR / "sites.json"
        if not path.exists():
            return sites
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return sites
        for entry in data:
            action = entry.get("action", "")
            if not action.startswith(("http://", "https://")):
                continue
            for phrase in entry.get("phrases", []):
                # «открой ютуб» → ключ «ютуб»
                key = phrase.lower().replace("открой", "").strip()
                if key and key not in sites:
                    title = entry.get("reply", key).replace("Открываю ", "").rstrip(".")
                    sites[key] = (title, action)
        log.info("SITES загружены из packs/sites.json: %d записей", len(sites))
    except Exception:
        log.exception("Не удалось загрузить packs/sites.json — fallback на хардкод")
    return sites


SITES = _load_sites()


MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня",
          "июля", "августа", "сентября", "октября", "ноября", "декабря"]

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]

_FOLDER_TITLES = {
    "Desktop": "на рабочем столе", "Downloads": "в загрузках",
    "Documents": "в документах", "Pictures": "в изображениях",
    "Music": "в музыке", "Videos": "в видео",
    "Screenshots": "в скриншотах",
}

_WEATHER_BAD_TARGET = (
    "курс", "доллар", "рубл", "евро", "юан", "валют",
    "цену", "цена", "поиск", "найди", "погод", "прогноз",
    "пожалуйста", "сколько", "стоит",
)

_NOT_A_CITY = (
    "открой", "закрой", "найди", "включи", "выключи",
    "как дела", "кто ты", "спасибо", "привет", "пока",
    "который час", "какое число", "сделай скриншот",
    "загугли", "поищи", "напечатай",
)

# Действия, требующие пароля (если danger_password задан)
_DANGER_ACTIONS = {
    "shutdown_pc", "reboot_pc", "kill_process",
    "clear_tasks", "cancel_timers", "delete_profile",
}


class IntentHandler:

    # Глаголы, с которых может начинаться часть составной команды (№67)
    _COMPOUND_VERBS = (
        "открой", "открывай", "закрой", "закрывай",
        "запусти", "врубай", "включи", "выключи",
        "найди", "поищи", "загугли", "погугли",
        "поставь", "сделай",
        "добавь", "запиши", "внеси",
        "покажи", "убери", "удали", "очисти",
        "смени", "поменяй", "переключи",
        "сверни", "разверни", "переключись",
        "напомни", "запомни",
        "громче", "тише", "потише", "погромче",
    )

    def __init__(self, config, apps, brain=None, listener=None):
        self.config = config
        self.apps = apps
        self.brain = brain
        self.listener = listener
        self.installed = scan_start_menu()
        self.steam_games = scan_steam_games()
        self.music_app = config.get("music_app", "яндекс музыка")
        self.music_wait = float(config.get("music_wait_sec", 6))
        self.last_file = None
        self.last_folder = None

        # Лимиты памяти — из config (не хардкод).
        self._memory_max = int(config.get("memory_max", 100))
        self._llm_context = int(config.get("llm_context_messages", 20))
        self.dialog = deque(maxlen=self._memory_max)
        for msg in memory.load(limit=self._memory_max):
            self.dialog.append(msg)

        self.last_was_chat = False
        self.mode = modes.get_mode(config)
        self.active_packs = list(config.get("active_packs", []))
        self.last_macro = None
        self._reset_requested = False
        self._last_reply = ""
        self._pending_question = None

        # Диагностика (Н2, Н3)
        self._last_debug: dict = {}
        self._recent_phrases: deque = deque(maxlen=10)

        # Последняя команда (для коррекции «это не то»)
        self._last_cmd: str = ""

        # Пароль (2.13)
        self._pending_password: dict | None = None

        # Миграция plaintext → sha256 при старте (№81)
        self._migrate_password_if_needed()

        self._config_custom_original = []
        for entry in config.get("custom_commands", []):
            phrases = [normalize(p) for p in entry.get("phrases", []) if p.strip()]
            action = entry.get("action", "").strip() or entry.get("steps")
            if phrases and action:
                self._config_custom_original.append(
                    (phrases, action, entry.get("reply", "Выполняю."))
                )
        self.custom = list(self._config_custom_original) + self._load_packs_as_custom(config)

        # Подписка на изменения memory_max / llm_context_messages
        config.subscribe(self._on_config_change)

        # Подписка на смену профиля — чтобы перечитать dialog
        profile.subscribe(self._on_profile_switch)

    def _migrate_password_if_needed(self) -> None:
        """Если danger_password в plaintext — захешировать (№81)."""
        raw = str(self.config.get("danger_password") or "").strip()
        if not raw or _is_hashed(raw):
            return
        self.config.set("danger_password", _hash_password(raw))
        log.info("Пароль миграции: plaintext → sha256")

    def _on_config_change(self, key: str, value) -> None:
        """Реагирует на смену memory_max / llm_context_messages в рантайме."""
        if key == "memory_max":
            try:
                new_max = int(value)
            except (TypeError, ValueError):
                return
            if new_max <= 0:
                return
            self._memory_max = new_max
            self.dialog = deque(self.dialog, maxlen=new_max)
            log.info("IntentHandler: memory_max = %d", new_max)
        elif key == "llm_context_messages":
            try:
                self._llm_context = int(value)
            except (TypeError, ValueError):
                return
            log.info("IntentHandler: llm_context_messages = %d", self._llm_context)

    def _on_profile_switch(self, old_name: str, new_name: str) -> None:
        """Перечитывает dialog при смене профиля.

        Без этого Феникс продолжает помнить диалог старого профиля
        и подсовывает его в LLM-контекст нового пользователя.
        """
        if old_name == new_name:
            return

        self.dialog.clear()
        for msg in memory.load(limit=self._memory_max):
            self.dialog.append(msg)
        log.info(
            "Профиль сменился: %s → %s, диалог перечитан (%d сообщений)",
            old_name, new_name, len(self.dialog),
        )

    def handle(self, cmd: str) -> Reply:
        """Возвращает Reply: либо text, либо stream."""
        self.last_was_chat = False

        # Нормализация — единая точка входа.
        cmd = normalize(cmd)

        actions_log.info("Команда: %r (режим: %s)", cmd, self.mode)

        # Диагностика: сохраняем последнюю команду
        self._recent_phrases.append(cmd)

        # Запоминаем ДО применения коррекции
        prev_cmd = self._last_cmd
        self._last_cmd = cmd

        result = self._handle_single(cmd)

        user_msg = {"role": "user", "content": cmd}
        self.dialog.append(user_msg)
        memory.append(user_msg)

        if result is None:
            result = "Не понял команду."

        if isinstance(result, str):
            assistant_msg = {"role": "assistant", "content": result}
            self.dialog.append(assistant_msg)
            memory.append(assistant_msg)
            actions_log.info("Ответ: %r", result[:120])
            self._last_reply = result
            return Reply(text=result)

        # result — генератор (chat_stream)
        return Reply(stream=result)

    def finalize_stream(self, cmd: str, full_text: str) -> None:
        if not full_text:
            return
        assistant_msg = {"role": "assistant", "content": full_text}
        self.dialog.append(assistant_msg)
        memory.append(assistant_msg)
        self._last_reply = full_text

    def _chat_stream(self, cmd: str):
        """Отправляет в LLM только последние _llm_context сообщений."""
        ctx = list(self.dialog)[-self._llm_context:] if self._llm_context else []
        return self.brain.chat_stream(cmd, ctx)

    def _danger_password(self) -> str:
        """Возвращает СОХРАНЁННЫЙ (захешированный) пароль. №81."""
        return str(self.config.get("danger_password") or "").strip()

    # =================================================================
    # Разбиение составных команд (№67)
    # =================================================================

    def _split_compound(self, cmd: str) -> list[str] | None:
        """Разбивает «открой стим и запусти доту» на части.

        Возвращает список частей или None, если это не составная команда.
        Разбиваем по « и » (с пробелами) или «, ».

        Ключевое: все части должны начинаться с глагола-команды.
        Иначе «добавь в список купить хлеб и молоко» разобьётся зря.
        """
        parts = re.split(r"\s+и\s+|,\s*", cmd)
        if len(parts) < 2:
            return None

        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) < 2:
            return None

        for part in parts:
            first_word = part.split()[0].lower() if part.split() else ""
            if first_word not in self._COMPOUND_VERBS:
                return None

        return parts

    def _handle_single(self, cmd: str) -> str | Iterator[str]:
        # === CANCEL — самый первый (фикс №6) ===
        if cmd in CANCEL:
            self._pending_password = None
            self._pending_question = None
            self._reset_requested = True
            return "Жду обращение, сэр."

        # Применяем коррекцию, если есть
        corrected = learning.find_correction(cmd)
        if corrected and corrected != cmd:
            log.info("Применена коррекция: %r → %r", cmd, corrected)
            cmd = corrected

        # Пароль (2.13) — если ждём ввода
        if self._pending_password and time.time() < self._pending_password.get("expires_at", 0):
            return self._handle_password_answer(cmd)
        elif self._pending_password:
            self._pending_password = None

        # Удаление профиля — до tasks
        m = re.match(r"^удали\s+профиль\s+(\S+)$", cmd)
        if m:
            name = m.group(1)
            if self._danger_password():
                return self._ask_password({"action": "delete_profile", "target": name})
            if profile.delete(name):
                return f"Профиль {name} удалён."
            return f"Профиль {name} не найден или активен."

        # Память диалога — до всего остального
        mem_reply, clear_requested = memory.handle_memory_command(cmd, list(self.dialog))
        if mem_reply:
            if clear_requested:
                self.dialog.clear()
            return mem_reply

        if self._pending_question and time.time() < self._pending_question.get("expires_at", 0):
            return self._handle_pending_answer(cmd)
        else:
            self._pending_question = None

        # Буфер обмена
        if re.search(r"скопируй\s+(выделенное|выделенный|это\s+выделенное)", cmd) \
                or re.search(r"(выдели|выделенное)\s+(и\s+)?скопируй", cmd) \
                or cmd in {"скопируй выделенное", "скопируй это выделенное"}:
            return self._execute_intent({"action": "copy_selection"})

        if re.search(r"скопируй\s+(свой\s+)?(ответ|ответь|последнее|сказанное)", cmd) \
                or cmd in {"скопируй свой ответ", "скопируй ответ", "скопируй что ты сказал"}:
            return self._execute_intent({"action": "clipboard_copy_last"})

        if re.search(r"(что|чё)\s+(в\s+)?буфере", cmd) \
                or re.search(r"(покажи|прочитай|что)\s+буфер", cmd) \
                or cmd in {"что скопировано", "что в буфере"}:
            return self._execute_intent({"action": "clipboard_read"})

        if re.search(r"(очисти|сотри|удали)\s+буфер", cmd) \
                or cmd in {"очисти буфер", "сотри буфер"}:
            return self._execute_intent({"action": "clipboard_clear"})

        # Режимы
        if any(w in cmd for w in ("режим", "комбо", "комбинирован")):
            prev_mode = self.mode
            reply, new_mode = modes.handle_mode_command(cmd, self.mode, self.config)
            if reply:
                if new_mode != prev_mode:
                    history.push({
                        "action": "set_mode",
                        "prev_value": prev_mode,
                    })
                self.mode = new_mode
                return reply

        reply = self._match_custom(cmd)
        if reply:
            return reply

        reply = self._small_talk(cmd)
        if reply:
            return reply

        if re.search(r"скрин|снимок экрана", cmd):
            return self._take_screenshot(cmd)

        # === Многослойные команды: «открой стим и запусти доту» (№67) ===
        compound = self._split_compound(cmd)
        if compound:
            replies = []
            for part in compound:
                sub = self._handle_single(part)
                if isinstance(sub, str) and sub.strip():
                    replies.append(sub.strip())
                # Если sub — генератор (chat_stream), пропускаем.
            if replies:
                return ". ".join(replies) + "."
            # Если ни одна часть не дала ответа — идём дальше обычным путём.

        # --- Быстрые правила без LLM (реестр) ---
        # Порядок в _fast_handlers() = приоритет.
        # Специфичные — выше общих (open_profile выше open).
        for name, handler in self._fast_handlers():
            try:
                reply = handler(cmd)
            except Exception:
                log.exception("Обработчик %s упал на %r", name, cmd)
                continue
            if reply:
                log.debug("Команда %r обработана: %s", cmd, name)
                return reply

        if self.mode == "commands":
            self._last_debug = {
                "cmd": cmd, "reason": "режим commands",
                "mode": self.mode, "llm": False,
            }
            return "Я не понял команду. Скажите «режим ИИ» или добавьте фразу в конфиг."

        if self.brain is None or not self.brain.available:
            self._last_debug = {
                "cmd": cmd, "reason": "LLM недоступна",
                "mode": self.mode, "llm": False,
            }
            return "LLM недоступна. Скажите «режим команды»."

        # === Мусорный ввод (№70) ===
        # Одна повторяющаяся буква или слишком коротко — LLM
        # на такое галлюцинирует («Всё в порядке»), лучше явно сказать.
        # Исключения: «да», «нет», «ок» — это ответы на pending-вопросы.
        clean = cmd.replace(" ", "")
        if cmd not in {"да", "нет", "ок"}:
            if len(cmd) < 3 or (len(clean) > 0 and len(set(clean)) <= 2):
                self._last_debug = {
                    "cmd": cmd, "reason": "мусорный ввод",
                    "mode": self.mode, "llm": False,
                }
                return "Не расслышал, сэр. Повторите, пожалуйста."

        intent = self.brain.parse(cmd)
        self._last_debug = {
            "cmd": cmd,
            "intent": intent,
            "mode": self.mode,
            "llm": True,
        }
        if intent and intent.get("action") not in ("answer", "none"):
            if self._is_danger(intent):
                return self._ask_password(intent)

            if intent.get("action") == "search" \
                    and not any(v in cmd for v in SEARCH_VERBS):
                return "Сэр, чтобы поискать, скажите «найди» и запрос. Например: «найди погоду»."
            if isinstance(intent.get("steps"), list):
                reply = self._execute_steps(intent["steps"])
            else:
                reply = self._execute_intent(intent)
            if reply:
                return reply

        if intent and intent.get("action") == "answer":
            gen = self._chat_stream(cmd)
            if gen is not None:
                self.last_was_chat = True
                return gen
            if intent.get("reply"):
                return str(intent["reply"])[:600]

        gen = self._chat_stream(cmd)
        if gen is not None:
            self.last_was_chat = True
            return gen
        return "Я не понял команду."

    def _is_danger(self, intent: dict) -> bool:
        """Проверяет, опасно ли действие (2.13)."""
        if not self._danger_password():
            return False
        action = intent.get("action")
        if action in _DANGER_ACTIONS:
            return True
        if action == "open_app":
            target = str(intent.get("target") or "").lower()
            if "shutdown" in target or "выключ" in target or "перезагруз" in target:
                return True
        return False

    def _ask_password(self, intent: dict) -> str:
        """Запрашивает пароль для опасного действия."""
        self._pending_password = {
            "intent": intent,
            "expires_at": time.time() + 30,
        }
        action = intent.get("action")
        human = {
            "shutdown_pc": "выключение компьютера",
            "reboot_pc": "перезагрузку",
            "kill_process": "закрытие процесса",
            "clear_tasks": "очистку списка задач",
            "cancel_timers": "отмену напоминаний",
            "delete_profile": "удаление профиля",
            "open_app": "это действие",
        }.get(action, "это действие")
        return f"Для этого нужен пароль ({human}). Назовите пароль."

    def _handle_password_answer(self, cmd: str) -> str:
        """Проверяет пароль и выполняет отложенное действие."""
        pending = self._pending_password
        self._pending_password = None

        if cmd in CANCEL:
            return "Жду обращение, сэр."

        # Убираем «пароль», «код», лишние слова
        candidate = re.sub(r"^(?:пароль|код|пин)\s*", "", cmd).strip()

        # №81: сравнение через _verify_password (sha256 или legacy plaintext)
        if not _verify_password(candidate, self._danger_password()):
            log.warning("Пароль неверный")
            return "Пароль неверный. Действие отменено."

        intent = pending.get("intent") or {}
        if isinstance(intent.get("steps"), list):
            result = self._execute_steps(intent["steps"])
        else:
            result = self._execute_intent(intent)
        return result or "Готово."

    def _fast_handlers(self):
        """Реестр быстрых обработчиков без LLM.

        Порядок = приоритет. Специфичные — выше общих.

        Каждый обработчик: (cmd: str) -> str | None.
        Если вернул непустую строку — команда обработана.
        Если None — идём к следующему.
        """
        return [
            # Специфичные — ВЫШЕ
            ("custom", self._match_custom),
            ("small_talk", self._small_talk),
            ("music", self._music_fast),
            ("open_profile", self._open_profile_fast),

            # Общие — ниже
            ("open", self._open_fast),
            ("voices", lambda cmd: voices.handle_voice_command(cmd, self.config)),
            ("packs", self._packs_handler),
            ("timers", timers.handle_timer_command),
            ("tasks", tasks.handle_task_command),
            ("profile", self._profile_fast),
            ("memory", self._memory_fast),
            ("system", self._system_fast),
            ("debug", self._debug_fast),
            ("correction", self._correction_fast),
            ("undo", self._undo_fast),
            ("weather_currency", self._weather_currency_fast),
        ]

    def _packs_handler(self, cmd: str) -> str | None:
        """Обёртка для packs с side-effect.

        packs.handle_pack_command возвращает (reply, new_active),
        и меняет self.active_packs. Инкапсулируем это здесь.
        """
        reply, new_active = packs.handle_pack_command(
            cmd, self.active_packs, self.config
        )
        if reply:
            if new_active != self.active_packs:
                self.active_packs = new_active
                self._reload_packs()
            return reply
        return None

    def _music_fast(self, cmd: str) -> str | None:
        """Музыка — ДО _open_fast."""
        if re.search(r"(включи|врубай|играй|поставь)\s+(музыку|музыка|плейлист)", cmd):
            actions.media_key("play")
            return "Включаю музыку."

        if cmd in {"пауза", "плей", "play", "pause"}:
            actions.media_key("play")
            return "Готово."
        if re.search(r"^(включи|врубай)\s+(плей|музыку)$", cmd):
            actions.media_key("play")
            return "Включаю."

        if re.search(r"(следующ|дальше|переключи|переключ)\w*\s*(трек|песн|музык)?", cmd):
            if any(w in cmd for w in ("трек", "песн", "музык", "дальше")):
                actions.media_key("next")
                return "Переключаю."

        if re.search(r"(предыдущ|назад)\w*\s*(трек|песн|музык)", cmd):
            actions.media_key("prev")
            return "Возвращаю."

        if re.search(r"(останови|стоп)\s+(музык|трек|песн)", cmd):
            actions.media_key("play")
            return "Останавливаю."

        return None

    def _open_fast(self, cmd: str) -> str | None:
        """Быстрое открытие приложений/сайтов/папок — без LLM."""
        m = re.match(r"^(?:открой|запусти|врубай|включи|открывай)\s+(.+)$", cmd)
        if not m:
            return None
        target = m.group(1).strip()
        if not target:
            return None
        return self._do_open(target)

    def _profile_fast(self, cmd: str) -> str | None:
        """Команды профиля: смена, список, факты."""
        log.info("_profile_fast: %r", cmd)
        m = re.match(r"^(?:я\s*[-—]?\s*|зови\s+меня\s+|переключись\s+на\s+|я\s+это\s+)([а-яёa-z][а-яёa-z\s\-]{0,40})$", cmd)
        if m:
            name = m.group(1).strip()
            if name and name not in _NOT_A_CITY:
                return profile.switch(name)

        if re.search(r"(кто|какой)\s+(сейчас\s+)?(активен|профиль|пользователь)", cmd) \
                or cmd in {"кто активен", "какой профиль", "текущий профиль"}:
            name = profile.get("name") or profile.current()
            return f"Сейчас профиль {name}."

        if re.search(r"(список|какие|покажи)\s+профил", cmd) \
                or cmd in {"список профилей", "какие профили"}:
            all_p = profile.list_all()
            if not all_p:
                return "Профилей нет."
            return f"Профили: {', '.join(all_p)}."

        # === Общий «запомни: X — Y» → facts ===
        # (УДАЛЁН ДУБЛЬ, который был в строках 558–569)
        m = re.match(r"^(?:запомни|запиши)\s*[,:]?\s*(?:что\s+)?(.+)$", cmd)
        if m:
            fact = m.group(1).strip(" ,.:!?")
            if not fact:
                return "Что запомнить?"
            sep = re.match(r"^(.+?)\s*[—\-=:]\s*(.+)$", fact)
            if sep:
                key, value = sep.group(1).strip(), sep.group(2).strip()
            else:
                key, value = fact, "да"
            ok = learning.add_fact(key, value)
            if ok:
                return f"Запомнил: {key} — {value}."
            return "Не удалось сохранить — проверь профиль (возможно, битый JSON)."

        if re.search(r"(что|чё)\s+ты\s+(обо\s+мне\s+)?знаешь", cmd) \
                or cmd in {"что ты обо мне знаешь", "что ты знаешь"}:
            facts = profile.all_facts()
            name = profile.get("name")
            city = profile.get("default_city")
            parts = []
            if name:
                parts.append(f"Тебя зовут {name}")
            if city:
                parts.append(f"твой город — {city}")
            if facts:
                facts_str = "; ".join(f"{k} — {v}" for k, v in facts.items())
                parts.append(f"Знаю: {facts_str}")
            if not parts:
                return "Пока ничего о тебе не знаю."
            return ". ".join(parts) + "."

        m = re.match(r"^забудь\s+(?:факт\s+)?(.+)$", cmd)
        if m:
            key = m.group(1).strip(" ,.:!?")
            if profile.forget_fact(key):
                return f"Забыл: {key}."
            return f"Факта «{key}» не знаю."

        return None

    def _memory_fast(self, cmd: str) -> str | None:
        """Голосовые команды для управления памятью."""
        if re.search(r"(коротк|быстр)\w*\s+память", cmd):
            self.config.update({
                "memory_max": 40,
                "llm_context_messages": 10,
            })
            return "Память: короткая. 40 сообщений, контекст LLM — 10."

        if re.search(r"(обычн|стандартн|нормальн)\w*\s+память", cmd):
            self.config.update({
                "memory_max": 100,
                "llm_context_messages": 20,
            })
            return "Память: обычная. 100 сообщений, контекст LLM — 20."

        if re.search(r"(долг|глубок)\w*\s+память", cmd):
            self.config.update({
                "memory_max": 200,
                "llm_context_messages": 40,
            })
            return "Память: долгая. 200 сообщений, контекст LLM — 40."

        if re.search(r"(какая|текущ)\w*\s+память", cmd) \
                or cmd in {"какая память", "текущая память"}:
            mm = self.config.get("memory_max", 100)
            lc = self.config.get("llm_context_messages", 20)
            return f"Память: {mm} сообщений, контекст LLM — {lc}."

        return None

    def _system_fast(self, cmd: str) -> str | None:
        """Быстрые системные команды: раскладка, громкость, яркость."""

        # --- раскладка ---
        if re.search(r"раскладк", cmd):
            if re.search(r"(переключ|смени|поменяй|следующ)", cmd):
                ok = actions.switch_layout()
                if ok:
                    history.push({"action": "switch_layout"})
                return "Переключаю раскладку." if ok else "Не удалось переключить."
            if re.search(r"(русск|ru)", cmd):
                ok = actions.set_layout_ru()
                return "Русская раскладка." if ok else "Не удалось."
            if re.search(r"(англ|english|en)", cmd):
                ok = actions.set_layout_en()
                return "Английская раскладка." if ok else "Не удалось."
            if re.search(r"(какая|текущ|что)", cmd):
                layout = actions.get_layout()
                if layout == "ru":
                    return "Сейчас русская раскладка."
                if layout == "en":
                    return "Сейчас английская раскладка."
                return "Не смог определить раскладку."

        # --- громкость: «громкость 50» ---
        m = re.search(r"громкость\s+(?:на\s+)?(\d+)", cmd)
        if m:
            pct = int(m.group(1))
            prev = actions.get_volume()
            ok = actions.set_volume(pct)
            if ok:
                history.push({"action": "set_volume", "prev_value": prev})
            return f"Громкость: {pct}%." if ok else "Не удалось."

        # --- громкость: «сделай на 10 потише» (№69) ---
        m = re.search(
            r"(?:сделай|поставь|сделай\s+пожалуйста)\s+(?:на\s+)?(\d+)\s+(потише|тише|погромче|громче)",
            cmd,
        )
        if m:
            delta = int(m.group(1))
            direction = m.group(2)
            if "тише" in direction:
                delta = -delta
            prev = actions.get_volume()
            if prev is not None:
                new_vol = max(0, min(100, prev + delta))
                ok = actions.set_volume(new_vol)
                if ok:
                    history.push({"action": "set_volume", "prev_value": prev})
                return f"Громкость: {new_vol}%." if ok else "Не удалось."

        # --- громкость: «потише» / «погромче» (без числа, ±10) ---
        if re.search(r"\b(потише|тише)\b", cmd):
            prev = actions.get_volume()
            if prev is not None:
                new_vol = max(0, prev - 10)
                ok = actions.set_volume(new_vol)
                if ok:
                    history.push({"action": "set_volume", "prev_value": prev})
                return f"Громкость: {new_vol}%." if ok else "Не удалось."

        if re.search(r"\b(погромче|громче)\b", cmd):
            prev = actions.get_volume()
            if prev is not None:
                new_vol = min(100, prev + 10)
                ok = actions.set_volume(new_vol)
                if ok:
                    history.push({"action": "set_volume", "prev_value": prev})
                return f"Громкость: {new_vol}%." if ok else "Не удалось."

        if re.search(r"(какая|текущ|узнай)\s+громкость", cmd) \
                or cmd in {"какая громкость", "текущая громкость"}:
            vol = actions.get_volume()
            return f"Громкость: {vol}%." if vol is not None else "Не смог узнать."

        # --- яркость ---
        m = re.search(r"яркость\s+(?:на\s+)?(\d+)", cmd)
        if m:
            pct = int(m.group(1))
            prev = actions.get_brightness()
            ok = actions.set_brightness(pct)
            if ok:
                history.push({"action": "set_brightness", "prev_value": prev})
            return f"Яркость: {pct}%." if ok else "Не удалось."

        if re.search(r"(какая|текущ|узнай)\s+яркость", cmd) \
                or cmd in {"какая яркость", "текущая яркость"}:
            br = actions.get_brightness()
            return f"Яркость: {br}%." if br is not None else "Не смог узнать."

        return None
        
    def _open_profile_fast(self, cmd: str) -> str | None:
        """«открой профиль» → открыть profile.json в Notepad++ / VS Code / системном редакторе.

        Опционально: «открой профиль в вс код», «открой профиль в блокноте».
        """
        if not re.search(r"откр\w*\s+профиль", cmd):
            return None

        # Определяем предпочитаемый редактор
        prefer = "auto"
        if re.search(r"\bв\s+(vs\s*code|вс\s*код|вскод|code)\b", cmd):
            prefer = "vscode"
        elif re.search(r"\bв\s+(notepad\+\+|нотпад\s*плюс|нотепад)\b", cmd):
            prefer = "notepad++"
        elif re.search(r"\bв\s+(блокнот|notepad)\b", cmd):
            prefer = "system"
        elif re.search(r"\bв\s+(системн|обычн)\w*\s+редактор", cmd):
            prefer = "system"

        prof_path = profile.profile_path()
        if not prof_path.exists():
            return f"Профиль не найден: {prof_path.name}"

        ok = actions.open_in_editor(prof_path, prefer=prefer)
        if ok:
            editor_name = {
                "auto": "редакторе",
                "vscode": "VS Code",
                "notepad++": "Notepad++",
                "system": "системном редакторе",
            }.get(prefer, "редакторе")
            return f"Открываю профиль в {editor_name}."
        return "Не удалось открыть профиль."
        
    def _debug_fast(self, cmd: str) -> str | None:
        """Команды диагностики: что слышал, почему не понял."""
        if re.search(r"(что|чё)\s+ты\s+слышал", cmd) \
                or cmd in {"что ты слышал", "что слышал", "история"}:
            phrases = []
            if self.listener is not None and hasattr(self.listener, "recent_phrases"):
                phrases = list(self.listener.recent_phrases)
            if not phrases:
                phrases = list(self._recent_phrases)
            if not phrases:
                return "Пока ничего не слышал."
            lines = [f"{i+1}. {p}" for i, p in enumerate(phrases[-5:])]
            return "Последние фразы: " + "; ".join(lines) + "."

        if re.search(r"почему\s+(ты\s+)?не\s+понял", cmd) \
                or cmd in {"почему не понял", "почему не поняла"}:
            d = self._last_debug
            if not d:
                return "Пока нечего диагностировать."
            parts = [f"Фраза: «{d.get('cmd', '?')}»"]
            parts.append(f"Режим: {d.get('mode', '?')}")
            if d.get("llm"):
                intent = d.get("intent")
                if intent:
                    parts.append(f"LLM вернула: {intent.get('action', '?')}")
                else:
                    parts.append("LLM не разобрала")
            else:
                parts.append(f"LLM: {d.get('reason', 'выкл')}")
            return ". ".join(parts) + "."

        return None

    def _undo_fast(self, cmd: str) -> str | None:
        """Отмена последнего действия (Н1)."""
        if not re.search(r"(не\s+то|отмени|верни\s+как\s+было|откат)", cmd):
            return None

        item = history.pop()
        if not item:
            return "Нечего отменять."

        action = item.get("action")

        if action == "macro":
            steps = item.get("steps") or []
            if not steps:
                return "Нечего отменять."
            results = []
            for step in reversed(steps):
                s_action = step.get("action")
                s_target = step.get("target")
                if s_action == "open_app" and s_target:
                    r = self._do_close(s_target)
                    results.append(r)
            if results:
                return "Откатываю макрос: " + "; ".join(results)
            return "Макрос отменён."

        if action == "open_app":
            target = item.get("target") or ""
            if target:
                result = self._do_close(target)
                return f"Откатываю: {result}"

        if action == "set_mode":
            prev = item.get("prev_value")
            if prev:
                reply = modes.set_mode(prev, self.config)
                self.mode = prev
                return f"Вернул режим: {reply}"

        if action == "change_voice":
            prev = item.get("prev_value")
            if prev:
                reply = voices.switch(prev, self.config)
                return f"Вернул голос: {reply}"

        if action == "set_volume":
            prev = item.get("prev_value")
            if prev is not None:
                actions.set_volume(int(prev))
                return f"Вернул громкость: {prev}%."

        if action == "set_brightness":
            prev = item.get("prev_value")
            if prev is not None:
                actions.set_brightness(int(prev))
                return f"Вернул яркость: {prev}%."

        if action == "switch_layout":
            actions.switch_layout()
            return "Переключил раскладку обратно."

        return f"Действие «{action}» отменить нельзя."

    def _correction_fast(self, cmd: str) -> str | None:
        """Коррекция: «это не то, я сказал логи»."""
        m = re.match(
            r"^(?:это\s+)?не\s+то\s*,?\s*(?:я\s+сказал[а]?\s+)?(.+)$",
            cmd,
        )
        if m:
            right = m.group(1).strip(" ,.:!?")
            if not right:
                return None
            wrong = self._last_cmd
            if wrong and wrong != cmd:
                learning.add_correction(wrong, right)
                return f"Понял, запомнил. Повторяю: {right}."
            return "Что было не так?"

        return None

    def _weather_currency_fast(self, cmd: str) -> str | None:
        """Простые правила для погоды и курса — без LLM."""
        if re.search(r"\bкурс\b|\bвалют", cmd):
            code_map = {
                "доллар": "USD", "доллара": "USD", "бакс": "USD", "бакса": "USD",
                "евро": "EUR",
                "юан": "CNY", "юаня": "CNY",
                "фунт": "GBP", "фунта": "GBP",
                "йен": "JPY", "йены": "JPY",
                "лир": "TRY", "лиры": "TRY",
                "тенге": "KZT",
                "белорусск": "BYN", "бел рубл": "BYN",
                "гривн": "UAH",
            }
            code = ""
            for word, iso in code_map.items():
                if word in cmd:
                    code = iso
                    break
            r = weather.get_currency_rates()
            return weather.describe_currency(r, code=code)

        if re.search(r"\bпогод|\bпрогноз", cmd):
            day = "tomorrow" if "завтра" in cmd else "today"

            m = re.search(r"\bв\s+([а-яёa-z\-]+(?:\s+[а-яёa-z\-]+)?)", cmd)
            city = m.group(1).strip() if m else ""

            if not city:
                city = profile.get("default_city")
            if not city:
                self._pending_question = {
                    "type": "city_for_weather",
                    "day": day,
                    "expires_at": time.time() + 30,
                }
                return "В каком городе узнать погоду?"

            w = weather.get_weather(city, day=day)
            if not w:
                return None
            return weather.describe_weather(w)

        return None

    def _handle_pending_answer(self, cmd: str) -> str:
        pending = self._pending_question
        self._pending_question = None

        if pending.get("type") == "city_for_weather":
            city = cmd.strip()
            words = city.split()

            if not city or len(city) > 60 or len(words) > 3:
                return "Не расслышал город. Повторите, пожалуйста."

            if any(w in city for w in _NOT_A_CITY):
                log.info("pending_question: %r не похоже на город — обрабатываю как команду", city)
                result = self._handle_single(cmd)
                return result if isinstance(result, str) else "Не понял команду."

            profile.set("default_city", city)
            log.info("Запомнил город по умолчанию: %s", city)

            day = pending.get("day", "today")
            w = weather.get_weather(city, day=day)
            if w:
                return f"Запомнил. {weather.describe_weather(w)}"
            return f"Запомнил город «{city}», но погоду узнать не удалось."

        return "Не понял уточнение."

    def _execute_steps(self, steps: list) -> str | None:
        reply = None
        history.push_macro(steps)

        for step in steps[:6]:
            if not isinstance(step, dict):
                continue
            action = step.get("action")
            if action == "wait":
                time.sleep(min(float(step.get("seconds", 1) or 1), 15))
                continue
            if action == "media_key":
                actions.media_key(str(step.get("key", "")), int(step.get("times", 1) or 1))
                continue
            r = self._execute_intent(step)
            if r:
                reply = r
        return reply

    def _execute_intent(self, intent: dict) -> str | None:
        action = intent.get("action")
        target = normalize(str(intent.get("target") or ""))
        query = str(intent.get("query") or "").strip()

        actions_log.info("Интент: %s (target=%r, query=%r)", action, target, query)

        if action == "open_app" and target:
            if intent.get("minimized"):
                hit = find_installed(self.installed, target)
                if hit:
                    actions.open_path(hit[1], minimized=True)
                    return f"Открываю {hit[0]}."
            running = actions.find_process(target, threshold=0.8)
            if running:
                from jarvis.actions import activate_window_by_title
                if activate_window_by_title(target):
                    return f"Переключаюсь на {target}."
            result = self._do_open(target)
            return result
        if action == "close_app" and target:
            return self._do_close(target)
        if action == "open_file":
            return self._open_last_file()

        if action == "open_site" and (target or query):
            site = target or query
            if "." in (intent.get("target") or ""):
                actions.open_url("https://" + str(intent["target"]).strip().lower())
                return f"Открываю {site}."
            return self._open_site(site)
        if action == "search" and (query or target):
            engine = intent.get("engine") if intent.get("engine") in ("google", "youtube", "wiki") else "google"
            q = query or target
            actions.open_search(engine, q)
            return f"Ищу: {q}."

        if action == "screenshot":
            path = actions.take_screenshot()
            self.last_file = path
            return f"Скриншот сохранён в папку {path.parent.name}."

        if action == "open_folder" and target:
            folder = files.resolve_folder(target, explicit=True)
            if folder:
                self.last_folder = folder
                files.open_folder(folder)
                return f"Открываю папку {folder.name}."
            return None
        if action == "list_folder":
            folder = files.resolve_folder(target, explicit=True) if target else self.last_folder
            if folder:
                self.last_folder = folder
                return files.describe_folder(folder)
            return None
        if action == "create_file":
            folder_name = str(intent.get("folder") or "").strip()
            folder = None
            if folder_name:
                folder = files.resolve_folder(folder_name, explicit=True)
                if folder is None:
                    return f"Папку «{folder_name}» не нашёл. Куда создать файл?"
            if folder is None:
                folder = Path.home() / "Desktop"
            path = files.create_file(folder, target or "новый файл")
            self.last_file = path
            return f"Создал {path.name} {self._folder_title(folder)}."

        if action == "type_text":
            text = str(intent.get("text") or intent.get("target") or "").strip()
            ok = actions.type_text(text)
            return f"Печатаю: {text}." if ok else "Не удалось напечатать."

        if action == "media_key":
            ok = actions.media_key(str(intent.get("key", "")),
                                   int(intent.get("times", 1) or 1))
            return "Готово." if ok else None
        if action == "play_pause":
            actions.media_key("play")
            return "Готово."
        if action == "next_track":
            actions.media_key("next")
            return "Переключаю."
        if action == "prev_track":
            actions.media_key("prev")
            return "Возвращаю."
        if action == "volume_up":
            actions.media_key("vol_up", 5)
            return "Громче."
        if action == "volume_down":
            actions.media_key("vol_down", 5)
            return "Тише."
        if action == "mute":
            actions.media_key("mute")
            return "Без звука."

        if action == "switch_layout":
            ok = actions.switch_layout()
            if ok:
                history.push({"action": "switch_layout"})
            return "Переключаю раскладку." if ok else None
        if action == "set_layout_ru":
            ok = actions.set_layout_ru()
            return "Русская раскладка." if ok else None
        if action == "set_layout_en":
            ok = actions.set_layout_en()
            return "Английская раскладка." if ok else None
        if action == "get_layout":
            layout = actions.get_layout()
            if layout == "ru":
                return "Русская раскладка."
            if layout == "en":
                return "Английская раскладка."
            return None

        if action == "set_volume":
            try:
                pct = int(intent.get("percent") or 50)
            except (TypeError, ValueError):
                pct = 50
            prev = actions.get_volume()
            ok = actions.set_volume(pct)
            if ok:
                history.push({"action": "set_volume", "prev_value": prev})
            return f"Громкость: {pct}%." if ok else None
        if action == "get_volume":
            vol = actions.get_volume()
            return f"Громкость: {vol}%." if vol is not None else None

        if action == "set_brightness":
            try:
                pct = int(intent.get("percent") or 50)
            except (TypeError, ValueError):
                pct = 50
            prev = actions.get_brightness()
            ok = actions.set_brightness(pct)
            if ok:
                history.push({"action": "set_brightness", "prev_value": prev})
            return f"Яркость: {pct}%." if ok else None
        if action == "get_brightness":
            br = actions.get_brightness()
            return f"Яркость: {br}%." if br is not None else None

        if action == "clipboard_read":
            text = actions.clipboard_read()
            if not text:
                return "Буфер обмена пуст."
            return f"В буфере: {text[:400]}"

        if action == "copy_selection":
            ok = actions.copy_selection()
            if not ok:
                return "Не удалось скопировать."
            time.sleep(0.15)
            text = actions.clipboard_read()
            if text:
                short = text[:200] + ("..." if len(text) > 200 else "")
                return f"Скопировал: {short}"
            return "Скопировал выделенное."

        if action == "clipboard_copy_last":
            last = self._last_reply
            if not last:
                return "Нечего копировать."
            ok = actions.clipboard_write(last)
            return "Скопировал свой ответ в буфер." if ok else "Не удалось скопировать."

        if action == "clipboard_clear":
            ok = actions.clipboard_clear()
            return "Буфер очищен." if ok else "Не удалось очистить буфер."

        if action == "minimize_all":
            actions.minimize_all()
            return "Сворачиваю всё."
        if action == "minimize_window" and target:
            ok = actions.minimize_window_by_title(target)
            return f"Сворачиваю {target}." if ok else f"Окно {target} не нашёл."
        if action == "maximize_window" and target:
            ok = actions.maximize_window_by_title(target)
            return f"Разворачиваю {target}." if ok else f"Окно {target} не нашёл."
        if action == "activate_window" and target:
            ok = actions.activate_window_by_title(target)
            return f"Переключаюсь на {target}." if ok else f"Окно {target} не нашёл."
        if action == "minimize_active":
            actions.minimize_active()
            return "Сворачиваю активное окно."
        if action == "maximize_active":
            actions.maximize_active()
            return "Разворачиваю активное окно."
        if action == "switch_window":
            actions.switch_window(back=bool(intent.get("back")))
            return "Переключаю окно."

        if action == "set_mode":
            prev_mode = self.mode
            mode = str(intent.get("mode") or "combo").lower()
            if mode not in ("commands", "llm", "combo"):
                mode = "combo"
            reply = modes.set_mode(mode, self.config)
            if mode != prev_mode:
                history.push({"action": "set_mode", "prev_value": prev_mode})
            self.mode = mode
            return reply

        if action == "load_pack":
            name = packs.normalize_name(str(intent.get("name") or ""))
            available = packs.list_available()
            if name not in available:
                return f"Пак '{name}' не найден. Доступны: {', '.join(available)}."
            if name in self.active_packs:
                return f"Пак '{name}' уже активен."
            self.active_packs.append(name)
            packs.save_active(self.active_packs, self.config)
            self._reload_packs()
            return f"Пак '{name}' загружен."
        if action == "unload_pack":
            name = packs.normalize_name(str(intent.get("name") or ""))
            if name not in self.active_packs:
                return f"Пак '{name}' и так не активен."
            self.active_packs.remove(name)
            packs.save_active(self.active_packs, self.config)
            self._reload_packs()
            return f"Пак '{name}' выгружен."
        if action == "list_packs":
            available = packs.list_available()
            active_str = ", ".join(self.active_packs) if self.active_packs else "нет"
            return f"Доступны: {', '.join(available)}. Активны: {active_str}."

        if action == "change_voice":
            prev = voices.current_voice(self.config)
            voice = str(intent.get("voice") or "").strip().lower()
            reply = voices.switch(voice, self.config)
            if voice in voices.PIPER_VOICES and voice != prev:
                history.push({"action": "change_voice", "prev_value": prev})
            return reply
        if action == "list_voices":
            return voices.handle_voice_command("список голосов", self.config)

        if action == "set_timer":
            text = str(intent.get("text") or "").strip()
            seconds = intent.get("seconds")
            time_str = intent.get("time")
            fire_at = None
            if seconds:
                try:
                    fire_at = time.time() + float(seconds)
                except (TypeError, ValueError):
                    fire_at = None
            elif time_str:
                try:
                    hh, mm = str(time_str).split(":")
                    now = datetime.datetime.now()
                    t = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
                    if t <= now:
                        t += datetime.timedelta(days=1)
                    fire_at = t.timestamp()
                except Exception:
                    fire_at = None
            if fire_at:
                timers.add(text, fire_at)
                when = datetime.datetime.fromtimestamp(fire_at).strftime("%H:%M")
                return f"Напомню в {when}: {text}." if text else f"Напомню в {when}."
            return "Не понял время напоминания."
        if action == "list_timers":
            return timers.format_list(timers.list_all())
        if action == "cancel_timers":
            n = timers.remove_all()
            return f"Отменено напоминаний: {n}." if n else "Напоминаний не было."

        if action == "add_task":
            text = str(intent.get("text") or intent.get("task") or "").strip()
            if not text:
                return "Что добавить?"
            task = tasks.add(text)
            return f"Добавил: {task['text']}."
        if action == "list_tasks":
            return tasks.format_list()
        if action == "done_task":
            q = str(intent.get("task") or "").strip()
            task = tasks.mark_done(q)
            return f"Отметил: {task['text']}." if task else f"Задачу «{q}» не нашёл."
        if action == "remove_task":
            q = str(intent.get("task") or "").strip()
            task = tasks.remove(q)
            return f"Убрал: {task['text']}." if task else f"Задачу «{q}» не нашёл."
        if action == "clear_tasks":
            n = tasks.clear_all()
            return f"Очищено задач: {n}." if n else "Список и так пуст."

        if action == "open_config":
            cfg_path = Path(__file__).resolve().parent.parent / "config.json"
            actions.open_path(cfg_path)
            return "Открываю конфиг."
        if action == "open_log":
            log_path = Path(__file__).resolve().parent.parent / "logs" / "jarvis.log"
            actions.open_path(log_path)
            return "Открываю журнал."
        if action == "open_profile":
            # Открывает profiles/<current>/profile.json в редакторе.
            # Notepad++ → VS Code → системный (os.startfile).
            prof_path = profile.profile_path()
            prefer = str(intent.get("editor") or "auto").lower()
            ok = actions.open_in_editor(prof_path, prefer=prefer)
            if ok:
                return f"Открываю профиль {profile.current()}."
            return f"Не удалось открыть профиль: {prof_path}"

        if action == "get_weather":
            city = str(intent.get("target") or "").strip()
            day = "tomorrow" if intent.get("day") == "tomorrow" else "today"

            if any(w in city.lower() for w in _WEATHER_BAD_TARGET):
                log.warning("get_weather: LLM подсунула мусор target=%r — игнорирую", city)
                city = ""

            if not city:
                city = profile.get("default_city")
            if not city:
                self._pending_question = {
                    "type": "city_for_weather",
                    "day": day,
                    "expires_at": time.time() + 30,
                }
                return "В каком городе узнать погоду?"

            w = weather.get_weather(city, day=day)
            if not w:
                return f"Не удалось узнать погоду для «{city}». Проверь название или интернет."
            return weather.describe_weather(w)

        if action == "get_currency":
            code = str(intent.get("target") or "").strip().upper()
            r = weather.get_currency_rates()
            return weather.describe_currency(r, code=code)

        if action == "delete_profile":
            name = str(intent.get("target") or "").strip()
            if profile.delete(name):
                return f"Профиль {name} удалён."
            return f"Профиль {name} не найден или активен."
        # Профиль — универсально через LLM
        if action == "set_profile":
            key = str(intent.get("key") or "").strip()
            value = str(intent.get("value") or "").strip()
            if not key or not value:
                return "Не понял, что сохранить."

            # Нормализация ключей (LLM может вернуть синонимы)
            key_map = {
                "имя": "name", "name": "name",
                "город": "default_city", "default_city": "default_city",
                "city": "default_city", "мой город": "default_city",
            }
            key = key_map.get(key.lower(), key.lower())

            if key not in ("name", "default_city", "prev_city"):
                return f"Не знаю, что такое «{key}»."

            # Для города — сохраняем предыдущий
            if key == "default_city":
                prev = profile.get("default_city")
                if prev and prev.lower() != value.lower():
                    profile.set("prev_city", prev)

            ok = profile.set(key, value)
            if ok:
                if key == "name":
                    return f"Имя изменено на {value}."
                if key == "default_city":
                    return f"Город изменён на {value}."
                return f"Сохранено: {key} = {value}."
            return "Не удалось сохранить."

        if action == "get_profile":
            key = str(intent.get("key") or "").strip()
            key_map = {
                "имя": "name", "name": "name",
                "город": "default_city", "default_city": "default_city",
                "city": "default_city",
            }
            key = key_map.get(key.lower(), key.lower())

            if key == "name":
                v = profile.get("name")
                return f"Тебя зовут {v}." if v else "Имя не задано."
            if key == "default_city":
                v = profile.get("default_city")
                return f"Твой город — {v}." if v else "Город не задан."
            return "Не знаю, что прочитать."

        if action == "answer" and intent.get("reply"):
            return str(intent["reply"])[:600]

        return None

    def _do_open(self, target: str) -> str:
        if not target:
            return "Что именно открыть?"
        if target in {"его", "ее", "это", "этот файл", "файл", "последний файл"}:
            return self._open_last_file()

        tokens = target.split()
        rest = [t for t in tokens if t not in BROWSER_WORDS]
        if len(rest) < len(tokens):
            if not rest:
                actions.open_browser()
                return "Открываю браузер."
            return self._open_site(" ".join(rest))

        app = find_app(self.apps, target)
        if app:
            spec = app.resolve_open()
            if spec is None:
                return f"{app.title} не найден на этом компьютере."
            actions.run_spec(spec)
            return f"Открываю {app.title}."

        for key, (title, url) in SITES.items():
            if key in target.split() or target == key:
                actions.open_url(url)
                return f"Открываю {title}."

        folder = files.resolve_folder(target, explicit="папк" in target)
        if folder:
            self.last_folder = folder
            files.open_folder(folder)
            return f"Открываю папку {folder.name}."

        game = find_game(self.steam_games, target)
        if game:
            title, appid = game
            actions.run_spec(("uri", f"steam://rungameid/{appid}"))
            return f"Запускаю {title}."

        hit = find_installed(self.installed, target)
        if hit:
            name, lnk = hit
            actions.open_path(lnk)
            return f"Открываю {name}."

        return self._open_site(target)

    def _open_site(self, name: str) -> str:
        if not name:
            return "Какой сайт открыть?"
        for key, (title, url) in SITES.items():
            if name == key or key in name.split():
                actions.open_url(url)
                return f"Открываю {title}."
        url = actions.spoken_domain(name) or actions.guess_site(name)
        if url:
            actions.open_url(url)
            return f"Открываю сайт {name}."
        return f"Сайт {name} не нашёл. Скажите «найди {name}», и я поищу."

    def _open_last_file(self) -> str:
        if self.last_file:
            actions.open_path(self.last_file)
            return "Открываю."
        return "Пока нечего открывать."

    def _do_close(self, target: str) -> str:
        if not target:
            return "Что именно закрыть?"
        if any(w in target for w in ("браузер", "интернет", "хром")):
            return "Закрываю браузер." if actions.close_browser() else "Браузер не запущен."
        app = find_app(self.apps, target)
        if app and app.procs:
            ok = any(actions.kill_process(p) for p in app.procs)
            if ok:
                return f"Закрываю {app.title}."
        exe = actions.find_process(target)
        if exe:
            actions.kill_process(exe)
            return f"Закрываю {exe.removesuffix('.exe')}."
        if app:
            return f"{app.title} сейчас не запущен."
        return f"Не нашёл запущенной программы {target}."

    def _match_custom(self, cmd: str) -> str | None:
        for phrases, action, reply in self.custom:
            for phrase in phrases:
                if cmd == phrase:
                    log.info("Custom (точно): %r → %r, action=%r", cmd, phrase, action)
                    if isinstance(action, list):
                        return self._execute_steps(action) or reply
                    actions.run_spec(actions.spec_from_string(action))
                    return reply
                if len(cmd) >= 12 and len(phrase) >= 12:
                    ratio = SequenceMatcher(None, cmd, phrase).ratio()
                    if ratio >= 0.85:
                        log.info("Custom (нечётко %.2f): %r → %r, action=%r",
                                 ratio, cmd, phrase, action)
                        if isinstance(action, list):
                            return self._execute_steps(action) or reply
                        actions.run_spec(actions.spec_from_string(action))
                        return reply
        return None

    def _take_screenshot(self, cmd: str) -> str:
        if re.search(r"откр|покаж", cmd):
            if self.last_file:
                actions.open_path(self.last_file)
                return "Открываю."
            return "Пока нечего открывать."
        path = actions.take_screenshot()
        self.last_file = path
        return f"Скриншот сохранён в папку {path.parent.name}."

    def _load_packs_as_custom(self, config):
        result = []
        for entry in packs.load_active(config):
            phrases = [normalize(p) for p in entry.get("phrases", []) if p.strip()]
            action = entry.get("action", "").strip() or entry.get("steps")
            if phrases and action:
                result.append((phrases, action, entry.get("reply", "Выполняю.")))
        return result

    def _reload_packs(self):
        self.custom = list(self._config_custom_original) + self._load_packs_as_custom(self.config)

    def _folder_title(self, path: Path) -> str:
        return _FOLDER_TITLES.get(path.name, f"в папке {path.name}")

    def _small_talk(self, cmd: str) -> str | None:
        now = datetime.datetime.now()
        if any(p in cmd for p in ("который час", "сколько времени", "время")):
            return f"Сейчас {now.hour} {_hours(now.hour)} {now.minute} {_minutes(now.minute)}."
        if any(p in cmd for p in ("какое число", "какая дата", "какое сегодня число", "дата")):
            return f"Сегодня {now.day} {MONTHS[now.month - 1]} {now.year} года, {WEEKDAYS[now.weekday()]}."
        if "день недели" in cmd or cmd == "какой сегодня день":
            return f"Сегодня {WEEKDAYS[now.weekday()]}."
        if any(p in cmd for p in ("как дела", "как ты", "как настроение")):
            return random.choice([
                "Все системы функционируют нормально.",
                "Отлично, сэр. Готов к работе.",
                "В полном порядке, спасибо.",
                "Работаю в штатном режиме, сэр. А вы как?",
                "Не жалуюсь. Процессор холодный, настроение бодрое.",
                "Всё хорошо, сэр. Чем займёмся?",
                "Как у ассистента: без сбоев и скуки. Слушаю вас.",
            ])
        if any(p in cmd for p in ("кто ты", "ты кто", "представься", "как тебя зовут")):
            return f"Я {APP_NAME}, локальный голосовой ассистент, версия {__version__}."
        if any(p in cmd for p in ("что ты умеешь", "помощь", "что умеешь", "команды")):
            return ("Я умею открывать и закрывать приложения и сайты, делать скриншоты, "
                    "искать в интернете, печатать текст, управлять окнами, ставить "
                    "напоминания, вести списки задач, узнавать погоду и курс валют, "
                    "и отвечать на вопросы.")
        if any(p in cmd for p in ("спасибо", "благодарю")):
            return "Всегда пожалуйста."
        if any(p in cmd for p in ("привет", "здравствуй", "добрый день", "доброе утро", "добрый вечер")):
            name = profile.get("name")
            if name:
                return f"Привет, {name}! Чем могу помочь?"
            return "Привет! Чем могу помочь?"
        if any(p in cmd for p in ("пока", "до свидания", "спокойной ночи")):
            return "До связи."
        return None


def _hours(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "час"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "часа"
    return "часов"


def _minutes(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "минута"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "минуты"
    return "минут"
```

### `jarvis\learning.py`

```python
"""Самообучение Феникса: факты и коррекции.

Факты:
    «Феникс, запомни: мой город Нижний Новгород» → facts["город"] = "Нижний Новгород".

Коррекции:
    «Феникс, открой лок» → Феникс: «Открываю калькулятор»
    «Феникс, это не то, я сказал логи» → corrections["открой лок"] = "открой логи"

Подгрузка:
    В brain.py перед запросом к LLM добавляется блок с фактами и corrections.

Хранение:
    profiles/<user>/profile.json — там же, где name, default_city.
    Ключи: facts (dict), corrections (dict).
"""

import logging
from difflib import SequenceMatcher

from jarvis import profile

log = logging.getLogger("jarvis.learning")


# ---------------------------------------------------------------
# Факты
# ---------------------------------------------------------------

def add_fact(key: str, value: str) -> bool:
    """Сохраняет факт. Ключ нормализуется (нижний регистр)."""
    key = key.strip().lower()
    value = value.strip()
    if not key or not value:
        return False

    facts = profile.get("facts", {}) or {}
    facts[key] = value
    ok = profile.set("facts", facts)
    if ok:
        log.info("Факт: %s = %r", key, value)
    return ok


def get_fact(key: str, default=None):
    facts = profile.get("facts", {}) or {}
    return facts.get(key.strip().lower(), default)


def all_facts() -> dict:
    return profile.get("facts", {}) or {}


def forget_fact(key: str) -> bool:
    facts = profile.get("facts", {}) or {}
    key = key.strip().lower()
    if key not in facts:
        return False
    del facts[key]
    return profile.set("facts", facts)


# ---------------------------------------------------------------
# Коррекции
# ---------------------------------------------------------------

def add_correction(wrong: str, right: str) -> bool:
    """Сохраняет коррекцию: «открой лок» → «открой логи»."""
    wrong = wrong.strip().lower()
    right = right.strip()
    if not wrong or not right:
        return False
    if wrong == right.lower():
        return False

    corrections = profile.get("corrections", {}) or {}
    corrections[wrong] = right
    ok = profile.set("corrections", corrections)
    if ok:
        log.info("Коррекция: %r → %r", wrong, right)
    return ok


def find_correction(cmd: str, threshold: float = 0.85) -> str | None:
    """Ищет коррекцию для команды.

    Сначала точное совпадение, потом — нечёткое (SequenceMatcher).
    """
    corrections = profile.get("corrections", {}) or {}
    if not corrections:
        return None

    cmd_low = cmd.strip().lower()
    # Точное
    if cmd_low in corrections:
        return corrections[cmd_low]

    # Нечёткое
    best, best_ratio = None, threshold
    for wrong, right in corrections.items():
        ratio = SequenceMatcher(None, cmd_low, wrong).ratio()
        if ratio > best_ratio:
            best_ratio, best = ratio, right
    if best:
        log.info("Коррекция (нечётко): %r → %r (ratio %.2f)", cmd, best, best_ratio)
    return best


def all_corrections() -> dict:
    return profile.get("corrections", {}) or {}


def forget_correction(wrong: str) -> bool:
    corrections = profile.get("corrections", {}) or {}
    wrong = wrong.strip().lower()
    if wrong not in corrections:
        return False
    del corrections[wrong]
    return profile.set("corrections", corrections)


# ---------------------------------------------------------------
# Сборка контекста для промпта
# ---------------------------------------------------------------

def build_context() -> str:
    """Собирает блок для промпта из профиля, фактов и коррекций.

    Возвращает пустую строку, если нечего добавить.
    """
    parts = []

    # Базовые поля профиля — name, default_city.
    # Без них LLM не знает, как зовут пользователя и где он живёт,
    # хотя _small_talk и профиль-команды это знают.
    name = profile.get("name")
    city = profile.get("default_city")
    profile_lines = []
    if name:
        profile_lines.append(f"- Имя пользователя: {name}")
    if city:
        profile_lines.append(f"- Город по умолчанию: {city}")
    if profile_lines:
        parts.append("Данные профиля пользователя:\n" + "\n".join(profile_lines))

    facts = all_facts()
    if facts:
        lines = [f"- {k}: {v}" for k, v in facts.items()]
        parts.append("Известные факты о пользователе:\n" + "\n".join(lines))

    corrections = all_corrections()
    if corrections:
        lines = [f"- «{wrong}» → «{right}»" for wrong, right in corrections.items()]
        parts.append("Известные исправления (если пользователь говорит первое, делай второе):\n"
                     + "\n".join(lines))

    if not parts:
        return ""

    return "\n\n" + "\n\n".join(parts) + "\n"
```

### `jarvis\main.py`

```python
"""Точка входа: связывает распознавание, интенты, синтез речи и трей.

Barge-in: во время речи Феникса микрофон НЕ глушится, а следит за громкостью.
Если юзер заговорил — TTS прерывается через speaker.stop().
После barge-in окно диалога открывается заново — можно продолжать без wake-слова.

Стриминг: генератор оборачивается в tee — чанки идут и в TTS, и в GUI.

launch_mode:
    "gui"  — окно Flet + трей + голос (по умолчанию).
    "tray" — только трей + голос, без окна.
"""

import logging
import logging.handlers
import threading
import time
from pathlib import Path

from jarvis.matching import wake_score

from jarvis import APP_NAME, __version__
from jarvis.apps import build_apps
from jarvis.config import Config, load_config
from jarvis.intents import IntentHandler, normalize
from jarvis.model import ensure_model
from jarvis.reply import Reply
from jarvis.stt import Listener
from jarvis.tray import build_tray
from jarvis import timers
from jarvis.tts import Speaker
from jarvis.gui import FenixGUI

log = logging.getLogger("jarvis")

BASE_DIR = Path(__file__).resolve().parent.parent
_REJECT = object()


class Jarvis:
    def __init__(self, config, listener, speaker, handler, base_dir: Path,
                 whisper=None, gui=None):
        self.config = config
        self.listener = listener
        self.speaker = speaker
        self.handler = handler
        self.base_dir = base_dir
        self.whisper = whisper
        self.gui = gui
        self.listening_enabled = True
        self.stop_event = threading.Event()
        self._awaiting_until = 0.0
        self._wake_words = [normalize(w) for w in config["wake_words"]]
        self.barge_enabled = bool(config.get("barge_enabled", True))
        if self.listener is not None:
            self.listener.barge_enabled = self.barge_enabled
        self._barge_just_happened = False

    def say(self, reply: Reply) -> bool:
        """Озвучивает Reply. Возвращает True, если сработал barge-in."""
        if reply is None:
            return False
        if not reply.is_stream and not reply.text:
            return False

        if self.gui is not None:
            self.gui.set_state("speaking")

        if self.barge_enabled and self.listener is not None:
            self.listener.barge_start()
        else:
            self.listener.muted = True

        barge_happened = False
        try:
            if reply.is_stream:
                self._say_stream(reply.stream)
            else:
                self._say_text(reply.text)
            barge_happened = self.barge_enabled and self.listener.barge_flag
        finally:
            if self.barge_enabled and self.listener is not None:
                self.listener.barge_end()
            self.listener.flush()
            self.listener.muted = False
            if self.gui is not None:
                self.gui.set_state("idle")
        return barge_happened

    def _say_text(self, text: str) -> None:
        self.speaker.play_async(text)
        while self.speaker.is_playing():
            if self.barge_enabled and self.listener.barge_flag:
                log.info("Barge-in сработал — прерываю TTS")
                self.speaker.stop()
                break
            time.sleep(0.05)
        self.speaker.wait_end(timeout=30.0)

    def _say_stream(self, gen) -> None:
        """Озвучивает стрим и показывает чанки в GUI.

        №73: end_stream вызывается ВСЕГДА (try/finally) — иначе при
        ошибке внутри потока стрим-пузырь в GUI зависает навсегда.

        Генератор оборачивается в tee: каждый чанк идёт и в speak_stream,
        и в GUI через add_stream_chunk.
        """
        result = {"text": ""}

        def _tee(iterator):
            """Пропускает чанки и в TTS, и в GUI."""
            for chunk in iterator:
                result["text"] += chunk
                if self.gui is not None:
                    self.gui.add_stream_chunk(chunk)
                yield chunk

        def _run():
            try:
                self.speaker.speak_stream(_tee(gen))
            except Exception:
                log.exception("Ошибка в speak_stream")

        t = threading.Thread(target=_run, daemon=True, name="tts-stream")
        t.start()

        try:
            while t.is_alive():
                if self.barge_enabled and self.listener.barge_flag:
                    log.info("Barge-in сработал — прерываю стриминг")
                    self.speaker.stop()
                    t.join(timeout=1.0)
                    break
                time.sleep(0.05)
            t.join(timeout=5.0)
        finally:
            # №73: закрываем стрим-пузырь ВСЕГДА
            if self.gui is not None:
                self.gui.end_stream()

            # Финальный текст — в память
            if result["text"] and hasattr(self.handler, "finalize_stream"):
                self.handler.finalize_stream("", result["text"])

    def shutdown(self) -> None:
        self.stop_event.set()

    def mic_watchdog(self) -> None:
        """Проверяет микрофон ОДИН РАЗ через mic_check_sec.

        Больше не спамит: если микрофон молчит — предупреждает один раз
        за сессию. Дальше — тишина, пока пользователь сам не разберётся.
        """
        if not self.config.get("mic_watchdog_enabled", True):
            log.info("mic_watchdog выключен в config")
            return

        delay = float(self.config.get("mic_check_sec", 20))
        if self.stop_event.wait(delay):
            return

        if self.listener.peak >= 50:
            log.info("mic_watchdog: пик %d — микрофон живой", self.listener.peak)
            return

        log.warning("Микрофон молчит (пик %d за %.0f с): %s",
                    self.listener.peak, delay, self.listener.device_name)

        self.say(Reply(text="Я не слышу микрофон. Проверьте, включён ли он, "
                           "или выберите другое устройство в настройках."))

        if self.gui is not None:
            self.gui._queue.put(("open_mic_tab", None))

        log.info("mic_watchdog: предупреждение показано, больше не повторяем")

    def run_loop(self) -> None:
        try:
            for phrase, audio in self.listener.phrases(self.stop_event):
                if not self.listening_enabled:
                    continue
                try:
                    self._process(phrase, audio)
                except Exception:
                    log.exception("Ошибка обработки фразы %r", phrase)
        except Exception:
            log.exception("Аудиопоток упал")
            self.say(Reply(text="Проблема с микрофоном. Проверьте журнал."))

    def _process(self, phrase: str, audio: bytes) -> None:
        awaiting = time.time() < self._awaiting_until
        cmd = self._extract_command(normalize(phrase))
        pending = getattr(self.handler, "_pending_question", None)
        if pending and time.time() < pending.get("expires_at", 0):
            awaiting = True
        if cmd is None:
            return
        if cmd == "":
            self.say(Reply(text="Слушаю."))
            self._awaiting_until = time.time() + self.config["command_window_sec"]
            return
        if self.whisper is not None and audio:
            refined = self._refine(audio, awaiting)
            if refined is _REJECT:
                log.info("Whisper не подтвердил wake-слово — игнорирую (ложное срабатывание)")
                return
            if refined:
                cmd = refined

        if self.gui is not None:
            self.gui.add_message("user", cmd)
            self.gui.set_state("listening")

        reply = self.handler.handle(cmd)

        if self.gui is not None and not reply.is_stream:
            self.gui.add_message("assistant", reply.text or "")

        self._awaiting_until = time.time() + float(
            self.config.get("dialog_window_sec", 8))

        if getattr(self.handler, "_reset_requested", False):
            self.speaker.stop()
            self.speaker.wait_end(timeout=1.0)

        barge_happened = self.say(reply)

        if getattr(self.handler, "_reset_requested", False):
            self._awaiting_until = 0.0
            self.handler._reset_requested = False
            log.info("Сброс: жду wake-слово")
            return

        if barge_happened:
            log.info("Barge-in: окно диалога уже открыто (без wake-слова)")
            self._awaiting_until = time.time() + float(
                self.config.get("dialog_window_sec", 8))

    def _refine(self, audio: bytes, awaiting: bool):
        try:
            text = normalize(self.whisper.transcribe(audio))
        except Exception:
            log.exception("Whisper не справился, использую текст Vosk")
            return None
        if not text:
            return _REJECT
        tokens = text.split()
        for i, tok in enumerate(tokens):
            if self._is_wake(tok):
                return " ".join(tokens[i + 1:])
        if awaiting:
            return text
        if tokens and wake_score(tokens[0], self._wake_words[0]) >= 0.5:
            return " ".join(tokens[1:])
        return _REJECT

    def _extract_command(self, text: str) -> str | None:
        tokens = text.split()
        for i, tok in enumerate(tokens):
            if self._is_wake(tok):
                return " ".join(tokens[i + 1:])
        if time.time() < self._awaiting_until:
            return text
        return None

    def _is_wake(self, token: str) -> bool:
        return token in self._wake_words or any(
            wake_score(token, w) >= 0.8 for w in self._wake_words
        )


def setup_logging() -> None:
    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    LOGS_DIR = BASE_DIR / "logs"
    LOGS_DIR.mkdir(exist_ok=True)

    fmt = "%(asctime)s %(name)s %(levelname)s %(message)s"
    formatter = logging.Formatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(logging.INFO)
    root.addHandler(console)

    jarvis_handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / "jarvis.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    jarvis_handler.setFormatter(formatter)
    jarvis_handler.setLevel(logging.INFO)
    root.addHandler(jarvis_handler)

    errors_handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / "errors.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    errors_handler.setFormatter(formatter)
    errors_handler.setLevel(logging.WARNING)
    root.addHandler(errors_handler)

    actions_logger = logging.getLogger("jarvis.actions")
    actions_logger.setLevel(logging.INFO)
    actions_logger.propagate = False
    actions_handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / "actions.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    actions_handler.setFormatter(formatter)
    actions_logger.addHandler(actions_handler)

    # Глобальный перехват исключений в потоках
    def _thread_excepthook(args):
        thread_name = args.thread.name if args.thread else "?"
        log.critical(
            "Необработанное исключение в потоке %r:",
            thread_name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = _thread_excepthook

    # Глобальный перехват для ГЛАВНОГО потока
    import sys

    def _sys_excepthook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            return
        log.critical(
            "Необработанное исключение в главном потоке:",
            exc_info=(exc_type, exc_value, exc_tb),
        )

    sys.excepthook = _sys_excepthook


def main() -> None:
    setup_logging()
    log.info("%s v%s запускается", APP_NAME, __version__)

    # Порядок импортов критичен для Windows:
    #   faster_whisper → ctranslate2 → winrt.
    # Если faster_whisper нет — ctranslate2 нет — winrt может дать
    # access violation. Поэтому логируем явно, что отсутствует.
    for _mod in ("faster_whisper", "ctranslate2"):
        try:
            __import__(_mod)
        except ImportError:
            log.warning(
                "Модуль %s не установлен. Whisper будет недоступен, "
                "работаю только на Vosk. Установи: pip install %s",
                _mod, _mod.replace("_", "-"),
            )

    config: Config = load_config(BASE_DIR)
    from jarvis import profile as _profile
    from jarvis import weather as _weather
    _profile.init()
    _weather.set_config(config)
    model_dir = ensure_model(BASE_DIR / "models")

    whisper = None
    if config.get("use_whisper", True):
        try:
            from jarvis.stt import WhisperTranscriber
            whisper = WhisperTranscriber(
                config.get("whisper_model", "auto"),
                config.get("whisper_device", "auto"),
            )
        except Exception:
            log.exception("Whisper не завёлся, работаю только на Vosk")

    brain = None
    if config.get("use_llm", True):
        from jarvis.brain import Brain
        brain = Brain(
            config.get("llm_model", "qwen2.5:7b-instruct"),
            config.get("ollama_url", "http://127.0.0.1:11434"),
            prompt_level=config.get("prompt_level", "auto"),
            temperature=config.get("llm_temperature", 0.7),
            config=config,
        )
        if not brain.available:
            brain = None

    speaker = Speaker(config)
    listener = Listener(model_dir, config["sample_rate"], config.get("input_device"))
    handler = IntentHandler(config, build_apps(config), brain, listener=listener)

    gui = None
    if config.get("gui_enabled", True):
        try:
            gui = FenixGUI(None, config)
        except Exception:
            log.exception("GUI не завёлся")

    jarvis = Jarvis(config, listener, speaker, handler, BASE_DIR, whisper, gui=gui)

    if gui is not None:
        gui.jarvis = jarvis

    # --- Подписки: изменения конфига применяются на лету ---
    def _on_config_change(key: str, value):
        if key == "tts_voice":
            speaker.set_voice(value)
        elif key == "voice_rate":
            speaker.set_rate(value)
        elif key == "mode":
            handler.mode = value
        elif key == "barge_enabled":
            jarvis.barge_enabled = bool(value)
            if listener is not None:
                listener.barge_enabled = bool(value)

    config.subscribe(_on_config_change)

    def _on_timer_fire(timer: dict):
        text = timer.get("text") or "время вышло"
        msg = f"Напоминание: {text}."
        log.info("Таймер сработал: %s", msg)
        jarvis.say(Reply(text=msg))

    timers.set_on_fire(_on_timer_fire)
    restored = timers.restore_all()
    if restored:
        log.info("Восстановлено напоминаний: %d", restored)

    # Jarvis — в фоновом потоке
    worker = threading.Thread(target=jarvis.run_loop, daemon=True, name="jarvis-listener")
    worker.start()
    threading.Thread(target=jarvis.mic_watchdog, daemon=True, name="mic-watchdog").start()

    jarvis.say(Reply(text=f"{APP_NAME} запущен и готов к работе."))

    # Трей — в отдельном потоке (может не работать на некоторых системах)
    if config.get("tray_enabled", True):
        try:
            tray = build_tray(jarvis)

            def _run_tray():
                try:
                    tray.run()
                except (Exception, SystemExit):
                    # №90: SystemExit — наследник BaseException, не Exception.
                    # pystray может его бросить при выходе — не роняем процесс.
                    log.exception("Трей упал в потоке — работаю без него")

            threading.Thread(target=_run_tray, daemon=True, name="tray").start()
        except (Exception, SystemExit):
            log.exception("Трей не завёлся — работаю без него")

    # === Режим запуска (№84) ===
    # launch_mode:
    #   "gui"  — окно Flet (по умолчанию).
    #   "tray" — только трей + голос, без окна.
    launch_mode = str(config.get("launch_mode", "gui") or "gui").lower()
    if launch_mode not in ("gui", "tray"):
        launch_mode = "gui"

    # Защита от конфликта: launch_mode=tray, но трей выключен.
    # Иначе окно скрыто, трея нет — показать некому.
    if launch_mode == "tray" and not config.get("tray_enabled", True):
        log.warning(
            "launch_mode=tray, но tray_enabled=false — переключаюсь на gui"
        )
        launch_mode = "gui"

    if gui is not None:
        if launch_mode == "tray":
            log.info("launch_mode=tray — GUI запущен, но окно скрыто")
            gui.start_hidden = True
        else:
            log.info("Запускаю Flet в главном потоке (launch_mode=gui)")

        # Flet ВСЕГДА в главном потоке (signal.signal)
        gui.run_main()
    else:
        log.info("GUI выключен — жду завершения")
        jarvis.stop_event.wait()

    jarvis.shutdown()
    log.info("Завершение работы")


if __name__ == "__main__":
    main()
```

### `jarvis\matching.py`

```python
"""Нечёткое сопоставление речи с названиями: транслитерация + difflib.

Vosk выдаёт только кириллицу («обс студио»), а программы называются латиницей
(«OBS Studio»), поэтому сравниваем и оригинал, и транслит.
"""

import re
from difflib import SequenceMatcher

_RU_DIGRAPHS = {"дж": "j"}  # фонетика: «джарвис» -> jarvis, а не dzharvis
_RU_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def translit(text: str) -> str:
    text = text.lower()
    for ru, lat in _RU_DIGRAPHS.items():
        text = text.replace(ru, lat)
    return "".join(_RU_LAT.get(ch, ch) for ch in text)


_FOLD = str.maketrans({"c": "k", "q": "k", "w": "v", "x": "ks"})


def _fold(s: str) -> str:
    """Фонетическое выравнивание латиницы: Camo ~ камо(kamo), roblox ~ роблокс."""
    return s.replace("ph", "f").translate(_FOLD)


_NUM = {"ноль": "0", "один": "1", "одна": "1", "два": "2", "две": "2", "три": "3",
        "четыре": "4", "пять": "5", "шесть": "6", "семь": "7", "восемь": "8",
        "девять": "9", "десять": "10"}


def _num_norm(s: str) -> str:
    """«дота два» -> «дота 2»: в названиях номера всегда цифрами."""
    return " ".join(_NUM.get(w, w) for w in s.split())


def wake_score(token: str, wake_word: str) -> float:
    """Строгая похожесть для wake-слова.

    №94: убраны лишние сравнения. Раньше было 4 сравнения через
    set comprehension, включая бессмысленное token vs token-транслит.
    Теперь — 4 явных сравнения, семантика ясная:
        token ~ wake
        translit(token) ~ translit(wake)
        token ~ translit(wake)
        translit(token) ~ wake
    """
    if not token or not wake_word:
        return 0.0
    tok = token.lower()
    wake = wake_word.lower()
    tok_t = translit(tok)
    wake_t = translit(wake)
    return max(
        SequenceMatcher(None, tok, wake).ratio(),
        SequenceMatcher(None, tok_t, wake_t).ratio(),
        SequenceMatcher(None, tok, wake_t).ratio(),
        SequenceMatcher(None, tok_t, wake).ratio(),
    )


def _skeleton(s: str) -> str:
    """Согласный скелет: stim/steam -> stm. Гласные между языками плавают,
    согласные при транслитерации сохраняются."""
    return re.sub(r"[aeiouy\s]", "", translit(s))


def match_score(spoken: str, candidate: str) -> float:
    """Похожесть сказанного на название (0..1). Оба сравниваются в нижнем регистре,
    сказанное — ещё и в транслите; пробуем целиком, без пробелов и по словам."""
    cand = re.sub(r"\(.*?\)", " ", candidate.lower()).strip()
    cand = re.sub(r"\s+", " ", cand)
    if not spoken or not cand:
        return 0.0
    spoken = _num_norm(spoken)
    cand = _num_norm(cand)

    len_spoken = len(spoken.replace(" ", ""))

    best = 0.0
    for s in {spoken, _fold(translit(spoken))}:
        for c in {cand, _fold(translit(cand))}:
            if s == c:
                return 1.0
            if len(s) >= 5 and (s in c or c in s):
                best = max(best, 0.9)
            best = max(best, SequenceMatcher(None, s, c).ratio())
            best = max(best, SequenceMatcher(None, s.replace(" ", ""), c.replace(" ", "")).ratio())
            s_words, c_words = s.split(), c.split()
            for word in c_words:
                best = max(best, SequenceMatcher(None, s, word).ratio())
            if len(s_words) > 1 and c_words:
                avg = sum(
                    max(SequenceMatcher(None, sw, cw).ratio() for cw in c_words)
                    for sw in s_words
                ) / len(s_words)
                best = max(best, avg)
    sk_s, sk_c = _skeleton(spoken), _skeleton(cand)
    if len(sk_s) >= 3 and sk_s == sk_c:
        best = max(best, 0.8)

    if len_spoken < 4 and best < 0.85:
        return 0.0

    return best
```

### `jarvis\memory.py`

```python
"""Память диалога — на профиль.

Архитектура:
    profiles/<user>/dialog.json  — история диалога пользователя.

API чистое:
    load(limit)         — читает последние N сообщений.
    append(message)     — добавляет одно сообщение на диск.
    clear()             — очищает историю текущего профиля.
    describe(messages)  — пересказ для озвучки.
    handle_memory_command(cmd, messages) — команды памяти.

Лимиты — НЕ здесь. Их задаёт вызывающий (IntentHandler) из config.
"""

import json
import logging
import re
import threading
from pathlib import Path

from jarvis import profile as _profile

log = logging.getLogger("jarvis.memory")

_lock = threading.Lock()


# ---------------------------------------------------------------
# Чтение / запись
# ---------------------------------------------------------------

def load(limit: int | None = None) -> list:
    """Загружает историю диалога. Без limit — все сообщения."""
    path = _profile.dialog_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            log.warning("%s — не массив, игнорирую", path)
            return []
        if limit and limit > 0:
            return data[-limit:]
        return data
    except Exception:
        log.exception("Не удалось прочитать %s", path)
        return []


def append(message: dict) -> None:
    """Добавляет одно сообщение и пишет на диск."""
    if not isinstance(message, dict):
        return
    path = _profile.dialog_path()
    with _lock:
        try:
            data = []
            if path.exists():
                raw = path.read_text(encoding="utf-8")
                if raw.strip():
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        data = parsed
            data.append(message)
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            log.exception("Не удалось дописать в %s", path)


def clear() -> None:
    """Очищает память текущего профиля."""
    path = _profile.dialog_path()
    try:
        if path.exists():
            path.unlink()
        log.info("Память диалога очищена: %s", path)
    except Exception:
        log.exception("Не удалось очистить %s", path)


# ---------------------------------------------------------------
# Команды / описание
# ---------------------------------------------------------------

def describe(messages: list, limit: int = 6) -> str:
    """Краткий пересказ последних тем."""
    if not messages:
        return "Пока ничего не обсуждали."
    user_msgs = [m.get("content", "") for m in messages
                 if m.get("role") == "user" and m.get("content")]
    if not user_msgs:
        return "Пока ничего не обсуждали."
    recent = user_msgs[-limit:]
    topics = ", ".join(f"«{t}»" for t in recent)
    return f"Последние темы: {topics}."


def handle_memory_command(cmd: str, messages: list) -> tuple[str | None, bool]:
    """Разбирает команды памяти.

    Возвращает (ответ_или_None, нужно_очистить_память).
    """
    if re.search(r"(что|о\s+ч[её]м)\s+(мы\s+)?(обсуждал|говорил|болтал)", cmd) \
            or cmd in {"что мы обсуждали", "о чём мы говорили", "что обсуждали"}:
        return describe(messages), False

    if re.search(r"(забудь|очисти|сбрось|сотри)\s+(вс[её]|память|историю|диалог)", cmd) \
            or cmd in {"забудь всё", "очисти память", "сбрось память", "сотри память"}:
        clear()
        return "Память очищена.", True

    if re.search(r"(сохрани|запиши)\s+память", cmd) \
            or cmd in {"сохрани память", "запиши память"}:
        return "Память сохраняется автоматически.", False

    return None, False
```

### `jarvis\model.py`

```python
"""Скачивание и распаковка модели Vosk для русского языка (~45 МБ)."""

import logging
import sys
import urllib.request
import zipfile
from pathlib import Path

log = logging.getLogger("jarvis.model")

MODEL_NAME = "vosk-model-small-ru-0.22"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"


def _progress(blocks: int, block_size: int, total: int) -> None:
    if total > 0:
        pct = min(100, blocks * block_size * 100 // total)
        sys.stdout.write(f"\rСкачивание модели: {pct}%")
        sys.stdout.flush()


def ensure_model(models_dir: Path) -> Path:
    """Возвращает путь к модели, при необходимости скачивает её."""
    model_dir = models_dir / MODEL_NAME
    if model_dir.exists():
        return model_dir

    models_dir.mkdir(parents=True, exist_ok=True)
    zip_path = models_dir / f"{MODEL_NAME}.zip"
    log.info("Модель не найдена, скачиваю %s", MODEL_URL)
    try:
        urllib.request.urlretrieve(MODEL_URL, zip_path, reporthook=_progress)
        sys.stdout.write("\n")
        log.info("Распаковка модели...")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(models_dir)
    finally:
        zip_path.unlink(missing_ok=True)

    if not model_dir.exists():
        raise RuntimeError(f"После распаковки не найдена папка {model_dir}")
    log.info("Модель готова: %s", model_dir)
    return model_dir
```

### `jarvis\modes.py`

```python
"""Режимы работы Феникса: commands, llm, combo."""

import logging
import re

from jarvis import config_manager

log = logging.getLogger("jarvis.modes")

NAMES = {
    "commands": "только команды",
    "llm": "только ИИ",
    "combo": "комбинированный",
}


def get_mode(config) -> str:
    m = config.get("mode", "combo")
    return m if m in NAMES else "combo"


def set_mode(mode: str, config=None) -> str:
    if mode not in NAMES:
        return f"Неизвестный режим: {mode}."
    if config is not None:
        config.set("mode", mode)
    else:
        config_manager.update("mode", mode)
    log.info("Режим переключён на %s", mode)
    return f"Режим: {NAMES[mode]}."


def handle_mode_command(cmd: str, current_mode: str, config=None) -> tuple[str | None, str]:
    if re.search(r"режим\s+(команд|команды|только\s+команд)", cmd) \
            or cmd in {"только команды", "без ии"}:
        return set_mode("commands", config), "commands"

    if re.search(r"режим\s+(ии|искусственн\w*|нейросет\w*|нейронк\w*)", cmd) \
            or cmd in {"только ии", "режим ии", "режим нейросети", "только нейросеть"}:
        return set_mode("llm", config), "llm"

    if re.search(r"(комбинированн|обычн|стандартн|смешанн)\w*\s+режим", cmd) \
            or re.search(r"режим\s+(комбо|обычн|стандартн|смешанн|комбинированн)", cmd) \
            or cmd in {"обычный режим", "комбо", "режим комбо"}:
        return set_mode("combo", config), "combo"

    if re.search(r"(какой|текущий|что\s+за)\s+режим", cmd) \
            or cmd in {"какой режим", "текущий режим"}:
        return f"Сейчас режим: {NAMES.get(current_mode, current_mode)}.", current_mode

    return None, current_mode
```

### `jarvis\packs.py`

```python
"""Загрузка и выгрузка паков команд из папки packs/."""

import json
import logging
import re
from pathlib import Path

log = logging.getLogger("jarvis.packs")

BASE_DIR = Path(__file__).resolve().parent.parent
PACKS_DIR = BASE_DIR / "packs"

# Алиасы имён паков: что говорит пользователь → имя файла
_PACK_ALIASES = {
    "игр": "games", "игры": "games", "игра": "games",
    "играм": "games", "игру": "games", "гейм": "games", "геймс": "games",
    "приложение": "apps", "приложения": "apps", "приложению": "apps",
    "приложений": "apps", "прог": "apps", "проги": "apps", "прогу": "apps",
    "сайт": "sites", "сайты": "sites", "сайтов": "sites", "сайту": "sites",
    "работа": "work", "работы": "work", "работу": "work", "рабочий": "work",
    "система": "system", "системы": "system", "систем": "system",
    "системный": "system", "системные": "system",
}


def normalize_name(name: str) -> str:
    """Приводит «игр» → «games», «приложение» → «apps» и т.п."""
    n = name.strip().lower().rstrip(".,!?")
    return _PACK_ALIASES.get(n, n)


def list_available() -> list[str]:
    if not PACKS_DIR.exists():
        return []
    return sorted(p.stem for p in PACKS_DIR.glob("*.json"))


def load_pack(name: str) -> list | None:
    name = normalize_name(name)
    path = PACKS_DIR / f"{name}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            log.warning("Пак %s — не массив, игнорирую", name)
            return None
        return data
    except Exception:
        log.exception("Не удалось прочитать пак %s", name)
        return None


def load_active(config) -> list:
    active = config.get("active_packs", [])
    result = []
    for name in active:
        pack = load_pack(name)
        if pack:
            result.extend(pack)
            log.info("Пак '%s': загружено %d команд", name, len(pack))
    return result


def save_active(active: list[str], config=None) -> None:
    if config is not None:
        config.set("active_packs", sorted(set(active)))
    else:
        from jarvis import config_manager
        config_manager.update("active_packs", sorted(set(active)))
    log.info("Активные паки сохранены: %s", active)


def handle_pack_command(cmd: str, current_active: list[str], config=None) -> tuple[str | None, list[str]]:
    available = list_available()

    if re.search(r"(какие|список|покажи)\s+пак", cmd) \
            or cmd in {"какие паки", "список паков", "покажи паки"}:
        if not available:
            return "Папка packs пуста.", current_active
        active_str = ", ".join(current_active) if current_active else "нет"
        return f"Доступны: {', '.join(available)}. Активны: {active_str}.", current_active

    m = re.search(r"(загрузи|включи|подключи)\s+пак\s+(\S+)", cmd)
    if m:
        name = normalize_name(m.group(2))
        if name not in available:
            return f"Пак '{name}' не найден. Доступны: {', '.join(available)}.", current_active
        if name in current_active:
            return f"Пак '{name}' уже активен.", current_active
        new_active = current_active + [name]
        save_active(new_active, config)
        return f"Пак '{name}' загружен.", new_active

    if re.search(r"(активируй|загрузи|включи|подключи)\s+все\s+пак", cmd) \
            or cmd in {"активируй все паки", "загрузи все паки", "включи все паки"}:
        if not available:
            return "Папка packs пуста.", current_active
        new_active = sorted(set(current_active + available))
        save_active(new_active, config)
        return f"Активированы все паки: {', '.join(available)}.", new_active

    if re.search(r"(выгрузи|отключи|убери)\s+все\s+пак", cmd) \
            or cmd in {"выгрузи все паки", "отключи все паки"}:
        save_active([], config)
        return "Все паки выгружены.", []

    m = re.search(r"(выгрузи|отключи|убери)\s+пак\s+(\S+)", cmd)
    if m:
        name = normalize_name(m.group(2))
        if name not in current_active:
            return f"Пак '{name}' и так не активен.", current_active
        new_active = [p for p in current_active if p != name]
        save_active(new_active, config)
        return f"Пак '{name}' выгружен.", new_active

    return None, current_active
```

### `jarvis\profile.py`

```python
"""Профиль пользователя — мультипрофиль.

Архитектура:
    profiles/
    ├── default/
    │   ├── profile.json
    │   └── dialog.json
    ├── maksim/
    │   ├── profile.json
    │   └── dialog.json
    └── masha/
        ├── profile.json
        └── dialog.json

Логика:
    - При старте: getpass.getuser() → имя Windows-юзера.
    - Если profiles/<user>/profile.json есть — используется.
    - Если нет — создаётся (с миграцией из старого user_profile.json).
    - «Феникс, я — Маша» → переключает на profiles/masha/.

Запись — через config_manager (единый FileLock, атомарная замена).
"""

import getpass
import json
import logging
import re
import threading
import time
from pathlib import Path

from jarvis import config_manager

log = logging.getLogger("jarvis.profile")

BASE_DIR = Path(__file__).resolve().parent.parent
PROFILES_DIR = BASE_DIR / "profiles"
_OLD_PROFILE = BASE_DIR / "user_profile.json"
_OLD_DIALOG = BASE_DIR / "dialog.json"

# №76: один RLock вместо двух локов. Раньше _current_lock и _listeners_lock
# могли дать гонку: _current менялся, а подписчики читали memory со старым
# профилем. RLock реентерабельный — безопасен для вложенных вызовов.
_lock = threading.RLock()

_current: str | None = None
_listeners: list = []


# ---------------------------------------------------------------
# Служебное
# ---------------------------------------------------------------

def _sanitize(name: str) -> str:
    """Приводит имя к безопасному имени папки."""
    if not name:
        return "default"
    name = name.strip().lower()
    translit = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    name = "".join(translit.get(ch, ch) for ch in name)
    name = re.sub(r"[^a-z0-9_-]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "default"


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _windows_user() -> str:
    """Имя Windows-пользователя. Fallback — default."""
    try:
        return getpass.getuser() or "default"
    except Exception:
        return "default"


# ---------------------------------------------------------------
# Пути
# ---------------------------------------------------------------

def profile_dir() -> Path:
    """Папка текущего профиля. Создаётся при вызове."""
    with _lock:
        cur = current()
    path = PROFILES_DIR / _sanitize(cur)
    _ensure_dir(path)
    return path


def profile_path() -> Path:
    """Путь к profile.json текущего профиля."""
    return profile_dir() / "profile.json"


def dialog_path() -> Path:
    """Путь к dialog.json текущего профиля."""
    return profile_dir() / "dialog.json"


# ---------------------------------------------------------------
# Миграция
# ---------------------------------------------------------------

def _migrate_old() -> None:
    """Переносит старые user_profile.json и dialog.json в profiles/<user>/."""
    if not PROFILES_DIR.exists():
        return
    user_dir = PROFILES_DIR / _sanitize(_windows_user())
    _ensure_dir(user_dir)

    new_profile = user_dir / "profile.json"
    if _OLD_PROFILE.exists() and not new_profile.exists():
        try:
            data = json.loads(_OLD_PROFILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("created_at", time.time())
                config_manager.save(data, path=new_profile)
                log.info("Миграция: %s → %s", _OLD_PROFILE.name, new_profile)
        except Exception:
            log.exception("Не удалось мигрировать старый профиль")

    new_dialog = user_dir / "dialog.json"
    if _OLD_DIALOG.exists() and not new_dialog.exists():
        try:
            data = json.loads(_OLD_DIALOG.read_text(encoding="utf-8"))
            if isinstance(data, list):
                new_dialog.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                log.info("Миграция: %s → %s", _OLD_DIALOG.name, new_dialog)
        except Exception:
            log.exception("Не удалось мигрировать старый диалог")


# ---------------------------------------------------------------
# Текущий профиль
# ---------------------------------------------------------------

def current() -> str:
    """Имя текущего активного профиля (папки)."""
    global _current
    with _lock:
        if _current is None:
            _current = _windows_user()
        return _current


def subscribe(callback) -> None:
    """Регистрирует callback(old_name, new_name) — вызывается при switch()."""
    with _lock:
        if callback in _listeners:
            return
        _listeners.append(callback)


def unsubscribe(callback) -> None:
    """Удаляет подписку."""
    with _lock:
        try:
            _listeners.remove(callback)
        except ValueError:
            pass


def switch(name: str) -> str:
    """Переключает текущий профиль. Создаёт папку, если нет.

    №76: всё под одним _lock. Пока _current меняется и уведомляются
    подписчики — другие потоки не могут читать profile_dir()/memory.
    """
    global _current
    safe = _sanitize(name)

    with _lock:
        old_name = _current or _windows_user()

        user_dir = PROFILES_DIR / safe
        _ensure_dir(user_dir)

        profile_file = user_dir / "profile.json"
        if not profile_file.exists():
            data = {
                "name": name.strip()[:60] or safe,
                "created_at": time.time(),
            }
            config_manager.save(data, path=profile_file)
            log.info("Создан новый профиль: %s", profile_file)
        else:
            # Профиль существует — если name нет, ставим его.
            # Иначе "я — Максим" на старом профиле вернёт старое имя
            # (например, "тест" из стресс-теста).
            try:
                raw = profile_file.read_text(encoding="utf-8")
                if raw.strip():
                    d = json.loads(raw)
                    if not d.get("name"):
                        d["name"] = name.strip()[:60] or safe
                        config_manager.save(d, path=profile_file)
                        log.info("Профиль %s: добавлено name = %r",
                                 safe, d["name"])
            except Exception:
                log.exception("Не удалось проверить name в профиле %s", safe)

        _current = safe

        # human — читаем имя из нового профиля
        human = safe
        try:
            raw = profile_file.read_text(encoding="utf-8")
            if raw.strip():
                d = json.loads(raw)
                human = d.get("name") or safe
        except Exception:
            log.exception("Не удалось прочитать name из нового профиля")

        log.info("Активный профиль: %s (%s → %s)", human, old_name, safe)

        # Уведомляем подписчиков под тем же локом
        listeners = list(_listeners)

    # Вызываем подписчиков ВНЕ лока, но с уже обновлённым _current.
    # Подписчики (IntentHandler._on_profile_switch) перечитывают dialog —
    # к этому моменту _current уже новый.
    for cb in listeners:
        try:
            cb(old_name, safe)
        except Exception:
            log.exception("Подписчик profile упал на switch(%r)", safe)

    return f"Профиль переключён на {human}."


def list_all() -> list[str]:
    """Список доступных профилей (имена папок)."""
    _ensure_dir(PROFILES_DIR)
    return sorted(p.name for p in PROFILES_DIR.iterdir() if p.is_dir())


def delete(name: str) -> bool:
    """Удаляет папку профиля. Активный — нельзя."""
    import shutil
    safe = _sanitize(name)
    with _lock:
        if safe == current():
            log.warning("Нельзя удалить активный профиль: %s", safe)
            return False
    path = PROFILES_DIR / safe
    if not path.exists() or not path.is_dir():
        return False
    try:
        try:
            from send2trash import send2trash
            send2trash(str(path))
            log.info("Профиль перемещён в корзину: %s", safe)
        except ImportError:
            shutil.rmtree(path)
            log.info("Профиль удалён: %s", safe)
        return True
    except Exception:
        log.exception("Не удалось удалить профиль %s", safe)
        return False


# ---------------------------------------------------------------
# Чтение / запись полей профиля
# ---------------------------------------------------------------

def _safe_load() -> dict:
    path = profile_path()
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        log.error("Профиль %s битый — НЕ перезаписываю. Почини вручную.", path)
        raise


def get(key: str, default=None):
    try:
        return _safe_load().get(key, default)
    except json.JSONDecodeError:
        return default


def set(key: str, value) -> bool:
    with _lock:
        try:
            data = _safe_load()
        except json.JSONDecodeError:
            return False
        data[key] = value
        data.setdefault("created_at", time.time())
        ok = config_manager.save(data, path=profile_path())
        if ok:
            log.info("Профиль %s: %s = %r", current(), key, value)
        else:
            log.error("Профиль %s: не удалось сохранить %s", current(), key)
        return ok


def all_data() -> dict:
    try:
        return _safe_load()
    except json.JSONDecodeError:
        return {}


def forget(key: str) -> bool:
    with _lock:
        try:
            data = _safe_load()
        except json.JSONDecodeError:
            return False
        if key not in data:
            return False
        del data[key]
        ok = config_manager.save(data, path=profile_path())
        if ok:
            log.info("Профиль %s: удалено %s", current(), key)
        return ok


# ---------------------------------------------------------------
# Факты
# ---------------------------------------------------------------

def set_fact(key: str, value: str) -> bool:
    facts = get("facts", {}) or {}
    facts[key] = value
    return set("facts", facts)


def get_fact(key: str, default=None):
    facts = get("facts", {}) or {}
    return facts.get(key, default)


def all_facts() -> dict:
    return get("facts", {}) or {}


def forget_fact(key: str) -> bool:
    facts = get("facts", {}) or {}
    if key not in facts:
        return False
    del facts[key]
    return set("facts", facts)


# ---------------------------------------------------------------
# Инициализация при старте
# ---------------------------------------------------------------

def init() -> None:
    """Вызывается при старте Феникса."""
    global _current
    _ensure_dir(PROFILES_DIR)
    with _lock:
        _current = _windows_user()
    _migrate_old()

    user_dir = profile_dir()
    profile_file = user_dir / "profile.json"
    if not profile_file.exists():
        data = {"name": _windows_user(), "created_at": time.time()}
        config_manager.save(data, path=profile_file)
        log.info("Создан профиль по умолчанию: %s", profile_file)
    log.info("Активный профиль: %s (%s)", current(), user_dir.name)
```

### `jarvis\recorder.py`

```python
"""Запись действий: клавиши, клики, паузы."""

import logging
import threading
import time

log = logging.getLogger("jarvis.recorder")

_recording = False
_events = []
_start_time = 0.0
_last_event_time = 0.0
_lock = threading.Lock()

MAX_DURATION_SEC = 60
MIN_WAIT_SEC = 0.05
MAX_WAIT_SEC = 5.0


def is_recording() -> bool:
    return _recording


def start() -> bool:
    global _recording, _events, _start_time, _last_event_time
    try:
        import keyboard
        import mouse
    except ImportError:
        log.error("Библиотеки keyboard/mouse не установлены. pip install keyboard mouse")
        return False

    with _lock:
        if _recording:
            return False
        _events = []
        _recording = True
        _start_time = time.time()
        _last_event_time = _start_time

    try:
        keyboard.hook(_on_key)
        mouse.hook(_on_mouse)
    except Exception:
        log.exception("Не удалось повесить хуки (нужны права администратора)")
        with _lock:
            _recording = False
        return False

    log.info("Запись действий начата")
    return True


def stop() -> dict | None:
    global _recording
    try:
        import keyboard
        import mouse
        keyboard.unhook_all()
        mouse.unhook_all()
    except Exception:
        pass

    with _lock:
        if not _recording:
            return None
        _recording = False
        events = list(_events)

    log.info("Запись действий остановлена: %d событий", len(events))
    return {"events": events, "duration": time.time() - _start_time}


def _add_wait_if_needed():
    global _last_event_time
    now = time.time()
    delta = now - _last_event_time
    if delta >= MIN_WAIT_SEC:
        _events.append({"type": "wait", "seconds": min(delta, MAX_WAIT_SEC)})
    _last_event_time = now


def _check_limits() -> bool:
    if time.time() - _start_time > MAX_DURATION_SEC:
        log.info("Запись остановлена: превышена максимальная длина")
        return False
    return True


def _on_key(event):
    if not _recording or not _check_limits():
        return
    _add_wait_if_needed()
    _events.append({
        "type": "key",
        "name": event.name,
        "event": "down" if event.event_type == "down" else "up",
    })


def _on_mouse(event):
    if not _recording or not _check_limits():
        return
    import mouse
    if isinstance(event, mouse.ButtonEvent):
        _add_wait_if_needed()
        _events.append({
            "type": "click",
            "x": mouse.get_position()[0],
            "y": mouse.get_position()[1],
            "button": event.button,
            "event": "down" if event.event_type == "down" else "up",
        })


def play(macro: dict, speed: float = 1.0) -> bool:
    if not macro or not macro.get("events"):
        return False
    try:
        import keyboard
        import mouse
    except ImportError:
        log.error("Библиотеки keyboard/mouse не установлены")
        return False

    events = macro["events"]
    log.info("Воспроизведение макроса: %d событий", len(events))
    try:
        for ev in events:
            t = ev.get("type")
            if t == "wait":
                time.sleep(float(ev.get("seconds", 0)) / max(speed, 0.1))
            elif t == "key":
                if ev.get("event") == "down":
                    keyboard.press(ev["name"])
                else:
                    keyboard.release(ev["name"])
            elif t == "click":
                mouse.move(ev["x"], ev["y"], absolute=True, duration=0)
                if ev.get("event") == "down":
                    mouse.press(button=ev.get("button", "left"))
                else:
                    mouse.release(button=ev.get("button", "left"))
        return True
    except Exception:
        log.exception("Ошибка воспроизведения макроса")
        return False


def describe(macro: dict) -> str:
    if not macro:
        return "Запись пустая."
    events = macro.get("events", [])
    keys = sum(1 for e in events if e.get("type") == "key" and e.get("event") == "down")
    clicks = sum(1 for e in events if e.get("type") == "click" and e.get("event") == "down")
    duration = macro.get("duration", 0)
    return f"Макрос: {keys} нажатий, {clicks} кликов, длительность {duration:.1f} секунд."
```

### `jarvis\reply.py`

```python
"""Reply — результат IntentHandler.handle().

Ровно одно из двух:
    - text   — готовая строка (озвучить целиком)
    - stream — итератор строк (озвучивать по мере поступления)

Никаких «Reply ведёт себя как строка». Либо text, либо stream.
"""

from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass
class Reply:
    text: Optional[str] = None
    stream: Optional[Iterator[str]] = None

    def __post_init__(self) -> None:
        if (self.text is None) == (self.stream is None):
            raise ValueError("Reply: ровно одно из text/stream должно быть задано")

    @property
    def is_stream(self) -> bool:
        return self.stream is not None
```

### `jarvis\steam.py`

```python
"""Индекс установленных игр Steam: appmanifest -> (название, appid).

Позволяет «запусти сабнатику» для любой игры из библиотеки,
запуск через steam://rungameid/{appid}.
"""

import logging
import re
import winreg
from pathlib import Path

from jarvis.matching import match_score

log = logging.getLogger("jarvis.steam")

# Служебные «игры», которые запускать не надо
_SKIP = ("redistributable", "proton", "steamworks", "steam linux", "runtime")


def _steam_root() -> Path | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            return Path(winreg.QueryValueEx(k, "SteamPath")[0])
    except OSError:
        return None


def scan_steam_games() -> list[tuple[str, str]]:
    """[(название, appid), ...] по всем библиотекам Steam."""
    root = _steam_root()
    if root is None or not root.exists():
        return []
    libs = {root}
    vdf = root / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        for path in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text("utf-8", errors="ignore")):
            libs.add(Path(path.replace("\\\\", "\\")))
    games = []
    for lib in libs:
        for acf in (lib / "steamapps").glob("appmanifest_*.acf"):
            try:
                text = acf.read_text("utf-8", errors="ignore")
            except OSError:
                continue
            appid = re.search(r'"appid"\s+"(\d+)"', text)
            name = re.search(r'"name"\s+"([^"]+)"', text)
            if not appid or not name:
                continue
            title = name.group(1)
            if any(s in title.lower() for s in _SKIP):
                continue
            games.append((title, appid.group(1)))
    log.info("Steam: проиндексировано %d игр", len(games))
    return games


def find_game(games: list[tuple[str, str]], spoken: str,
              threshold: float = 0.72) -> tuple[str, str] | None:
    best, best_score = None, 0.0
    for title, appid in games:
        score = match_score(spoken, title)
        if score > best_score:
            best, best_score = (title, appid), score
    if best and best_score >= threshold:
        log.info("Игра Steam: %r -> %r (score %.2f)", spoken, best[0], best_score)
        return best
    return None
```

### `jarvis\stt.py`

```python
"""Распознавание речи.

Гибрид: Vosk (wake) + Whisper (точная расшифровка).
Barge-in: адаптивная калибровка эха и фона при старте.
Ring buffer: последние 10 фраз (для «что ты слышал»).
"""

import json
import logging
import os
import queue
import time
from collections import deque
from pathlib import Path

import numpy as np
import sounddevice as sd
from vosk import KaldiRecognizer, Model, SetLogLevel

log = logging.getLogger("jarvis.stt")

TURBO_MODEL = "deepdml/faster-whisper-large-v3-turbo-ct2"

WHISPER_PROMPT = (
    "Это русская речь. Пожалуйста, транскрибируй текст на русском языке. "
    "Частые слова: Феникс, открой, закрой, найди, погода, напоминание, "
    "задача, голос, режим, паки, Нижний Новгород, курс доллара."
)

ECHO_WINDOW_SEC = 0.5
BARGE_LOG_INTERVAL = 0.5

# Флаг, чтобы не добавлять пути CUDA в PATH повторно при каждом импорте stt.
_CUDA_DLLS_ADDED = False


def _enable_cuda_dlls():
    """Добавляет пути к CUDA-библиотекам (cuBLAS, cuDNN) в PATH.

    Идемпотентна: повторный вызов ничего не делает.
    """
    global _CUDA_DLLS_ADDED
    if _CUDA_DLLS_ADDED:
        return
    try:
        import nvidia
    except ImportError:
        return
    base = Path(nvidia.__path__[0])
    dirs = [str(p) for p in (base / "cublas" / "bin", base / "cudnn" / "bin") if p.exists()]
    if dirs:
        os.environ["PATH"] = os.pathsep.join(dirs) + os.pathsep + os.environ["PATH"]
        _CUDA_DLLS_ADDED = True


class Listener:
    def __init__(self, model_dir, sample_rate=16000, device=None):
        SetLogLevel(-1)
        self._model = Model(str(model_dir))
        self._rec = KaldiRecognizer(self._model, sample_rate)
        self._sample_rate = sample_rate
        self._device = self.resolve_device(device)
        self.device_name = self._current_device_name()
        self._audio = queue.Queue()
        self._utt_buf = []
        self._utt_len = 0
        self.peak = 0
        self.utterances = 0
        self.current_rms = 0  # текущий уровень сигнала (для GUI)
        
        self.barge_enabled = True
        self.muted = False
        self.barge_flag = False
        self._block_size = 8000

        # Ring buffer последних фраз (для «что ты слышал»)
        self.recent_phrases: deque = deque(maxlen=10)

        # Адаптивный barge-in
        self._echo_window_samples = deque(maxlen=20)
        self._echo_baseline = 0
        self._barge_threshold = 150
        self._barge_speech_ms = 0
        self._speech_active = False
        self._speech_started_at = 0.0
        self._last_barge_log = 0.0
        self._echo_done = False

    def barge_start(self):
        self.barge_flag = False
        self._barge_speech_ms = 0
        self._speech_active = True
        self._speech_started_at = time.time()
        self._echo_done = False
        self._echo_window_samples.clear()
        self._barge_threshold = max(150, int(self._echo_baseline * 1.8))

    def barge_end(self):
        self._speech_active = False
        log.info("Barge-in: стоп (echo=%d, thr=%d, речь=%d мс)",
                 self._echo_baseline, self._barge_threshold, self._barge_speech_ms)

    def _process_barge(self, rms):
        if not self._speech_active or not self.barge_enabled:
            return
        now = time.time()
        elapsed = now - self._speech_started_at

        if elapsed < ECHO_WINDOW_SEC:
            return

        if not self._echo_done:
            self._echo_window_samples.append(rms)
            if elapsed >= ECHO_WINDOW_SEC + 0.5:
                if self._echo_window_samples:
                    arr = sorted(self._echo_window_samples)
                    self._echo_baseline = arr[int(len(arr) * 0.7)]
                self._barge_threshold = max(150, int(self._echo_baseline * 1.8))
                self._echo_done = True
                log.info("Barge-in: калибровка echo=%d, threshold=%d",
                         self._echo_baseline, self._barge_threshold)
            return

        self._echo_window_samples.append(rms)
        if len(self._echo_window_samples) >= 10:
            arr = sorted(self._echo_window_samples)
            new_echo = arr[int(len(arr) * 0.7)]
            self._echo_baseline = int(0.9 * self._echo_baseline + 0.1 * new_echo)
            self._barge_threshold = max(150, int(self._echo_baseline * 1.8))

        if rms > self._barge_threshold:
            self._barge_speech_ms += int(self._block_size / 16)
            if self._barge_speech_ms >= 150:
                self.barge_flag = True
        else:
            self._barge_speech_ms = 0

        if now - self._last_barge_log >= BARGE_LOG_INTERVAL:
            log.info("barge: rms=%d, echo=%d, thr=%d, speech_ms=%d, flag=%s",
                     rms, self._echo_baseline, self._barge_threshold,
                     self._barge_speech_ms, self.barge_flag)
            self._last_barge_log = now

    @staticmethod
    def resolve_device(device):
        if device is None or device == "":
            return None
        if isinstance(device, int):
            return device
        name = str(device).lower()
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0 and name in d["name"].lower():
                return i
        log.warning("Микрофон %r не найден, беру по умолчанию", device)
        return None

    def _current_device_name(self):
        try:
            idx = self._device if self._device is not None else sd.default.device[0]
            return sd.query_devices(idx)["name"]
        except Exception:
            return "по умолчанию"

    def _callback(self, indata, frames, time_info, status):
        if status:
            log.warning("Аудиопоток: %s", status)
        arr = np.frombuffer(indata, dtype=np.int16)
        if arr.size:
            self.peak = max(self.peak, int(np.abs(arr).max()))
            rms = int(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
            self.current_rms = rms
        else:
            rms = 0
            self.current_rms = 0
        self._process_barge(rms)
        if not self.muted:
            self._audio.put(bytes(indata))

    def flush(self):
        """Сброс буфера + контекста Vosk.

        После Reset() прогоняем 0.5 сек тишины — Vosk «забудет»
        незакрытую фразу. Иначе в barge-in просачивается обрывок.
        """
        while not self._audio.empty():
            try:
                self._audio.get_nowait()
            except queue.Empty:
                break
        self._utt_buf.clear()
        self._utt_len = 0
        self._rec.Reset()

        # Прогоняем тишину — сброс контекста
        silence = b"\x00" * 16000  # 0.5 сек при 16 кГц, int16
        try:
            self._rec.AcceptWaveform(silence)
            self._rec.Reset()   # ещё раз — сбросить результат тишины
        except Exception:
            log.exception("Не удалось сбросить контекст Vosk тишиной")
        
    def reset_stats(self):
        """Сбрасывает peak и utterances — для кнопки «Проверить микрофон»."""
        self.peak = 0
        self.utterances = 0
        log.info("Listener: статистика сброшена")

    def phrases(self, stop_event):
        max_buf = self._sample_rate * 2 * 30
        with sd.RawInputStream(
            samplerate=self._sample_rate,
            blocksize=self._block_size,
            dtype="int16",
            channels=1,
            device=self._device,
            callback=self._callback,
        ):
            log.info("Микрофон открыт, слушаю...")
            while not stop_event.is_set():
                try:
                    data = self._audio.get(timeout=0.2)
                except queue.Empty:
                    continue
                self._utt_buf.append(data)
                self._utt_len += len(data)
                while self._utt_len > max_buf and len(self._utt_buf) > 1:
                    self._utt_len -= len(self._utt_buf.pop(0))
                if self._rec.AcceptWaveform(data):
                    text = json.loads(self._rec.Result()).get("text", "").strip()
                    audio = b"".join(self._utt_buf)
                    self._utt_buf.clear()
                    self._utt_len = 0
                    if text:
                        self.utterances += 1
                        self.recent_phrases.append(text)
                        log.info("Распознано (vosk): %s", text)
                        yield text, audio


class WhisperTranscriber:
    def __init__(self, model_name="auto", device="auto"):
        _enable_cuda_dlls()
        import ctranslate2
        from faster_whisper import WhisperModel

        if device == "auto":
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        if device == "cuda":
            name = TURBO_MODEL if model_name == "auto" else model_name
            try:
                log.info("Загрузка Whisper (%s) на GPU...", name)
                self._model = WhisperModel(name, device="cuda", compute_type="int8_float16")
                log.info("Whisper готов (GPU)")
                return
            except Exception:
                log.exception("GPU не завёлся, откатываюсь на CPU")
        name = "small" if model_name == "auto" else model_name
        log.info("Загрузка Whisper (%s) на CPU...", name)
        self._model = WhisperModel(name, device="cpu", compute_type="int8")
        log.info("Whisper готов (CPU)")

    def transcribe(self, pcm, sample_rate=16000):
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if sample_rate != 16000 and len(audio) > 1:
            n = int(len(audio) * 16000 / sample_rate)
            audio = np.interp(
                np.linspace(0, len(audio) - 1, n),
                np.arange(len(audio)), audio
            ).astype(np.float32)
        segments, _ = self._model.transcribe(
            audio, language="ru", beam_size=2, vad_filter=True,
            condition_on_previous_text=False, initial_prompt=WHISPER_PROMPT,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        log.info("Распознано (whisper): %s", text)
        return text
```

### `jarvis\tasks.py`

```python
"""Списки задач.

Голосом:
    «добавь в список купить хлеб»             → добавляет
    «что в списке»                            → перечисляет
    «отметь хлеб выполненным»                 → помечает
    «убери хлеб из списка»                    → удаляет
    «очисти список»                           → удаляет всё

Хранение: tasks.json.
"""

import json
import logging
import re
import threading
from difflib import SequenceMatcher
from pathlib import Path

log = logging.getLogger("jarvis.tasks")

BASE_DIR = Path(__file__).resolve().parent.parent
TASKS_FILE = BASE_DIR / "tasks.json"
_lock = threading.RLock()   # RLock — find() вызывается из-под лока в remove/mark_done


# ---------------------------------------------------------------
# Хранение
# ---------------------------------------------------------------

def _load() -> list:
    if not TASKS_FILE.exists():
        return []
    try:
        data = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        log.exception("Не удалось прочитать tasks.json")
        return []


def _save(tasks: list) -> None:
    try:
        tmp = TASKS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(TASKS_FILE)
    except Exception:
        log.exception("Не удалось сохранить tasks.json")


# ---------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------

def add(text: str) -> dict:
    """Добавляет задачу."""
    with _lock:
        tasks = _load()
        task = {
            "id": (max((t["id"] for t in tasks), default=0) + 1),
            "text": text.strip(),
            "done": False,
            "created_at": __import__("time").time(),
        }
        tasks.append(task)
        _save(tasks)
    log.info("Задача добавлена: %s", task["text"])
    return task


def find(query: str) -> dict | None:
    """Находит задачу по нечёткому совпадению.

    Берёт _lock — вызывается и напрямую, и из remove/mark_done.
    RLock позволяет повторный вход из-под лока.
    """
    with _lock:
        tasks = _load()
        query_low = query.lower().strip()
        if not query_low:
            return None
        # 1. точная подстрока
        for t in tasks:
            if query_low in t["text"].lower():
                return t
        # 2. нечёткое совпадение
        best, best_ratio = None, 0.5
        for t in tasks:
            ratio = SequenceMatcher(None, query_low, t["text"].lower()).ratio()
            if ratio > best_ratio:
                best_ratio, best = ratio, t
        return best


def mark_done(query: str) -> dict | None:
    """Помечает задачу выполненной."""
    with _lock:
        tasks = _load()
        target = find(query)
        if not target:
            return None
        for t in tasks:
            if t["id"] == target["id"]:
                t["done"] = True
                _save(tasks)
                return t
    return None


def remove(query: str) -> dict | None:
    """Удаляет задачу."""
    with _lock:
        tasks = _load()
        target = find(query)
        if not target:
            return None
        tasks = [t for t in tasks if t["id"] != target["id"]]
        _save(tasks)
    return target


def clear_all() -> int:
    """Удаляет все задачи. Возвращает количество."""
    with _lock:
        tasks = _load()
        count = len(tasks)
        _save([])
    return count


# ---------------------------------------------------------------
# Озвучка
# ---------------------------------------------------------------

def format_list(tasks: list | None = None) -> str:
    """Человекочитаемый список для озвучки."""
    if tasks is None:
        tasks = _load()
    if not tasks:
        return "Список пуст."

    active = [t for t in tasks if not t.get("done")]
    done = [t for t in tasks if t.get("done")]

    parts = []
    if active:
        items = ", ".join(t["text"] for t in active[:15])
        parts.append(f"Активные: {items}")
    if done:
        items = ", ".join(t["text"] for t in done[:5])
        parts.append(f"Выполнено: {items}")
    return ". ".join(parts) + "."


# ---------------------------------------------------------------
# Обработка команд
# ---------------------------------------------------------------

def _extract_text(cmd: str, verb: str) -> str:
    """Вырезает текст задачи после глагола."""
    # убираем «в список», «из списка», «задачу» и т.п.
    text = re.sub(rf"^{verb}\s+", "", cmd, count=1)
    text = re.sub(r"^(в\s+список|в\s+задачи|задачу|задачу\s+в\s+список)\s*", "", text)
    text = re.sub(r"^(из\s+списка|из\s+задач|задачу)\s*", "", text)
    return text.strip(" ,.:!?")


def handle_task_command(cmd: str) -> str | None:
    """Разбирает команды списка задач. Возвращает ответ или None."""

    # показать список
    if re.search(r"(что|что\s+там)\s+в\s+списке", cmd) \
            or cmd in {"что в списке", "покажи список", "список задач", "мои задачи"}:
        return format_list()

    # очистить
    if re.search(r"(очисти|удали)\s+(весь\s+)?список", cmd) \
            or cmd in {"очисти список", "удали все задачи"}:
        n = clear_all()
        return f"Очищено задач: {n}." if n else "Список и так пуст."

    # отметить выполненным
    m = re.match(r"^(?:отметь|помечу|пометь|сделано|выполнено|готово)\s+(.+)$", cmd)
    if m:
        query = m.group(1).strip()
        query = re.sub(r"\s+(выполненным|сделанным|готовым)$", "", query)
        query = re.sub(r"^(задачу|задачу\s+)?", "", query)
        task = mark_done(query)
        if task:
            return f"Отметил: {task['text']}."
        return f"Задачу «{query}» не нашёл."

    # удалить одну
    m = re.match(r"^(?:убери|удали)\s+(?:из\s+списка\s+)?(.+)$", cmd)
    if m:
        query = m.group(1).strip()
        task = remove(query)
        if task:
            return f"Убрал: {task['text']}."
        return f"Задачу «{query}» не нашёл."

    # добавить
    m = re.match(r"^(?:добавь|запиши|внеси)\s+(?:в\s+список\s+|в\s+задачи\s+)?(.+)$", cmd)
    if m:
        text = m.group(1).strip(" ,.:!?")
        if not text:
            return "Что добавить?"
        task = add(text)
        return f"Добавил: {task['text']}."

    return None
```

### `jarvis\timers.py`

```python
"""Таймеры и напоминания.

Голосом:
    «напомни через 10 минут выпить чай»      → через 10 минут скажет голосом
    «напомни в 18:30 позвонить маме»          → скажет в указанное время
    «напомни через полчаса»                   → без текста
    «какие напоминания»                       → список
    «отмени все напоминания»                  → очистка
    «таймер на 5 минут»                       → обратный отсчёт

Хранение: timers.json (сохраняется на диск).
При старте Феникса: загружает, проверяет, ставит threading.Timer на каждое.
"""

import datetime
import json
import logging
import re
import threading
import time
from pathlib import Path

log = logging.getLogger("jarvis.timers")

BASE_DIR = Path(__file__).resolve().parent.parent
TIMERS_FILE = BASE_DIR / "timers.json"

_lock = threading.Lock()
_scheduled: dict[int, threading.Timer] = {}  # id → Timer
_next_id = 1
_on_fire_callback = None  # функция, которая вызывается при срабатывании


# ---------------------------------------------------------------
# Хранение
# ---------------------------------------------------------------

def _load() -> list:
    if not TIMERS_FILE.exists():
        return []
    try:
        data = json.loads(TIMERS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        log.exception("Не удалось прочитать timers.json")
        return []


def _save(timers: list) -> None:
    try:
        tmp = TIMERS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(timers, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(TIMERS_FILE)
    except Exception:
        log.exception("Не удалось сохранить timers.json")


# ---------------------------------------------------------------
# Разбор времени из фразы
# ---------------------------------------------------------------

_NUM_WORDS = {
    "один": 1, "одну": 1, "одна": 1, "два": 2, "две": 2, "три": 3, "четыре": 4,
    "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10,
    "пятнадцать": 15, "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50,
    "полтора": 1.5,
}


def _parse_duration(text: str) -> int | None:
    """«через 10 минут» → 600 секунд. Возвращает int или None."""
    # «через X единица»
    m = re.search(r"через\s+(\d+|[а-яё]+)\s*(секунд|мин|минут|час|часов|ч|с|м)?", text)
    if not m:
        # «на X минут» / «таймер на X»
        m = re.search(r"(?:на|таймер)\s+(\d+|[а-яё]+)\s*(секунд|мин|минут|час|часов|ч|с|м)",
                      text)
    if not m:
        # «полчаса», «час», «минуту»
        if "полчаса" in text or "пол часа" in text:
            return 30 * 60
        if re.search(r"\bчас\b", text):
            return 60 * 60
        if re.search(r"\bминуту\b", text):
            return 60
        return None

    raw = m.group(1)
    unit = m.group(2) or "мин"

    # число
    if raw.isdigit():
        num = int(raw)
    else:
        num = _NUM_WORDS.get(raw.lower())
        if num is None:
            return None

    # единица
    if unit.startswith("сек") or unit == "с":
        return int(num)
    if unit.startswith("мин") or unit == "м":
        return int(num * 60)
    if unit.startswith("час") or unit == "ч":
        return int(num * 3600)
    return int(num * 60)


def _parse_absolute_time(text: str) -> float | None:
    """«в 18:30» → timestamp. Возвращает float (unix) или None."""
    m = re.search(r"\bв\s+(\d{1,2})[:.](\d{2})", text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"\bв\s+(\d{1,2})\s+час", text)
        if not m:
            return None
        hour, minute = int(m.group(1)), 0

    if not (0 <= hour < 24 and 0 <= minute < 60):
        return None

    now = datetime.datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        # время уже прошло — значит, на завтра
        target += datetime.timedelta(days=1)
    return target.timestamp()


def _extract_reminder_text(cmd: str) -> str:
    """Вырезает из фразы текст напоминания (после времени)."""
    # убираем всё до времени (включительно)
    text = re.sub(r"^.*?(?:напомни|напоминание|таймер)\s*", "", cmd, count=1)
    text = re.sub(r"через\s+(\d+|[а-яё]+)\s*\S+", "", text, count=1)
    text = re.sub(r"\bв\s+\d{1,2}[:.]\d{2}", "", text, count=1)
    text = re.sub(r"\bв\s+\d{1,2}\s+час\w*", "", text, count=1)
    text = text.strip(" ,.:!?")
    return text


# ---------------------------------------------------------------
# Планирование
# ---------------------------------------------------------------

def set_on_fire(callback) -> None:
    """Регистрирует callback(timer_dict) — вызывается при срабатывании."""
    global _on_fire_callback
    _on_fire_callback = callback


def _fire(timer_id: int) -> None:
    """Срабатывание таймера."""
    with _lock:
        timers = _load()
        timer = next((t for t in timers if t["id"] == timer_id), None)
        if not timer:
            _scheduled.pop(timer_id, None)
            return
        # удаляем из файла
        timers = [t for t in timers if t["id"] != timer_id]
        _save(timers)
        _scheduled.pop(timer_id, None)

    log.info("Таймер #%d сработал: %s", timer_id, timer.get("text") or "(без текста)")
    if _on_fire_callback:
        try:
            _on_fire_callback(timer)
        except Exception:
            log.exception("Ошибка в callback таймера")


def _schedule_one(timer: dict) -> None:
    """Ставит threading.Timer на конкретное напоминание."""
    delay = timer["fire_at"] - time.time()
    if delay <= 0:
        # уже прошло — срабатываем сразу
        delay = 0.1
    t = threading.Timer(delay, _fire, args=(timer["id"],))
    t.daemon = True
    t.start()
    _scheduled[timer["id"]] = t


def _next_id(timers: list) -> int:
    if not timers:
        return 1
    return max(t["id"] for t in timers) + 1


def add(text: str, fire_at: float) -> dict:
    """Добавляет напоминание. Возвращает dict таймера."""
    global _next_id
    with _lock:
        timers = _load()
        tid = _next_id(timers)
        timer = {
            "id": tid,
            "text": text.strip(),
            "fire_at": float(fire_at),
            "created_at": time.time(),
        }
        timers.append(timer)
        _save(timers)
    _schedule_one(timer)
    return timer


def remove_all() -> int:
    """Отменяет все напоминания. Возвращает количество."""
    with _lock:
        timers = _load()
        count = len(timers)
        for t in _scheduled.values():
            t.cancel()
        _scheduled.clear()
        _save([])
    return count


def list_all() -> list:
    """Возвращает список активных напоминаний."""
    return _load()


def format_list(timers: list) -> str:
    """Человекочитаемый список для озвучки."""
    if not timers:
        return "Напоминаний нет."
    now = time.time()
    parts = []
    for t in timers[:10]:
        left = int(t["fire_at"] - now)
        if left < 0:
            left = 0
        m, s = divmod(left, 60)
        h, m = divmod(m, 60)
        if h:
            when = f"через {h} ч {m} мин"
        elif m:
            when = f"через {m} мин"
        else:
            when = f"через {s} сек"
        text = t.get("text") or "без текста"
        parts.append(f"{when} — {text}")
    return "Напоминания: " + "; ".join(parts) + "."


def restore_all() -> int:
    """Восстанавливает таймеры при старте. Возвращает количество."""
    timers = _load()
    for t in timers:
        _schedule_one(t)
    if timers:
        log.info("Восстановлено напоминаний: %d", len(timers))
    return len(timers)


# ---------------------------------------------------------------
# Обработка команд
# ---------------------------------------------------------------

def handle_timer_command(cmd: str) -> str | None:
    """Разбирает команды таймеров. Возвращает ответ или None."""
    # список
    if re.search(r"(какие|список|покажи)\s*(напоминани|таймер)", cmd) \
            or cmd in {"какие напоминания", "список напоминаний", "мои напоминания"}:
        return format_list(list_all())

    # отмена
    if re.search(r"(отмени|удали|очисти|сбрось)\s*(все\s+)?(напоминани|таймер)", cmd) \
            or cmd in {"отмени все напоминания", "удали все напоминания"}:
        n = remove_all()
        return f"Отменено напоминаний: {n}." if n else "Напоминаний не было."

    # добавить напоминание
    if re.search(r"(напомни|напоминание|таймер|напоминай)", cmd):
        # абсолютное время
        abs_ts = _parse_absolute_time(cmd)
        if abs_ts:
            text = _extract_reminder_text(cmd)
            t = add(text, abs_ts)
            when = datetime.datetime.fromtimestamp(abs_ts).strftime("%H:%M")
            if text:
                return f"Напомню в {when}: {text}."
            return f"Напомню в {when}."

        # относительное время
        dur = _parse_duration(cmd)
        if dur and dur > 0:
            text = _extract_reminder_text(cmd)
            fire_at = time.time() + dur
            t = add(text, fire_at)
            # озвучка длительности
            if dur >= 3600:
                h = dur // 3600
                m = (dur % 3600) // 60
                when = f"через {h} ч {m} мин" if m else f"через {h} ч"
            elif dur >= 60:
                m = dur // 60
                when = f"через {m} мин"
            else:
                when = f"через {dur} сек"
            if text:
                return f"Хорошо, напомню {when}: {text}."
            return f"Хорошо, напомню {when}."

    return None
```

### `jarvis\tray.py`

```python
"""Иконка в системном трее (pystray)."""

import logging
import os

import pystray
from PIL import Image, ImageDraw

from jarvis import APP_NAME, __version__, actions

log = logging.getLogger("jarvis.tray")


def _make_icon_image() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, 62, 62), fill=(18, 32, 58, 255), outline=(86, 156, 255, 255), width=3)
    # стилизованная «J»
    d.line((38, 16, 38, 42), fill=(86, 156, 255, 255), width=6)
    d.arc((20, 30, 42, 52), start=20, end=180, fill=(86, 156, 255, 255), width=6)
    return img


def build_tray(jarvis) -> pystray.Icon:
    def on_toggle(icon, item):
        jarvis.listening_enabled = not jarvis.listening_enabled
        log.info("Прослушивание: %s", jarvis.listening_enabled)

    def on_screenshot(icon, item):
        actions.take_screenshot()

    def on_show_window(icon, item):
        """Показать окно GUI (для launch_mode=tray)."""
        if getattr(jarvis, "gui", None) is not None:
            jarvis.gui.show_window()
        else:
            log.warning("GUI не запущен — окно показать нельзя")

    def on_open_settings(icon, item):
        """Открыть GUI и переключиться на вкладку «Настройки»."""
        if getattr(jarvis, "gui", None) is not None:
            jarvis.gui.show_window()
            jarvis.gui.open_settings_tab()
        else:
            log.warning("GUI не запущен — настройки открыть нельзя")

    def on_config(icon, item):
        os.startfile(jarvis.base_dir / "config.json")

    def on_log(icon, item):
        os.startfile(jarvis.base_dir / "logs" / "jarvis.log")

    def on_exit(icon, item):
        jarvis.shutdown()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(f"{APP_NAME} v{__version__}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        # default=True — двойной клик по иконке открывает окно
        pystray.MenuItem("Открыть окно", on_show_window, default=True),
        pystray.MenuItem("Настройки", on_open_settings),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Слушать микрофон", on_toggle,
                         checked=lambda item: jarvis.listening_enabled),
        pystray.MenuItem("Сделать скриншот", on_screenshot),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Открыть конфиг", on_config),
        pystray.MenuItem("Открыть журнал", on_log),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Выход", on_exit),
    )
    return pystray.Icon("jarvis", _make_icon_image(), f"{APP_NAME} v{__version__}", menu)
```

### `jarvis\tts.py`

```python
"""Синтез речи.

Бэкенды: xtts / piper / winrt / sapi.
Смена голоса на лету: через Config.subscribe — main.py вызывает speaker.set_voice().
Streaming: speak_stream(iterator) — озвучивает по предложениям.
Barge-in: воспроизведение через sounddevice с проверкой per-call токена —
реально прерывает звук.
Предобработка текста: _prepare_text() — CJK, единицы, числа.

Фикс гонки: вместо одного _stop_flag — per-call stop-token. Каждый
play_async / speak_stream создаёт свой threading.Event, stop() взводит
ТОЛЬКО текущий. Старый поток проверяет свой токен, который новый
поток не сбрасывает. Иначе 2-3 голоса одновременно.

wait_end: возвращает bool (успел ли поток завершиться). play_async
проверяет результат — если старый поток не завершился, новый не
запускается (иначе наложение TTS).
"""

import asyncio
import io
import logging
import os
import re
import threading
import time
import wave
from pathlib import Path

log = logging.getLogger("jarvis.tts")

PIPER_REPO = "rhasspy/piper-voices"
BASE_DIR = Path(__file__).resolve().parent.parent

_SENTENCE_END = re.compile(r"[.!?…]+\s+")


# ---------------------------------------------------------------
# Предобработка текста
# ---------------------------------------------------------------

_REPLACEMENTS = [
    (r"\bм/с\b", " метров в секунду"),
    (r"\bкм/ч\b", " километров в час"),
    (r"\bкм/с\b", " километров в секунду"),
    (r"\bм/c\b", " метров в секунду"),
    (r"\bкм/ч\.", " километров в час"),
    (r"([+-]?\d+)\s*°\s*[CFЦ]?\b", r"\1 градусов"),
    (r"°\s*[CFЦ]?\b", " градусов"),
    (r"(\d+)\s*%", r"\1 процентов"),
    (r"\bт\.\s*д\.", " так далее"),
    (r"\bт\.\s*е\.", " то есть"),
    (r"\bт\.\s*к\.", " так как"),
    (r"\bт\.\s*п\.", " тому подобное"),
    (r"\bдр\.", " другие"),
    (r"\bг\.", " год"),
    (r"\bгг\.", " годы"),
    (r"\bруб\.", " рублей"),
    (r"\bкоп\.", " копеек"),
    (r"\bтыс\.", " тысяч"),
    (r"\bмлн\.", " миллионов"),
    (r"\bмлрд\.", " миллиардов"),
    (r"\b(\d+)\s*см\b", r"\1 сантиметров"),
    (r"\b(\d+)\s*мм\b", r"\1 миллиметров"),
    (r"\b(\d+)\s*км\b", r"\1 километров"),
    (r"\b(\d+)\s*кг\b", r"\1 килограммов"),
    (r"\b(\d+)\s*мг\b", r"\1 миллиграммов"),
    (r"\b(\d+)\s*МБ\b", r"\1 мегабайт"),
    (r"\b(\d+)\s*ГБ\b", r"\1 гигабайт"),
    (r"\b(\d+)\s*КБ\b", r"\1 килобайт"),
    (r"\b(\d+)\s*м\b", r"\1 метров"),
    (r"\b(\d+)\s*г\b", r"\1 граммов"),
    (r"→", " стремится к "),
    (r"←", " из "),
    (r"≈", " примерно "),
    (r"≥", " больше или равно "),
    (r"≤", " меньше или равно "),
    (r"≠", " не равно "),
    (r"&", " и "),
    (r"\+", " плюс "),
    (r"(?<!\w)-(?!\w)", " минус "),
    (r"\*+", ""),
    (r"_+", ""),
    (r"#+\s*", ""),
    (r"`+", ""),
    (r"^\s*[-•]\s+", ""),
]

_RE_COMPILED = [(re.compile(pat), repl) for pat, repl in _REPLACEMENTS]

_CJK_RE = re.compile(
    r"[\u4e00-\u9fff"
    r"\u3040-\u309f"
    r"\u30a0-\u30ff"
    r"\uac00-\ud7af"
    r"\u3000-\u303f"
    r"\uff00-\uffef]+"
)


def _prepare_text(text: str) -> str:
    if not text:
        return text
    text = _CJK_RE.sub(" ", text)
    for pattern, repl in _RE_COMPILED:
        text = pattern.sub(repl, text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    return text


class Speaker:
    def __init__(self, config):
        self._config = config
        cfg = config if hasattr(config, "get") else {}
        self.rate = float(cfg.get("voice_rate", 1.15))
        self.voice = cfg.get("tts_voice", "ruslan")
        self._voice_hint = cfg.get("voice", "Pavel")
        self._mode = None
        self._engine = None
        self._piper = None
        self._piper_cfg = None
        self._piper_quality = "medium"

        # Глобальное состояние воспроизведения
        self._play_thread = None
        self._playing = False
        self._play_lock = threading.Lock()

        # Per-call stop-token
        self._current_token: threading.Event = threading.Event()
        self._token_lock = threading.Lock()

        backend = cfg.get("tts_backend", "auto")
        ref = BASE_DIR / cfg.get("xtts_ref", "voices/jarvis.wav")
        if backend in ("auto", "xtts"):
            if ref.exists():
                try:
                    self._init_xtts(ref)
                except Exception:
                    log.exception("XTTS не завёлся, переключаюсь на piper")
            elif backend == "xtts":
                log.warning("Референс голоса не найден: %s", ref)
        if self._mode is None and backend in ("auto", "xtts", "piper"):
            try:
                self._init_piper(self.voice)
            except Exception:
                log.exception("Piper не завёлся, переключаюсь на WinRT")
        if self._mode is None:
            try:
                from winrt.windows.media.speechsynthesis import SpeechSynthesizer  # noqa: F401
                self._mode = "winrt"
                log.info("TTS: WinRT, голос %r, скорость %.2f", self._voice_hint, self.rate)
            except Exception:
                log.exception("WinRT недоступен, переключаюсь на SAPI")
                self._init_sapi()

    # --- сеттеры для Config.subscribe ------------------------------------

    def set_voice(self, voice: str) -> None:
        if voice == self.voice:
            return
        log.info("Голос изменился: %s → %s", self.voice, voice)
        self.voice = voice
        if self._mode == "piper":
            try:
                self._init_piper(voice)
            except Exception:
                log.exception("Не удалось переключить Piper на %s", voice)

    def set_rate(self, rate: float) -> None:
        self.rate = float(rate)
        if self._piper_cfg is not None:
            try:
                from piper import SynthesisConfig
                self._piper_cfg = SynthesisConfig(length_scale=round(1.0 / self.rate, 2))
            except Exception:
                pass

    # --- per-call stop-token ---------------------------------------------

    def _new_token(self) -> threading.Event:
        """Создаёт новый stop-token и делает его текущим.

        ВАЖНО: старый токен НЕ сбрасывается — старый поток продолжит
        видеть его взведённым и завершится корректно.
        """
        with self._token_lock:
            self._current_token = threading.Event()
            return self._current_token

    def _current_stop(self) -> threading.Event:
        with self._token_lock:
            return self._current_token

    # --- воспроизведение через sounddevice (для barge-in) ----------------

    def _play_wav(self, wav_bytes: bytes, token: threading.Event) -> None:
        """Играет WAV-байты чанками, проверяя per-call token."""
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError:
            log.warning(
                "sounddevice/numpy недоступны — играю через winsound. "
                "Barge-in НЕ БУДЕТ РАБОТАТЬ. Установи: pip install sounddevice numpy"
            )
            import winsound
            winsound.PlaySound(wav_bytes, winsound.SND_MEMORY)
            return

        with wave.open(io.BytesIO(wav_bytes)) as wf:
            rate = wf.getframerate()
            channels = wf.getnchannels()
            width = wf.getsampwidth()

        dtype = {1: "int8", 2: "int16", 4: "int32"}.get(width)
        if dtype is None:
            log.warning("Неподдерживаемая ширина сэмпла: %d", width)
            return

        with wave.open(io.BytesIO(wav_bytes)) as wf:
            frames = wf.readframes(wf.getnframes())
        audio = np.frombuffer(frames, dtype=dtype)
        if channels > 1:
            audio = audio.reshape(-1, channels)

        chunk = int(rate * 0.05)
        try:
            with sd.OutputStream(samplerate=rate, channels=channels, dtype=dtype) as stream:
                for i in range(0, len(audio), chunk):
                    if token.is_set():
                        log.info("TTS: воспроизведение прервано (token)")
                        break
                    stream.write(audio[i:i + chunk])
        except Exception:
            log.exception("sounddevice.OutputStream не завёлся — падаю на winsound")
            import winsound
            winsound.PlaySound(wav_bytes, winsound.SND_MEMORY)

    # --- xtts / piper / sapi / winrt --------------------------------------

    def _init_xtts(self, ref: Path) -> None:
        os.environ.setdefault("COQUI_TOS_AGREED", "1")
        import torch
        from TTS.api import TTS as CoquiTTS

        device = "cuda" if torch.cuda.is_available() else "cpu"
        log.info("Загрузка XTTS-v2 на %s...", device)
        self._xtts = CoquiTTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
        self._xtts_ref = str(ref)
        self._mode = "xtts"
        log.info("TTS: XTTS-v2, клон голоса из %s", ref.name)

    def _speak_xtts(self, text: str, token: threading.Event) -> None:
        import numpy as np
        if token.is_set():
            return
        samples = self._xtts.tts(text=text, speaker_wav=self._xtts_ref,
                                 language="ru", speed=self.rate)
        if token.is_set():
            return
        pcm = (np.clip(np.asarray(samples), -1, 1) * 32767).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(pcm.tobytes())
        self._play_wav(buf.getvalue(), token)

    def _init_piper(self, voice: str) -> None:
        from huggingface_hub import hf_hub_download
        from piper import PiperVoice, SynthesisConfig

        cfg = self._config if hasattr(self, "_config") else {}
        quality = "medium"
        if hasattr(cfg, "get"):
            quality = cfg.get("tts_voice_quality", "medium")
        if quality not in ("medium", "high"):
            quality = "medium"

        rel = f"ru/ru_RU/{voice}/{quality}/ru_RU-{voice}-{quality}.onnx"

        try:
            onnx = hf_hub_download(PIPER_REPO, rel)
            hf_hub_download(PIPER_REPO, rel + ".json")
            log.info("TTS: piper, голос %s/%s", voice, quality)
        except Exception:
            log.warning("Голос %s/%s не найден, откат на medium", voice, quality)
            quality = "medium"
            rel = f"ru/ru_RU/{voice}/medium/ru_RU-{voice}-medium.onnx"
            onnx = hf_hub_download(PIPER_REPO, rel)
            hf_hub_download(PIPER_REPO, rel + ".json")

        self._piper = PiperVoice.load(onnx)
        self._piper_cfg = SynthesisConfig(length_scale=round(1.0 / self.rate, 2))
        self._mode = "piper"
        self._piper_quality = quality
        log.info("TTS: piper, голос %s/%s, скорость %.2f", voice, quality, self.rate)

    def _speak_piper(self, text: str, token: threading.Event) -> None:
        if token.is_set():
            return
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            self._piper.synthesize_wav(text, wf, self._piper_cfg)
        if token.is_set():
            return
        self._play_wav(buf.getvalue(), token)

    def _init_sapi(self) -> None:
        import pyttsx3
        self._engine = pyttsx3.init()
        for v in self._engine.getProperty("voices"):
            ident = f"{v.id} {v.name}".lower()
            if self._voice_hint.lower() in ident or "ru" in ident or "irina" in ident:
                self._engine.setProperty("voice", v.id)
                log.info("TTS: SAPI, голос %s", v.name)
                break
        self._mode = "sapi"

    async def _synthesize(self, text: str) -> bytes:
        from winrt.windows.media.speechsynthesis import SpeechSynthesizer
        from winrt.windows.storage.streams import DataReader

        synth = SpeechSynthesizer()
        voices = list(SpeechSynthesizer.all_voices)
        voice = next(
            (v for v in voices if self._voice_hint.lower() in v.display_name.lower()),
            None,
        ) or next((v for v in voices if v.language.lower().startswith("ru")), None)
        if voice is not None:
            synth.voice = voice
        try:
            synth.options.speaking_rate = self.rate
        except Exception:
            pass
        stream = await synth.synthesize_text_to_stream_async(text)
        reader = DataReader(stream.get_input_stream_at(0))
        await reader.load_async(stream.size)
        return bytes(reader.read_buffer(stream.size))

    def _speak_one(self, text: str, token: threading.Event) -> None:
        text = _prepare_text(text)
        if not text or token.is_set():
            return
        log.info("Говорю: %s", text)
        try:
            if self._mode == "xtts":
                self._speak_xtts(text, token)
            elif self._mode == "piper":
                self._speak_piper(text, token)
            elif self._mode == "winrt":
                wav = asyncio.run(self._synthesize(text))
                if token.is_set():
                    return
                self._play_wav(wav, token)
            else:
                if token.is_set():
                    return
                self._engine.say(text)
                self._engine.runAndWait()
        except Exception:
            log.exception("Ошибка синтеза речи")

    def speak(self, text: str) -> None:
        """Синхронная озвучка (для тестов)."""
        if not text:
            return
        token = self._new_token()
        self._speak_one(text, token)

    def play_async(self, text: str) -> None:
        """Асинхронная озвучка одного текста.

        №74: если старый поток не завершился за timeout — НЕ запускаем
        новый (иначе наложение TTS). Логируем и выходим.
        """
        self.stop()

        # Ждём завершения старого потока. Если не успел — не запускаем новый.
        finished = self.wait_end(timeout=2.0)
        if not finished:
            log.warning(
                "TTS: старый поток не завершился за 2 сек — пропускаю новый вызов "
                "(иначе наложение)"
            )
            return

        token = self._new_token()

        with self._play_lock:
            self._playing = True

        def _run():
            try:
                self._speak_one(text, token)
            finally:
                with self._play_lock:
                    self._playing = False

        self._play_thread = threading.Thread(target=_run, daemon=True, name="tts-play")
        self._play_thread.start()

    def stop(self) -> None:
        """Взводит ТЕКУЩИЙ токен. Старые токены не трогает."""
        with self._token_lock:
            token = self._current_token
        if not token.is_set():
            log.info("TTS: прерывание (stop)")
        token.set()

    def is_playing(self) -> bool:
        with self._play_lock:
            return self._playing and self._play_thread is not None and self._play_thread.is_alive()

    def wait_end(self, timeout: float = 30.0) -> bool:
        """Ждёт завершения текущего TTS-потока.

        №72: возвращает bool — успел ли поток завершиться.
        _playing = False ставится ТОЛЬКО если поток реально завершился.
        Иначе is_playing() начнёт врать.
        """
        with self._play_lock:
            thread = self._play_thread
        if thread is None:
            return True
        thread.join(timeout=timeout)
        finished = not thread.is_alive()
        if finished:
            with self._play_lock:
                self._playing = False
        else:
            log.warning("TTS: поток не завершился за %.1f сек (timeout)", timeout)
        return finished

    def speak_stream(self, text_iter, timeout: float = 30.0) -> str:
        """Streaming TTS. Разбивает текст по предложениям и озвучивает по мере поступления.

        №93: append чанка в full_text_parts ДО проверки токена —
        иначе последний прочитанный чанк теряется.
        """
        self.stop()
        self.wait_end(timeout=1.0)

        token = self._new_token()

        with self._play_lock:
            self._playing = True

        buffer = ""
        full_text_parts = []
        pending = []

        def _flush_sentences(force: bool = False):
            nonlocal buffer
            while True:
                m = _SENTENCE_END.search(buffer)
                if not m:
                    break
                sentence = buffer[:m.end()].strip()
                buffer = buffer[m.end():]
                if sentence:
                    pending.append(sentence)
            if force and buffer.strip():
                pending.append(buffer.strip())
                buffer = ""

        try:
            for chunk in text_iter:
                # №93: append ДО проверки токена — иначе при barge-in
                # последний чанк теряется.
                if chunk:
                    full_text_parts.append(chunk)
                    buffer += chunk
                if token.is_set():
                    log.info("TTS: стриминг прерван")
                    break
                _flush_sentences()
                while pending and not token.is_set():
                    sentence = pending.pop(0)
                    self._speak_one(sentence, token)
            if not token.is_set():
                _flush_sentences(force=True)
                while pending and not token.is_set():
                    sentence = pending.pop(0)
                    self._speak_one(sentence, token)
        except Exception:
            log.exception("Ошибка в speak_stream")
        finally:
            with self._play_lock:
                self._playing = False

        return "".join(full_text_parts).strip()
```

### `jarvis\voices.py`

```python
"""Управление голосами Piper: ruslan, dmitri, irina, denis."""

import logging
import re

from jarvis import config_manager

log = logging.getLogger("jarvis.voices")

PIPER_VOICES = {
    "ruslan": "Руслан — мужской, спокойный",
    "dmitri": "Дмитрий — мужской, ниже и медленнее",
    "irina":  "Ирина — женский",
    "denis":  "Денис — мужской, дикторский",
}

ALIASES = {
    "руслан": "ruslan", "руслана": "ruslan",
    "дмитрий": "dmitri", "дмитрия": "dmitri",
    "дима": "dmitri", "диму": "dmitri",
    "ирина": "irina", "ирину": "irina",
    "ира": "irina", "иру": "irina",
    "денис": "denis", "дениса": "denis",
}


def current_voice(config=None) -> str:
    if config is not None:
        return config.get("tts_voice", "ruslan")
    return config_manager.load().get("tts_voice", "ruslan")


def switch(voice: str, config=None) -> str:
    if voice not in PIPER_VOICES:
        return f"Голос '{voice}' не знаю. Доступны: {', '.join(PIPER_VOICES)}."
    if config is not None:
        config.set("tts_voice", voice)
    else:
        config_manager.update("tts_voice", voice)
    log.info("Голос переключён на %s", voice)
    return f"Голос переключён на {voice.capitalize()}."


def handle_voice_command(cmd: str, config=None) -> str | None:
    if re.search(r"(какой|текущий|что\s+за)\s+голос", cmd) \
            or cmd in {"какой голос", "текущий голос"}:
        return f"Сейчас голос: {current_voice(config).capitalize()}."

    if re.search(r"(список|какие|покажи|доступные)\s+голос", cmd) \
            or cmd in {"список голосов", "какие голоса", "покажи голоса"}:
        return f"Доступные голоса: {', '.join(PIPER_VOICES.keys())}."

    m = re.search(r"(?:смени|поменяй|переключи|включи|поставь)\s+голос\s+(?:на\s+)?(\S+)", cmd)
    if m:
        name = m.group(1).strip().rstrip(".,!?").lower()
        key = ALIASES.get(name, name)
        if key in PIPER_VOICES:
            return switch(key, config)
        return f"Голос '{name}' не знаю. Доступны: {', '.join(PIPER_VOICES)}."

    m = re.match(r"^голос\s+(\S+)$", cmd)
    if m:
        name = m.group(1).strip().rstrip(".,!?").lower()
        key = ALIASES.get(name, name)
        if key in PIPER_VOICES:
            return switch(key, config)
        return f"Голос '{name}' не знаю."

    return None
```

### `jarvis\weather.py`

```python
"""Погода и курс валют.

Источники:
    - open-meteo.com (погода, без ключа)
    - cbr-xml-daily.ru (курс ЦБ РФ, без ключа)

Кэш: 10 минут на город / на курс.

ВАЖНО: нормализация города и валюты (падежи, синонимы, ISO-коды) — задача LLM.
Этот модуль ожидает уже нормализованные данные.
"""

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from typing import Optional

log = logging.getLogger("jarvis.weather")

# Кэш: {(тип, ключ): (timestamp, data)}
_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()

# TTL по умолчанию, если Config недоступен.
_DEFAULT_TTL = 600  # 10 минут

# Ссылка на Config — устанавливается через set_config() из main.py.
_config = None


def set_config(config) -> None:
    """Регистрирует Config — оттуда читаем weather_cache_ttl_sec.

    Вызывается один раз при старте Феникса.
    """
    global _config
    _config = config
    log.info("weather: Config подключён, TTL = %d сек",
             _current_ttl())


def _current_ttl() -> int:
    """Актуальный TTL кэша в секундах.

    Читает weather_cache_ttl_sec из Config на КАЖДЫЙ вызов —
    чтобы смена значения на лету работала.
    """
    if _config is None:
        return _DEFAULT_TTL
    try:
        v = _config.get("weather_cache_ttl_sec", _DEFAULT_TTL)
        v = int(v)
        return v if v > 0 else _DEFAULT_TTL
    except (TypeError, ValueError):
        return _DEFAULT_TTL


def _cached(key: tuple, fetcher):
    now = time.time()
    ttl = _current_ttl()

    with _CACHE_LOCK:
        if key in _CACHE:
            ts, data = _CACHE[key]
            if now - ts < ttl:
                return data

    # fetcher() вызываем ВНЕ лока — иначе блокируем HTTP на весь кэш
    data = fetcher()

    if data is not None:
        with _CACHE_LOCK:
            _CACHE[key] = (time.time(), data)
    return data


def _http_get_json(url: str, timeout: float = 8.0):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Phoenix/0.2.2"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        log.exception("HTTP GET не удался: %s", url)
        return None


# --- геокодинг --------------------------------------------------------------

def geocode(city: str) -> Optional[dict]:
    """Возвращает {'name': ..., 'country': ..., 'lat': ..., 'lon': ...} или None.

    Ожидает название города в именительном падеже (нормализует LLM).
    """
    key = ("geo", city.lower().strip())
    return _cached(key, lambda: _geocode_uncached(city))


def _geocode_uncached(city: str) -> Optional[dict]:
    q = urllib.parse.quote(city.strip())
    url = f"https://geocoding-api.open-meteo.com/v1/search?name={q}&count=1&language=ru&format=json"
    data = _http_get_json(url)
    if not data:
        return None
    results = data.get("results")
    if not results:
        return None
    r = results[0]
    return {
        "name": r.get("name") or city,
        "country": r.get("country") or "",
        "admin1": r.get("admin1") or "",
        "lat": r.get("latitude"),
        "lon": r.get("longitude"),
    }


# --- погода -----------------------------------------------------------------

_WEATHER_CODES = {
    0: "ясно",
    1: "преимущественно ясно", 2: "переменная облачность", 3: "пасмурно",
    45: "туман", 48: "изморозь",
    51: "лёгкая морось", 53: "морось", 55: "сильная морось",
    61: "небольшой дождь", 63: "дождь", 65: "сильный дождь",
    71: "небольшой снег", 73: "снег", 75: "сильный снег",
    77: "снежная крупа",
    80: "небольшие ливни", 81: "ливни", 82: "сильные ливни",
    85: "снегопад", 86: "сильный снегопад",
    95: "гроза", 96: "гроза с градом", 99: "сильная гроза с градом",
}


def get_weather(city: str, day: str = "today") -> Optional[dict]:
    """Возвращает погоду для города.

    day: 'today' | 'tomorrow'
    """
    key = ("weather", city.lower().strip(), day)
    return _cached(key, lambda: _get_weather_uncached(city, day))


def _get_weather_uncached(city: str, day: str) -> Optional[dict]:
    geo = geocode(city)
    if not geo:
        return None
    lat, lon = geo["lat"], geo["lon"]
    params = (
        f"latitude={lat}&longitude={lon}"
        "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m"
        "&daily=temperature_2m_max,temperature_2m_min,weather_code,precipitation_sum"
        "&timezone=auto&forecast_days=2"
    )
    url = f"https://api.open-meteo.com/v1/forecast?{params}"
    data = _http_get_json(url)
    if not data:
        return None

    try:
        if day == "tomorrow":
            return {
                "city": geo["name"],
                "country": geo.get("country", ""),
                "day": "завтра",
                "temp_min": round(data["daily"]["temperature_2m_min"][1]),
                "temp_max": round(data["daily"]["temperature_2m_max"][1]),
                "code": data["daily"]["weather_code"][1],
                "precip": data["daily"]["precipitation_sum"][1] or 0,
            }
        cur = data["current"]
        daily = data["daily"]
        return {
            "city": geo["name"],
            "country": geo.get("country", ""),
            "day": "сегодня",
            "temp": round(cur["temperature_2m"]),
            "feels": round(cur["apparent_temperature"]),
            "code": cur["weather_code"],
            "wind": round(cur["wind_speed_10m"]),
            "humidity": cur["relative_humidity_2m"],
            "temp_min": round(daily["temperature_2m_min"][0]),
            "temp_max": round(daily["temperature_2m_max"][0]),
            "precip": daily["precipitation_sum"][0] or 0,
        }
    except (KeyError, IndexError, TypeError):
        log.exception("Не удалось разобрать ответ погоды")
        return None


def describe_weather(w: dict) -> str:
    """Формирует человеческую фразу для озвучки.

    Падежи: «Сейчас в городе Казань» / «Завтра в городе Казань» —
    именительный падеж уместен, никаких склонений не нужно.
    """
    if not w:
        return "Не удалось узнать погоду."
    code = w.get("code", -1)
    desc = _WEATHER_CODES.get(code, "неизвестно")

    country = (w.get("country") or "").strip()
    city = w.get("city", "")
    city_full = f"{city}, {country}" if country else city

    if w.get("day") == "завтра":
        return (
            f"Прогноз на завтра — {city_full}: {desc}, "
            f"от {w['temp_min']} до {w['temp_max']} градусов, "
            f"осадки {round(w['precip'], 1)} мм."
        )
    return (
        f"Сейчас в городе {city_full}: {desc}, "
        f"{w['temp']} градусов, ощущается как {w['feels']}. "
        f"Ветер {w['wind']} метров в секунду, влажность {w['humidity']} процентов. "
        f"Днём от {w['temp_min']} до {w['temp_max']} градусов."
    )


# --- курс валют -------------------------------------------------------------

def get_currency_rates() -> Optional[dict]:
    """Возвращает все валюты ЦБ:
        {
            "date": "2026-10-04",
            "valutes": {
                "USD": {"name": "Доллар США", "value": 83.48, "nominal": 1},
                "EUR": {...},
                "BYN": {...},
                ...
            }
        }
    """
    key = ("currency", "cbr")
    return _cached(key, _get_currency_uncached)


def _get_currency_uncached() -> Optional[dict]:
    url = "https://www.cbr-xml-daily.ru/daily_json.js"
    data = _http_get_json(url)
    if not data:
        return None
    try:
        valutes = {}
        for code, v in data["Valute"].items():
            valutes[code] = {
                "name": v.get("Name") or code,
                "value": v.get("Value"),
                "nominal": v.get("Nominal", 1),
            }
        return {
            "date": data.get("Date", "")[:10],
            "valutes": valutes,
        }
    except (KeyError, TypeError):
        log.exception("Не удалось разобрать ответ ЦБ")
        return None


# Приоритет для вывода «общего курса»
_DEFAULT_CURRENCIES = ["USD", "EUR", "CNY"]


def describe_currency(rates: dict, code: str = "") -> str:
    """Озвучивает курс.

    rates: результат get_currency_rates()
    code:  ISO-код валюты ("USD", "BYN", "KZT", ...). Пусто — основные.
    """
    if not rates:
        return "Не удалось узнать курс валют."

    valutes = rates.get("valutes", {})

    # Конкретная валюта
    if code:
        v = valutes.get(code.upper())
        if not v:
            return f"Курс валюты {code} не нашёл в базе ЦБ."
        nominal = v.get("nominal") or 1
        value = v.get("value")
        if value is None:
            return f"Курс валюты {code} не удалось прочитать."
        if nominal == 1:
            return f"{v['name']} — {value:.2f} рубля."
        return f"{v['name']} ({nominal} шт.) — {value:.2f} рубля."

    # Общий курс — основные валюты
    parts = []
    for c in _DEFAULT_CURRENCIES:
        v = valutes.get(c)
        if not v or v.get("value") is None:
            continue
        parts.append(f"{v['name']} — {v['value']:.2f} рубля")

    if not parts:
        return "Не удалось прочитать основные валюты."

    date = rates.get("date") or "сегодня"
    return f"Курс ЦБ на {date}: " + ", ".join(parts) + "."
```

### `launcher.py`

```python
"""Лаунчер Феникса: молча запускает `pythonw -m jarvis` без окна консоли.

Собирается в exe и кладётся в корень проекта. Вычисляет рабочую папку
(где лежит exe) и интерпретатор (pythonw из PATH). Защищён от повторного
запуска именованным мьютексом.
"""

import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path

MUTEX_NAME = "Global\\JarvisPhoenixSingleInstance"

# №88: держим HANDLE мьютекса на уровне модуля, чтобы он не терялся.
# Без этого второй вызов already_running() в том же процессе вернул бы
# True ложно (мьютекс уже наш, но HANDLE потерян — Windows посчитала бы,
# что мы «уже запущены» и это не мы).
_MUTEX_HANDLE = None


def already_running() -> bool:
    """Проверяет, запущен ли уже Феникс.

    №88: HANDLE мьютекса сохраняется в _MUTEX_HANDLE. Пока процесс жив,
    мьютекс остаётся захваченным — второй запуск увидит ERROR_ALREADY_EXISTS.
    """
    global _MUTEX_HANDLE

    # Если уже проверяли в этом процессе — не создаём второй мьютекс.
    if _MUTEX_HANDLE is not None:
        return False

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    last_error = kernel32.GetLastError()

    if last_error == 183:  # ERROR_ALREADY_EXISTS
        # Мьютекс уже занят другим процессом — закрываем наш HANDLE
        if handle:
            kernel32.CloseHandle(handle)
        return True

    # Наш мьютекс — держим HANDLE до конца процесса.
    # НЕ закрываем — если закроем, мьютекс освободится и второй
    # запуск не увидит «уже запущен».
    _MUTEX_HANDLE = handle
    return False


def project_dir() -> Path:
    base = Path(sys.executable if getattr(sys, "frozen", False) else __file__)
    return base.resolve().parent


def find_pythonw() -> str:
    for name in ("pythonw.exe", "pythonw"):
        found = shutil.which(name)
        if found:
            return found
    cand = Path(sys.base_prefix) / "pythonw.exe"
    return str(cand) if cand.exists() else "pythonw"


def main() -> None:
    if already_running():
        return
    cwd = project_dir()
    pythonw = find_pythonw()
    creationflags = 0x08000000 | 0x00000008  # NO_WINDOW | DETACHED_PROCESS
    subprocess.Popen(
        [pythonw, "-m", "jarvis"],
        cwd=str(cwd),
        creationflags=creationflags,
        close_fds=True,
    )


if __name__ == "__main__":
    main()
```

### `packs\apps.json`

```json
[
  {"phrases": ["открой дискорд", "открой дс"], "action": "open_app:discord", "reply": "Открываю Discord."},
  {"phrases": ["открой телеграм", "открой тг", "открой телегу"], "action": "open_app:telegram", "reply": "Открываю Telegram."},
  {"phrases": ["открой обс", "открой обс студио"], "action": "open_app:obs", "reply": "Открываю OBS Studio."},
  {"phrases": ["открой вс код", "открой вскод", "открой код"], "action": "open_app:code", "reply": "Открываю VS Code."},
  {"phrases": ["открой спотифай", "открой споти"], "action": "open_app:spotify", "reply": "Открываю Spotify."},
  {"phrases": ["открой яндекс музыку"], "action": "open_app:яндекс музыка", "reply": "Открываю Яндекс Музыку."},
  {"phrases": ["открой эпик геймс", "открой эпик"], "action": "open_app:epic", "reply": "Открываю Epic Games."},
  {"phrases": ["открой фотошоп"], "action": "open_app:photoshop", "reply": "Открываю Photoshop."},
  {"phrases": ["открой браузер"], "action": "browser", "reply": "Открываю браузер."},
  {"phrases": ["открой проводник", "открой мой компьютер"], "action": "explorer.exe", "reply": "Открываю проводник."},
  {"phrases": ["открой калькулятор", "открой калк"], "action": "calc.exe", "reply": "Открываю калькулятор."},
  {"phrases": ["открой блокнот"], "action": "notepad.exe", "reply": "Открываю блокнот."},
  {"phrases": ["открой диспетчер задач", "открой таск менеджер"], "action": "taskmgr.exe", "reply": "Открываю диспетчер задач."},
  {"phrases": ["открой настройки", "открой параметры"], "action": "ms-settings:", "reply": "Открываю настройки."},
  {"phrases": ["открой панель управления"], "action": "control.exe", "reply": "Открываю панель управления."},
  {"phrases": ["открой терминал", "открой консоль"], "action": "cmd.exe", "reply": "Открываю терминал."},
  {"phrases": ["открой павершелл", "открой powershell"], "action": "powershell.exe", "reply": "Открываю PowerShell."},
  {"phrases": ["открой часы", "открой будильник"], "action": "ms-clock:", "reply": "Открываю часы."},
  {"phrases": ["открой камеру"], "action": "microsoft.windows.camera:", "reply": "Открываю камеру."}
]
```

### `packs\games.json`

```json
[
  {"phrases": ["запусти доту", "врубай доту"], "action": "steam://rungameid/570", "reply": "Запускаю Доту."},
  {"phrases": ["запусти кс", "врубай кс", "запусти кс2"], "action": "steam://rungameid/730", "reply": "Запускаю CS2."},
  {"phrases": ["запусти сабнатику", "врубай сабнатику"], "action": "steam://rungameid/264710", "reply": "Запускаю Subnautica."},
  {"phrases": ["запусти тарков", "запусти побег из таркова"], "action": "steam://rungameid/270880", "reply": "Запускаю Тарков."},
  {"phrases": ["запусти пабг", "запусти пубг"], "action": "steam://rungameid/578080", "reply": "Запускаю PUBG."},
  {"phrases": ["запусти апекс", "врубай апекс"], "action": "steam://rungameid/1172470", "reply": "Запускаю Apex Legends."},
  {"phrases": ["запусти раст", "врубай раст"], "action": "steam://rungameid/252490", "reply": "Запускаю Rust."},
  {"phrases": ["запусти гта", "запусти гта 5"], "action": "steam://rungameid/271590", "reply": "Запускаю GTA V."},
  {"phrases": ["запусти рдр", "запусти ред дед"], "action": "steam://rungameid/1174180", "reply": "Запускаю Red Dead Redemption 2."},
  {"phrases": ["запусти дум", "врубай дум"], "action": "steam://rungameid/782330", "reply": "Запускаю DOOM Eternal."},
  {"phrases": ["запусти витчер", "запусти ведьмака"], "action": "steam://rungameid/292030", "reply": "Запускаю Ведьмака 3."},
  {"phrases": ["запусти скайрим"], "action": "steam://rungameid/489830", "reply": "Запускаю Skyrim."},
  {"phrases": ["запусти фоллаут 4"], "action": "steam://rungameid/377160", "reply": "Запускаю Fallout 4."},
  {"phrases": ["запусти террарию"], "action": "steam://rungameid/105600", "reply": "Запускаю Terraria."},
  {"phrases": ["запусти стардев"], "action": "steam://rungameid/413150", "reply": "Запускаю Stardew Valley."},
  {"phrases": ["открой стим"], "action": "steam://open/main", "reply": "Открываю Steam."},
  {"phrases": ["открой библиотеку стим"], "action": "steam://open/games", "reply": "Открываю библиотеку Steam."},
  {"phrases": ["открой магазин стим"], "action": "steam://store", "reply": "Открываю магазин Steam."},
  {"phrases": ["открой друзей стим"], "action": "steam://open/friends", "reply": "Открываю друзей."},
  {"phrases": ["открой загрузки стим"], "action": "steam://open/downloads", "reply": "Открываю загрузки Steam."}
]
```

### `packs\sites.json`

```json
[
  {"phrases": ["открой ютуб", "открой youtube"], "action": "https://www.youtube.com", "reply": "Открываю YouTube."},
  {"phrases": ["открой твич", "открой twitch"], "action": "https://www.twitch.tv", "reply": "Открываю Twitch."},
  {"phrases": ["открой гитхаб", "открой github"], "action": "https://github.com", "reply": "Открываю GitHub."},
  {"phrases": ["открой вк", "открой вконтакте"], "action": "https://vk.com", "reply": "Открываю ВКонтакте."},
  {"phrases": ["открой телегу веб", "открой веб телеграм"], "action": "https://web.telegram.org", "reply": "Открываю Telegram Web."},
  {"phrases": ["открой кинопоиск"], "action": "https://www.kinopoisk.ru", "reply": "Открываю Кинопоиск."},
  {"phrases": ["открой хабр", "открой habr"], "action": "https://habr.com", "reply": "Открываю Хабр."},
  {"phrases": ["открой википедию"], "action": "https://ru.wikipedia.org", "reply": "Открываю Википедию."},
  {"phrases": ["открой почту", "открой gmail"], "action": "https://mail.google.com", "reply": "Открываю почту."},
  {"phrases": ["открой яндекс"], "action": "https://ya.ru", "reply": "Открываю Яндекс."},
  {"phrases": ["открой гугл"], "action": "https://www.google.com", "reply": "Открываю Google."},
  {"phrases": ["открой авито"], "action": "https://www.avito.ru", "reply": "Открываю Авито."},
  {"phrases": ["открой озон", "открой ozon"], "action": "https://www.ozon.ru", "reply": "Открываю Ozon."},
  {"phrases": ["открой вайлдберриз", "открой вб"], "action": "https://www.wildberries.ru", "reply": "Открываю Wildberries."},
  {"phrases": ["открой дзен"], "action": "https://dzen.ru", "reply": "Открываю Дзен."},
  {"phrases": ["открой пикабу"], "action": "https://pikabu.ru", "reply": "Открываю Пикабу."},
  {"phrases": ["открой реддит"], "action": "https://www.reddit.com", "reply": "Открываю Reddit."},
  {"phrases": ["открой тикток"], "action": "https://www.tiktok.com", "reply": "Открываю TikTok."},
  {"phrases": ["открой инстаграм"], "action": "https://www.instagram.com", "reply": "Открываю Instagram."},
  {"phrases": ["открой стим комьюнити"], "action": "https://steamcommunity.com", "reply": "Открываю Steam Community."}
]
```

### `packs\system.json`

```json
[
  {"phrases": ["заблокируй компьютер", "заблокируй пк", "залочь пк"], "action": "rundll32.exe user32.dll,LockWorkStation", "reply": "Блокирую компьютер."},
  {"phrases": ["спящий режим", "усни", "сон пк"], "action": "rundll32.exe powrprof.dll,SetSuspendState 0,1,0", "reply": "Ухожу в спящий режим."},
  {"phrases": ["перезагрузи компьютер", "перезагрузка"], "action": "shutdown /r /t 10", "reply": "Перезагружаю через 10 секунд."},
  {"phrases": ["выключи компьютер", "отключи пк"], "action": "shutdown /s /t 10", "reply": "Выключаю через 10 секунд."},
  {"phrases": ["отмени выключение", "отмена выключения"], "action": "shutdown /a", "reply": "Отменяю выключение."},
  {"phrases": ["открой диспетчер устройств"], "action": "devmgmt.msc", "reply": "Открываю диспетчер устройств."},
  {"phrases": ["открой редактор реестра"], "action": "regedit.exe", "reply": "Открываю редактор реестра."},
  {"phrases": ["открой управление дисками"], "action": "diskmgmt.msc", "reply": "Открываю управление дисками."},
  {"phrases": ["покажи ip", "какой у меня ip"], "action": "cmd /k ipconfig", "reply": "Показываю IP."},
  {"phrases": ["покажи процессы", "список процессов"], "action": "cmd /k tasklist", "reply": "Показываю процессы."},
  {"phrases": ["покажи версию винды"], "action": "cmd /k winver", "reply": "Показываю версию Windows."},
  {"phrases": ["открой монитор ресурсов"], "action": "resmon.exe", "reply": "Открываю монитор ресурсов."},
  {"phrases": ["открой службы"], "action": "services.msc", "reply": "Открываю службы."},
  {"phrases": ["открой планировщик задач"], "action": "taskschd.msc", "reply": "Открываю планировщик."},
  {"phrases": ["открой программы и компоненты"], "action": "appwiz.cpl", "reply": "Открываю список программ."}
]
```

### `packs\work.json`

```json
[
  {"phrases": ["открой рабочий стол"], "action": "shell:Desktop", "reply": "Открываю рабочий стол."},
  {"phrases": ["открой загрузки"], "action": "shell:Downloads", "reply": "Открываю загрузки."},
  {"phrases": ["открой документы"], "action": "shell:Personal", "reply": "Открываю документы."},
  {"phrases": ["открой изображения", "открой картинки"], "action": "shell:My Pictures", "reply": "Открываю изображения."},
  {"phrases": ["открой музыку"], "action": "shell:My Music", "reply": "Открываю музыку."},
  {"phrases": ["открой видео"], "action": "shell:My Video", "reply": "Открываю видео."},
  {"phrases": ["открой корзину"], "action": "shell:RecycleBinFolder", "reply": "Открываю корзину."},
  {"phrases": ["открой сеть"], "action": "shell:NetworkPlacesFolder", "reply": "Открываю сеть."},
  {"phrases": ["открой системный диск"], "action": "shell:MyComputerFolder", "reply": "Открываю Этот компьютер."},
  {"phrases": ["открой проект феникс", "открой проект"], "action": "C:\\jarvis", "reply": "Открываю проект."},
  {"phrases": ["открой конфиг феникса", "открой конфиг"], "action": "C:\\jarvis\\config.json", "reply": "Открываю конфиг."},
  {"phrases": ["открой логи феникса", "открой журнал"], "action": "C:\\jarvis\\jarvis.log", "reply": "Открываю логи."}
]
```

### `PLAN.md`

```markdown
# 📋 План развития «Феникс»

Форк [jsays12/jarvis](https://github.com/jsays12/jarvis).
Коммиты до июня 2026 — от оригинала, с октября 2026 — мои изменения.

**Сложность:** 🟢 легко · 🟡 средне · 🔴 сложно
**Статус:** ✅ готово · 🚧 в работе · ⏸ отложено · ❌ не начато

---

## 📊 СВОДКА

| Категория | Всего | ✅ Закрыто | ❌ Осталось |
|---|---|---|---|
| 🔴 Критичные баги | 8 | 8 | 0 |
| 🟡 Серьёзные баги | 7 | 7 | 0 |
| 🟢 Мелкие баги | 8 | 8 | 0 |
| 🏗 Архитектурные | 3 | 1 | 2 |
| 📝 Документация | 1 | 1 | 0 |
| 🔐 Безопасность | 1 | 1 | 0 |
| 🆕 Запуск / фон | 1 | 1 | 0 |
| 🆕 Отмена (нормальная) | 1 | 0 | 1 |
| 🆕 Wake-слово | 1 | 0 | 1 |
| 🆕 Дизайн | 1 | 1 | 0 |
| 🆕 Многошаговые сценарии | 6 | 0 | 6 |
| 🆕 UI/UX | 3 | 0 | 3 |
| 🆕 Знакомство | 7 | 0 | 7 |
| 🆕 Мои команды | 9 | 0 | 9 |
| 🆕 Фичи (бесплатные) | 13 | 0 | 13 |
| 🆕 Управление приложениями | 6 | 0 | 6 |
| 🆕 Persistent memory | 3 | 0 | 3 |
| 🆕 MCP + плагины | 2 | 0 | 2 |
| 🆕 Telegram + веб | 2 | 0 | 2 |
| 🆕 Визуализация | 4 | 0 | 4 |
| 💰 Платные фичи | 6 | 0 | 6 |
| 💤 Долгий ящик | 5 | 0 | 5 |
| **ИТОГО** | **100** | **29** | **71** |

---

## ✅ СЕССИЯ 06.10.2026 (вечерняя) — закрыто

### Ревизия (минус 5)

| № | Баг | Где | Как закрыт |
|---|---|---|---|
| №9 | `weather._CACHE` без lock | `weather.py` | `_CACHE_LOCK` уже был |
| №11 | `Vosk.Reset()` не откатывает | `stt.py` | `flush()` уже прогоняет тишину |
| №16 | `_debug_fast` не тот буфер | `intents.py` | берёт из `listener.recent_phrases` |
| №17 | Макрос забивает стек | `intents.py` + `history.py` | `push_macro()` уже был |
| №19 | Нумерация этапов | README/PLAN | синхронизирована |

### Мелкие баги (4)

| № | Баг | Как закрыт |
|---|---|---|
| №18 | Мусорные профили | Удалены |
| №22 | Падежи погоды | «Сейчас в городе X» |
| №23 | Контекст LLM | `build_context` + name/city |
| №38 | `requirements-dev.txt` | Создан |

### Аудит DeepSeek (19)

| № | Баг | Как закрыт |
|---|---|---|
| №71 | `scripts/__init__.py` | Создан |
| №72 | `wait_end` врёт | → `bool` |
| №73 | Пузырь зависает | `try/finally` в `_say_stream` |
| №74 | TTS накладывается | `play_async` проверяет `wait_end` |
| №76 | `profile.switch` гонка | Один `RLock` |
| №78 | Докстринг `__init__.py` | Переписан |
| №79 | Комментарии-номера | Переписаны |
| №80 | Groq в README | «🚧 в планах» |
| №84 | `launch_mode` | Окно/трей + защита конфликта |
| №88 | `launcher.py` мьютекс | HANDLE хранится |
| №89 | `close_browser` | Убивает все браузеры |
| №90 | `pystray.SystemExit` | Ловится |
| №91 | `profiles/` из git | `git rm --cached` |
| №92 | `_tabs` при смене профиля | `rebuild_ui` + сохранение истории |
| №93 | `chat_stream` чанк | `append` до проверки токена |
| №94 | `wake_score` | 4 явных сравнения |
| №95 | `Config.unsubscribe` | Добавлен |
| №96 | `SITES` дублируется | Из `packs/sites.json` |
| №97 | `build_context` / `_profile_fast` | Через `set_profile` |
| №98 | `check_syntax.bat` | `%~dp0` |

### Стресс-тест (4)

| № | Баг | Как закрыт |
|---|---|---|
| №67 | Многослойные команды | `_split_compound` |
| №68 | «ютуб и …» | Вместе с №67 |
| №69 | «потише на 10» | В `_system_fast` |
| №70 | Мусорный ввод | Проверка длины/set |

### Профиль универсально

- **`set_profile` / `get_profile`** — LLM сама разбирает, без костылей.
- **`open_profile`** — Notepad++ → VS Code → системный, с активацией окна.
- **Реестр `_fast_handlers()`** — вместо 22 `if` подряд.

---

## 🚧 ОСТАЛОСЬ

### 🏗 Архитектурные (2)

| № | Баг | Время |
|---|---|---|
| №75 | God Object `Jarvis` / `_handle_single` | 4+ ч |
| №77 | `_handle_single` — задокументировать | 20 мин |

### 🆕 Отмена (нормальная) (1)

| № | Баг | Время |
|---|---|---|
| №85 | Восстановление состояния | 2+ ч ⏸ |

### 🆕 Wake-слово (1)

| № | Баг | Время |
|---|---|---|
| №86 | openWakeWord | 2–3 ч 🧪 |

### 🆕 UI/UX (3)

| № | Задача | Время |
|---|---|---|
| №42 | Иконка приложения | 30 мин |
| №43 | Сборка `.exe` | 1 ч |
| №44 | Ярлык на рабочем столе | 15 мин |

### 🆕 Знакомство (7)

З1–З7. Время: ~3.5 ч.

### 🆕 Мои команды и сценарии (12)

К1–К12. Время: ~11 ч.

### 🆕 Многошаговые сценарии (6)

№101–№106. Время: ~8 ч.

### 🆕 Фичи (бесплатные) (13)

Ф1–Ф13 (Groq / Edge TTS / Cloud). Время: ~12 ч.

### 🆕 Управление приложениями (6)

№45–№50. Время: ~8–10 ч.

### 🆕 Persistent memory (3)

№51–№53. Время: ~3.5 ч.

### 🆕 MCP + плагины (2)

№54–№55. Время: ~5–6 ч.

### 🆕 Telegram + веб (2)

№56–№57. Время: ~5–6 ч.

### 🆕 Визуализация (4)

№58–№61. Время: ~8–9 ч.

### 💰 Платные фичи (6)

Ф14–Ф19. Время: ~8.5 ч. ⏸

### 💤 Долгий ящик (5)

№62–№66. A2A Hermes, XTTS-каталог, git.

---

## 🎯 ПОРЯДОК РАБОТЫ

### ЭТАП 1 — Баги — ✅ ЗАКРЫТ

### ЭТАП 1.5 — Документация — 🚧 (сейчас)

### ЭТАП 1.6 — UI/UX (2 ч)

№42–№44: иконка, `.exe`, ярлык.

### ЭТАП 1.7 — Знакомство (3.5 ч)

З1–З7.

### ЭТАП 1.8 — Мои команды и сценарии (11 ч)

К1–К12.

### ЭТАП 2 — Бесплатное облако (12 ч)

Ф1–Ф13.

### ЭТАП 3 — Управление приложениями (8–10 ч)

№45–№50.

### ЭТАП 4 — Persistent memory (3.5 ч)

№51–№53.

### ЭТАП 5 — MCP + плагины (5–6 ч)

№54–№55.

### ЭТАП 6 — Telegram + веб (5–6 ч)

№56–№57.

### ЭТАП 7 — Визуализация (8–9 ч)

№58–№61.

### ЭТАП 8 — Платное облако (8.5 ч) ⏸

Ф14–Ф19.

### 💤 ДОЛГИЙ ЯЩИК

№62–№66.

---

## 📊 ПРОГРЕСС

| Этап | Прогресс |
|---|---|
| Этап 0 — Фундамент | ✅ 100% |
| Этап 1 — Баги | ✅ **100%** |
| Этап 1.5 — Документация | 🚧 50% |
| Этап 1.6 — UI/UX | ❌ 0% |
| Этап 1.7 — Знакомство | ❌ 0% |
| Этап 1.8 — Мои команды | ❌ 0% |
| Этап 2 — Бесплатное облако | ❌ 0% |
| Этап 3 — Управление | ❌ 0% |
| Этап 4 — Persistent memory | ❌ 0% |
| Этап 5 — MCP + плагины | ❌ 0% |
| Этап 6 — Telegram + веб | ❌ 0% |
| Этап 7 — Визуализация | ❌ 0% |
| Этап 8 — Платное облако | ⏸ 0% |
| 💤 Долгий ящик | 💤 |
```

### `profiles\maksim\profile.json`

```json
{
  "created_at": 1791301628.2279227,
  "name": "максим",
  "facts": {
    "мой город казань": "да"
  }
}
```

### `PROMPT.md`

```markdown
# 🤖 ПРОМПТ для LLM — «Феникс»

> Этот файл — **самодостаточный промпт**. Скопируй его **целиком**
> в новый чат, если текущий переполнен. LLM прочитает и **сразу вникнет**.

---

## 🎯 Контекст

Проект — **«Феникс»**, локальный голосовой ассистент для Windows.
Форк `jsays12/jarvis`. Коммиты до июня 2026 — от оригинала, с октября 2026 — мои.

**Стек:**
- **Python 3.11** (обязательно, через `.venv311`) — Vosk не работает на 3.13/3.14
- **Vosk** (wake-слово) + **faster-whisper** (расшифровка)
- **Piper** / **XTTS** / **WinRT** (TTS)
- **Ollama** (LLM: qwen2.5, gemma2, llama3.1, mistral)
- **Flet 1.0.3** (GUI)
- **pystray** (трей)

**Репозиторий:** `C:\jarvis`
**Ветка:** `main`
**GitHub:** `https://github.com/BobLoTiK/jarvis-fenix`
**CI:** GitHub Actions на `windows-latest`.

---

## 🎭 Как со мной работать

**Обращение:** «брат».

**Стиль:** кратко, без воды, с юмором. Русский.

**Формат ответов:**
- **Команды** — в `bat`-блоках.
- **Код** — в `python`-блоках, целиком или точечные патчи.
- **В каждом патче указывать — после какого момента вставлять.**
- **Полные файлы** — в **Markdown-блоках** с языком:
  - `.md` → ` ```markdown `
  - `.json` → ` ```json `
  - `.py` → ` ```python `
  - `.bat` → ` ```batch `
- **При запросе «скинь файл целиком»** — **всегда в Markdown-блоке**, независимо от расширения.
- **Скриншоты** — если просят, описать что видно.

**Запрещено:**
- **Костыли.** Если решение «работает, но грязно» — это **не решение**.
- **Хардкод.** Всё через `config.json` и `Config`.
- **Прямая запись в `config.json`.** Только `Config.set()` или `config_manager.save()`.
- **Прямое чтение `config.json`.** Только `config.get()`.
- **Глобальное состояние.** Кроме `Config._GLOBAL`.
- **Словари синонимов в коде** для городов/валют/паков — **это задача LLM**.
- **Использовать Python 3.13/3.14** — Vosk 0.3.45 падает с access violation в `libvosk.dll`. Только **3.10–3.12**.
- **Коммитить `.venv311`** — он в `.gitignore`. Если попал — `git rm -r --cached .venv311`.
- **Коммитить `SNAPSHOT.md` > 1 МБ** — исключай `.venv311` в `snapshot.py`.
- **Скидывать полный файл** без обрамления в тройные обратные кавычки.
- **Упоминать личные данные пользователя** (имя, город, CPU, GPU, ОС) в публичных файлах:
  `PLAN.md`, `README.md`, `CHANGELOG.md`, `PROMPT.md`, `ARCHITECTURE.md`,
  `CONTRIBUTING.md`, `config.example.json`. Всё личное — только в `config.json`,
  `profiles/`, `system_caps.json` (и они в `.gitignore`).

**Поощряется:**
- **`Config.subscribe`** для реакции на изменения.
- **Разделение ответственности** — что где.
- **Тесты** — `pytest` + `test_intents.py`.
- **Логи** — в `logs/actions.log`.
- **Реестр `_fast_handlers()`** — новые быстрые правила **туда**, а не в 22 `if`.

---

## 🏗 Архитектура (кратко)

### Модули

```
jarvis/
├── main.py           — точка входа, Jarvis, barge-in
├── config.py         — Config в памяти + подписки
├── config_manager.py — атомарная запись (FileLock, mkstemp, os.replace)
├── brain.py          — Ollama: parse() и chat_stream()
├── intents.py        — IntentHandler: правила + LLM + _fast_handlers()
├── reply.py          — Reply (text | stream)
├── gui.py            — Flet GUI + PALETTES + _detect_system_theme()
├── history.py        — стек отмены («стоп, не то»)
├── stt.py            — Vosk + Whisper + ring buffer
├── tts.py            — Piper / XTTS / WinRT / SAPI + barge-in + per-call token
├── modes.py          — commands / llm / combo
├── voices.py         — смена голоса Piper
├── packs.py          — паки команд
├── profile.py        — profiles/<user>/profile.json + subscribe
├── memory.py         — profiles/<user>/dialog.json
├── learning.py       — факты + коррекции
├── weather.py        — погода + курс + настраиваемый TTL
├── timers.py         — напоминания
├── tasks.py          — задачи
├── actions.py        — окна, медиа, печать, буфер, громкость, яркость, раскладка,
│                       open_in_editor, _activate_window_hard
├── files.py          — папки
├── apps.py           — каталог приложений
├── installed.py      — индекс «Пуск»
├── steam.py          — индекс Steam
├── matching.py       — нечёткое сравнение
├── model.py          — загрузка Vosk
├── recorder.py       — макросы
└── tray.py           — трей
```

### Поток обработки

```
Микрофон → Vosk (wake) → Whisper → Jarvis._process
   → IntentHandler.handle(cmd)   ← normalize(cmd)
      → CANCEL / memory / pending / буфер / режимы
      → custom / small_talk / скриншот
      → _split_compound (многослойные)
      → ⚡ РЕЕСТР _fast_handlers()
         (custom, small_talk, music, open_profile,
          open, voices, packs, timers, tasks,
          profile, memory, system, debug, correction,
          undo, weather_currency)
      → brain.parse(cmd) → intent → _execute_intent
      → brain.chat_stream() → генератор
   → Reply (text | stream)
   → Jarvis.say(reply)
      → text → speaker.play_async()
      → stream → speaker.speak_stream() + tee → gui.add_stream_chunk()
```

### GUI

```
Flet главный поток
   ├── NavigationRail: Главная / Микрофон / Настройки
   ├── Контент-область (кеш _tabs)
   ├── page.run_task(_process_queue)
   └── page.run_task(_mic_level_loop)

Jarvis фоновый поток
   ├── listener.phrases()
   └── handler.handle() + say()
```

**Связь:** `queue.Queue()` — Jarvis пишет, GUI читает.
**Важно:** Flet — **в главном потоке** (`gui.run_main()`), Jarvis — **в фоне**.

### Реестр обработчиков

**`IntentHandler._fast_handlers()`** — список `(имя, функция)`.

**Порядок = приоритет.** Специфичные — **выше** общих.
**`open_profile` — ВЫШЕ `open`** (иначе `_open_fast` съест «открой профиль»).

**Добавить новый** — одна строка в список.

### Универсальный профиль

**Не через `re.match`**, а через LLM:
- «меня зовут X» → `set_profile` → `name`.
- «какой город» → `get_profile` → `default_city`.
- «открой профиль» → `open_profile` → Notepad++ / VS Code / системный.

---

## 📋 Режимы работы

### 🏠 Local (по умолчанию)

- **Интернет:** почти не нужен.
- **LLM:** Qwen через Ollama.
- **STT:** Vosk + Whisper small CPU.
- **TTS:** Piper (medium).

### 🌐 Hybrid

- **LLM:** Qwen 14b/32b (локально).
- **STT:** Whisper large-v3-turbo на GPU.
- **TTS:** Piper.

### ☁️ Cloud (бесплатно, ключ Groq) — 🚧 в планах

- **LLM:** Llama 3.3 70B через Groq.
- **STT:** Whisper large-v3 через Groq.
- **TTS:** Edge TTS (Microsoft).
- **Fallback:** при ошибке облака — откат на local.

### 💎 Premium (отложено)

- **LLM:** GPT-4o, Claude 3.5.
- **STT:** Whisper API, Deepgram.
- **TTS:** Fish Audio, ElevenLabs.

---

## 📊 ТЕКУЩИЙ СТАТУС

### ✅ Закрыто (все баги Этапа 1)

| Категория | Всего | Закрыто |
|---|---|---|
| 🔴 Критичные | 8 | 8 |
| 🟡 Серьёзные | 7 | 7 |
| 🟢 Мелкие | 8 | 8 |
| 🏗 Архитектурные | 3 | 1 |
| 📝 Документация | 1 | 1 |
| 🔐 Безопасность | 1 | 1 |
| 🆕 Запуск / фон | 1 | 1 |
| 🆕 Дизайн | 1 | 1 |

**Ключевые закрытые:**

- **№67** — многослойные команды (`_split_compound`).
- **№69** — «потише на 10».
- **№70** — мусорный ввод.
- **№72** — `wait_end` → `bool`.
- **№73** — `try/finally` в `_say_stream`.
- **№74** — TTS не накладывается.
- **№84** — `launch_mode` (gui / tray).
- **№88** — `launcher.py` мьютекс.
- **№89** — `close_browser` все браузеры.
- **№90** — `pystray.SystemExit`.
- **№91** — `profiles/` из git.
- **№92** — `_tabs` не теряют историю.
- **№93** — `chat_stream` чанк.
- **№94** — `wake_score`.
- **№95** — `Config.unsubscribe`.
- **№96** — `SITES` из packs.
- **№97** — `build_context` / `_profile_fast`.
- **№98** — `check_syntax.bat`.
- **set_profile / get_profile** — универсально через LLM.
- **open_profile** — Notepad++ / VS Code / системный.
- **Реестр `_fast_handlers()`** — вместо 22 `if`.

### 🚧 Осталось

**🏗 Архитектурные:**
- №75 — God Object `Jarvis` (4+ ч).
- №77 — `_handle_single` — задокументировать (20 мин).

**🆕 Отмена (нормальная)** — ⏸:
- №85 — Восстановление состояния (2+ ч).

**🆕 Wake-слово** — 🧪:
- №86 — openWakeWord (2–3 ч).

**🆕 UI/UX:**
- №42 — Иконка (30 мин).
- №43 — `.exe` (1 ч).
- №44 — Ярлык (15 мин).

**🆕 Знакомство** (7 пунктов, 3.5 ч):
- З1–З7 — persona + onboarding_done + GUI вкладка.

**🆕 Мои команды и сценарии** (12 пунктов, 11 ч):
- К1–К12 — `custom_commands.py` + рецепты + fallback.

**🆕 Многошаговые сценарии** (6 пунктов, 8 ч):
- №101–№106.

**🆕 Фичи (бесплатные)** (13 пунктов, 12 ч):
- Ф1–Ф13 — Groq / Edge TTS / Cloud.

**🆕 Управление приложениями** (6, 8–10 ч):
- №45–№50 — YouTube, браузер, VLC, Spotify, редакторы, игры.

**🆕 Persistent memory** (3, 3.5 ч):
- №51–№53.

**🆕 MCP + плагины** (2, 5–6 ч):
- №54–№55.

**🆕 Telegram + веб** (2, 5–6 ч):
- №56–№57.

**🆕 Визуализация** (4, 8–9 ч):
- №58–№61.

**💰 Платные фичи** (6, 8.5 ч) — ⏸:
- Ф14–Ф19.

**💤 Долгий ящик** (5):
- №62–№66 — A2A Hermes, XTTS-каталог, Smart Home, календарь, git.

---

## 🎯 ПОРЯДОК РАБОТЫ

### ЭТАП 1 — Баги — ✅ ЗАКРЫТ

### ЭТАП 1.5 — Документация — ✅ ЗАКРЫТ

### ЭТАП 1.6 — UI/UX (2 ч)

№42–№44.

### ЭТАП 1.7 — Знакомство (3.5 ч)

З1–З7.

### ЭТАП 1.8 — Мои команды и сценарии (11 ч)

К1–К12.

### ЭТАП 2 — Бесплатное облако (12 ч)

Ф1–Ф13.

### ЭТАП 3 — Управление приложениями (8–10 ч)

№45–№50.

### ЭТАП 4 — Persistent memory (3.5 ч)

№51–№53.

### ЭТАП 5 — MCP + плагины (5–6 ч)

№54–№55.

### ЭТАП 6 — Telegram + веб (5–6 ч)

№56–№57.

### ЭТАП 7 — Визуализация (8–9 ч)

№58–№61.

### ЭТАП 8 — Платное облако (8.5 ч) ⏸

Ф14–Ф19.

### 💤 ДОЛГИЙ ЯЩИК

№62–№66.

---

## 🎯 КЛЮЧЕВЫЕ ПРАВИЛА

### Код

1. **`Config` — единственный источник истины.**
2. **Не плоди `_atomic_write`.** `config_manager.save()`.
3. **Не плоди глобальное состояние.** Кроме `Config._GLOBAL`.
4. **Нормализация — задача LLM.**
5. **`test_intents.py`** — после каждой правки.
6. **`normalize(cmd)` в `IntentHandler.handle()`.**
7. **Per-call stop-token в `tts.py`.**
8. **`PALETTES` в `gui.py`** — две темы.
9. **`ft.Button`** вместо `ElevatedButton`/`TextButton`.
10. **`ft.BoxShadow`** — без `blur_style` (в Flet 1.0.3 нет).
11. **Реестр `_fast_handlers()`** — новые правила **туда**, не в 22 `if`.
12. **`open_profile` — выше `open`** в реестре.
13. **`set_profile` / `get_profile`** — через LLM, без `re.match`-костылей.
14. **Активация окон — через `win32gui` + `AttachThreadInput`** (`pygetwindow` не работает).

### GUI

1. **Flet — только в главном потоке.**
2. **Связь через `queue.Queue()`.**
3. **Разделы — в `_tabs`.**
4. **Тема — `page.theme_mode` + `PALETTES`.**
5. **`launch_mode`** — `"gui"` или `"tray"` (окно скрыто).
6. **`_rebuild_ui_for_theme`** сохраняет историю чата.

### Безопасность

1. **Личные данные — только в `config.json`, `profiles/`, `system_caps.json`.**
2. **Все — в `.gitignore`.**
3. **`config.example.json` — только дефолты.**
4. **Пароль (`danger_password`) — SHA-256.**

### Окружение

1. **Python 3.10–3.12.** Vosk не работает на 3.13/3.14.
2. **`.venv311`** — обязательный venv.
3. **`snapshot.py`** — исключать `.venv311`.

### Git

1. **`git push`** — после `.venv311` в `.gitignore`.
2. **`git filter-repo`** — если venv попал в историю.
3. **`profiles/`** — НЕ коммитить (личные данные).

---

## 🛠 Как чинить баги

1. **Лог.** `logs/actions.log`, `logs/errors.log`, `logs/jarvis.log`.
2. **Воспроизвести.**
3. **Локализовать.** Какой модуль?
4. **Фикс.** Без костылей.
5. **Тесты.** `python check_syntax.py` + `pytest` + `test_intents.py`.
6. **Коммит.** `fix: <краткое описание>`.

---

## 📎 БЫСТРЫЕ ССЫЛКИ

| Что | Где |
|---|---|
| **План** | `PLAN.md` |
| **Архитектура** | `ARCHITECTURE.md` |
| **Changelog** | `CHANGELOG.md` |
| **README** | `README.md` |
| **SNAPSHOT** | `SNAPSHOT.md` |
| **CI** | `.github/workflows/test.yml` |
| **Логи** | `logs/` |
| **GitHub** | `https://github.com/BobLoTiK/jarvis-fenix` |

---

**Погнали, брат.** 🚀
```

### `README.md`

```markdown
# Феникс

[![tests](https://github.com/BobLoTiK/jarvis-fenix/actions/workflows/test.yml/badge.svg)](https://github.com/BobLoTiK/jarvis-fenix/actions/workflows/test.yml)

Локальный голосовой ассистент для Windows. Форк проекта [jsays12/jarvis](https://github.com/jsays12/jarvis).

Коммиты до июня 2026 — от оригинала, с октября 2026 — мои изменения.

Офлайн для распознавания и синтеза речи (Vosk + Whisper + Piper). Онлайн — только для погоды и курса валют (с кэшем 10 минут). Опционально — Qwen 2.5 через Ollama для свободного диалога и разбора сложных фраз.

## Содержание

- [Что добавлено в форке](#что-добавлено-в-форке)
- [Требования](#требования)
- [Установка](#установка)
- [Первый запуск](#первый-запуск)
- [GUI (Flet)](#gui-flet)
- [Режимы работы](#режимы-работы)
- [Настройка LLM (Ollama)](#настройка-llm-ollama)
- [Режимы обработки](#режимы-обработки)
- [Паки команд](#паки-команд)
- [Мультипрофиль](#мультипрофиль)
- [Память диалога](#память-диалога)
- [Отмена действий](#отмена-действий)
- [Пароль на опасные](#пароль-на-опасные)
- [Голоса](#голоса)
- [Streaming TTS](#streaming-tts)
- [Barge-in (перебивание)](#barge-in-перебивание)
- [Микрофон](#микрофон)
- [Темы GUI](#темы-gui)
- [Логи и ошибки](#логи-и-ошибки)
- [Атомарная запись конфига](#атомарная-запись-конфига)
- [Погода и курс валют](#погода-и-курс-валют)
- [Команды](#команды)
- [Свои команды в custom_commands](#свои-команды-в-custom_commands)
- [Запуск без консоли](#запуск-без-консоли)
- [Автозапуск](#автозапуск)
- [Права администратора](#права-администратора)
- [Инструменты разработчика](#инструменты-разработчика)
- [CI (Continuous Integration)](#ci-continuous-integration)
- [Технологии](#технологии)

## Что добавлено в форке

### Этап 0: рефакторинг (закрыт)

- **Единый `config_manager.py`** — один `FileLock` на весь проект, уникальный `.tmp` через `tempfile.mkstemp`, `os.replace` для атомарной подмены. Гонка записи в `config.json` исчезла как класс.
- **Объект `Config` в памяти** — читается один раз при старте, изменения рассылаются подписчикам. Смена голоса и режима применяется мгновенно.
- **Калибровка Barge-in** — при старте измеряется фоновое эхо, порог подстраивается автоматически.
- **CJK-фильтр** — в `brain.py` и `tts.py`. LLM больше не «сорвётся в китайский».
- **Temperature 0.7** — ответы живее.
- **Тесты** — `test_intents.py` (40 сценариев) + `pytest`.

### Этап 1: команды и удобство

- **Голосовые режимы** — «режим команды», «режим ИИ», «обычный режим».
- **Паки команд** — 5 паков в `packs/`: игры, приложения, сайты, работа, системные.
- **Запись действий** — «запиши действие» → делаешь что-то → «стоп запись» → макрос.
- **Память диалога** — на профиль.
- **Голоса Piper** — «смени голос на Ирину», «голос Дмитрий».

### Этап 2: живой диалог

- **Streaming TTS** — первое слово через 0.2 сек.
- **Barge-in** — можно перебить Феникса.
- **Логи по категориям** — `logs/jarvis.log`, `logs/actions.log`, `logs/errors.log`.
- **Буфер обмена** — «что в буфере», «очисти буфер», «скопируй выделенное», «скопируй свой ответ».
- **Погода и курс валют** — `open-meteo.com` и `cbr-xml-daily.ru`. Кэш **настраиваемый** (`weather_cache_ttl_sec`, по умолчанию 10 минут).

### Этап 3: Reply + CI

- **`jarvis/reply.py`** — тип `Reply` (`text` | `stream`).
- **Быстрые правила без LLM** — голоса, паки, таймеры, задачи, погода/курс.
- **`_open_fast`** — открытие приложений/сайтов/папок без LLM.
- **GitHub Actions** — CI на `windows-latest`.
- **UTF-8 fix** — `reconfigure` + `PYTHONUTF8=1`.

### Этап 4: Системные команды

- **Раскладка RU/EN** — «переключи раскладку», «русская», «английская», «какая раскладка». Через `SendInput` (надёжно).
- **Громкость в %** — «громкость 50», «какая громкость». Через `pycaw`.
- **Яркость в %** — «яркость 30», «какая яркость». Через `screen-brightness-control`.
- **Диагностика** — «что ты слышал», «почему не понял».
- **Отмена** — «стоп, не то», «отмени» — откат последнего действия.
- **Пароль** — `danger_password` (SHA-256) для выключения/перезагрузки.

### Этап 5: Мультипрофиль

- **`profiles/<user>/profile.json`** — папка на пользователя.
- **`profiles/<user>/dialog.json`** — история на профиль.
- **`profile.subscribe()`** — подписка на смену профиля.
- **Автомиграция** из старого `user_profile.json`.
- **`profile.switch()`** — «я — Маша», «кто активен», «список профилей».
- **Факты** — «запомни: город Нижний Новгород» → `profile.set_fact()`.
- **Универсальные `set_profile` / `get_profile`** — через LLM. «Меня зовут X», «мой город Y», «поменяй город на Z», «как меня зовут», «какой город» — **работают без костылей-`re.match`**.

### Этап 6: Flet GUI

- **Окно 1100×760** на Flet 1.0.3.
- **NavigationRail** — Главная / Микрофон / Настройки.
- **Статус-сфера** с анимацией (смена цвета и размера).
- **Чат-пузыри** с аватарами (иконки Flet), тенями, fade-in.
- **Поле ввода** + Send / Mic.
- **Настройки** — модель LLM, Ollama URL, TTS, скорость речи (слайдер), тема.
- **Смена темы на лету** — Тёмная / Светлая / Системная.
- **Системная тема** — автоопределение через реестр Windows.
- **Стриминг в GUI** через tee-генератор.
- **Вкладка «Микрофон»** — прогресс-бар уровня, кнопка теста, dropdown.
- **`launch_mode`** — `"gui"` (окно сразу) или `"tray"` (окно скрыто, трей + голос).

### Этап 7: Реестр обработчиков + open_profile

- **`_fast_handlers()`** в `IntentHandler` — вместо 22 `if reply: return reply`. Порядок = приоритет, легко добавить новый.
- **`open_profile`** — «открой профиль» → Notepad++ → VS Code → системный.
- **`_activate_window_hard`** — активация окна редактора через `win32gui` + `AttachThreadInput`.
- **Трей: «Открыть окно»** — двойной клик по иконке трея.

### Инструменты

- **`install.bat`** — интерактивный установщик.
- **`check_syntax.py`** — синтаксис всех `.py`.
- **`snapshot.py`** — проект в `SNAPSHOT.md`.
- **`PROMPT.md`** — самодостаточный промпт для LLM.
- **`commit.bat`** — автокоммит с обновлением `SNAPSHOT.md`.
- **`requirements-dev.txt`** — dev-зависимости (pyinstaller, pytest-cov, ruff).

## Требования

- Windows 10/11 (x64)
- **Python 3.10–3.12** (3.11 рекомендуется)
  - ⚠️ **Python 3.13/3.14 не поддерживается** — Vosk 0.3.45 падает с access violation в `libvosk.dll`
- Микрофон
- Опционально: NVIDIA GPU (для Whisper large-v3-turbo)
- Опционально: Ollama (для LLM)

## Установка

### Автоматическая (рекомендуется)

1. Клонировать репозиторий:

       git clone https://github.com/BobLoTiK/jarvis-fenix.git
       cd jarvis-fenix

2. Запустить установщик:

       install.bat

   Он сам:
   - Проверит Python.
   - Установит `pip`-пакеты.
   - Спросит про eSpeak NG (нужен для Piper TTS).
   - Спросит про Ollama (для LLM-диалога).
   - Даст выбрать модель Qwen 2.5 по размеру.
   - Определит тему Windows (тёмная/светлая).
   - Скопирует `config.example.json` → `config.json`.
   - Прогонит проверку (синтаксис + pytest + интент-тесты).

3. Запустить Феникса:

       start_fenix.bat

### Ручная

    pip install -r requirements.txt
    copy config.example.json config.json

### ⚠️ Важно: отдельное окружение (venv)

**Если у тебя уже стоит Python 3.13/3.14** — **не трогай его**. Создай **отдельное окружение** на 3.11:

```bat
cd C:\jarvis
py -3.11 -m venv .venv311
.venv311\Scripts\activate.bat
pip install -r requirements.txt
```

**Запуск Феникса:**

```bat
.venv311\Scripts\activate.bat
python -m jarvis
```

**Или через батник** `start_fenix_311.bat`:

```batch
@echo off
chcp 65001 >nul
cd /d C:\jarvis
call .venv311\Scripts\activate.bat
python -m jarvis
pause
```

**Почему:** Vosk 0.3.45 собран под Python 3.7–3.12. На 3.13/3.14 падает с `access violation` в `libvosk.dll` при **инициализации**.

## Первый запуск

    python -m jarvis

При первом запуске скачается Vosk (~45 МБ) и Whisper (large-v3-turbo на GPU).

## GUI (Flet)

Феникс запускается **с GUI** по умолчанию.

**Что есть:**
- **NavigationRail** слева: Главная / Микрофон / Настройки.
- **Статус-сфера** — серая (спит), жёлтая (слушаю), зелёная (говорю), красная (ошибка).
- **Чат-пузыри** — твои справа (синие), Феникса слева (серые). С аватарами и тенями.
- **Поле ввода** — можно писать команды текстом.
- **Кнопка 🎤** — пауза/возобновить микрофон.
- **Настройки:**
  - Модель LLM (dropdown).
  - Ollama URL.
  - TTS бэкенд.
  - Скорость речи (слайдер).
  - Тема (Тёмная / Светлая / Системная) — **на лету**.
- **Микрофон:**
  - Уровень сигнала (прогресс-бар).
  - Кнопка «🎙 Проверить микрофон (3 сек)».
  - Выбор устройства.

**Режим запуска:**

В `config.json`:

    "launch_mode": "gui"

- `"gui"` — окно Flet при старте (по умолчанию).
- `"tray"` — окно скрыто, Феникс стартует в трее. **Двойной клик** по иконке трея — **показать окно**. Правый клик — «Открыть окно», «Настройки», «Слушать микрофон», «Сделать скриншот», «Открыть конфиг», «Открыть журнал», «Выход».

**Отключить GUI полностью:**

    "gui_enabled": false

Тогда — только трей и голос.

**Отключить трей:**

    "tray_enabled": false

**Почему Flet в главном потоке:** Flet ставит `signal.signal(SIGINT, ...)` — работает только в главном. Jarvis запускается **в фоне**.

## Режимы работы

Феникс поддерживает **три режима**, выбирается в GUI или config.

### 🏠 Local (по умолчанию)

- **Интернет:** почти не нужен.
- **LLM:** Qwen через Ollama.
- **STT:** Vosk + Whisper small CPU.
- **TTS:** Piper (medium).
- **Погода:** кэш 24 часа (`weather_cache_ttl_sec: 86400`).

### 🌐 Hybrid

- **LLM:** Qwen 14b/32b (локально).
- **STT:** Whisper large-v3-turbo на GPU.
- **TTS:** Piper.
- **Погода:** real-time (кэш 10 мин).

### ☁️ Cloud (бесплатно, ключ Groq) — 🚧 в планах

**⚠️ Пока не реализовано.** Запланировано в PLAN.md (Ф1–Ф13).

- **LLM:** Llama 3.3 70B через Groq.
- **STT:** Whisper large-v3 через Groq.
- **TTS:** Edge TTS (Microsoft).
- **Погода:** real-time.
- **Fallback:** при ошибке облака — откат на local.

**В `config.json`:**

    "operation_mode": "local",
    "cloud": {
      "llm_provider": null,
      "llm_api_key": null,
      "stt_provider": null,
      "stt_api_key": null,
      "tts_provider": null,
      "tts_voice": null,
      "fallback_to_local": true
    }

## Настройка LLM (Ollama)

В `config.json`:

    "llm_model": "qwen2.5:7b-instruct",
    "use_llm": true,
    "ollama_url": "http://127.0.0.1:11434"

| Модель | VRAM | Качество |
|---|---|---|
| `qwen2.5:0.5b` | ~0.5 ГБ | Очень слабо, для теста |
| `qwen2.5:1.5b-instruct` | ~1.5 ГБ | Базовое |
| `qwen2.5:3b-instruct` | ~3 ГБ | Заметно лучше |
| `qwen2.5:7b-instruct` | ~5–6 ГБ | Отличное (рекомендуется) |
| `qwen2.5:14b-instruct` | ~10 ГБ | Максимум для 12 ГБ VRAM |
| `qwen2.5:32b-instruct` | ~20 ГБ | Профессиональное |
| `gemma2:2b` | ~1.5 ГБ | Быстрая, для слабых ПК |
| `gemma2:9b` | ~6 ГБ | Хорошо держит русский |
| `llama3.1:8b` | ~5 ГБ | Популярная, многоязычная |
| `mistral:7b` | ~5 ГБ | Быстрая, живая |

**Смена модели — через GUI** (Настройки → LLM) или `config.json`.

## Режимы обработки

| Команда | Режим | Что делает |
|---|---|---|
| «режим команды» | `commands` | Только правила |
| «режим ИИ» | `llm` | Только LLM |
| «обычный режим» | `combo` | Правила → LLM (по умолчанию) |

## Паки команд

Папка `packs/` — JSON-файлы. Активные — в `config.json` → `active_packs`.

**Готовые паки:** `games`, `apps`, `sites`, `work`, `system`.

**Голосом:**
- «загрузи пак игр»
- «выгрузи пак игр»
- «какие паки»

## Мультипрофиль

```
profiles/
├── maksim/
│   ├── profile.json    ← name, default_city, facts, tts_voice
│   └── dialog.json     ← история диалога
└── masha/
    ├── profile.json
    └── dialog.json
```

**Голосом:**
- «Феникс, я — Маша» — создать/переключиться.
- «Феникс, кто активен?» — текущий профиль.
- «Феникс, список профилей».
- «Феникс, удали профиль Маша» (с паролем, если задан).
- «Феникс, меня зовут Максим» → `set_profile` → **сохранит**.
- «Феникс, мой город Казань» → `set_profile` → **сохранит**.
- «Феникс, поменяй город на Москву» → `set_profile` → **сохранит**.
- «Феникс, как меня зовут» → `get_profile` → **прочитает**.
- «Феникс, какой город» → `get_profile` → **прочитает**.
- «Феникс, открой профиль» → **Notepad++** (или VS Code, или системный).
- «Феникс, что ты обо мне знаешь» — расскажет `name`, `default_city`, `facts`.

**Файлы** — в `.gitignore`. **Миграция** из старого `user_profile.json` — при первом запуске.

## Память диалога

История — в `profiles/<user>/dialog.json`.

- «что мы обсуждали» → пересказ.
- «забудь всё» → очистка.
- «короткая память» → 40 сообщений.
- «обычная память» → 100.
- «долгая память» → 200.

**Лимит** и **контекст LLM** — настраиваются в `config.json`:
- `memory_max` — сколько хранить.
- `llm_context_messages` — сколько отдавать LLM.

## Отмена действий

- «Феникс, не то» / «отмени» / «верни как было» → откат последнего действия.
- Стек — последние 5 действий.
- Отмена: `open_app` → `close_app`, `set_mode`, `change_voice`, `set_volume`, `set_brightness`, `switch_layout`.

## Пароль на опасные

В `config.json`:

    "danger_password": "sha256:..."

**Пароль хранится в SHA-256.** Если ты вводишь `"1234"` в config — при старте он **автоматически** превратится в хеш.

Если **пусто** — пароль не нужен.

**Опасные:** выключение/перезагрузка, `kill_process`, `clear_tasks`, `cancel_timers`, `delete_profile`.

**Голосом:**
- «Феникс, выключи компьютер» → «Для этого нужен пароль.»
- «Феникс, пароль 1234» → «Подтверждено. Выключаю.»

## Голоса

4 голоса Piper:

| Голос | Описание |
|---|---|
| `ruslan` | Мужской, спокойный |
| `dmitri` | Мужской, ниже |
| `irina` | Женский |
| `denis` | Мужской, дикторский |

- «смени голос на Ирину» / «какой голос» / «список голосов».
- **Смена — на лету** (через `Config.subscribe`).
- **Также** — через GUI (Настройки → голос).

**Качество голоса:**
- `medium` — быстрее, меньше файлы (по умолчанию).
- `high` — лучше качество, больше файлы.

В `config.json`:

    "tts_voice_quality": "medium"

**Fallback:** если `high` не скачался — откат на `medium`.

## Streaming TTS

LLM отдаёт ответ по предложениям → первое сразу в Piper → пока играет, генерируется второе.

**Результат:** первое слово через 0.2 сек.

**В GUI:** текст **печатается по мере генерации** (один пузырь, дописывается).

## Barge-in (перебивание)

1. Первые 0.5 сек — слепое окно (эхо не меряется).
2. Потом замеряется фоновое эхо → порог = `эхо × 1.8`.
3. Если ты говоришь громче порога >100 мс → TTS прерывается.
4. Феникс переходит в диалог — можно говорить без «Феникс».

**Настройка:** `"barge_enabled": true`.

**Per-call stop-token:** каждый `play_async` / `speak_stream` создаёт свой токен. Старый поток корректно завершается. Никаких наложений.

## Микрофон

**Вкладка «Микрофон» в GUI:**
- **Прогресс-бар уровня сигнала** — обновляется 5 раз в секунду.
- **Кнопка «🎙 Проверить микрофон (3 сек)»** — слушает, показывает результат:
  - ✅ Работает (пик ≥ 500)
  - ⚠️ Тихий (100 ≤ пик < 500)
  - ❌ Молчит (пик < 100)
- **Статус:** Работает / Тихий / Ожидание.
- **Выбор устройства** — dropdown.

**`mic_watchdog`:**
- Проверяет микрофон через `mic_check_sec` (по умолчанию 20 сек).
- Пик ≥ 50 → микрофон живой, не спамит.
- Пик < 50 → одно предупреждение **за сессию**, потом тишина.
- Автоматически открывает вкладку «Микрофон» в GUI.

**Отключить:** `"mic_watchdog_enabled": false`.

## Темы GUI

**Три темы:**
- **Системная** (по умолчанию) — автоопределение через реестр Windows.
- **Тёмная** — тёмная палитра.
- **Светлая** — светлая палитра.

**Смена — на лету.** UI пересобирается с новой палитрой.

**Подхват смены темы Windows:** раз в 2 сек проверка (если тема = «Системная»).

## Логи и ошибки

Все логи — в `logs/`:

| Файл | Что пишет |
|---|---|
| `jarvis.log` | Общий лог |
| `actions.log` | Команды, интенты, действия |
| `errors.log` | Только WARNING и ERROR |

Открыть голосом: «открой журнал».

**Глобальный `threading.excepthook`** — падения в фоновых потоках попадают в `errors.log` с трейсбеком.

## Атомарная запись конфига

Запись `config.json` — через `config_manager.py`:

- Один `FileLock` на весь проект.
- Уникальный `.tmp` через `tempfile.mkstemp`.
- `os.replace` для атомарной подмены.

Все модули пишут только через `config_manager` или `Config.set()`.

## Погода и курс валют

- **Погода:** `open-meteo.com`.
- **Курс валют:** `cbr-xml-daily.ru` (ЦБ РФ).

**Кэш — настраиваемый:**

    "weather_cache_ttl_sec": 600

- `600` — 10 минут (по умолчанию).
- `86400` — 24 часа (для Local-режима).

**Смена TTL — на лету** (читается при каждом запросе к кэшу).

**Голосом:**
- «какая погода» — если `default_city` задан, спросит без города.
- «погода в Москве», «погода в питере на завтра».
- «курс доллара», «курс белорусского рубля», «курс валют».

## Команды

**Приложения:** «открой стим», «закрой дискорд», «запусти сабнатику».

**Сайты:** «открой ютуб», «открой хабр», «хабр точка ру».

**Поиск:** «загугли погоду», «найди на ютубе лофи».

**Печать:** «напечатай привет мир».

**Окна:** «сверни все окна», «сверни дискорд», «разверни браузер».

**Скриншот:** «сделай скриншот».

**Файлы:** «создай файл список покупок», «что на рабочем столе».

**Музыка:** «включи музыку», «пауза», «следующий трек», «громче», «тише».

**Громкость/яркость:** «громкость 50», «яркость 30», «какая громкость», «сделай на 10 потише».

**Раскладка:** «переключи раскладку», «русская раскладка», «какая раскладка».

**Время:** «который час», «какое сегодня число».

**Разговор:** «как дела», «расскажи шутку», «что такое фотосинтез».

**Голос:** «смени голос на Ирину», «какой голос».

**Буфер:** «что в буфере», «очисти буфер», «скопируй выделенное», «скопируй свой ответ».

**Погода/курс:** «какая погода», «погода в Москве», «курс доллара».

**Паки:** «загрузи пак игр», «выгрузи пак игр», «какие паки».

**Профиль:** «я — Маша», «кто активен», «список профилей».

**Профиль-память:** «меня зовут X», «мой город Y», «поменяй город на Z», «как меня зовут», «какой город», «что ты обо мне знаешь».

**Открыть файлы:** «открой профиль», «открой профиль в вс код», «открой профиль в блокноте», «открой конфиг», «открой журнал».

**Память:** «короткая память», «долгая память», «какая память», «что мы обсуждали», «забудь всё».

**Отмена:** «не то», «отмени».

**Диагностика:** «что ты слышал», «почему не понял».

**Стоп:** «стой», «хватит», «отбой».

**В планах — Знакомство:**
- «поменяй стиль на строгий»
- «как ты ко мне обращаешься»
- «давай заново познакомимся»

**В планах — Мои команды:**
- «Феникс, научись новому» → диалог.
- «какие у меня команды»
- «удали команду X»
- «покажи команду X»

## Свои команды в custom_commands

**Сейчас (в `config.json`):**

    {
      "phrases": ["открой конфиг"],
      "action": "C:\\jarvis\\config.json",
      "reply": "Открываю конфиг."
    }

**В планах — через профиль (`profiles/<user>/custom_commands.json`) и голосом.**

Типы: путь, `open_app:discord`, `browser`, URL, `steam://`, `{"steps": [...]}`.

## Запуск без консоли

    pythonw -m jarvis

Либо собрать `.exe` (нужен `pyinstaller` из dev-зависимостей):

    pip install -r requirements-dev.txt
    python scripts/build_exe.py

## Автозапуск

Win+R → `shell:startup` → Enter. Скопируй туда ярлык.

## Права администратора

Для базовой работы — **не нужны**. **Только для макросов** (`keyboard`).

## Инструменты разработчика

| Скрипт | Что делает |
|---|---|
| `install.bat` | Интерактивная установка |
| `start_fenix.bat` | Запуск без консоли |
| `start_fenix_debug.bat` | Запуск с логами |
| `start_fenix_311.bat` | Запуск на Python 3.11 venv |
| `check_syntax.py` | `ast.parse()` |
| `test_intents.py` | 40 сценариев (флаги `--llm`, `--network`, `--voice`) |
| `snapshot.py` | `SNAPSHOT.md` |
| `commit.bat` | Автокоммит с обновлением `SNAPSHOT.md` |
| `scripts/selftest.py` | TTS → Vosk → разбор |
| `scripts/mics.py` | Выбор микрофона |
| `scripts/wakebench.py` | Бенчмарк wake-слов |
| `scripts/voicedemo.py` | Прослушка голосов |
| `scripts/build_exe.py` | Сборка `.exe` |
| `.github/workflows/test.yml` | CI |

Запуск тестов:

    python check_syntax.py
    python -m pytest tests/ -v
    python test_intents.py

## CI (Continuous Integration)

При каждом push GitHub:
1. Проверяет синтаксис.
2. Гоняет `pytest`.
3. Гоняет `test_intents.py` (без LLM и сети).

Результат — на вкладке **Actions**: ✅ / ❌.

**Подробнее** — `CI.md`.

### Тесты локально

    python test_intents.py                  # без LLM, без сети
    python test_intents.py --network        # + погода/курс
    python test_intents.py --llm            # + LLM (Ollama)
    python test_intents.py --llm --network  # всё
    python test_intents.py --voice          # с озвучкой
    python test_intents.py -k weather       # фильтр

## Технологии

| Компонент | Решение |
|---|---|
| Wake-слово | Vosk (`vosk-model-small-ru-0.22`) |
| Расшифровка | faster-whisper (large-v3-turbo GPU / small CPU) |
| Синтез речи | Piper TTS (ruslan/dmitri/irina/denis) |
| Streaming TTS | `speak_stream()` + `chat_stream()` + tee |
| Barge-in | Автокалибровка + per-call stop-token |
| LLM | Qwen 2.5 / Gemma 2 / Llama 3.1 / Mistral через Ollama |
| GUI | **Flet 1.0.3** + PALETTES (3 темы) |
| Мультипрофиль | `profiles/<user>/` + `subscribe()` |
| Универсальный профиль | `set_profile` / `get_profile` через LLM |
| Реестр обработчиков | `_fast_handlers()` в `IntentHandler` |
| Отмена | `jarvis/history.py` |
| Пароль | `danger_password` (SHA-256) |
| Запись действий | keyboard + mouse |
| Микрофон | sounddevice + вкладка с прогресс-баром |
| Трей | pystray + Pillow |
| Печать/окна | pyautogui + pygetwindow |
| Активация окон | win32gui + AttachThreadInput |
| Погода | open-meteo.com |
| Курс валют | cbr-xml-daily.ru (ЦБ РФ) |
| Логирование | `logging.handlers.RotatingFileHandler` |
| Буфер обмена | pyperclip + pyautogui |
| Атомарная запись | filelock + os.replace |
| Профиль | `profiles/<user>/profile.json` (в `.gitignore`) |
| CI | GitHub Actions (`windows-latest`, Python 3.11) |

## Лицензия

См. оригинальный репозиторий [jsays12/jarvis](https://github.com/jsays12/jarvis).
```

### `requirements-ci.txt`

```
# Зависимости для CI (GitHub Actions) и минимального прогона тестов.
#
# Здесь НЕТ:
#   - piper-tts, faster-whisper, sounddevice, vosk, winrt-* — на сервере нет звука
#   - pycaw, screen-brightness-control — тяжёлые, Windows-специфичные
#   - pyautogui, pygetwindow, keyboard, mouse — GUI
#
# Здесь ЕСТЬ только то, что реально импортируется IntentHandler
# и тестами (tests/, test_intents.py).

# --- Утилиты ---
filelock>=3.13
num2words>=0.5.14
psutil>=5.9
pyperclip>=1.8
Pillow>=10

# --- Тесты ---
pytest>=8.0
pytest-asyncio>=0.23
```

### `requirements-dev.txt`

```
# Зависимости для разработки (не нужны в проде).

# --- Сборка .exe ---
pyinstaller>=6.0

# --- Покрытие тестов ---
pytest-cov>=5.0

# --- Линтеры ---
ruff>=0.4
```

### `requirements.txt`

```
# === Ядро STT ===
vosk>=0.3.45
faster-whisper>=1.2.1
ctranslate2>=4.8.2
sounddevice>=0.5
numpy>=1.26

# === TTS ===
piper-tts>=1.8.0
pyttsx3>=2.99

# === WinRT (для медиа, TTS, уведомлений) ===
winrt-runtime>=3.2
winrt-Windows.Foundation>=3.2
winrt-Windows.Foundation.Collections>=3.2
winrt-Windows.Media.SpeechSynthesis>=3.2
winrt-Windows.Media.Control>=3.2
winrt-Windows.Storage.Streams>=3.2

# === Утилиты ===
filelock>=3.13
num2words>=0.5.14
psutil>=5.9
pyperclip>=1.8
Pillow>=10
huggingface_hub>=0.20

# === Трей ===
pystray>=0.19

# === Автоматизация Windows ===
pyautogui>=0.9.54
pygetwindow>=0.0.9
keyboard>=0.13.5
mouse>=0.7.1

# === Громкость / яркость ===
pycaw>=20240210
comtypes>=1.4
screen-brightness-control>=0.22

# === GUI ===
flet>=1.0.3
flet-desktop>=1.0.3

# === Тесты ===
pytest>=8.0
pytest-asyncio>=0.23

# === Опционально: мягкое удаление профиля ===
send2trash>=1.8
```

### `scripts\__init__.py`

```python
"""Пакет scripts: утилиты разработчика.

№71: раньше scripts/ не имел __init__.py. Тесты делали
`from scripts import check_caps` — работало на CI случайно
(namespace package + CWD). На чистой машине из другого места — упадёт.
Пустой __init__.py делает scripts/ полноценным пакетом.
"""
```

### `scripts\build_exe.py`

```python
"""Сборка Феникс.exe (лёгкий лаунчер) и иконки.

Запуск: python scripts/build_exe.py
Результат: <корень>/Феникс.exe — кладётся рядом с пакетом jarvis.
"""

import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ICON = BASE / "jarvis" / "icon.ico"
EXE_NAME = "Феникс"


def make_icon() -> None:
    """Иконка из того же рисунка, что и в трее (несколько размеров)."""
    from PIL import Image, ImageDraw

    def draw(size: int) -> Image.Image:
        k = size / 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((2 * k, 2 * k, 62 * k, 62 * k), fill=(18, 32, 58, 255),
                  outline=(86, 156, 255, 255), width=max(1, int(3 * k)))
        d.line((38 * k, 16 * k, 38 * k, 42 * k), fill=(86, 156, 255, 255),
               width=max(1, int(6 * k)))
        d.arc((20 * k, 30 * k, 42 * k, 52 * k), start=20, end=180,
              fill=(86, 156, 255, 255), width=max(1, int(6 * k)))
        return img

    sizes = [16, 24, 32, 48, 64, 128, 256]
    draw(256).save(ICON, sizes=[(s, s) for s in sizes])
    print("Иконка:", ICON)


def build() -> None:
    make_icon()
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile", "--noconsole", "--clean", "--noconfirm",
        "--name", EXE_NAME,
        "--icon", str(ICON),
        "--distpath", str(BASE / "dist"),
        "--workpath", str(BASE / "build"),
        "--specpath", str(BASE / "build"),
        str(BASE / "launcher.py"),
    ]
    print("PyInstaller:", " ".join(cmd))
    subprocess.run(cmd, check=True)

    src = BASE / "dist" / f"{EXE_NAME}.exe"
    dst = BASE / f"{EXE_NAME}.exe"
    dst.write_bytes(src.read_bytes())
    print("Готово:", dst)


if __name__ == "__main__":
    build()
```

### `scripts\check_caps.py`

```python
"""Проверка возможностей системы — запускается из install.bat.

Пишет system_caps.json:
    {
        "volume":     {"available": true,  "method": "volume_percent"},
        "brightness": {"available": true,  "method": "sbc"},
        "layout":     {"available": true,  "method": "sendinput"},
        "checked_at": 1791210000.0
    }

Зачем:
    API pycaw / screen-brightness-control меняется между версиями.
    Проверяем ОДИН РАЗ при установке, а не в рантайме.

Если что-то не работает — видно сразу при установке.
"""
import json
import logging
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUTPUT = BASE / "system_caps.json"

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("check_caps")


def check_volume() -> dict:
    """Проверяет громкость. Возвращает {'available': bool, 'method': str}."""
    try:
        from pycaw.pycaw import AudioUtilities
        device = AudioUtilities.GetSpeakers()

        # Способ 1: volume_percent (pycaw >= 2026)
        if hasattr(device, "volume_percent"):
            try:
                _ = device.volume_percent
                return {"available": True, "method": "volume_percent"}
            except Exception:
                pass

        # Способ 2: EndpointVolume
        if hasattr(device, "EndpointVolume"):
            try:
                _ = device.EndpointVolume.GetMasterVolumeLevelScalar()
                return {"available": True, "method": "endpoint_volume"}
            except Exception:
                pass

        # Способ 3: Activate
        if hasattr(device, "Activate"):
            try:
                from ctypes import cast, POINTER
                from comtypes import CLSCTX_ALL
                from pycaw.pycaw import IAudioEndpointVolume
                interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                vol = cast(interface, POINTER(IAudioEndpointVolume))
                _ = vol.GetMasterVolumeLevelScalar()
                return {"available": True, "method": "activate"}
            except Exception:
                pass

        return {"available": False, "method": "none", "reason": "no known API"}
    except Exception as e:
        return {"available": False, "method": "none", "reason": str(e)[:80]}


def check_brightness() -> dict:
    """Проверяет яркость."""
    try:
        import screen_brightness_control as sbc
        values = sbc.get_brightness()
        if values:
            return {"available": True, "method": "sbc"}
        return {"available": False, "method": "none", "reason": "no monitors"}
    except Exception as e:
        return {"available": False, "method": "none", "reason": str(e)[:80]}


def check_layout() -> dict:
    """Проверяет раскладку (SendInput)."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        _ = user32.SendInput
        return {"available": True, "method": "sendinput"}
    except Exception as e:
        return {"available": False, "method": "none", "reason": str(e)[:80]}

def check_cpu() -> dict:
    """Определяет категорию CPU для рекомендации Piper.

    Возвращает: категория (weak/normal/strong) + рекомендация (medium/high).
    Никаких конкретных моделей CPU — только количество ядер/потоков.
    """
    try:
        import psutil
    except ImportError:
        return {"available": False, "reason": "psutil не установлен"}

    try:
        cores = psutil.cpu_count(logical=False) or 0
        threads = psutil.cpu_count(logical=True) or 0

        if cores >= 6 and threads >= 12:
            power = "strong"
            recommended_piper = "high"
        elif cores >= 4 and threads >= 8:
            power = "normal"
            recommended_piper = "medium"
        else:
            power = "weak"
            recommended_piper = "medium"

        return {
            "available": True,
            "cores": cores,
            "threads": threads,
            "power": power,
            "recommended_piper": recommended_piper,
        }
    except Exception as e:
        return {"available": False, "reason": str(e)[:80]}

def main() -> int:
    log.info("=" * 60)
    log.info("  Проверка возможностей системы")
    log.info("=" * 60)

    caps = {
        "volume": check_volume(),
        "brightness": check_brightness(),
        "layout": check_layout(),
        "cpu": check_cpu(),
        "checked_at": time.time(),
    }

    log.info("")
    for name, info in caps.items():
        if name == "checked_at":
            continue
        mark = "[OK]  " if info.get("available") else "[FAIL]"

        if name == "cpu":
            # Специальный вывод для CPU
            if info.get("available"):
                log.info(
                    "%s %-12s %s ядер / %s потоков → рекомендация: %s",
                    mark, name,
                    info.get("cores"), info.get("threads"),
                    info.get("recommended_piper", "medium"),
                )
            else:
                log.info("%s %-12s %s", mark, name, info.get("reason", "?"))
            continue

        reason = f"  ({info.get('reason', '')})" if not info.get("available") else ""
        log.info("%s %-12s %s%s", mark, name, info.get("method", "?"), reason)

    OUTPUT.write_text(
        json.dumps(caps, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("")
    log.info("Сохранено: %s", OUTPUT)
    log.info("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### `scripts\mics.py`

```python
"""Подбор микрофона: показывает устройства ввода и уровень сигнала.

Запуск: python scripts/mics.py
Скажите что-нибудь — у живого микрофона будет высокий пик. Затем впишите
его имя (или часть) в config.json: "input_device": "camo".
"""

import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

FS = 16000


def main() -> None:
    default = sd.query_devices(kind="input")["name"]
    print(f"Устройство по умолчанию: {default}\n")

    # уникальные по имени входные устройства
    seen = {}
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            seen.setdefault(d["name"][:24], i)

    print("Говорите/шумите — измеряю уровень каждого микрофона...\n")
    results = []
    for name, idx in seen.items():
        try:
            rec = sd.rec(int(1.2 * FS), samplerate=FS, channels=1, dtype="int16", device=idx)
            sd.wait()
            results.append((int(np.abs(rec).max()), idx, name))
        except Exception as e:
            results.append((-1, idx, f"{name} (ошибка: {str(e)[:24]})"))

    results.sort(reverse=True)
    for peak, idx, name in results:
        mark = "  <-- ЖИВОЙ, впишите его имя в config" if peak > 1500 else ""
        lvl = "ошибка" if peak < 0 else str(peak)
        print(f"  [{idx:2}] пик={lvl:>6}  {name}{mark}")

    print('\nВ config.json: "input_device": "<часть имени>"  (например "camo"),')
    print('или null — устройство по умолчанию. Перезапустите Феникс после правки.')


if __name__ == "__main__":
    main()
```

### `scripts\selftest.py`

```python
"""Самопроверка без микрофона: TTS -> Vosk -> разбор команды.

Запуск: python scripts/selftest.py
"""

import asyncio
import io
import json
import sys
import wave
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from vosk import KaldiRecognizer, Model, SetLogLevel  # noqa: E402

from jarvis.apps import build_apps, find_app  # noqa: E402
from jarvis.installed import find_installed, scan_start_menu  # noqa: E402
from jarvis.intents import IntentHandler, normalize  # noqa: E402
from jarvis.matching import match_score, wake_score  # noqa: E402
from jarvis.actions import find_process, spoken_domain, guess_site  # noqa: E402
from jarvis.tts import Speaker  # noqa: E402

PHRASES = [
    "феникс открой стим",
    "феникс закрой дискорд",
    "феникс сколько времени",
    "феникс открой ютуб",
]


def recognize(model: Model, wav_bytes: bytes) -> str:
    wf = wave.open(io.BytesIO(wav_bytes))
    rec = KaldiRecognizer(model, wf.getframerate())
    while True:
        chunk = wf.readframes(4000)
        if not chunk:
            break
        rec.AcceptWaveform(chunk)
    return json.loads(rec.FinalResult()).get("text", "")


def main() -> None:
    SetLogLevel(-1)
    # Whisper — строго до первого использования WinRT (иначе access violation)
    from jarvis.stt import WhisperTranscriber
    whisper = WhisperTranscriber("auto", "auto")
    # для прогона TTS->STT нужен WinRT-бэкенд
```

### `scripts\set_llm_model.py`

```python
"""Устанавливает llm_model в config.json.

Используется из install.bat после выбора модели.

Запуск:
    python scripts/set_llm_model.py qwen2.5:7b-instruct
"""

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CONFIG = BASE / "config.json"


def main() -> int:
    if len(sys.argv) < 2:
        print("Использование: python scripts/set_llm_model.py <model_name>")
        return 1

    model = sys.argv[1].strip()
    if not model:
        print("Пустое имя модели")
        return 1

    data = {}
    if CONFIG.exists():
        try:
            data = json.loads(CONFIG.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Не удалось прочитать config.json: {e}")
            return 1

    old = data.get("llm_model")
    data["llm_model"] = model
    CONFIG.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"llm_model: {old} -> {model}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### `scripts\voicedemo.py`

```python
"""Прослушка голосов: проигрывает одну фразу всеми доступными голосами.

Запуск: python scripts/voicedemo.py [текст]
"""

import io
import sys
import wave
import winsound
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

TEXT = " ".join(sys.argv[1:]) or "Феникс на связи. Открываю Стим, сэр. Скриншот сохранён."


def main() -> None:
    from huggingface_hub import hf_hub_download
    from piper import PiperVoice, SynthesisConfig

    for v in ["ruslan", "dmitri"]:
        rel = f"ru/ru_RU/{v}/medium/ru_RU-{v}-medium.onnx"
        voice = PiperVoice.load(hf_hub_download("rhasspy/piper-voices", rel))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            voice.synthesize_wav(TEXT, wf, SynthesisConfig(length_scale=0.87))
        print(f"piper/{v}...")
        winsound.PlaySound(buf.getvalue(), winsound.SND_MEMORY)

    import asyncio

    from jarvis.tts import Speaker

    s = Speaker({"tts_backend": "winrt", "voice": "Pavel", "voice_rate": 1.15})
    print("winrt/Pavel...")
    winsound.PlaySound(asyncio.run(s._synthesize(TEXT)), winsound.SND_MEMORY)


if __name__ == "__main__":
    main()
```

### `scripts\wakebench.py`

```python
"""Бенчмарк кандидатов в wake-слово: TTS (Pavel) -> Vosk-small -> что услышалось.

Wake-слово ловит Vosk-small в стриме, поэтому слово должно стабильно
распознаваться именно им. Запуск: python scripts/wakebench.py
"""

import asyncio
import io
import json
import sys
import wave
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from vosk import KaldiRecognizer, Model, SetLogLevel  # noqa: E402

from jarvis.matching import match_score  # noqa: E402
from jarvis.tts import Speaker  # noqa: E402

CANDIDATES = [
    "джарвис",   # текущее, для сравнения
    "нексус",
    "оракул",
    "феникс",
    "гермес",
    "юпитер",
    "кронос",
    "протон",
    "сокол",
    "вектор",
    "циклоп",
    "альтрон",
]

TEMPLATES = [
    "{w} сделай скриншот",
    "{w} открой стим",
    "эй {w} который час",
]


def recognize(model: Model, wav_bytes: bytes) -> str:
    wf = wave.open(io.BytesIO(wav_bytes))
    rec = KaldiRecognizer(model, wf.getframerate())
    while True:
        chunk = wf.readframes(4000)
        if not chunk:
            break
        rec.AcceptWaveform(chunk)
    return json.loads(rec.FinalResult()).get("text", "")


def main() -> None:
    SetLogLevel(-1)
    speaker = Speaker("Pavel")
    model = Model(str(BASE / "models" / "vosk-model-small-ru-0.22"))

    results = []
    for word in CANDIDATES:
        heard_words = []
        exact = fuzzy = 0
        for tpl in TEMPLATES:
            wav = asyncio.run(speaker._synthesize(tpl.format(w=word)))
            heard = recognize(model, wav)
            tokens = heard.split()
            # ищем wake-токен в начале фразы (как в боевом коде)
            tok = ""
            for t in tokens[:2]:  # «эй X ...» — слово может быть вторым
                if match_score(t, word) >= 0.8:
                    tok = t
                    break
            if tok == word:
                exact += 1
                fuzzy += 1
            elif tok:
                fuzzy += 1
            heard_words.append(" ".join(tokens[:2]))
        results.append((word, exact, fuzzy, heard_words))

    print(f"{'слово':<10} {'точно':<6} {'фаззи':<6} услышано (первые 2 токена)")
    for word, exact, fuzzy, heard in sorted(results, key=lambda r: (-r[2], -r[1])):
        print(f"{word:<10} {exact}/3    {fuzzy}/3    {heard}")


if __name__ == "__main__":
    main()
```

### `snapshot.py`

```python
"""Собирает снимок проекта в один SNAPSHOT.md.

Исключения: логи, кэш, модели, личные данные.
Запуск: python snapshot.py
Результат: SNAPSHOT.md в корне проекта.
"""

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUTPUT = BASE / "SNAPSHOT.md"

EXCLUDE_DIRS = {
    ".git", "__pycache__",
    ".venv", ".venv311", "venv", "env", "envs",
    "logs", "models", "dist", "build", ".pytest_cache",
    ".idea", ".vscode", "node_modules",
    ".mypy_cache", ".ruff_cache",
    "voices",
}

EXCLUDE_FILES = {
    "config.json",
    "user_profile.json",
    "dialog.json",
    "timers.json",
    "tasks.json",
    "SNAPSHOT.md",
    ".gitignore",
    "config.json.lock",
    "user_profile.json.lock",
}

EXCLUDE_EXT = {
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".exe", ".bin",
    ".onnx", ".wav", ".mp3", ".zip", ".7z", ".rar",
    ".jpg", ".jpeg", ".png", ".gif", ".ico", ".bmp",
    ".tmp", ".lock", ".log",
}

TEXT_EXT = {
    ".py", ".md", ".txt", ".json", ".bat", ".cmd", ".cfg", ".ini",
    ".yaml", ".yml", ".toml", ".html", ".css", ".js", ".ts",
    ".ps1", ".sh", ".env", ".gitignore",
}

MAX_FILE_SIZE = 200 * 1024


def should_skip_dir(path: Path) -> bool:
    name = path.name
    # Явные исключения
    if name in EXCLUDE_DIRS:
        return True
    # Любая папка вида .venvXXX, venvXXX, envXXX
    if name.startswith((".venv", "venv", "env")) and len(name) <= 12:
        return True
    return False


def should_skip_file(path: Path) -> bool:
    if path.name in EXCLUDE_FILES:
        return True
    if path.suffix.lower() in EXCLUDE_EXT:
        return True
    if path.stat().st_size > MAX_FILE_SIZE:
        return True
    return False


def collect_tree(root: Path) -> list[Path]:
    result = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        if should_skip_file(path):
            continue
        result.append(path)
    return result


def read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="cp1251")
        except Exception:
            return f"[бинарный или нечитаемый файл: {path.suffix}]"
    except Exception as e:
        return f"[ошибка чтения: {e}]"


def build_tree_text(paths: list[Path], root: Path) -> str:
    tree = {}
    for p in paths:
        rel = p.relative_to(root)
        parts = rel.parts
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = None

    def render(node, indent=""):
        lines = []
        items = sorted(node.items(), key=lambda x: (x[1] is None, x[0].lower()))
        for name, sub in items:
            if sub is None:
                lines.append(f"{indent}├── {name}")
            else:
                lines.append(f"{indent}├── {name}/")
                lines.extend(render(sub, indent + "│   "))
        return lines

    return "\n".join(render(tree))


def main() -> int:
    print(f"Сбор снимка проекта: {BASE}")
    files = collect_tree(BASE)
    print(f"Найдено файлов: {len(files)}")

    lines = []
    lines.append("# SNAPSHOT проекта «Феникс»")
    lines.append("")
    lines.append(f"_Автоматически сгенерировано `snapshot.py`. Обновляется при `git push`._")
    lines.append(f"_Файлов в снимке: {len(files)}_")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 📁 Структура проекта")
    lines.append("")
    lines.append("```")
    lines.append(BASE.name + "/")
    lines.append(build_tree_text(files, BASE))
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 📄 Содержимое файлов")
    lines.append("")

    for i, path in enumerate(files, 1):
        rel = path.relative_to(BASE)
        suffix = path.suffix.lower()

        lines.append(f"### `{rel}`")
        lines.append("")

        if suffix not in TEXT_EXT and suffix != "":
            lines.append(f"_Бинарный или нетекстовый файл: {path.suffix or 'без расширения'}_")
            lines.append("")
            continue

        content = read_file(path)
        lang = {
            ".py": "python",
            ".md": "markdown",
            ".json": "json",
            ".bat": "batch",
            ".cmd": "batch",
            ".html": "html",
            ".css": "css",
            ".js": "javascript",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".toml": "toml",
            ".ps1": "powershell",
            ".sh": "bash",
            ".ini": "ini",
            ".cfg": "ini",
        }.get(suffix, "")

        lines.append(f"```{lang}")
        lines.append(content.rstrip())
        lines.append("```")
        lines.append("")

    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    size_kb = OUTPUT.stat().st_size / 1024
    print(f"Готово: {OUTPUT}")
    print(f"Размер: {size_kb:.1f} КБ, строк: {len(lines)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### `start_fenix.bat`

```batch
@echo off
cd /d C:\jarvis
start "" pythonw -m jarvis
exit
```

### `start_fenix_debug.bat`

```batch
@echo off
title Феникс
cd /d C:\jarvis
echo ============================================
echo  Феникс запускается...
echo  Чтобы выключить — нажми Ctrl+C
echo ============================================
echo.
python -m jarvis
echo.
echo ============================================
echo  Феникс остановлен.
echo  Нажми любую клавишу, чтобы закрыть окно.
echo ============================================
pause >nul
```

### `system_caps.json`

```json
{
  "volume": {
    "available": true,
    "method": "volume_percent"
  },
  "brightness": {
    "available": true,
    "method": "sbc"
  },
  "layout": {
    "available": true,
    "method": "sendinput"
  },
  "cpu": {
    "available": true,
    "cores": 6,
    "threads": 12,
    "power": "strong",
    "recommended_piper": "high"
  },
  "checked_at": 1791272042.5586116
}
```

### `test_intents.py`

```python
"""Автотест Феникса без микрофона.

Прогоняет список команд через IntentHandler, проверяет ответы
по ожидаемым подстрокам, пишет всё в logs/test_intents.log.

По умолчанию:
    - Без LLM (Brain не создаётся). Хочешь с LLM — флаг --llm.
    - Без озвучки. Хочешь озвучку — флаг --voice.
    - Без сети (тесты погоды/курса пропускаются). Хочешь сеть — флаг --network.

Запуск:
    python test_intents.py                  # правила, без LLM, без сети, без озвучки
    python test_intents.py --llm            # + LLM (нужна Ollama)
    python test_intents.py --network        # + тесты погоды/курса (нужна сеть)
    python test_intents.py --llm --network  # всё вместе
    python test_intents.py --voice          # с озвучкой
    python test_intents.py -k weather       # только тесты со словом 'weather'
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Принудительно UTF-8 для stdout/stderr — иначе на CI (Windows, cp1252)
# падает UnicodeEncodeError при печати русских букв.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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


# =================================================================
# Setup / teardown для тестов, которым нужно особое окружение.
# Возвращают (setup, teardown), либо None.
# =================================================================

def _no_password_setup(handler):
    """Временно выставить danger_password = "" — сценарий без пароля."""
    handler._saved_password = handler.config.get("danger_password", "")
    handler.config.set("danger_password", "")


def _no_password_teardown(handler):
    """Вернуть пароль как было."""
    handler.config.set("danger_password", getattr(handler, "_saved_password", ""))
    handler._saved_password = ""


def _with_password_setup(handler):
    """Временно выставить danger_password = 'test_password_123'."""
    handler._saved_password = handler.config.get("danger_password", "")
    handler.config.set("danger_password", "test_password_123")


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
    # danger_no_password: setup ставит пароль пустым — команда уходит в profile.delete.
    ("danger_no_password",  "удали профиль тест",
     ["не найден", "активен", "удалён"],
     False, False, (_no_password_setup, _no_password_teardown)),

    # danger_with_password: setup ставит пароль — команда уходит в _ask_password.
    ("danger_with_password", "удали профиль тест",
     ["пароль"],
     False, False, (_with_password_setup, _no_password_teardown)),

    # === Learning (5.3) ===
    ("learn_fact",          "запомни: мой город Казань",  ["Запомнил"],              False, False, None),
    ("learn_fact_query",    "что ты обо мне знаешь",      ["Казань", "Знаю"],        False, False, None),
    ("learn_correction",    "это не то, я сказал логи",   ["Понял", "запомнил", "Что было"], False, False, None),
]


class Result:
    def __init__(self, name, cmd, reply_text, expected, elapsed):
        self.name = name
        self.cmd = cmd
        self.reply_text = reply_text
        self.expected = expected
        self.elapsed = elapsed
        self.passed = self._check()
        self.error = None

    def _check(self):
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
            handler.finalize_stream(cmd, reply_text)
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
    parser.add_argument("-k", "--filter",
                        help="Фильтр по имени теста")
    args = parser.parse_args()

    log.info("=" * 70)
    log.info("АВТОТЕСТ ФЕНИКСА")
    log.info("LLM: %s | Сеть: %s | Озвучка: %s",
             "вкл" if args.llm else "выкл",
             "вкл" if args.network else "выкл",
             "вкл" if args.voice else "выкл")
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
```

### `tests\test_caps.py`

```python
"""Тесты check_caps: структура system_caps.json."""
import json

from scripts import check_caps


def test_check_volume_structure():
    r = check_caps.check_volume()
    assert "available" in r
    assert "method" in r
    assert isinstance(r["available"], bool)


def test_check_brightness_structure():
    r = check_caps.check_brightness()
    assert "available" in r
    assert "method" in r


def test_check_layout_structure():
    r = check_caps.check_layout()
    assert "available" in r
    assert "method" in r
```

### `tests\test_config_manager.py`

```python
"""Тесты config_manager: параллельная запись не рвёт файл."""
import json
import threading
import time
from pathlib import Path

from jarvis import config_manager


def test_parallel_writes(tmp_path):
    """20 потоков пишут разные ключи — все должны сохраниться."""
    target = tmp_path / "test.json"
    config_manager.save({}, path=target)

    def writer(i):
        config_manager.update(f"key_{i}", i, path=target)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    data = json.loads(target.read_text(encoding="utf-8"))
    present = [k for k in data if k.startswith("key_")]
    assert len(present) == 20, f"Потерялись ключи: {present}"


def test_atomic_write_valid_json(tmp_path):
    """Если файл есть — он всегда валидный JSON."""
    target = tmp_path / "test.json"
    for i in range(50):
        config_manager.update("counter", i, path=target)
        data = json.loads(target.read_text(encoding="utf-8"))
        assert "counter" in data


def test_load_nonexistent(tmp_path):
    """Несуществующий файл — возвращает {}."""
    assert config_manager.load(path=tmp_path / "nope.json") == {}


def test_load_broken(tmp_path):
    """Битый файл — возвращает {}, не падает."""
    bad = tmp_path / "bad.json"
    bad.write_text("{это не json", encoding="utf-8")
    assert config_manager.load(path=bad) == {}
```

### `tests\test_weather.py`

```python
"""Тесты weather: структура ответов, describe_*, geocode с моками.

Сеть не нужна — мокаем _http_get_json.
"""

from unittest.mock import patch

from jarvis import weather


# --- describe_weather ------------------------------------------------------

def test_describe_weather_none():
    assert "Не удалось" in weather.describe_weather(None)


def test_describe_weather_today():
    w = {
        "city": "Москва", "country": "Россия", "day": "сегодня",
        "temp": 5, "feels": 2, "code": 3, "wind": 4,
        "humidity": 70, "temp_min": 1, "temp_max": 8, "precip": 0.2,
    }
    s = weather.describe_weather(w)
    assert "Москва" in s
    assert "5 градусов" in s
    assert "Россия" in s


def test_describe_weather_tomorrow():
    w = {
        "city": "Казань", "country": "Россия", "day": "завтра",
        "temp_min": -2, "temp_max": 3, "code": 71, "precip": 1.5,
    }
    s = weather.describe_weather(w)
    assert "Казань" in s
    assert "завтра" in s


# --- describe_currency -----------------------------------------------------

def test_describe_currency_specific():
    rates = {
        "date": "2026-10-04",
        "valutes": {
            "USD": {"name": "Доллар США", "value": 83.48, "nominal": 1},
            "BYN": {"name": "Белорусский рубль", "value": 27.5, "nominal": 1},
        },
    }
    s = weather.describe_currency(rates, code="BYN")
    assert "Белорусский" in s
    assert "27.50" in s


def test_describe_currency_default():
    rates = {
        "date": "2026-10-04",
        "valutes": {
            "USD": {"name": "Доллар США", "value": 83.48, "nominal": 1},
            "EUR": {"name": "Евро", "value": 94.32, "nominal": 1},
        },
    }
    s = weather.describe_currency(rates)
    assert "Доллар" in s and "Евро" in s


def test_describe_currency_unknown():
    rates = {"date": "2026-10-04", "valutes": {}}
    s = weather.describe_currency(rates, code="XXX")
    assert "не нашёл" in s


# --- geocode с моками ------------------------------------------------------

def test_geocode_ok():
    """geocode возвращает нормализованный dict при успешном ответе."""
    fake = {
        "results": [{
            "name": "Москва",
            "country": "Россия",
            "admin1": "Москва",
            "latitude": 55.75,
            "longitude": 37.62,
        }],
    }
    with patch.object(weather, "_http_get_json", return_value=fake):
        weather._CACHE.clear()
        geo = weather.geocode("Москва")
    assert geo is not None
    assert geo["name"] == "Москва"
    assert geo["country"] == "Россия"
    assert geo["lat"] == 55.75
    assert geo["lon"] == 37.62


def test_geocode_not_found():
    """geocode возвращает None, если результатов нет."""
    with patch.object(weather, "_http_get_json", return_value={"results": []}):
        weather._CACHE.clear()
        assert weather.geocode("НесуществующийГород12345") is None


def test_geocode_http_error():
    """geocode возвращает None, если _http_get_json вернул None (сеть упала)."""
    with patch.object(weather, "_http_get_json", return_value=None):
        weather._CACHE.clear()
        assert weather.geocode("Москва") is None


# --- _get_weather_uncached с моками ----------------------------------------

def test_get_weather_today_ok():
    """get_weather парсит ответ open-meteo и возвращает dict."""
    geo = {"name": "Москва", "country": "Россия", "lat": 55.75, "lon": 37.62}
    api = {
        "current": {
            "temperature_2m": 5.4,
            "apparent_temperature": 2.1,
            "weather_code": 3,
            "wind_speed_10m": 4.2,
            "relative_humidity_2m": 70,
        },
        "daily": {
            "temperature_2m_min": [1.0, -2.0],
            "temperature_2m_max": [8.0, 3.0],
            "weather_code": [3, 71],
            "precipitation_sum": [0.2, 1.5],
        },
    }
    with patch.object(weather, "geocode", return_value=geo), \
         patch.object(weather, "_http_get_json", return_value=api):
        weather._CACHE.clear()
        w = weather.get_weather("Москва", day="today")
    assert w is not None
    assert w["city"] == "Москва"
    assert w["temp"] == 5
    assert w["feels"] == 2
    assert w["code"] == 3
    assert w["wind"] == 4
    assert w["humidity"] == 70
    assert w["temp_min"] == 1
    assert w["temp_max"] == 8


def test_get_weather_tomorrow_ok():
    """get_weather(day='tomorrow') берёт индексы [1] из daily."""
    geo = {"name": "Казань", "country": "Россия", "lat": 55.79, "lon": 49.11}
    api = {
        "current": {
            "temperature_2m": 5.4, "apparent_temperature": 2.1,
            "weather_code": 3, "wind_speed_10m": 4.2, "relative_humidity_2m": 70,
        },
        "daily": {
            "temperature_2m_min": [1.0, -2.0],
            "temperature_2m_max": [8.0, 3.0],
            "weather_code": [3, 71],
            "precipitation_sum": [0.2, 1.5],
        },
    }
    with patch.object(weather, "geocode", return_value=geo), \
         patch.object(weather, "_http_get_json", return_value=api):
        weather._CACHE.clear()
        w = weather.get_weather("Казань", day="tomorrow")
    assert w is not None
    assert w["day"] == "завтра"
    assert w["temp_min"] == -2
    assert w["temp_max"] == 3
    assert w["code"] == 71


def test_get_weather_no_geocode():
    """Если geocode не нашёл город — get_weather возвращает None."""
    with patch.object(weather, "geocode", return_value=None):
        weather._CACHE.clear()
        assert weather.get_weather("НесуществующийГород12345") is None


# --- get_currency_rates с моками -------------------------------------------

def test_get_currency_rates_ok():
    """get_currency_rates парсит ответ ЦБ."""
    api = {
        "Date": "2026-10-04T11:30:00+03:00",
        "Valute": {
            "USD": {"Name": "Доллар США", "Value": 83.48, "Nominal": 1},
            "EUR": {"Name": "Евро", "Value": 94.32, "Nominal": 1},
            "BYN": {"Name": "Белорусский рубль", "Value": 27.5, "Nominal": 1},
        },
    }
    with patch.object(weather, "_http_get_json", return_value=api):
        weather._CACHE.clear()
        r = weather.get_currency_rates()
    assert r is not None
    assert r["date"] == "2026-10-04"
    assert r["valutes"]["USD"]["value"] == 83.48
    assert r["valutes"]["BYN"]["name"] == "Белорусский рубль"


def test_get_currency_rates_http_error():
    """get_currency_rates возвращает None при падении сети."""
    with patch.object(weather, "_http_get_json", return_value=None):
        weather._CACHE.clear()
        assert weather.get_currency_rates() is None


# --- кэш -------------------------------------------------------------------

def test_cache_used():
    """Второй вызов geocode не дёргает _http_get_json — берёт из кэша."""
    fake = {
        "results": [{
            "name": "Москва", "country": "Россия",
            "latitude": 55.75, "longitude": 37.62,
        }],
    }
    weather._CACHE.clear()
    with patch.object(weather, "_http_get_json", return_value=fake) as mock:
        weather.geocode("Москва")
        weather.geocode("Москва")
    assert mock.call_count == 1, "Второй вызов должен брать из кэша"


def test_cache_different_cities():
    """Разные города — разные ключи кэша, _http_get_json вызывается дважды."""
    fake_msk = {
        "results": [{"name": "Москва", "country": "Россия",
                     "latitude": 55.75, "longitude": 37.62}],
    }
    fake_kzn = {
        "results": [{"name": "Казань", "country": "Россия",
                     "latitude": 55.79, "longitude": 49.11}],
    }
    weather._CACHE.clear()
    with patch.object(weather, "_http_get_json") as mock:
        mock.side_effect = [fake_msk, fake_kzn]
        weather.geocode("Москва")
        weather.geocode("Казань")
    assert mock.call_count == 2
```

### `вкладка`

```
    Win+R - - - "Экран"
```
