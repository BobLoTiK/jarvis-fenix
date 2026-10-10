# 🏗 Архитектура «Феникс»

> Документ описывает модули проекта, их роль и связи.
> Помогает быстро вникнуть в проект — человеку или LLM.

---

## 📑 Содержание

- [🏗 Архитектура «Феникс»](#-архитектура-феникс)
  - [📑 Содержание](#-содержание)
  - [🗂 Два корня путей](#-два-корня-путей)
    - [Fallback для `PROGRAM_DIR`](#fallback-для-program_dir)
    - [В `USER_DIR` также живут](#в-user_dir-также-живут)
  - [🗺 Карта модулей](#-карта-модулей)
  - [🔄 Поток обработки фразы](#-поток-обработки-фразы)
  - [🎓 Онбординг (первый запуск)](#-онбординг-первый-запуск)
  - [👁 Observer (фоновое извлечение фактов)](#-observer-фоновое-извлечение-фактов)
  - [🎭 Персона](#-персона)
  - [💗 Mood](#-mood)
  - [🖥 UIA](#-uia)
  - [⚡ Реестр быстрых обработчиков](#-реестр-быстрых-обработчиков)
  - [👤 Универсальный профиль (`set_profile` / `get_profile`)](#-универсальный-профиль-set_profile--get_profile)
  - [🖼 GUI (Flet 1.0.3)](#-gui-flet-103)
    - [Режим запуска](#режим-запуска)
    - [Трей (отключён)](#трей-отключён)
    - [Темы GUI](#темы-gui)
    - [Подписки GUI](#подписки-gui)
    - [Вкладка «Микрофон»](#вкладка-микрофон)
    - [Салют (праздничный)](#салют-праздничный)
    - [Иконка окна](#иконка-окна)
  - [👥 Мультипрофиль](#-мультипрофиль)
  - [⚙️ Поток конфига](#️-поток-конфига)
  - [🌤 Погода и курс валют](#-погода-и-курс-валют)
  - [📂 Открытие файлов в редакторе](#-открытие-файлов-в-редакторе)
  - [📦 Пак-команды с аргументами](#-пак-команды-с-аргументами)
  - [🚀 Лаунчер (`Феникс.exe`)](#-лаунчер-фениксexe)
  - [🧩 Ключевые объекты](#-ключевые-объекты)
  - [💾 Файлы данных](#-файлы-данных)
  - [🌐 Внешние зависимости](#-внешние-зависимости)
  - [🧪 Тесты](#-тесты)
  - [🏗 Инфраструктура](#-инфраструктура)
    - [`.venv311`](#venv311)
    - [Git](#git)
    - [`commit.bat`](#commitbat)
  - [📦 Сборка и установка](#-сборка-и-установка)
    - [`scripts/make_icon.py`](#scriptsmake_iconpy)
    - [`scripts/make_installer_images.py`](#scriptsmake_installer_imagespy)
    - [`scripts/build_exe.py`](#scriptsbuild_exepy)
    - [`installer.iss`](#installeriss)
    - [`create_shortcut.bat`](#create_shortcutbat)
  - [⚠️ Что важно помнить при доработке](#️-что-важно-помнить-при-доработке)
    - [Код](#код)
    - [GUI](#gui)

---

## 🗂 Два корня путей

~~~~
PROGRAM_DIR — C:\ProgramData\Phoenix\   (ASCII, для Vosk/Whisper)
USER_DIR    — %APPDATA%\Phoenix\         (личные данные юзера)
~~~~

> **Почему:** Vosk (C++ на Kaldi) **ломается** на не-ASCII путях
> (`C:\Users\Максим\...`). Поэтому модель Vosk и кэш Whisper — **всегда
> в `PROGRAM_DIR`** (ASCII). Остальное — в `USER_DIR` (кириллица ок).

**Управляет `jarvis/paths.py`:**

| Метод | Путь |
|---|---|
| `paths.program_dir()` | `C:\ProgramData\Phoenix` |
| `paths.user_dir()` | `%APPDATA%\Phoenix` |
| `paths.program_models_dir()` | `C:\ProgramData\Phoenix\models` |
| `paths.program_whisper_cache_dir()` | `C:\ProgramData\Phoenix\whisper-cache` |
| `paths.logs_dir()` | `%APPDATA%\Phoenix\logs` |
| `paths.profiles_dir()` | `%APPDATA%\Phoenix\profiles` |
| `paths.config_path()` | `%APPDATA%\Phoenix\config.json` |

### Fallback для `PROGRAM_DIR`

1. `C:\ProgramData\Phoenix`
2. `C:\Phoenix`
3. `%TEMP%\Phoenix`
4. `<рядом с exe>\runtime`

### В `USER_DIR` также живут

- `timers.json` — напоминания.
- `tasks.json` — задачи.
- `dialog.json` — в `profiles/<user>/`.

---

## 🗺 Карта модулей

~~~~
jarvis/
├── main.py           — точка входа, Jarvis, barge-in, cmd_lock
├── config.py         — Config в памяти + подписки
├── config_manager.py — атомарная запись (FileLock per-path)
├── paths.py          — PROGRAM_DIR / USER_DIR
├── brain.py          — Ollama: parse() / chat_stream() / onboarding_chat()
├── intents/          — пакет (после рефакторинга)
│   ├── handler.py    — IntentHandler, pipeline, подписки
│   ├── context.py    — Ctx для стадий
│   ├── verbs.py      — COMMAND_VERBS, CANCEL, SEARCH_VERBS
│   ├── password.py   — хеш пароля, миграция, DANGER_ACTIONS
│   ├── sites.py      — SITES из packs/sites.json
│   ├── execute.py    — dispatch: action → функция + UIA-обработчики
│   ├── stages/       — 11 стадий pipeline
│   │   ├── base.py       — class Stage
│   │   ├── cancel.py     — «стоп», «хватит»
│   │   ├── onboarding.py — LLM-диалог + _looks_like_command
│   │   ├── correction.py — learning.find_correction
│   │   ├── password.py   — пароль + «удали профиль»
│   │   ├── memory.py     — dialog
│   │   ├── pending.py    — уточнения
│   │   ├── clipboard.py  — 4 команды буфера
│   │   ├── modes.py      — commands/llm/combo
│   │   ├── compound.py   — «открой стим и запусти доту»
│   │   ├── fast.py       — вызов реестра
│   │   └── llm.py        — brain.parse + chat_stream
│   └── fast/         — 17 быстрых обработчиков
│       ├── custom.py, small_talk.py, music.py, screenshot.py
│       ├── uia.py, open.py, voices.py, packs.py
│       ├── timers.py, tasks.py, persona.py, profile.py
│       ├── memory.py, system.py, debug.py
│       └── undo.py, correction.py, weather.py
├── reply.py          — Reply (text | stream)
├── gui.py            — Flet GUI + PALETTES + fireworks
├── history.py        — стек отмены
├── stt.py            — Vosk (wake) + Whisper, HF_HOME временно
├── tts.py            — Piper / XTTS / WinRT / SAPI, per-call token
├── modes.py          — commands / llm / combo
├── voices.py         — смена голоса Piper
├── packs.py          — загрузка/выгрузка паков
├── profile.py        — profiles/<user>/profile.json + subscribe
├── persona.py        — персона: стиль, черты, backstory
├── mood.py           — эмоциональное состояние (neutral/happy/...)
├── uia.py            — окна, вкладки, кнопки (20+ браузеров)
├── memory.py         — profiles/<user>/dialog.json (атомарно)
├── observer.py       — фоновое извлечение фактов через LLM
├── first_run.py      — greeting, is_first_run, mark_done
├── learning.py       — факты + коррекции
├── weather.py        — погода/курс + настраиваемый TTL
├── timers.py         — напоминания (USER_DIR, атомарно)
├── tasks.py          — задачи (USER_DIR, атомарно)
├── actions.py        — окна, медиа, _looks_like_cmd, _activate_window_hard
├── text_utils.py     — normalize(), strip_cjk(), prepare_text()
├── celebrations.py   — поздравление с ДР (триггеры из config)
├── files.py          — папки (Desktop, Downloads, ...)
├── apps.py           — каталог приложений
├── installed.py      — индекс меню «Пуск»
├── steam.py          — индекс игр Steam
├── matching.py       — нечёткое сравнение + транслитерация
├── model.py          — загрузка Vosk (всегда в ASCII-путь)
├── recorder.py       — запись макросов
├── tray.py           — трей (временно отключён)
└── (vision.py / hermes.py / resources.py — НЕ существуют,
                     это планы на Этап 8, файлов в репозитории нет)
~~~~

---

## 🔄 Поток обработки фразы

~~~~
Микрофон
   ↓
stt.Listener (Vosk) — ловит wake-слово
   ↓
stt.WhisperTranscriber — уточняет (HF_HOME временно → ASCII)
   ↓
main.Jarvis._process → извлекает команду (без wake)
   ↓
intents.IntentHandler.handle(cmd)   ← normalize(cmd)
   ↓
Pipeline (11 стадий, порядок важен):
   ├── cancel       — «стой», «хватит»
   ├── onboarding   — первый запуск, LLM-диалог
   ├── correction   — «это не то, я сказал …»
   ├── password     — пароль / «удали профиль X»
   ├── memory       — «что обсуждали», «забудь всё»
   ├── pending      — уточнения («в каком городе?»)
   ├── clipboard    — 4 команды буфера
   ├── modes        — commands/llm/combo
   ├── compound     — «открой стим и запусти доту»
   ├── fast         — реестр быстрых правил
   └── llm          — brain.parse + chat_stream
   ↓
main.Jarvis.say(reply) ← cmd_lock
   ├── если text → speaker.play_async()
   └── если stream → speaker.speak_stream() + tee → gui.add_stream_chunk()
   ↓
tts.Speaker → Piper / XTTS / WinRT / SAPI
~~~~

**Плюс:** в `handle` **до** pipeline идёт `mood.apply_from_text(cmd)` —
детекция эмоции из текста.

---

## 🎓 Онбординг (первый запуск)

> **Не сценарии.** LLM ведёт **живой диалог**.

~~~~
first_run.greeting() → «Привет! Я Феникс, локальный голосовой помощник.
                        Не хочешь немного поболтать? Расскажи — чем
                        занимаешься, что нового?»

Пользователь отвечает
   ↓
stages/onboarding.py
   ├── if not first_run.is_first_run() → None
   ├── if LLM недоступна → first_run.mark_done() → None
   ├── if _looks_like_command(cmd) → None (пусть идёт в обычный handle)
   ├── history = list(dialog)[-10:]
   ├── force_done = user_msgs >= 6
   ├── result = brain.onboarding_chat(cmd, history)
   │   → {"reply": str, "name": str|None, "style": str|None, "onboarding_done": bool}
   ├── profile.set("name", ...) если LLM вернула
   ├── persona.set_field("speech_style", ...) если LLM вернула
   └── if onboarding_done or force_done → first_run.mark_done()
~~~~

**`brain.onboarding_chat()`** — отдельный промпт (`ONBOARDING_CHAT_PROMPT`).
Цели: узнать имя/стиль, **не допрашивать**, завершить за 3–5 обменов.

**`_looks_like_command(cmd)`** — быстрая проверка: если фраза начинается
с глагола-команды (`COMMAND_VERBS`), онбординг её **пропускает**.

**`first_run.py`** — минимальный:

| Функция | Что делает |
|---|---|
| `is_first_run()` | `not persona.is_onboarded()` |
| `greeting()` | текст приветствия |
| `mark_done()` | `persona.mark_onboarded()` |

---

## 👁 Observer (фоновое извлечение фактов)

> **Не спрашивает — слушает.** Раз в 30 сек отправляет **историю диалога** в LLM.

~~~~
Jarvis._process → observer.observe("user", cmd)
                → observer.observe("assistant", reply)
   ↓
DialogObserver._loop (раз в 5 сек)
   ├── if len(history) < batch_size (6) → ждём
   ├── if now - last_extract < min_interval (30) → ждём
   ├── history = list(self._history)
   ├── LLM: EXTRACT_PROMPT
   │   → {"name": ..., "city": ..., "age": ..., "style": ..., "facts": {...}}
   └── _apply(data)
       ├── profile.set("name", ...) если пусто
       ├── profile.set("default_city", ...) если пусто
       ├── profile.set("age", ...) если пусто
       ├── persona.set_field("speech_style", ...) если friendly
       └── learning.add_fact(k, v) для facts
~~~~

**Ключевое:** observer **не блокирует** диалог. Работает **параллельно**.

**Конфиг:** `observer_enabled: true`, `min_interval: 30.0`, `batch_size: 6`.

---

## 🎭 Персона

**Файл:** `jarvis/persona.py`.

**Хранится в `profile.json` → `persona`:**

~~~~json
{
  "assistant_name": "Феникс",
  "speech_style": "friendly",
  "traits": [],
  "backstory": "",
  "onboarding_done": false,
  "onboarding_at": 0.0,
  "onboarding_step": 0
}
~~~~

**Стили:** `formal` / `friendly` / `sarcastic` / `brief`.

**API:**

| Метод | Что делает |
|---|---|
| `get()` | dict (с дефолтами) |
| `set_field(key, value)` | bool |
| `normalize_style(text)` | `"строгий"` → `formal` |
| `build_prompt_block()` | блок для system prompt |
| `describe()` | человеческое описание для озвучки |
| `mark_onboarded()` | отметить завершение |
| `reset_onboarding()` | сброс |
| `is_onboarded()` | bool |

**В `brain._system_with_context()`:**

~~~~
base (CHAT_SYSTEM) + persona.build_prompt_block()
                  + mood.build_prompt_block()
                  + learning.build_context()
~~~~

**Команды (`fast/persona.py`):**

| Фраза | Действие |
|---|---|
| «поменяй стиль на строгий» | → `formal` |
| «какой у тебя стиль» | → `describe()` |
| «как тебя зовут» | → `assistant_name` |
| «давай заново познакомимся» | → `reset_onboarding()` |

---

## 💗 Mood

**Файл:** `jarvis/mood.py`.

**Состояния:** `neutral` / `happy` / `excited` / `annoyed` / `bored` / `tired`.

**Хранится в `profile.json` → `mood`:**

~~~~json
{
  "state": "happy",
  "since": 1791626400.0,
  "reason": "похвала"
}
~~~~

**API:**

| Метод | Что делает |
|---|---|
| `get()` | dict (с дефолтами) |
| `get_state()` | строка состояния |
| `set_mood(state, reason)` | установить + оповестить подписчиков |
| `detect(cmd)` | эвристика: какое состояние вызвать? |
| `apply_from_text(cmd)` | detect + set |
| `decay(max_age_sec)` | возврат к `neutral` |
| `effective_rate(base)` | множитель для TTS |
| `color()` | цвет для GUI |
| `build_prompt_block()` | блок для LLM |
| `describe()` | человеческое описание |
| `handle_mood_command(cmd)` | «как настроение», «не грусти», «успокойся» |

**Детекция из текста:**

| Регулярка | Состояние |
|---|---|
| `_RUDE` (тупой, дурак, идиот) | `annoyed` |
| `_TIRED` (устал, спать хочу) | `tired` |
| `_EXCITED` (ура, получилось, вау) | `excited` |
| `_PRAISE` (спасибо, молодец, круто) | `happy` |

**Приоритет:** `rude` > `tired` > `excited` > `praise`.

**Влияние:**

- **TTS** — `effective_rate()`: `excited` +10%, `tired` -10%.
- **GUI** — `color()` перекрашивает статус-сферу в `idle`.
- **LLM** — `build_prompt_block()` добавляется в system prompt.

**Decay** — фоновый поток в `main.py` раз в 60 сек вызывает `mood.decay()`.
Возврат к `neutral` через 5 минут.

**Подписки:** `mood.subscribe(cb)` → `cb(old_state, new_state)`.
GUI использует это для перекраски сферы.

---

## 🖥 UIA

**Файл:** `jarvis/uia.py`.

**Обёртка над `uiautomation`** (Windows UI Automation через COM).

**Поиск браузера — по PID процесса**, а не по имени окна.
20+ известных процессов: `chrome.exe`, `msedge.exe`, `browser.exe`
(Яндекс), `opera.exe`, `brave.exe`, `vivaldi.exe`, `firefox.exe`,
`arc.exe`, `chromium.exe`, `librewolf.exe`, `waterfox.exe`, и др.

**API:**

| Метод | Что делает |
|---|---|
| `list_windows()` | все видимые окна (для отладки) |
| `list_browsers()` | запущенные браузеры (по процессам) |
| `find_browser_window()` | найти окно любого браузера |
| `get_active_window()` | активное окно |
| `get_active_window_title()` | заголовок активного окна |
| `read_browser_tab_title()` | заголовок активной вкладки |
| `read_browser_tabs()` | список всех вкладок |
| `read_browser_url()` | URL адресной строки |
| `close_browser_tab(name)` | закрыть вкладку по имени |
| `switch_browser_tab(name)` | переключиться на вкладку |
| `read_active_text(max_chars)` | текст активного окна |
| `click_button(name)` | нажать кнопку по имени |
| `click_menu_item(path)` | клик по меню («Файл > Сохранить») |
| `describe_active_window()` | описание активного окна |
| `describe_browsers()` | описание запущенных браузеров |

**Команды голосом (`fast/uia.py`):**

| Фраза | Что делает |
|---|---|
| «Что открыто» | описание активного окна |
| «Прочитай окно» | текст активного окна |
| «Какой сайт открыт» | URL или заголовок |
| «Какая вкладка» | заголовок активной вкладки |
| «Какие вкладки» | список вкладок |
| «Закрой вкладку ютуб» | находит и закрывает |
| «Переключись на вкладку хабр» | активирует |
| «Нажми OK» | ищет кнопку |
| «Нажми enter» | key_press |

**LLM-actions:** `uia_read_window`, `uia_read_url`, `uia_read_tab`,
`uia_list_tabs`, `uia_close_tab`, `uia_switch_tab`, `uia_click_button`,
`uia_active_window`, `uia_menu`.

**Особенности:**

- **Chromium-браузеры** (Chrome, Edge, Яндекс) держат вкладки внутри
  `ToolBarControl 'Вкладки'` → `TabItemControl`.
  Ищем через `uiautomation.ToolBarControl(searchFromControl=..., Name="Вкладки")`.
- **URL** Яндекс.Браузер **не отдаёт** через UIA. Fallback — заголовок
  окна. В Chrome/Edge — работает.
- **Поиск по процессу** — работает даже если браузер не в фокусе.
- **`FindAll` не существует** у `WindowControl`. Использовать
  конструкторы `auto.EditControl(searchFromControl=...)` и
  `auto.ToolBarControl(searchFromControl=..., Name="Вкладки")`.

---

## ⚡ Реестр быстрых обработчиков

`IntentHandler._fast_handlers_cache` — **список `(имя, lambda)`**. Порядок = приоритет.

Каждый: `(cmd: str) -> str | None`. Вернул строку — команда обработана. `None` — идём дальше.

> **Правило:** специфичные — **выше** общих.

Порядок (из `fast/__init__.py`):

| # | Имя | Обработчик |
|---|---|---|
| 1 | custom | `match_custom` |
| 2 | small_talk | `small_talk` |
| 3 | music | `music_fast` |
| 4 | screenshot | `screenshot_fast` |
| 5 | uia | `uia_fast` |
| 6 | open_profile | `open_profile_fast` |
| 7 | open | `open_fast` |
| 8 | voices | `voices_fast` |
| 9 | packs | `packs_fast` |
| 10 | timers | `timers_fast` |
| 11 | tasks | `tasks_fast` |
| 12 | persona | `persona_fast` |
| 13 | profile | `profile_fast` |
| 14 | memory | `memory_fast` |
| 15 | system | `system_fast` |
| 16 | debug | `debug_fast` |
| 17 | correction | `correction_fast` |
| 18 | undo | `undo_fast` |
| 19 | weather_currency | `weather_currency_fast` |

- **Кэш:** список строится **один раз** в `__init__` (`_fast_handlers_cache`).
- **Исключения** в обработчике **логируются**, но **не роняют** команду.

---

## 👤 Универсальный профиль (`set_profile` / `get_profile`)

**Раньше:** куча `re.match` под каждую фразу. **Костыли.**

**Сейчас:** LLM **сама разбирает**:

~~~~
«меня зовут Максим» → {"action": "set_profile", "key": "name", "value": "Максим"}
«какой город»       → {"action": "get_profile", "key": "default_city"}
~~~~

**Regex `_profile_fast`:** **тире обязательно** — `я\s*[-—]\s*Имя`.
Голое `я ` **не матчится** (иначе «я хочу спать» создаёт профиль).

**Обработчики:** `_do_set_profile` / `_do_get_profile` в `execute.py`.

**Нормализация ключей:** `_KEY_MAP` — `"имя" → "name"`, `"город" → "default_city"`,
`"city" → "default_city"`, `"мой город" → "default_city"`.

---

## 🖼 GUI (Flet 1.0.3)

~~~~
Flet Main Thread
   ├── NavigationRail (слева): Главная / Микрофон / Персона / Настройки
   ├── Контент-область (кеш _tabs)
   ├── page.run_task(_process_queue)
   └── page.run_task(_mic_level_loop)

Jarvis Thread
   ├── listener.phrases() → _process(cmd) ← cmd_lock
   ├── handler.handle(cmd) → Reply
   └── say(reply) ← cmd_lock
~~~~

> **Связь:** `queue.Queue()` → `gui._queue`.
> **Важно:** Flet — **в главном потоке** (`gui.run_main()`), Jarvis — **в фоне**.

### Режим запуска

~~~~json
"launch_mode": "gui"
~~~~

| Значение | Что делает |
|---|---|
| `"gui"` | окно видимо (по умолчанию) |
| `"tray"` | окно скрыто. **Трей отключён**, `main.py` принудительно `"gui"` |

### Трей (отключён)

> **Причина:** pystray требует **свой Windows message loop**, а главный поток
> **занят flet'ом**. Позже — отдельный процесс `tray_runner.py`.

### Темы GUI

~~~~
PALETTES = { "dark": {...}, "light": {...} }
_apply_palette(name)
_detect_system_theme() — HKCU\...\AppsUseLightTheme
_mic_level_loop → раз в 5 сек проверяет тему Windows
_rebuild_ui_for_theme → сохраняет историю чата
~~~~

### Подписки GUI

- `profile.subscribe(self._on_profile_switch)` — пересборка UI при смене профиля.
- `mood.subscribe(self._on_mood_change)` — перекраска статус-сферы при смене настроения.

### Вкладка «Микрофон»

- `Listener.current_rms` — RMS.
- `Listener.peak` — пик за сессию.
- `Listener.utterances` — распознано.
- `_on_mic_test` — **через очередь** (`set_mic_test_result`).
- `mic_watchdog` → `("open_mic_tab", None)`.

### Салют (праздничный)

- `gui.launch_fireworks(duration)` — кладёт в очередь.
- `_launch_fireworks_async(duration)` — анимация через **Stack + Container**
  (не Canvas — API капризный).
- `n_bursts` зависит от длительности.

### Иконка окна

`jarvis/icon.ico` → `page.window.icon`.

---

## 👥 Мультипрофиль

~~~~
%APPDATA%\Phoenix\profiles\
├── <user1>\
│   ├── profile.json    ← name, default_city, facts, tts_voice, persona, mood
│   └── dialog.json
└── <user2>\
~~~~

- Активный профиль — по имени Windows-юзера.
- `profile.switch(name)` — один `RLock`.
- `profile.subscribe(callback)` — подписка (old_name, new_name).
- Миграция из старого `user_profile.json`.

---

## ⚙️ Поток конфига

~~~~
%APPDATA%\Phoenix\config.json → Config.__init__ → config_manager.load()
   ↓
Config._data (в памяти) — источник истины
   ↓
config.get("key") / config.set("key", value)
   ├── config_manager.save() — атомарно
   │   ├── OK → оповещение подписчиков
   │   └── FAIL → откат в памяти (Config.set/update)
   └── ...
~~~~

**Подписки:**

| Метод | Что делает |
|---|---|
| `Config.subscribe(callback)` | добавить |
| `Config.unsubscribe(callback)` | удалить |

**Кто подписан:**

- `main.py` → `_on_config_change` (tts_voice, voice_rate, mode, barge_enabled).
- `handler.py` → `_on_config_change` (memory_max, llm_context_messages).
- `brain.py` → `_on_config_change` (llm_model, ollama_url).

---

## 🌤 Погода и курс валют

~~~~
weather.py
   ├── _CACHE: dict — (key, timestamp, data)
   ├── _CACHE_LOCK: threading.Lock
   ├── _config — ссылка на Config (set_config)
   ├── _current_ttl() — читает weather_cache_ttl_sec каждый раз
   ├── _cached(key, fetcher) — TTL применяется на каждый вызов
   └── _http_get_json — User-Agent из __version__
~~~~

**TTL:** 600 сек (10 мин) по умолчанию.

**Источники:** `open-meteo.com` (погода), `cbr-xml-daily.ru` (курс ЦБ).

---

## 📂 Открытие файлов в редакторе

~~~~
actions.open_in_editor(path, prefer="auto")
   ├── "notepad++" → _find_notepadpp()
   ├── "vscode"    → _find_vscode()
   ├── "system"    → os.startfile()
   └── "auto"      → [_find_notepadpp, _find_vscode] → os.startfile()
~~~~

**Активация окна** — `_activate_window_hard(title_part)`:

- `win32gui.EnumWindows`
- `AttachThreadInput` (обход блокировки `SetForegroundWindow`)
- `SetForegroundWindow` + `BringWindowToTop`

---

## 📦 Пак-команды с аргументами

~~~~
actions.spec_from_string(s)
   ├── open_app: → ...
   ├── http(s):// → url
   ├── steam:// → uri
   ├── browser/браузер → browser
   ├── _looks_like_cmd(s) → ("cmd", shlex.split(s, posix=False))
   │   (для "shutdown /s /t 10", "cmd /k ipconfig", "rundll32.exe ...")
   ├── .bat/.cmd → path
   └── os.path.exists(s) → path
~~~~

- **`_CMD_VERBS`** — известные системные команды (`shutdown`, `cmd`, `rundll32`, ...).
- **Zip Slip защита** — при распаковке Vosk: `resolved.is_relative_to(base)`.

---

## 🚀 Лаунчер (`Феникс.exe`)

`launcher.py` → `Феникс.exe` (PyInstaller). При запуске:

~~~~
1. Ищет Python 3.10–3.12.
2. Нет → MessageBox: [Скачать Python 3.11] [Отмена].
3. Проверяет .venv311. Нет → создаёт.
4. Проверяет зависимости (flet, vosk). Нет → pip install.
5. Проверяет Vosk-модель в C:\ProgramData\Phoenix\models.
6. Проверяет Ollama.
7. Запускает .venv311\Scripts\pythonw.exe -m jarvis.
~~~~

- **Диалоги** — `ctypes.windll.user32.MessageBoxW`.
- **Логи** — `logs/launcher.log`.
- **Мьютекс** — `Local\JarvisPhoenixSingleInstance` (без админа).
- **Zip Slip защита** при распаковке Vosk.

---

## 🧩 Ключевые объекты

| Объект | Модуль | Роль |
|---|---|---|
| `Config` | `config.py` | Конфиг в памяти + подписки |
| `IntentHandler` | `intents/handler.py` | Оркестрация pipeline |
| `Brain` | `brain.py` | LLM: `parse()` / `chat_stream()` / `onboarding_chat()` |
| `Speaker` | `tts.py` | Синтез, per-call token |
| `Listener` | `stt.py` | Vosk, ring buffer |
| `WhisperTranscriber` | `stt.py` | Расшифровка |
| `Jarvis` | `main.py` | Связка, wake, `cmd_lock` |
| `FenixGUI` | `gui.py` | Flet GUI, fireworks |
| `Reply` | `reply.py` | `text` \| `stream` |
| `history` | `history.py` | Стек отмены |
| `celebrations` | `celebrations.py` | Поздравление с ДР (из config) |
| `persona` | `persona.py` | Персона, стиль, промпт-блок |
| `mood` | `mood.py` | Эмоциональное состояние |
| `uia` | `uia.py` | UI Automation |
| `DialogObserver` | `observer.py` | Фоновое извлечение фактов |
| `first_run` | `jarvis/first_run.py` | greeting, `is_first_run`, `mark_done` |
| `PROJECT.md` | `PROJECT.md` (корень) | источник правды: инварианты, правила, история ошибок |

---

## 💾 Файлы данных

| Файл | Где |
|---|---|
| `config.json` | `%APPDATA%\Phoenix\` |
| `profiles/<user>/profile.json` | `%APPDATA%\Phoenix\` |
| `profiles/<user>/dialog.json` | `%APPDATA%\Phoenix\` |
| `timers.json` / `tasks.json` | `%APPDATA%\Phoenix\` |
| `models/vosk-model-small-ru-0.22/` | `C:\ProgramData\Phoenix\` |
| `whisper-cache/` | `C:\ProgramData\Phoenix\` |
| `logs/` | `%APPDATA%\Phoenix\` |
| `system_caps.json` | `C:\jarvis\` (только dev, в `.gitignore`) |

---

## 🌐 Внешние зависимости

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

## 🧪 Тесты

| Файл | Что тестирует |
|---|---|
| `test_intents.py` | 32 сценария (без LLM, без сети) |
| `tests/test_config_manager.py` | параллельная запись |
| `tests/test_weather.py` | погода/курс с моками |
| `tests/test_caps.py` | структура `system_caps.json` |
| `tests/test_mood.py` | Mood: состояние, детекция, decay, влияние (29 тестов) |
| `tests/test_uia.py` | UIA: логика обёртки с моками (17 тестов) |

**CI:** `.github/workflows/test.yml` — `check_syntax.py` + `pytest tests/` + `test_intents.py`.

**`requirements-ci.txt`** — лёгкие зависимости, без звука и Windows-специфики.

---

## 🏗 Инфраструктура

### `.venv311`

**Python 3.11** в отдельном venv — обход падения Vosk на 3.13/3.14.

### Git

**`.gitignore`:**

~~~~
.venv311/     config.json     profiles/     logs/
system_caps.json     models/     voices/
dist/     build/     timers.json     tasks.json
*.bak*
jarvis/intents_old.py
~~~~

**`SNAPSHOT.md`** — генерируется `snapshot.py`. Исключает `.venv311`,
`profiles/`, `system_caps.json`, `*.bak*`.

### `commit.bat`

Активирует `.venv311` → `snapshot.py` → `git add .` → `commit` → `push`.

---

## 📦 Сборка и установка

### `scripts/make_icon.py`

Генерирует `jarvis/icon.ico` (16/24/32/48/64/128/256). Синий круг с «J».

### `scripts/make_installer_images.py`

Генерирует BMP для Inno Setup из `jarvis/icon.ico`:

| Файл | Размер | Назначение |
|---|---|---|
| `installer_banner.bmp` | 164×314 | вертикальный баннер |
| `installer_small.bmp` | 55×55 | маленькая иконка вверху справа |

### `scripts/build_exe.py`

Собирает `launcher.py` → `dist/Феникс.exe` (~9 МБ) + копия в корень.

### `installer.iss`

Inno Setup 6.7 → `Феникс_Setup.exe`. Ставит в `C:\ProgramData\Phoenix`.
Ярлыки, автозапуск, деинсталлятор.

**Ключевые директивы:**

| Директива | Значение |
|---|---|
| `WizardStyle` | `modern` — современный вид |
| `WizardImageFile` | `installer_banner.bmp` — баннер |
| `WizardSmallImageFile` | `installer_small.bmp` — иконка |
| `PrivilegesRequired` | `lowest` — не требует админа |
| `ArchitecturesInstallIn64BitMode` | `x64compatible` |
| `Excludes` | `__pycache__,*.pyc` — мусор не тащится |

> **`DarkMode=1`** — **не поддерживается** в Inno Setup 6.7.3.

### `create_shortcut.bat`

Создаёт ярлык на рабочем столе для `Феникс.exe`.

---

## ⚠️ Что важно помнить при доработке

### Код

1. **Не читай `config.json` напрямую** — `config.get()`.
2. **Не пиши в `config.json` напрямую** — `Config.set()` или `config_manager.save()`.
3. **Не плоди глобальное состояние** — кроме `Config._GLOBAL`.
4. **Нормализация (города, валюты, паков) — задача LLM.**
5. **Логи в `actions.log`** — главный инструмент отладки.
6. **`test_intents.py`** — первое, что запускаешь после правок.
7. **`normalize(cmd)` в `IntentHandler.handle()`** — единая точка.
8. **Per-call stop-token в `tts.py`.**
9. **`ft.Button`** вместо `ElevatedButton`/`TextButton`.
10. **`ft.BoxShadow`** — без `blur_style`.
11. **Реестр `fast/__init__.py`** — новые правила **туда**.
12. **`open_profile` — выше `open`.**
13. **`set_profile` / `get_profile`** — через LLM.
14. **Активация окон — `win32gui` + `AttachThreadInput`.**
15. **`paths.py`** — единственное место для путей.
16. **Модели Vosk/Whisper — ВСЕГДА в `PROGRAM_DIR` (ASCII).**
17. **`HF_HOME` для Whisper — временно.**
18. **Vosk API — только из listener-потока.**
19. **Pack-команды с аргументами — `_looks_like_cmd` + `shlex`.**
20. **Атомарная запись везде — `mkstemp` + `os.replace`.**
21. **Zip Slip защита при распаковке.**
22. **`cmd_lock` в Jarvis — сериализация голос↔GUI.**
23. **`Local\` мьютекс — без админа.**
24. **Онбординг — через LLM.** `stages/onboarding.py` + `brain.onboarding_chat()`.
25. **Observer — фоновое извлечение фактов.** `observer.observe()` не блокирует.
26. **Персона — в system prompt.** `persona.build_prompt_block()` → `_system_with_context()`.
27. **Mood — в system prompt и TTS.** `mood.build_prompt_block()` + `mood.effective_rate()`.
28. **Праздничные триггеры — в `config.json`.** `enabled: false` по умолчанию.
29. **UIA — поиск браузера по PID процесса**, не по имени окна.
30. **`FindAll` не существует** у `WindowControl`. Используй `auto.EditControl(searchFromControl=...)` и `auto.ToolBarControl(searchFromControl=..., Name="Вкладки")`.
31. **`_COMPOUND_VERBS` — единый `COMMAND_VERBS`** в `intents/verbs.py`.
32. **Пакет `intents/`** — новые правила в `fast/`, стадии в `stages/`.
33. **Правки только в VS Code.** Терминал портит кодировку и BOM.
34. **UTF-8 без BOM.** `files.encoding: utf8`, `files.autoGuessEncoding: false`.

### GUI

1. **GUI Flet — только в главном потоке.** Jarvis — в фоне.
2. **Связь GUI ↔ Jarvis — через `queue.Queue()`.**
3. **`PALETTES` в `gui.py`** — две темы.
4. **`weather_cache_ttl_sec`** — настраиваемый TTL.
5. **Личные данные — только в `config.json`, `profiles/`, `system_caps.json`.**
6. **Python 3.10–3.12** — только `.venv311`.
7. **`snapshot.py`** — исключать `.venv311`, `profiles/`, `system_caps.json`, `*.bak*`.