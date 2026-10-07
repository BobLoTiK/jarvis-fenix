# 🏗 Архитектура «Феникс»

Документ описывает модули проекта, их роль и связи.
Помогает быстро вникнуть в проект — человеку или LLM.

---

## 🗂 Два корня путей

```
PROGRAM_DIR — C:\ProgramData\Phoenix\   (ASCII, для Vosk/Whisper)
USER_DIR    — %APPDATA%\Phoenix\         (личные данные юзера)
```

**Почему:** Vosk (C++ на Kaldi) **ломается** на не-ASCII путях
(`C:\Users\Максим\...`). Поэтому модель Vosk и кэш Whisper — **всегда
в `PROGRAM_DIR`** (ASCII). Остальное — в `USER_DIR` (кириллица ок).

Управляет **`jarvis/paths.py`**:

```
paths.program_dir()               → C:\ProgramData\Phoenix
paths.user_dir()                  → %APPDATA%\Phoenix
paths.program_models_dir()        → C:\ProgramData\Phoenix\models
paths.program_whisper_cache_dir() → C:\ProgramData\Phoenix\whisper-cache
paths.logs_dir()                  → %APPDATA%\Phoenix\logs
paths.profiles_dir()              → %APPDATA%\Phoenix\profiles
paths.config_path()               → %APPDATA%\Phoenix\config.json
```

**Fallback для PROGRAM_DIR:**
1. `C:\ProgramData\Phoenix`
2. `C:\Phoenix`
3. `%TEMP%\Phoenix`
4. `<рядом с exe>\runtime`

**В `USER_DIR` теперь также живут:**
- `timers.json` — напоминания.
- `tasks.json` — задачи.
- `dialog.json` — в `profiles/<user>/`.

---

## Карта модулей

```
jarvis/
├── main.py           — точка входа, Jarvis, barge-in, cmd_lock
├── config.py         — Config в памяти + подписки
├── config_manager.py — атомарная запись (FileLock per-path)
├── paths.py          — PROGRAM_DIR / USER_DIR
├── brain.py          — Ollama: parse() / chat_stream()
├── intents.py        — IntentHandler: правила + LLM + _fast_handlers()
├── reply.py          — Reply (text | stream)
├── gui.py            — Flet GUI + PALETTES + fireworks
├── history.py        — стек отмены
├── stt.py            — Vosk (wake) + Whisper, HF_HOME временно
├── tts.py            — Piper / XTTS / WinRT / SAPI, per-call token
├── modes.py          — commands / llm / combo
├── voices.py         — смена голоса Piper
├── packs.py          — загрузка/выгрузка паков
├── profile.py        — profiles/<user>/profile.json + subscribe
├── memory.py         — profiles/<user>/dialog.json (атомарно)
├── learning.py       — факты + коррекции
├── weather.py        — погода/курс + настраиваемый TTL
├── timers.py         — напоминания (USER_DIR, атомарно)
├── tasks.py          — задачи (USER_DIR, атомарно)
├── actions.py        — окна, медиа, _looks_like_cmd, _activate_window_hard
├── text_utils.py     — normalize(), strip_cjk(), prepare_text()
├── celebrations.py   — поздравление с ДР + двойной салют
├── files.py          — папки (Desktop, Downloads, ...)
├── apps.py           — каталог приложений
├── installed.py      — индекс меню «Пуск»
├── steam.py          — индекс игр Steam
├── matching.py       — нечёткое сравнение + транслитерация
├── model.py          — загрузка Vosk (всегда в ASCII-путь)
├── recorder.py       — запись макросов
├── tray.py           — трей (временно отключён)
├── uia.py            — UI Automation (в планах, Этап 1.10)
├── vision.py         — VLM-зрение (в планах, Этап 10)
├── hermes.py         — мост к Hermes (в планах, Этап 11)
└── resources.py      — приоритеты и очередь (в планах, Этап 12)
```

---

## Поток обработки фразы

```
Микрофон
   ↓
stt.Listener (Vosk) — ловит wake-слово
   ↓
stt.WhisperTranscriber — уточняет (HF_HOME временно → ASCII)
   ↓
main.Jarvis._process → извлекает команду (без wake)
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
   ├── celebrations.match_celebration (ДР)
   ├── _split_compound (многослойные)
   ├── ⚡ РЕЕСТР _fast_handlers()
   │   ├── custom, small_talk, music, open_profile
   │   ├── open, voices, packs, timers, tasks
   │   └── profile, memory, system, debug, correction,
   │       undo, weather_currency
   ├── brain.parse(cmd) → intent → _execute_intent
   └── brain.chat_stream() → генератор
   ↓
main.Jarvis.say(reply) ← cmd_lock
   ├── если text → speaker.play_async()
   └── если stream → speaker.speak_stream() + tee → gui.add_stream_chunk()
   ↓
tts.Speaker → Piper / XTTS / WinRT / SAPI
```

---

## Реестр быстрых обработчиков

`IntentHandler._fast_handlers()` — **список `(имя, функция)`**. Порядок = приоритет.

Каждый: `(cmd: str) -> str | None`. Вернул строку — команда обработана. `None` — идём дальше.

**Правило:** специфичные — **выше** общих. `open_profile` — **выше** `open`.

**Кэш:** список строится **один раз** в `__init__` (`self._fast_handlers_cache`).

**Исключения** в обработчике **логируются**, но **не роняют** команду.

---

## Универсальный профиль (set_profile / get_profile)

**Раньше:** куча `re.match` под каждую фразу. **Костыли.**

**Сейчас:** LLM **сама разбирает**:

```
«меня зовут Максим» → {"action": "set_profile", "key": "name", "value": "Максим"}
«какой город»       → {"action": "get_profile", "key": "default_city"}
```

**Regex `_profile_fast`:** **тире обязательно** — `я\s*[-—]\s*Имя`.
Голое `я ` **не матчится** (иначе «я хочу спать» создаёт профиль).

---

## GUI (Flet 1.0.3)

```
Flet Main Thread
   ├── NavigationRail (слева): Главная / Микрофон / Настройки
   ├── Контент-область (кеш _tabs)
   ├── page.run_task(_process_queue)
   └── page.run_task(_mic_level_loop)

Jarvis Thread
   ├── listener.phrases() → _process(cmd) ← cmd_lock
   ├── handler.handle(cmd) → Reply
   └── say(reply) ← cmd_lock
```

**Связь:** `queue.Queue()` → `gui._queue`.
**Важно:** Flet — **в главном потоке** (`gui.run_main()`), Jarvis — **в фоне**.

### Режим запуска

```json
"launch_mode": "gui"
```

- `"gui"` — окно видимо (по умолчанию).
- `"tray"` — окно скрыто. **Трей отключён**, `main.py` принудительно `"gui"`.

### Трей (отключён)

**Причина:** pystray требует **свой Windows message loop**, а главный поток
**занят flet'ом**. Позже — отдельный процесс `tray_runner.py`.

### Темы GUI

```
PALETTES = { "dark": {...}, "light": {...} }
_apply_palette(name)
_detect_system_theme() — HKCU\...\AppsUseLightTheme
_mic_level_loop → раз в 5 сек проверяет тему Windows
_rebuild_ui_for_theme → сохраняет историю чата
```

### Вкладка «Микрофон»

- `Listener.current_rms` — RMS.
- `Listener.peak` — пик за сессию.
- `Listener.utterances` — распознано.
- `_on_mic_test` — **через очередь** (`set_mic_test_result`).
- `mic_watchdog` → `("open_mic_tab", None)`.

### Салют (праздничный)

- `gui.launch_fireworks(duration)` — кладёт в очередь.
- `_launch_fireworks_async(duration)` — анимация через **Stack + Container** (не Canvas — API капризный).
- `n_bursts` зависит от длительности.

### Иконка окна

`jarvis/icon.ico` → `page.window.icon`.

---

## Мультипрофиль

```
%APPDATA%\Phoenix\profiles\
├── <user1>\
│   ├── profile.json    ← name, default_city, facts, tts_voice
│   └── dialog.json
└── <user2>\
```

- Активный профиль — по имени Windows-юзера.
- `profile.switch(name)` — один `RLock`.
- `profile.subscribe(callback)` — подписка (old_name, new_name).
- Миграция из старого `user_profile.json`.

---

## Поток конфига

```
%APPDATA%\Phoenix\config.json → Config.__init__ → config_manager.load()
   ↓
Config._data (в памяти) — источник истины
   ↓
config.get("key") / config.set("key", value)
   ├── config_manager.save() — атомарно
   │   ├── OK → оповещение подписчиков
   │   └── FAIL → откат в памяти (Config.set/update)
   └── ...
```

**Подписки:**
- `Config.subscribe(callback)` — добавить.
- `Config.unsubscribe(callback)` — удалить.

---

## Погода и курс валют

```
weather.py
   ├── _CACHE: dict — (key, timestamp, data)
   ├── _CACHE_LOCK: threading.Lock
   ├── _config — ссылка на Config (set_config)
   ├── _current_ttl() — читает weather_cache_ttl_sec каждый раз
   ├── _cached(key, fetcher) — TTL применяется на каждый вызов
   └── _http_get_json — User-Agent из __version__
```

**TTL:** 600 сек (10 мин) по умолчанию.

---

## Открытие файлов в редакторе

```
actions.open_in_editor(path, prefer="auto")
   ├── "notepad++" → _find_notepadpp()
   ├── "vscode"    → _find_vscode()
   ├── "system"    → os.startfile()
   └── "auto"      → [_find_notepadpp, _find_vscode] → os.startfile()
```

**Активация окна** — `_activate_window_hard(title_part)`:
- `win32gui.EnumWindows`
- `AttachThreadInput` (обход блокировки `SetForegroundWindow`)
- `SetForegroundWindow` + `BringWindowToTop`

---

## Пак-команды с аргументами

```
actions.spec_from_string(s)
   ├── open_app: → ...
   ├── http(s):// → url
   ├── steam:// → uri
   ├── browser/браузер → browser
   ├── _looks_like_cmd(s) → ("cmd", shlex.split(s, posix=False))
   │   (для "shutdown /s /t 10", "cmd /k ipconfig", "rundll32.exe ...")
   ├── .bat/.cmd → path
   └── os.path.exists(s) → path
```

**`_CMD_VERBS`** — известные системные команды (shutdown, cmd, rundll32, ...).

**Zip Slip защита** — при распаковке Vosk: `resolved.is_relative_to(base)`.

---

## Лаунчер (Феникс.exe)

`launcher.py` → `Феникс.exe` (PyInstaller). При запуске:

```
1. Ищет Python 3.10–3.12.
2. Нет → MessageBox: [Скачать Python 3.11] [Отмена].
3. Проверяет .venv311. Нет → создаёт.
4. Проверяет зависимости (flet, vosk). Нет → pip install.
5. Проверяет Vosk-модель в C:\ProgramData\Phoenix\models.
6. Проверяет Ollama.
7. Запускает .venv311\Scripts\pythonw.exe -m jarvis.
```

- **Диалоги** — `ctypes.windll.user32.MessageBoxW`.
- **Логи** — `logs/launcher.log`.
- **Мьютекс** — `Local\JarvisPhoenixSingleInstance` (без админа).
- **Zip Slip защита** при распаковке Vosk.

---

## Ключевые объекты

| Объект | Модуль | Роль |
|---|---|---|
| `Config` | `config.py` | Конфиг в памяти + подписки |
| `IntentHandler` | `intents.py` | Разбор, `_fast_handlers()` |
| `Brain` | `brain.py` | LLM: `parse()` / `chat_stream()` |
| `Speaker` | `tts.py` | Синтез, per-call token |
| `Listener` | `stt.py` | Vosk, ring buffer |
| `WhisperTranscriber` | `stt.py` | Расшифровка |
| `Jarvis` | `main.py` | Связка, wake, cmd_lock |
| `FenixGUI` | `gui.py` | Flet GUI, fireworks |
| `Reply` | `reply.py` | `text` \| `stream` |
| `history` | `history.py` | Стек отмены |
| `celebrations` | `celebrations.py` | Поздравление с ДР |

---

## Файлы данных

| Файл | Где |
|---|---|
| `config.json` | `%APPDATA%\Phoenix\` |
| `profiles/<user>/profile.json` | `%APPDATA%\Phoenix\` |
| `profiles/<user>/dialog.json` | `%APPDATA%\Phoenix\` |
| `timers.json` / `tasks.json` | `%APPDATA%\Phoenix\` |
| `models/vosk-model-small-ru-0.22/` | `C:\ProgramData\Phoenix\` |
| `whisper-cache/` | `C:\ProgramData\Phoenix\` |
| `logs/` | `%APPDATA%\Phoenix\` |
| `system_caps.json` | `C:\jarvis\` (только dev) |

---

## Внешние зависимости

| Сервис | URL | Зачем |
|---|---|---|
| Ollama | `http://127.0.0.1:11434` | LLM |
| open-meteo.com | `geocoding-api.open-meteo.com` | Геокодинг |
| open-meteo.com | `api.open-meteo.com` | Погода |
| cbr-xml-daily.ru | `www.cbr-xml-daily.ru` | Курс ЦБ |
| HuggingFace | `rhasspy/piper-voices` | Голоса Piper |
| HuggingFace | `deepdml/faster-whisper-large-v3-turbo-ct2` | Whisper |
| alphacephei.com | `vosk-model-small-ru-0.22` | Vosk |
| python.org | `python-3.11.9-amd64.exe` | Установщик Python |

**Облачные (в планах):** Groq, Edge TTS.

---

## Тесты

- **`test_intents.py`** — 40 сценариев.
- **`tests/test_config_manager.py`** — параллельная запись.
- **`tests/test_weather.py`** — погода/курс с моками.
- **`tests/test_caps.py`** — структура `system_caps.json`.

---

## Инфраструктура

### `.venv311`
**Python 3.11** в отдельном venv — обход падения Vosk на 3.13/3.14.

### Git
- **`.gitignore`:** `.venv311/`, `config.json`, `profiles/`, `logs/`, `system_caps.json`, `models/`, `voices/`, `dist/`, `build/`, `timers.json`, `tasks.json`, `*.bak`.
- **`SNAPSHOT.md`** — генерируется `snapshot.py`.

### `commit.bat`
Активирует `.venv311` → `snapshot.py` → `git add .` → `commit` → `push`.

---

## Сборка и установка

### `scripts/make_icon.py`
Генерирует `jarvis/icon.ico` (16/24/32/48/64/128/256). Синий круг с «J».

### `scripts/build_exe.py`
Собирает `launcher.py` → `dist/Феникс.exe` (~9 МБ) + копия в корень.

### `installer.iss`
Inno Setup → `Феникс_Setup.exe` (~11 МБ). Ставит в `C:\ProgramData\Phoenix`. Ярлыки, автозапуск, деинсталлятор.

### `create_shortcut.bat`
Создаёт ярлык на рабочем столе для `Феникс.exe`.

---

## Что важно помнить при доработке

1. **Не читай `config.json` напрямую** — `config.get()`.
2. **Не пиши в `config.json` напрямую** — `Config.set()` или `config_manager.save()`.
3. **Не плоди глобальное состояние** — кроме `Config._GLOBAL`.
4. **Нормализация (города, валюты, паков) — задача LLM.**
5. **Логи в `actions.log`** — главный инструмент отладки.
6. **`test_intents.py`** — первое, что запускаешь после правок.
7. **GUI Flet — только в главном потоке.** Jarvis — в фоне.
8. **Связь GUI ↔ Jarvis — через `queue.Queue()`.**
9. **`normalize(cmd)` в `IntentHandler.handle()`** — единая точка.
10. **Per-call stop-token в `tts.py`.**
11. **`PALETTES` в `gui.py`** — две темы.
12. **`ft.Button`** вместо `ElevatedButton`/`TextButton`.
13. **`ft.BoxShadow`** — без `blur_style`.
14. **Личные данные — только в `config.json`, `profiles/`, `system_caps.json`.**
15. **`weather_cache_ttl_sec`** — настраиваемый TTL.
16. **Python 3.10–3.12** — только `.venv311`.
17. **`snapshot.py`** — исключать `.venv311` и `profiles/`.
18. **Реестр `_fast_handlers()`** — новые правила **туда**.
19. **`open_profile` — выше `open`.**
20. **`set_profile` / `get_profile`** — через LLM.
21. **Активация окон — `win32gui` + `AttachThreadInput`.**
22. **`paths.py`** — единственное место для путей.
23. **Модели Vosk/Whisper — ВСЕГДА в `PROGRAM_DIR` (ASCII).**
24. **`HF_HOME` для Whisper — временно.**
25. **Vosk API — только из listener-потока.**
26. **Pack-команды с аргументами — `_looks_like_cmd` + `shlex`.**
27. **Атомарная запись везде — `mkstemp` + `os.replace`.**
28. **Zip Slip защита при распаковке.**
29. **`cmd_lock` в Jarvis — сериализация голос↔GUI.**
30. **`Local\` мьютекс — без админа.**