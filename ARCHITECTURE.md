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