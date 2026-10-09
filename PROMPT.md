## 📄 `PROMPT.md` — полный файл

```markdown
# 🤖 ПРОМПТ для LLM — «Феникс»

> Самодостаточный промпт. Копируй целиком в новый чат, если текущий переполнен.

---

## 🎯 Контекст

**«Феникс»** — локальный голосовой ассистент для Windows.
Форк `jsays12/jarvis`. Коммиты до июня 2026 — от оригинала, с октября 2026 — мои.

**Стек:**
- **Python 3.11** (только `.venv311`) — Vosk не работает на 3.13/3.14
- **Vosk** (wake) + **faster-whisper** (расшифровка)
- **Piper** / **XTTS** / **WinRT** (TTS)
- **Ollama** (LLM: qwen2.5, gemma2, llama3.1, mistral)
- **Flet 1.0.3** (GUI)
- **PyInstaller** (`Феникс.exe`)
- **Inno Setup** (установщик)
- **UIA** (`uiautomation`) — в планах (Этап 1.10)
- **VLM** (через Ollama) — в планах (Этап 10)

**Репозиторий:** `C:\jarvis`
**GitHub:** `https://github.com/BobLoTiK/jarvis-fenix`
**Лицензия:** MIT + attribution jsays12.

**Два корня путей:**
- `C:\ProgramData\Phoenix\` — **ASCII**, модели (Vosk, Whisper).
- `%APPDATA%\Phoenix\` — **личные данные** (config, profiles, logs, tasks, timers).

**Почему:** Vosk (C++ Kaldi) **ломается** на не-ASCII путях. См. `jarvis/paths.py`.

---

## 🎭 Как со мной работать

**Обращение:** «брат».

**Стиль:** кратко, без воды, с юмором. Русский.

**Формат:**
- **Команды** — в `bat`-блоках.
- **Код** — в `python`-блоках, целиком или точечные патчи.
- **Патч** — с точным маркером: «найди X, замени на Y».
- **Полные файлы** — в Markdown-блоках с языком.
- **Плотно.** Не разжёвывать очевидное.
- **Не переписывать то, что не менялось.**
- **Порядок файлов в документации:** сначала `PLAN.md`, потом `PROMPT.md`, потом остальные.

**Запрещено:**
- **Костыли.** Если решение «работает, но грязно» — это не решение.
- **Хардкод.** Всё через `config.json` и `Config`.
- **Прямая запись/чтение `config.json`.** Только `Config.set()`/`config.get()`.
- **Глобальное состояние.** Кроме `Config._GLOBAL`.
- **Словари синонимов в коде** для городов/валют/паков — задача LLM.
- **Хардкод путей** — только `jarvis/paths.py`.
- **Python 3.13/3.14** — Vosk падает.
- **Коммитить** `.venv311`, `config.json`, `profiles/`, `system_caps.json`, `timers.json`, `tasks.json`, `models/`, `voices/`, `dist/`, `build/`.
- **Дёргать Vosk API из главного потока.** Vosk **не thread-safe**. Всё, что вызывает `Model`, `KaldiRecognizer`, `Reset()`, `AcceptWaveform()` — **только в listener-потоке**.
- **`prevent_close` + `on_event`** в Flet 1.0.3 — не работает, ломает крестик.
- **Ставить `HF_HOME` глобально** — Piper качает в degraded mode. Ставить временно, сбрасывать.
- **Удалять attribution `jsays12`** из `LICENSE`, `README.md`, `CHANGELOG.md`.
- **Упоминать личные данные** (имя, город, CPU, GPU, ОС) в публичных файлах.

**Поощряется:**
- **`Config.subscribe`** для реакции на изменения.
- **Разделение ответственности.**
- **Тесты** — `pytest` + `test_intents.py`.
- **Логи** — `actions.log`.
- **Реестр `_fast_handlers()`** — новые быстрые правила туда.

---

## 🚨 Ошибки, которые я уже делал (не повторяю)

1. **Дробил файл на куски** без указания, куда вставлять. → **Целиком** или **точный маркер**.
2. **`prevent_close` + `on_event`** в Flet 1.0.3 — крестик ломается. → Не использовать.
3. **`HF_HOME` глобально** — Piper в degraded mode. → Временно, сбрасывать.
4. **Забыл `sys.stdout is None`** под `pythonw`. → Всегда проверять.
5. **`wait_end` на не-стартовавшем потоке** — `RuntimeError`. → Проверка `is_alive()`.
6. **`subprocess.Popen` для трея** — `main()` зависал. → Не пихать трей через Popen.
7. **`strip_cjk_chunk` не создал** — `ImportError`. → Проверять экспорт.
8. **Не исключил `profiles/` из `snapshot.py`** — личные данные. → Исключать.
9. **`chat_stream` терял чанк** — `append` до проверки токена. → Не забывать.
10. **Патч без точного маркера.** → Всегда «найди X».
11. **`text`/`markdown` внутри код-блока** — мешает копипасте.
12. **Обрезал diff** — ты не видишь изменений.
13. **Порядок файлов** — сначала `PLAN.md`, потом `PROMPT.md`.
14. **Не смотрел логи** — гадал. → Сначала лог, потом фикс.
15. **`flush()` из главного потока** — `libvosk.dll` падал с `0xc0000015`. → Vosk только из listener-потока.
16. **Zip Slip** при распаковке Vosk — не было проверки пути. → Проверять `is_relative_to`.
17. **Мьютекс `Global\`** — требует админа. → `Local\`.
18. **Pack-команды** (`shutdown /s /t 10`) шли в `os.startfile`. → `shlex.split` + subprocess.
19. **`timers.py`/`tasks.py` писали в `BASE_DIR`.** → `paths.user_dir()`.
20. **`memory.append` не атомарный.** → `mkstemp` + `os.replace`.
21. **`config_manager` дефолт — `BASE_DIR`.** → `paths.config_path()`.
22. **`_profile_fast` regex** — «я хочу спать» создавал профиль. → Тире обязательно.
23. **`say()` падал при `listener=None`.** → Guard.
24. **GUI ↔ голос — гонка.** → `cmd_lock` в Jarvis.
25. **`recorder.stop()`** — `unhook_all()` безусловно. → Только если шла запись.
26. **`launcher.py`** — мёртвый код после `return`. → Удалять.
27. **`install.bat`** — ссылки на несуществующие `.bat`. → Проверять.
28. **`weather.py` UA** — версия устарела. → Из `__version__`.
29. **`set_llm_model.py`** — путь и неатомарность. → `paths` + `config_manager`.
30. **`start_fenix.bat`** — хардкод `C:\jarvis`. → `%~dp0`.
31. **`tts.py`** падал на невидимом тексте (`\u200b`). → Пропускать невидимые.
32. **`CHAT_SYSTEM` с кракозябрами** — `??` в файле от cp1251. → Правки только в VS Code.
33. **BOM в `intents.py`** — `invalid non-printable character U+FEFF`. → Сохранять UTF-8 **без BOM**.
34. **Онбординг на `if/elif`** — зацикливался. → LLM-диалог через `onboarding_chat()`.
35. **`_extract_name` пропускал «работает»** — ставил как имя. → Blacklist + LLM-разбор.
36. **`_small_talk` перехватывал всё** — LLM не отвечала. → Убрать «привет», «как дела» из `_small_talk`.
37. **Правки через терминал → порча файлов (cp1251, BOM).** → **Только VS Code.**
38. **`_small_talk` тест FAIL без LLM** — `small_talk_who` ожидал «Феникс». → Вернуть ответ на «кто ты» в `_small_talk`.

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

```
jarvis/
├── main.py           — Jarvis, barge-in, cmd_lock
├── config.py         — Config в памяти + подписки
├── config_manager.py — атомарная запись (FileLock per-path)
├── paths.py          — PROGRAM_DIR / USER_DIR
├── brain.py          — Ollama: parse() / chat_stream() / onboarding_chat()
├── intents.py        — IntentHandler + _fast_handlers() + _onboarding_chat_step()
├── reply.py          — Reply (text | stream)
├── gui.py            — Flet GUI + PALETTES + fireworks
├── history.py        — стек отмены
├── stt.py            — Vosk + Whisper + HF_HOME временно
├── tts.py            — Piper / XTTS / WinRT / SAPI
├── modes.py          — commands / llm / combo
├── voices.py         — голоса Piper
├── packs.py          — паки
├── profile.py        — profiles/<user>/
├── persona.py        — персона: стиль, черты, backstory
├── memory.py         — dialog.json (атомарно)
├── observer.py       — фоновое извлечение фактов через LLM
├── first_run.py      — greeting, is_first_run, mark_done
├── learning.py       — факты + коррекции
├── weather.py        — погода/курс + TTL
├── timers.py         — напоминания (USER_DIR)
├── tasks.py          — задачи (USER_DIR)
├── actions.py        — окна, медиа, _looks_like_cmd
├── text_utils.py     — normalize, strip_cjk, prepare_text
├── celebrations.py   — поздравление с ДР
├── files.py          — папки
├── apps.py           — каталог приложений
├── installed.py      — индекс «Пуск»
├── steam.py          — индекс Steam
├── matching.py       — нечёткое сравнение
├── model.py          — загрузка Vosk
├── recorder.py       — макросы
├── uia.py            — в планах (Этап 1.10)
├── vision.py         — в планах (Этап 10)
├── hermes.py         — в планах (Этап 11)
├── resources.py      — в планах (Этап 12)
└── tray.py           — отключён
```

### Поток обработки

```
Микрофон → Vosk (wake) → Whisper → Jarvis._process
   → IntentHandler.handle(cmd)   ← normalize(cmd)
      → _onboarding_chat_step (первый запуск, LLM-диалог)
      → CANCEL / memory / pending / буфер / режимы
      → custom / small_talk / скриншот / celebrations
      → _split_compound
      → ⚡ РЕЕСТР _fast_handlers()
      → brain.parse → _execute_intent
      → brain.chat_stream() → генератор
   → Reply (text | stream)
   → Jarvis.say(reply) ← cmd_lock
```

### Observer

```
Jarvis._process → observer.observe("user", cmd)
               → observer.observe("assistant", reply)
   ↓
Observer._loop (раз в 5 сек)
   → если 6+ сообщений и 30+ сек с прошлого раза
   → LLM: EXTRACT_PROMPT
   → {name, city, age, style, facts}
   → profile.set / learning.add_fact (если пусто)
```

### GUI

```
Flet главный поток
   ├── NavigationRail: Главная / Микрофон / Настройки
   ├── Кеш _tabs
   ├── page.run_task(_process_queue)
   └── page.run_task(_mic_level_loop)

Jarvis фоновый поток
   ├── listener.phrases()
   └── handler.handle() + say() ← cmd_lock
```

**Связь:** `queue.Queue()`.

### Реестр обработчиков

**`IntentHandler._fast_handlers()`** — список `(имя, функция)`.
Порядок = приоритет. `open_profile` выше `open`.

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
| 🏗 Архитектурные | 3 | 1 |
| 📝 Документация | 1 | 1 |
| 🔐 Безопасность | 1 | 1 |
| 🆕 Запуск | 1 | 1 |
| 🆕 Дизайн | 1 | 1 |
| 🆕 Unicode | 2 | 2 |
| 🆕 Автолаунчер | 1 | 1 |
| 🆕 Установщик (v1) | 1 | 1 |
| 🆕 Релиз v1.0.0 | 1 | 1 |
| 🆕 Поздравление | 1 | 1 |
| 🆕 Аудит Kimi | 25 | 25 |
| 🆕 Inno UI | 1 | 1 |
| 🆕 Знакомство через LLM-диалог | 1 | 1 |
| 🆕 Персона + стиль | 1 | 1 |
| 🆕 Observer | 1 | 1 |

**Ключевое за последние сессии:**
- **Inno UI** — `WizardStyle=modern`, `WizardImageFile`, `WizardSmallImageFile`, `PrivilegesRequired=lowest`.
- **Персона** — `jarvis/persona.py`, стили (`formal`/`friendly`/`sarcastic`/`brief`), `build_prompt_block()`.
- **Observer** — `jarvis/observer.py`, фоновое извлечение фактов через LLM каждые 30 сек.
- **Онбординг через LLM-диалог** — `brain.onboarding_chat()`, `_onboarding_chat_step()`, `_looks_like_command()`.
- **`first_run.py`** — упрощён до greeting + is_first_run + mark_done.
- **`_small_talk`** — только время/дата/«кто ты». Остальное — в LLM.
- **Фикс `test_intents.py`** — вернул «кто ты» для работы без LLM.

### 🚧 Осталось

- №75, №77 — архитектура.
- №85 — отмена ⏸.
- №86 — wake 🧪.
- №108 — трей ⏸.
- №147–148 — PyInstaller (20–30 ч).
- №121 — GitHub Actions (4–6 ч).
- №123 — тест на виртуалке.
- Этап 1.9 — Mood.
- Этап 1.10 — UIA.
- Этап 1.11 — Silero TTS.
- Этап 1.12 — VAD.
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
6. **Этап 1.9 — Mood — ❌ следующий**
7. Этап 1.10 — UIA — ❌
8. Этап 1.11 — Silero TTS — ❌
9. Этап 1.12 — VAD — ❌
10. Этап 2 — Облако — ❌
11. Этап 3 — Управление приложениями — ❌
12. Этап 4 — Vector memory — ❌
13. Этап 5 — MCP (заготовки) — ❌
14. Этап 6 — Telegram + веб — ❌
15. Этап 7 — Визуализация + Спрайт — ❌
16. Этап 8 — PyInstaller + CI + VLM + Hermes — ⏸
17. 💤 Долгий ящик — Фаза 2

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
11. Реестр `_fast_handlers()`.
12. `open_profile` выше `open`.
13. `set_profile` / `get_profile` через LLM.
14. Активация окон — `win32gui` + `AttachThreadInput`.
15. Пути — только `jarvis/paths.py`.
16. Модели Vosk/Whisper — только `PROGRAM_DIR` (ASCII).
17. `HF_HOME` для Whisper — временно.
18. Vosk API — только из listener-потока.
19. UIA — через `uiautomation`.
20. Pack-команды с аргументами — через `_looks_like_cmd` + `shlex`.
21. Атомарная запись везде: `mkstemp` + `os.replace`.
22. Zip Slip защита при распаковке.
23. **Онбординг — через LLM.** `_onboarding_chat_step()` + `brain.onboarding_chat()`. Никаких `if/elif`-сценариев.
24. **Observer — фоновое извлечение фактов.** `observer.observe("user"/"assistant", text)`. Не блокирует.
25. **Персона — в system prompt.** `persona.build_prompt_block()` → `_system_with_context()`.
26. **Правки только в VS Code.** Терминал (PowerShell) портит кодировку и BOM.
27. **UTF-8 без BOM.** `files.encoding: utf8`, `files.autoGuessEncoding: false` в settings.json.

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

### Окружение
1. Python 3.10–3.12.
2. `.venv311` — обязательный.
3. `snapshot.py` — исключать `.venv311` и `profiles/`.

### Git
1. `.gitignore` — `.venv311`, `config.json`, `profiles/`, `logs/`, `system_caps.json`, `models/`, `voices/`, `dist/`, `build/`.
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
```

---
