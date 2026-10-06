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
- **PyInstaller** (сборка `Феникс.exe`)
- **Inno Setup** (сборка установщика)
- **UIA** (`uiautomation`) — работа с элементами окон (в планах, Этап 1.9)

**Репозиторий:** `C:\jarvis`
**Ветка:** `main`
**GitHub:** `https://github.com/BobLoTiK/jarvis-fenix`
**CI:** GitHub Actions на `windows-latest`.

**Два корня путей:**
- `C:\ProgramData\Phoenix\` — **ASCII**, код+модели (Vosk, Whisper).
- `%APPDATA%\Phoenix\` — **личные данные** (config, profiles, logs).

**Почему:** Vosk (C++ на Kaldi) **ломается** на не-ASCII путях. Всё, что читает Vosk — в ASCII. Остальное — где угодно. См. `jarvis/paths.py`.

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
  - `.iss` → ` ```ini `
- **При запросе «скинь файл целиком»** — **всегда в Markdown-блоке**.
- **Плотно, без воды.** Не разжёвывать очевидное.
- **Не переписывать то, что не менялось.** Только diff или замена блока.
- **Порядок файлов в документации:** **`PLAN.md` → `PROMPT.md` → остальное.**

**Запрещено:**
- **Костыли.** Если решение «работает, но грязно» — это **не решение**.
- **Хардкод.** Всё через `config.json` и `Config`.
- **Прямая запись в `config.json`.** Только `Config.set()` или `config_manager.save()`.
- **Прямое чтение `config.json`.** Только `config.get()`.
- **Глобальное состояние.** Кроме `Config._GLOBAL`.
- **Словари синонимов в коде** для городов/валют/паков — **это задача LLM**.
- **Хардкод путей** — только `jarvis/paths.py`.
- **Python 3.13/3.14** — Vosk падает. Только **3.10–3.12**.
- **Коммитить `.venv311`** — `.gitignore`.
- **Коммитить `profiles/`, `config.json`, `system_caps.json`** — личное.
- **Упоминать личные данные** (имя, город, CPU, GPU, ОС) в публичных файлах:
  `PLAN.md`, `README.md`, `CHANGELOG.md`, `PROMPT.md`, `ARCHITECTURE.md`,
  `CONTRIBUTING.md`, `config.example.json`.
- **Дёргать Vosk API из главного потока.** Vosk **не thread-safe**. Всё, что вызывает `Model`, `KaldiRecognizer`, `Reset()`, `AcceptWaveform()` — **только в listener-потоке**.
- **`prevent_close = True` + `on_event`** в Flet 1.0.3 — **не работает**. Крестик перестаёт закрывать окно.
- **Ставить `HF_HOME` глобально** — Piper скачает модель в degraded mode. Ставить **временно** на импорт Whisper, **сбрасывать** до Piper.

**Поощряется:**
- **`Config.subscribe`** для реакции на изменения.
- **Разделение ответственности** — что где.
- **Тесты** — `pytest` + `test_intents.py`.
- **Логи** — в `logs/actions.log`.
- **Реестр `_fast_handlers()`** — новые быстрые правила **туда**.

---

## 🚨 Ошибки, которые я уже делал (не повторяю)

1. **Дробил файл на куски** без указания, куда вставлять — получалось 2+ блока в разных местах. → Отдавать **целиком** либо патч с **точным маркером**.
2. **`prevent_close` + `on_event`** в Flet 1.0.3 — **крестик перестаёт работать**. → Не использовать.
3. **`HF_HOME` глобально** — Piper качает в degraded mode. → Ставить **временно**, сбрасывать.
4. **Забыл `sys.stdout is None`** под `pythonw` — падал `_progress` в `model.py`. → Всегда проверять.
5. **`wait_end` на не-стартовавшем потоке** — `RuntimeError: cannot join thread before it is started`. → Проверка `thread.is_alive()`.
6. **`subprocess.Popen` для трея** — `main()` зависал. → Не пихать трей через Popen.
7. **`strip_cjk_chunk` не создал в `text_utils.py`** — `ImportError` при импорте `brain.py`. → Проверять экспорт перед импортом.
8. **Не исключил `profiles/` из `snapshot.py`** — личные данные попадали в снимок. → Исключать `profiles/` и `.venv311`.
9. **`chat_stream` терял последний чанк** — `append` до проверки токена. → Не забывать.
10. **Патч без точного маркера** — ты ищешь, путаешься. → Всегда: «найди `X`», «замени на `Y`».
11. **`text` / `markdown` внутри код-блока** — мешает копипасте. → Только чистый код.
12. **Обрезал длинный diff** — ты не видишь изменений. → Или **целиком**, или **точный кусок с маркером**.
13. **Порядок файлов в документации** — сначала `PLAN.md`, потом `PROMPT.md`. → Всегда так.
14. **Не смотрел логи** — угадывал фикс. → Сначала **лог**, потом **фикс**.
15. **`flush()` из главного потока** — `libvosk.dll` падает с `0xc0000015` (race condition). → Vosk-API **только из listener-потока**.

---

## 🗂 Пути (главное правило)

**Всё, что читает Vosk** — только в `PROGRAM_DIR` (ASCII):
- `paths.program_models_dir()` → `C:\ProgramData\Phoenix\models\`
- `paths.program_whisper_cache_dir()` → `C:\ProgramData\Phoenix\whisper-cache\`

**Личные данные** — в `USER_DIR` (кириллица ок):
- `paths.config_path()` → `%APPDATA%\Phoenix\config.json`
- `paths.logs_dir()` → `%APPDATA%\Phoenix\logs\`
- `paths.profiles_dir()` → `%APPDATA%\Phoenix\profiles\`

**HF_HOME для Whisper** ставится **временно** и **сбрасывается** — иначе Piper качает модели в наш ASCII-кэш в degraded mode (без symlinks).

---

## 🏗 Архитектура (кратко)

### Модули

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
├── packs.py          — паки команд
├── profile.py        — profiles/<user>/profile.json + subscribe
├── memory.py         — profiles/<user>/dialog.json
├── learning.py       — факты + коррекции
├── weather.py        — погода + курс + настраиваемый TTL
├── timers.py         — напоминания
├── tasks.py          — задачи
├── actions.py        — окна, медиа, печать, буфер, громкость, яркость, раскладка,
│                       open_in_editor, _activate_window_hard
├── text_utils.py     — normalize(), strip_cjk(), strip_cjk_chunk(), prepare_text()
├── uia.py            — UI Automation (в планах, Этап 1.9)
├── files.py          — папки
├── apps.py           — каталог приложений
├── installed.py      — индекс «Пуск»
├── steam.py          — индекс Steam
├── matching.py       — нечёткое сравнение
├── model.py          — загрузка Vosk в ASCII-путь
├── recorder.py       — макросы
└── tray.py           — трей (временно отключён)
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
**`open_profile` — ВЫШЕ `open`.**

**Добавить новый** — одна строка в список.

### Универсальный профиль

**Не через `re.match`**, а через LLM:
- «меня зовут X» → `set_profile` → `name`.
- «какой город» → `get_profile` → `default_city`.
- «открой профиль» → `open_profile` → Notepad++ / VS Code / системный.

---

## 📋 Режимы работы

### 🏠 Local

- **LLM:** Qwen через Ollama.
- **STT:** Vosk + Whisper small CPU.
- **TTS:** Piper (medium).
- **Погода:** кэш 24 ч (`weather_cache_ttl_sec: 86400`).

### 🌐 Hybrid

- **LLM:** Qwen 14b/32b.
- **STT:** Whisper large-v3-turbo на GPU.
- **TTS:** Piper.

### ☁️ Cloud (бесплатно, ключ Groq) — 🚧 в планах

Ф1–Ф13.

### 💎 Premium — ⏸

Ф14–Ф19.

---

## 📊 ТЕКУЩИЙ СТАТУС

### ✅ Закрыто (Этап 1 + Этап 1.6)

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
| 🆕 Unicode / пути | 2 | 2 |
| 🆕 Автолаунчер | 1 | 1 |
| 🆕 Установщик | 1 | 1 |
| 🆕 UI/UX | 3 | 2 |
| 🆕 Критичный баг Vosk | 1 | 1 |

**Ключевые:**

- **№67** — многослойные команды (`_split_compound`).
- **№69** — «потише на 10».
- **№70** — мусорный ввод.
- **№72** — `wait_end` → `bool` + защита от `join` до `start`.
- **№73** — `try/finally` в `_say_stream`.
- **№74** — TTS не накладывается.
- **№84** — `launch_mode`.
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
- **№99** — Vosk на кириллице → ASCII-путь (`paths.py`).
- **№100** — `HF_HOME` для Whisper временно.
- **№101** — автолаунчер (`launcher.py`).
- **№102** — установщик в `C:\ProgramData\Phoenix`.
- **№103** — `sys.stdout is None` под `pythonw`.
- **№104** — `wait_end` защита от `join` до `start`.
- **№106** — `text_utils.py`.
- **№107** — `libvosk.dll` race condition. `flush()` убран из главного потока.
- **№42** — иконка (`make_icon.py`).
- **№43** — `.exe` (`build_exe.py`).
- **№44** — ярлык (`create_shortcut.bat`).

### 🚧 Осталось

**🏗 Архитектурные:**
- №75 — God Object `Jarvis` (4+ ч).
- №77 — `_handle_single` — задокументировать (20 мин).

**🆕 Отмена** — ⏸ №85.

**🆕 Wake-слово** — 🧪 №86.

**🆕 UI/UX:**
- №108 — трей через отдельный процесс (2–3 ч) ⏸.

**🆕 Знакомство** (7, 3.5 ч) — З1–З7.

**🆕 Мои команды** (12, 11 ч) — К1–К12.

**🆕 Многошаговые сценарии** (6, 8 ч) — №109–№114.

**🆕 UIA — элементы окон** (6, 13–19 ч) — №115–№120.

**🆕 Фичи бесплатные** (13, 12 ч) — Ф1–Ф13.

**🆕 Управление приложениями** (6, 8–10 ч) — №45–№50.

**🆕 Persistent memory** (3, 3.5 ч) — №51–№53.

**🆕 MCP + плагины** (2, 5–6 ч) — №54–№55.

**🆕 Telegram + веб** (2, 5–6 ч) — №56–№57.

**🆕 Визуализация** (4, 8–9 ч) — №58–№61.

**💰 Платные** — ⏸ Ф14–Ф19.

**💤 Долгий ящик** — №62–№66.

---

## 🎯 ПОРЯДОК РАБОТЫ

1. **Этап 1 — Баги** — ✅
2. **Этап 1.5 — Документация** — 🚧
3. **Этап 1.6 — UI/UX** — ✅ (трей отложен)
4. **Этап 1.7 — Знакомство** — ❌
5. **Этап 1.8 — Мои команды** — ❌
6. **Этап 1.9 — UIA (элементы окон)** — ❌ ⭐ новое
7. **Этап 2 — Бесплатное облако** — ❌
8. **Этап 3 — Управление приложениями** — ❌
9. **Этап 4 — Persistent memory** — ❌
10. **Этап 5 — MCP + плагины** — ❌
11. **Этап 6 — Telegram + веб** — ❌
12. **Этап 7 — Визуализация** — ❌
13. **Этап 8 — Платное** — ⏸
14. **💤 Долгий ящик** — 💤

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
10. **`ft.BoxShadow`** — без `blur_style`.
11. **Реестр `_fast_handlers()`** — новые правила **туда**.
12. **`open_profile` — выше `open`.**
13. **`set_profile` / `get_profile`** — через LLM.
14. **Активация окон — `win32gui` + `AttachThreadInput`.**
15. **Пути — только через `jarvis/paths.py`.**
16. **Модели Vosk/Whisper — только в `PROGRAM_DIR` (ASCII).**
17. **`HF_HOME` для Whisper — временно, сбрасывать до Piper.**
18. **Vosk API — только из listener-потока.** Никаких `Reset()`/`AcceptWaveform()` из главного.
19. **UIA — через `uiautomation`.** Пока — в планах.

### GUI

1. **Flet — только в главном потоке.**
2. **Связь через `queue.Queue()`.**
3. **Разделы — в `_tabs`.**
4. **Тема — `page.theme_mode` + `PALETTES`.**
5. **`launch_mode`** — `"gui"` или `"tray"`.
6. **`_rebuild_ui_for_theme`** сохраняет историю чата.
7. **Не использовать `prevent_close` + `on_event`** — не работает в 1.0.3.

### Безопасность

1. **Личные данные — только в `config.json`, `profiles/`, `system_caps.json`.**
2. **Все — в `.gitignore`.**
3. **`config.example.json` — только дефолты.**
4. **Пароль (`danger_password`) — SHA-256.**

### Окружение

1. **Python 3.10–3.12.** Vosk не работает на 3.13/3.14.
2. **`.venv311`** — обязательный venv.
3. **`snapshot.py`** — исключать `.venv311` и `profiles/`.

### Git

1. **`.gitignore`** — `.venv311`, `config.json`, `profiles/`, `logs/`, `system_caps.json`, `models/`, `voices/`, `dist/`, `build/`.
2. **`profiles/`** — НЕ коммитить.

---

## 🛠 Как чинить баги

1. **Лог.** `%APPDATA%\Phoenix\logs\` — `jarvis.log`, `actions.log`, `errors.log`.
2. **Event Viewer** — `eventvwr.msc` → Application/System — для крашей процессов.
3. **Воспроизвести.**
4. **Локализовать.** Какой модуль?
5. **Фикс.** Без костылей.
6. **Тесты.** `python check_syntax.py` + `pytest` + `test_intents.py`.
7. **Коммит.** `fix: <краткое описание>`.

---

## 📎 БЫСТРЫЕ ССЫЛКИ

| Что | Где |
|---|---|
| **План** | `PLAN.md` |
| **Архитектура** | `ARCHITECTURE.md` |
| **Changelog** | `CHANGELOG.md` |
| **README** | `README.md` |
| **CI** | `.github/workflows/test.yml` |
| **Логи (dev)** | `C:\jarvis\logs\` |
| **Логи (installed)** | `%APPDATA%\Phoenix\logs\` |
| **Модели (installed)** | `C:\ProgramData\Phoenix\models\` |
| **Конфиг (installed)** | `%APPDATA%\Phoenix\config.json` |
| **GitHub** | `https://github.com/BobLoTiK/jarvis-fenix` |

---

**Погнали, брат.** 🚀