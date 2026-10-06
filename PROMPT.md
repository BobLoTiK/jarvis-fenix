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