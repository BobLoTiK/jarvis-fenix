# 🤖 ПРОМПТ для LLM — «Феникс»

> Самодостаточный промпт. Копируй целиком в новый чат,
> если текущий переполнен или меняешь модель.

---

## 🎯 Контекст

**«Феникс»** — локальный голосовой ассистент для Windows.
Форк `jsays12/jarvis`. Коммиты до июня 2026 — от оригинала,
с октября 2026 — мои.

**Стек:**

- **Python 3.11** (только `.venv311`) — Vosk не работает на 3.13/3.14.
- **Vosk** (wake) + **faster-whisper** (расшифровка).
- **Piper** / **XTTS** / **WinRT** (TTS).
- **Ollama** (LLM: qwen2.5, gemma2, llama3.1, mistral).
- **Flet 1.0.3** (GUI).
- **PyInstaller** (`Феникс.exe`).
- **Inno Setup** (установщик).
- **UIA** (`uiautomation`) — управление окнами. **Готово.**
- **VLM** (через Ollama) — в планах.
- **Prosody** (эмоции из голоса) — в планах.

**Репозиторий:** `C:\jarvis`
**GitHub:** `https://github.com/BobLoTiK/jarvis-fenix`
**Лицензия:** MIT + attribution jsays12.

**Два корня путей:**

- `C:\ProgramData\Phoenix\` — **ASCII**, модели (Vosk, Whisper).
- `%APPDATA%\Phoenix\` — **личные данные** (config, profiles, logs, tasks, timers).

**Почему:** Vosk (C++ Kaldi) **ломается** на не-ASCII путях.
См. `jarvis/paths.py`.

---

## 🎭 Как со мной работать

**Обращение:** «брат».

**Стиль:** кратко, без воды, с юмором. Русский.

**Формат:**

- **Команды** — в `bat`/`powershell`-блоках.
- **Код** — в `python`-блоках, целиком или точечные патчи.
- **Патч** — с точным маркером: «найди X, замени на Y».
- **Полные файлы** — в Markdown-блоках с языком.
- **Плотно.** Не разжёвывать очевидное.
- **Не переписывать то, что не менялось.**
- **Порядок файлов в документации:** `PLAN.md`, `PROMPT.md`, остальные.
- **Отступы сохранять ровно** — не ломать при копипасте.
- **Документацию кидать в один markdown-блок целиком** — не частями,
  не с `python` внутри.
- **Вложенные ```-блоки:** внешний блок делать через `~~~~` (тильды),
  чтобы вложенные ``` не рвали парсер.

**Запрещено:**

- **Костыли.** «Работает, но грязно» = не решение.
- **Хардкод.** Всё через `config.json` и `Config`.
- **Прямая запись/чтение `config.json`** — только `Config.set()`/`config.get()`.
- **Глобальное состояние** — кроме `Config._GLOBAL`.
- **Словари синонимов** для городов/валют — задача LLM.
- **Хардкод путей** — только `jarvis/paths.py`.
- **Python 3.13/3.14** — Vosk падает.
- **Коммитить** `.venv311`, `config.json`, `profiles/`,
  `system_caps.json`, `timers.json`, `tasks.json`, `models/`,
  `voices/`, `dist/`, `build/`, `*.bak*`, `jarvis/intents_old.py`.
- **Vosk API из главного потока** — только listener-поток.
- **`prevent_close` + `on_event`** в Flet 1.0.3 — не работает.
- **`HF_HOME` глобально** — Piper degraded mode. Временно, сброс.
- **Удалять attribution `jsays12`**.
- **Упоминать личные данные** (имя, город, CPU, GPU, ОС) в публичных файлах.
- **Хардкод браузеров** — использовать список процессов (`_BROWSER_PROCESSES`).
- **Праздничные триггеры в коде** — только через `config.json`.

**Поощряется:**

- **`Config.subscribe`** для реакции на изменения.
- **Разделение ответственности** — один модуль = одна задача.
- **Тесты** — `pytest` + `test_intents.py`.
- **Логи** — `jarvis.log`, `actions.log`, `errors.log`.
- **Реестр `fast/__init__.py`** — новые быстрые правила туда.
- **Пакеты вместо монолитов** — `intents/` — пример.

---

## 🚨 Ошибки, которые я уже делал (не повторяй)

1. **Дробил файл на куски** без указания, куда вставлять. → **Целиком** или **точный маркер**.
2. **`prevent_close` + `on_event`** в Flet 1.0.3 — крестик ломается.
3. **`HF_HOME` глобально** — Piper в degraded mode.
4. **Забыл `sys.stdout is None`** под `pythonw`.
5. **`wait_end` на не-стартовавшем потоке** — `RuntimeError`.
6. **`subprocess.Popen` для трея** — `main()` зависал.
7. **`strip_cjk_chunk` не создал** — `ImportError`.
8. **Не исключил `profiles/` из `snapshot.py`** — личные данные.
9. **`chat_stream` терял чанк** — `append` до проверки токена.
10. **Патч без точного маркера.**
11. **`text`/`markdown` внутри код-блока** — мешает копипасте.
12. **Обрезал diff** — ты не видишь изменений.
13. **Порядок файлов** — `PLAN.md` первым, потом `PROMPT.md`.
14. **Не смотрел логи** — гадал.
15. **`flush()` из главного потока** — `libvosk.dll` падал (`0xc0000015`).
16. **Zip Slip** при распаковке Vosk.
17. **Мьютекс `Global\`** — требует админа. → `Local\`.
18. **Pack-команды** (`shutdown /s /t 10`) шли в `os.startfile`.
19. **`timers.py`/`tasks.py` писали в `BASE_DIR`.**
20. **`memory.append` не атомарный.**
21. **`config_manager` дефолт — `BASE_DIR`.**
22. **`_profile_fast` regex** — «я хочу спать» создавал профиль.
23. **`say()` падал при `listener=None`.**
24. **GUI ↔ голос — гонка.** → `cmd_lock` в Jarvis.
25. **`recorder.stop()`** — `unhook_all()` безусловно.
26. **`launcher.py`** — мёртвый код после `return`.
27. **`install.bat`** — ссылки на несуществующие `.bat`.
28. **`weather.py` UA** — из `__version__`.
29. **`set_llm_model.py`** — путь и неатомарность.
30. **`start_fenix.bat`** — хардкод `C:\jarvis`. → `%~dp0`.
31. **`tts.py`** падал на невидимом тексте (`\u200b`).
32. **`CHAT_SYSTEM` с кракозябрами** — правки только в VS Code.
33. **BOM в `intents.py`** — UTF-8 без BOM.
34. **Онбординг на `if/elif`** — LLM-диалог вместо.
35. **`_extract_name` пропускал «работает»** — blacklist + LLM.
36. **`_small_talk` перехватывал всё** — убрать «привет», «как дела».
37. **Правки через терминал → порча файлов.**
38. **`_small_talk` тест FAIL без LLM.**
39. **Монолит `intents.py` (2000+ строк)** — распил на пакет.
40. **Хардкод браузеров в `uia.py`** — список процессов.
41. **`FindAll` не существует** у `WindowControl` — использовать
    `ToolBarControl(searchFromControl=..., Name="Вкладки")` или
    `EditControl(searchFromControl=...)`.
42. **Праздничные триггеры в коде** — в `config.json`, `enabled: false` по умолчанию.
43. **`uia.ControlTypeName`** — не существует. Использовать строки `"TabItemControl"`.
44. **Скриншот не в `_fast_handlers`** — был в pipeline напрямую, забыли перенести.
45. **«Удали профиль X» перехватывается `tasks_fast`** — обрабатывать в `PasswordStage`.
46. **Вложенные ``` внутри markdown** — внешний блок через `~~~~`.

---

## 🗂 Пути (главное правило)

**Всё, что читает Vosk** — только в `PROGRAM_DIR` (ASCII):

- `paths.program_models_dir()` → `C:\ProgramData\Phoenix\models\`
- `paths.program_whisper_cache_dir()` → `C:\ProgramData\Phoenix\whisper-cache\`

**Личные данные** — в `USER_DIR`:

- `paths.config_path()` → `%APPDATA%\Phoenix\config.json`
- `paths.logs_dir()` → `%APPDATA%\Phoenix\logs\`
- `paths.profiles_dir()` → `%APPDATA%\Phoenix\profiles\`

**HF_HOME для Whisper** — временно, сброс после.

---

## 🏗 Архитектура (кратко)

### Модули

~~~~
jarvis/
├── main.py           — Jarvis, barge-in, cmd_lock
├── config.py         — Config в памяти + подписки
├── config_manager.py — атомарная запись (FileLock per-path)
├── paths.py          — PROGRAM_DIR / USER_DIR
├── brain.py          — Ollama: parse() / chat_stream() / onboarding_chat()
├── intents/          — пакет (после рефакторинга)
│   ├── handler.py    — IntentHandler, pipeline, подписки
│   ├── context.py    — Ctx для стадий
│   ├── verbs.py      — COMMAND_VERBS, CANCEL, SEARCH_VERBS
│   ├── password.py   — хеш, миграция, DANGER_ACTIONS
│   ├── sites.py      — SITES из packs/sites.json
│   ├── execute.py    — dispatch: action → функция + UIA
│   ├── stages/       — 11 стадий pipeline
│   │   ├── base.py, cancel.py, onboarding.py
│   │   ├── correction.py, password.py, memory.py
│   │   ├── pending.py, clipboard.py, modes.py
│   │   └── compound.py, fast.py, llm.py
│   └── fast/         — 17 быстрых обработчиков
│       ├── custom.py, small_talk.py, music.py, screenshot.py
│       ├── uia.py, open.py, voices.py, packs.py
│       ├── timers.py, tasks.py, persona.py, profile.py
│       ├── memory.py, system.py, debug.py
│       └── undo.py, correction.py, weather.py
├── reply.py          — Reply (text | stream)
├── gui.py            — Flet GUI + PALETTES + fireworks
├── history.py        — стек отмены
├── stt.py            — Vosk + Whisper, HF_HOME временно
├── tts.py            — Piper / XTTS / WinRT / SAPI, per-call token
├── modes.py          — commands / llm / combo
├── voices.py         — смена голоса Piper
├── packs.py          — загрузка/выгрузка паков
├── profile.py        — profiles/<user>/profile.json + subscribe
├── persona.py        — стиль, черты, backstory
├── mood.py           — состояние (neutral/happy/...)
├── uia.py            — окна, вкладки, кнопки (20+ браузеров)
├── memory.py         — dialog.json (атомарно)
├── observer.py       — фоновое извлечение фактов
├── first_run.py      — greeting, is_first_run, mark_done
├── learning.py       — факты + коррекции
├── weather.py        — погода/курс + TTL
├── timers.py         — напоминания (USER_DIR)
├── tasks.py          — задачи (USER_DIR)
├── actions.py        — окна, медиа, _looks_like_cmd
├── text_utils.py     — normalize, strip_cjk, prepare_text
├── celebrations.py   — поздравление с ДР (триггеры из config)
├── files.py          — папки
├── apps.py           — каталог приложений
├── installed.py      — индекс «Пуск»
├── steam.py          — индекс Steam
├── matching.py       — нечёткое сравнение
├── model.py          — загрузка Vosk
├── recorder.py       — макросы
├── tray.py           — трей (отключён)
├── vision.py         — VLM (в планах)
├── hermes.py         — мост Hermes (в планах)
└── resources.py      — приоритеты (в планах)
~~~~

### Поток обработки

~~~~
Микрофон → Vosk (wake) → Whisper → Jarvis._process
   → IntentHandler.handle(cmd)  ← normalize(cmd)
   → mood.apply_from_text(cmd)
   → Pipeline (11 стадий):
       cancel → onboarding → correction → password
       → memory → pending → clipboard → modes
       → compound → fast (реестр) → llm
   → Reply (text | stream)
   → Jarvis.say(reply)  ← cmd_lock
~~~~

### Mood

~~~~
Jarvis._process → mood.apply_from_text(cmd)
   → detect: rude/tired/excited/praise
   → set_mood → notify subscribers
      ├── TTS: effective_rate()
      ├── GUI: color() для статус-сферы
      └── LLM: build_prompt_block()
~~~~

**Decay:** фоновый поток раз в 60 сек → `mood.decay()`.

### UIA

~~~~
Команда → fast/uia.py (быстрые) → uia.py
   ├── find_browser_window() — по PID процесса
   ├── read_browser_tab_title() / read_browser_tabs()
   ├── read_browser_url() — с fallback
   ├── close_browser_tab() / switch_browser_tab()
   ├── read_active_text()
   └── click_button() / click_menu_item()
~~~~

---

## 📋 Режимы работы

### 🏠 Local

- LLM: Qwen через Ollama.
- STT: Vosk + Whisper small CPU.
- TTS: Piper medium.
- Погода: кэш 24 ч.

### 🌐 Hybrid

- LLM: Qwen 14b/32b.
- STT: Whisper large-v3-turbo на GPU.
- TTS: Piper.

### ☁️ Cloud — 🚧 в планах

Ф1–Ф13.

### 💎 Premium — ⏸

Ф14–Ф19.

---

## 📊 ТЕКУЩИЙ СТАТУС

### ✅ Закрыто

| Категория | Всего | ✅ |
|---|---|---|
| 🔴 Критичные | 8 | 8 |
| 🟡 Серьёзные | 7 | 7 |
| 🟢 Мелкие | 8 | 8 |
| 🏗 Архитектурные | 3 | 2 |
| 📝 Документация | 1 | 1 |
| 🔐 Безопасность | 1 | 1 |
| 🆕 Запуск | 1 | 1 |
| 🆕 Дизайн | 1 | 1 |
| 🆕 Unicode | 2 | 2 |
| 🆕 Автолаунчер | 1 | 1 |
| 🆕 Установщик (v1) | 1 | 1 |
| 🆕 Релиз v1.0.0 | 1 | 1 |
| 🆕 Поздравление (в config) | 1 | 1 |
| 🆕 Аудит Kimi | 25 | 25 |
| 🆕 Inno UI | 1 | 1 |
| 🆕 Знакомство через LLM | 1 | 1 |
| 🆕 Персона + стиль | 1 | 1 |
| 🆕 Observer | 1 | 1 |
| 🆕 Распил `intents.py` → пакет | 1 | 1 |
| 🆕 Техдолг (.bak, system_caps, send2trash) | 5 | 5 |
| 🆕 Mood | 3 | 3 |
| 🆕 UIA | 6 | 6 |

**Ключевое за последние сессии:**

- **Распил `intents.py`** → пакет `intents/` (~40 файлов).
- **Mood** — эмоциональное состояние, влияет на TTS/GUI/LLM.
- **UIA** — управление окнами Windows (браузеры по PID процесса).
- **Праздничные триггеры** — из `config.json`, по умолчанию выключены.
- **Техдолг** — `.bak*`, `system_caps.json` в snapshot, `send2trash` warning.

### 🚧 Осталось

- №75, №77 — архитектура.
- №85 — отмена ⏸.
- №86 — wake 🧪.
- №108 — трей ⏸.
- №147–148 — PyInstaller (20–30 ч).
- №121 — GitHub Actions (4–6 ч).
- №123 — тест на виртуалке.
- Этап 1.11 — Silero TTS. **Следующий.**
- Этап 1.12 — VAD.
- Этап 1.13.5 — Prosody (эмоции из голоса).
- Этап 1.13.6 — Non-verbal (смех, вздохи).
- Этап 2 — Облако.
- Этап 3 — Управление приложениями.
- Этап 4 — Vector memory.
- Этап 5 — MCP заготовки.
- Этап 6 — Telegram.
- Этап 7 — Визуализация + Спрайт.
- Этап 8 — PyInstaller + CI + VLM + Hermes.

---

## 🎯 ПОРЯДОК РАБОТЫ

1. Этап 1 — Баги — ✅
2. Этап 1.5 — Документация — 🚧
3. Этап 1.6 — UI/UX — ✅
4. Этап 1.7 — Красивый установщик — ✅
5. Этап 1.8 — Знакомство + Персона + Observer — ✅
6. Этап 1.9 — Mood — ✅
7. Этап 1.10 — UIA — ✅
8. **Этап 1.11 — Silero TTS — ❌ следующий**
9. Этап 1.12 — VAD — ❌
10. Этап 1.13.5 — Prosody — ❌ (в планах, будущее)
11. Этап 1.13.6 — Non-verbal — ❌ (в планах, будущее)
12. Этап 2 — Облако — ❌
13. Этап 3 — Управление приложениями — ❌
14. Этап 4 — Vector memory — ❌
15. Этап 5 — MCP (заготовки) — ❌
16. Этап 6 — Telegram + веб — ❌
17. Этап 7 — Визуализация + Спрайт — ❌
18. Этап 8 — PyInstaller + CI + VLM + Hermes — ⏸
19. 💤 Долгий ящик — Фаза 2

---

## 🎯 КЛЮЧЕВЫЕ ПРАВИЛА

### Код

1. `Config` — источник истины.
2. Не плоди `_atomic_write`. `config_manager.save()`.
3. Не плоди глобальное состояние.
4. Нормализация — задача LLM.
5. `test_intents.py` — после правок.
6. `normalize(cmd)` в `handle()`.
7. Per-call stop-token в `tts.py`.
8. `PALETTES` в `gui.py`.
9. `ft.Button` вместо `ElevatedButton`.
10. `ft.BoxShadow` без `blur_style`.
11. Реестр `fast/__init__.py`.
12. `open_profile` выше `open`.
13. `set_profile` / `get_profile` через LLM.
14. Активация окон — `win32gui` + `AttachThreadInput`.
15. Пути — только `jarvis/paths.py`.
16. Модели Vosk/Whisper — только `PROGRAM_DIR` (ASCII).
17. `HF_HOME` для Whisper — временно.
18. Vosk API — только из listener-потока.
19. UIA — через `uiautomation`. Поиск браузера — по PID процесса.
20. `FindAll` не существует. Используй `auto.EditControl(searchFromControl=...)`
    и `auto.ToolBarControl(searchFromControl=..., Name="Вкладки")`.
21. Pack-команды с аргументами — через `_looks_like_cmd` + `shlex`.
22. Атомарная запись везде: `mkstemp` + `os.replace`.
23. Zip Slip защита при распаковке.
24. **Онбординг — через LLM.** `stages/onboarding.py` + `brain.onboarding_chat()`.
25. **Observer — фоновое извлечение фактов.** Не блокирует.
26. **Персона — в system prompt.** `persona.build_prompt_block()`.
27. **Mood — в system prompt и TTS.** `mood.build_prompt_block()` +
    `mood.effective_rate()`.
28. **Праздничные триггеры — в `config.json`.** `enabled: false`.
29. **Правки только в VS Code.** Терминал портит кодировку и BOM.
30. **UTF-8 без BOM.** `files.encoding: utf8`,
    `files.autoGuessEncoding: false`.
31. **`intents/` — пакет.** Новые правила в `fast/`, стадии в `stages/`.
32. **`_COMPOUND_VERBS` = `COMMAND_VERBS`** из `intents/verbs.py`.
33. **Скриншот — в `fast/screenshot.py`**, не в pipeline.
34. **`delete_profile` — в `PasswordStage`**, до `fast`.
35. **Профиль читается через `profile._cache`** — не добавляй чтений
    `profile.json` в горячие пути (`effective_rate` зовётся на каждом
    синтезируемом предложении).
36. **`normalize()` режет пунктуацию** — для доменов бери сырой
    `intent["target"]`, иначе `habr.com` станет `habr com`.
37. **Сначала `PROJECT.md`** — там инварианты и вся история ошибок.

### GUI

1. Flet — главный поток.
2. Связь через `queue.Queue()`.
3. Разделы — `_tabs`.
4. Тема — `theme_mode` + `PALETTES`.
5. `launch_mode` — `"gui"` / `"tray"`.
6. `_rebuild_ui_for_theme` сохраняет историю.
7. Не использовать `prevent_close` + `on_event`.

### Безопасность

1. Личные данные — только `config.json`, `profiles/`, `system_caps.json`.
2. Все — в `.gitignore`.
3. `config.example.json` — только дефолты.
4. Пароль — SHA-256.
5. `send2trash` — warning при отсутствии.

### Окружение

1. Python 3.10–3.12.
2. `.venv311` — обязательный.
3. `snapshot.py` — исключать `.venv311`, `profiles/`,
   `system_caps.json`, `*.bak*`.

### Git

1. `.gitignore` — `.venv311`, `config.json`, `profiles/`, `logs/`,
   `system_caps.json`, `models/`, `voices/`, `dist/`, `build/`,
   `*.bak*`, `jarvis/intents_old.py`.
2. `LICENSE` — не удалять attribution.

---

## 🛠 Как чинить баги

1. Лог: `%APPDATA%\Phoenix\logs\` — `jarvis.log`, `actions.log`, `errors.log`.
2. Event Viewer: `eventvwr.msc` → Application/System.
3. Воспроизвести.
4. Локализовать.
5. Фикс без костылей.
6. Тесты: `check_syntax.py` + `pytest` + `test_intents.py`.
7. Коммит: `fix: <краткое>`.

---

## 📎 БЫСТРЫЕ ССЫЛКИ

| Что | Где |
|---|---|
| План | `PLAN.md` |
| Архитектура | `ARCHITECTURE.md` |
| Changelog | `CHANGELOG.md` |
| README | `README.md` |
| CI | `.github/workflows/test.yml` |
| Логи (dev) | `C:\jarvis\logs\` |
| Логи (installed) | `%APPDATA%\Phoenix\logs\` |
| Модели | `C:\ProgramData\Phoenix\models\` |
| Конфиг | `%APPDATA%\Phoenix\config.json` |
| GitHub | `https://github.com/BobLoTiK/jarvis-fenix` |

---

**Погнали, брат.** 🚀