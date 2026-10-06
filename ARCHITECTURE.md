# 🏗 Архитектура «Феникс»

Документ описывает модули проекта, их роль и связи.
Помогает быстро вникнуть в проект — человеку или LLM.

---

## 🗂 Два корня путей

```
PROGRAM_DIR — C:\ProgramData\Phoenix\   (ASCII, для Vosk/Whisper)
USER_DIR    — %APPDATA%\Phoenix\         (личные данные юзера)
```

**Почему:** Vosk (C++ на Kaldi) **ломается** на не-ASCII путях (`C:\Users\Максим\...`). Поэтому модель Vosk и кэш Whisper — **всегда в `PROGRAM_DIR`** (ASCII). Остальное — в `USER_DIR` (кириллица ок — Vosk не читает).

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

**Fallback для PROGRAM_DIR** (если ProgramData недоступен или не-ASCII):
1. `C:\ProgramData\Phoenix`
2. `C:\Phoenix`
3. `%TEMP%\Phoenix`
4. `<рядом с exe>\runtime`

---

## Карта модулей

```
jarvis/
├── main.py           — точка входа, Jarvis, barge-in
├── config.py         — Config в памяти + подписки
├── config_manager.py — атомарная запись (FileLock, mkstemp, os.replace)
├── paths.py          — PROGRAM_DIR / USER_DIR
├── brain.py          — Ollama: parse() и chat_stream()
├── intents.py        — IntentHandler: правила + LLM + _fast_handlers()
├── reply.py          — Reply (text | stream)
├── gui.py            — Flet GUI + PALETTES + _detect_system_theme()
├── history.py        — стек отмены («стоп, не то»)
├── stt.py            — Vosk + Whisper + ring buffer, HF_HOME → ASCII
├── tts.py            — Piper / XTTS / WinRT / SAPI + barge-in + per-call token
├── modes.py          — commands / llm / combo
├── voices.py         — смена голоса Piper
├── packs.py          — загрузка/выгрузка паков
├── profile.py        — profiles/<user>/profile.json + subscribe
├── memory.py         — profiles/<user>/dialog.json
├── learning.py       — факты + коррекции
├── weather.py        — погода + курс + настраиваемый TTL
├── timers.py         — напоминания
├── tasks.py          — списки задач
├── actions.py        — окна, медиа, печать, буфер, громкость, яркость, раскладка,
│                       open_in_editor, _activate_window_hard
├── text_utils.py     — normalize(), strip_cjk(), strip_cjk_chunk(), prepare_text()
├── files.py          — папки (Desktop, Downloads, ...)
├── apps.py           — каталог приложений
├── installed.py      — индекс меню «Пуск»
├── steam.py          — индекс игр Steam
├── matching.py       — нечёткое сравнение + транслитерация
├── model.py          — загрузка Vosk (всегда в ASCII-путь)
├── recorder.py       — запись макросов
└── tray.py           — иконка в трее (временно отключён)
```

---

## Поток обработки фразы

```
Микрофон
   ↓
stt.Listener (Vosk) — ловит wake-слово
   ↓
stt.WhisperTranscriber — уточняет расшифровку (HF_HOME → ASCII)
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

**Кэш:** список строится **один раз** в `__init__` (`self._fast_handlers_cache`).

**Исключения** в обработчике **логируются** через `log.exception`, но **не роняют** команду.

---

## Универсальный профиль (set_profile / get_profile)

**Раньше:** куча `re.match` под каждую фразу — «мой город X», «меня зовут Y», ... **Костыли.**

**Сейчас:** LLM **сама разбирает**:

```
«меня зовут Максим» → {"action": "set_profile", "key": "name", "value": "Максим"}
«какой город»       → {"action": "get_profile", "key": "default_city"}
```

**В `brain.py`** — action'ы в `ACTIONS` + примеры в промптах.
**В `intents._execute_intent`** — обработка с `key_map` для синонимов.

---

## GUI (Flet 1.0.3)

```
Flet Main Thread
   ├── NavigationRail (слева): Главная / Микрофон / Настройки
   ├── Контент-область (кеш _tabs)
   ├── page.run_task(_process_queue)
   └── page.run_task(_mic_level_loop)

Jarvis Thread
   ├── listener.phrases() → _process(cmd)
   ├── handler.handle(cmd) → Reply
   └── say(reply):
       ├── text → gui.add_message("assistant", text)
       └── stream → tee → gui.add_stream_chunk(chunk)
```

**Связь:** `queue.Queue()` → `gui._queue`.
**Важно:** Flet — **в главном потоке** (`gui.run_main()`), Jarvis — **в фоне**.

### Режим запуска

**`config.json`:**
```json
"launch_mode": "gui"
```

- `"gui"` — окно видимо (по умолчанию).
- `"tray"` — окно скрыто. **Но:** трей сейчас отключён, `main.py` принудительно переключает на `"gui"`.

### Трей (отключён)

**Причина:** pystray требует **свой Windows message loop**, а главный поток **занят flet'ом**. Запуск pystray в фоне — **зависает GUI**.

**Позже:** отдельный процесс `tray_runner.py` с обменом через файл-сигнал.

### Темы GUI

```
PALETTES = { "dark": {...}, "light": {...} }
_apply_palette(name) — подменяет глобальные BG_DARK, TEXT, ACCENT
_detect_system_theme() — HKCU\...\AppsUseLightTheme (0=dark, 1=light)
_mic_level_loop → раз в 5 сек проверяет тему Windows (если gui_theme = "Системная")
_rebuild_ui_for_theme → сохраняет историю чата перед пересборкой
```

### Вкладка «Микрофон»

- `Listener.current_rms` — RMS, обновляется в `_callback`.
- `Listener.peak` — пик за сессию.
- `Listener.utterances` — распознано фраз.
- `_on_mic_test` — 3 сек, порог ≥500 ✅, ≥100 ⚠️, <100 ❌.
- `mic_watchdog` → `("open_mic_tab", None)` в очередь GUI.

### Иконка окна

`jarvis/icon.ico` генерируется `scripts/make_icon.py`. Подключена в `_main()` через `page.window.icon`.

---

## Мультипрофиль

```
%APPDATA%\Phoenix\profiles\
├── <user1>\
│   ├── profile.json    ← name, default_city, facts, tts_voice
│   └── dialog.json     ← история диалога
├── <user2>\
│   ├── profile.json
│   └── dialog.json
```

- **Активный профиль** — по имени Windows-юзера (`getpass.getuser()`).
- **`profile.switch(name)`** — один `RLock`.
- **`profile.subscribe(callback)`** — подписка (old_name, new_name).
- **Миграция** из старого `user_profile.json`.

**Универсальные команды:**
- «меня зовут X» → `set_profile` → `name`.
- «мой город Y» → `set_profile` → `default_city`.
- «открой профиль» → `open_profile` → Notepad++ / VS Code / системный.

---

## Поток конфига

```
%APPDATA%\Phoenix\config.json → Config.__init__ → config_manager.load()
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

```
weather.py
   ├── _CACHE: dict — (key, timestamp, data)
   ├── _CACHE_LOCK: threading.Lock
   ├── _config — ссылка на Config (set_config)
   ├── _current_ttl() — читает weather_cache_ttl_sec каждый раз
   └── _cached(key, fetcher) — TTL применяется на каждый вызов
```

**TTL:** 600 сек (10 мин) по умолчанию.

**Ключи:**
- `("geo", "москва")` — геокодинг.
- `("weather", "москва", "today")` — погода.
- `("currency", "cbr")` — курс ЦБ.

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
- `AttachThreadInput` — иначе `SetForegroundWindow` блокируется Windows
- `SetForegroundWindow` + `BringWindowToTop`

---

## Лаунчер (Феникс.exe)

`launcher.py` → `Феникс.exe` (PyInstaller). При запуске:

```
1. Ищет Python 3.10–3.12 (py launcher, where python, типичные пути).
2. Нет → MessageBox: [Скачать Python 3.11] [Отмена].
   Качает python-3.11.9-amd64.exe, запускает installer.
3. Проверяет .venv311. Нет → создаёт.
4. Проверяет зависимости (flet, vosk). Нет → pip install.
5. Проверяет Vosk-модель в C:\ProgramData\Phoenix\models. Нет → скачивает.
6. Проверяет Ollama (URL + поиск). Нет → MessageBox.
7. Запускает .venv311\Scripts\pythonw.exe -m jarvis.
```

**Диалоги** — через `ctypes.windll.user32.MessageBoxW` (встроено в Windows).
**Логи** — `logs/launcher.log`.
**Мьютекс** — `Global\JarvisPhoenixSingleInstance`.

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
| `Jarvis` | `main.py` | Связка, wake, watchdog |
| `FenixGUI` | `gui.py` | Flet GUI |
| `Reply` | `reply.py` | `text` \| `stream` |
| `history` | `history.py` | Стек отмены |

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
| `system_caps.json` | `C:\jarvis\` (только для разработки) |

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

**Облачные (в планах):** Groq (Llama 3.3 70B, Whisper), Edge TTS.

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
- **`.gitignore`:** `.venv311/`, `config.json`, `profiles/`, `logs/`, `system_caps.json`, `models/`, `voices/`, `dist/`, `build/`, `*.bak`.
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