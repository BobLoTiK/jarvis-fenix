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

---

## 🏗 Архитектура (кратко)

### Модули

```
jarvis/
├── main.py           — точка входа, Jarvis, barge-in
├── config.py         — Config в памяти + подписки
├── config_manager.py — атомарная запись (FileLock, mkstemp, os.replace)
├── brain.py          — Ollama: parse() и chat_stream()
├── intents.py        — IntentHandler: правила + LLM
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
├── custom_commands.py — профильные команды (в планах)
├── cloud/            — облачные провайдеры (в планах)
├── weather.py        — погода + курс + настраиваемый TTL
├── timers.py         — напоминания
├── tasks.py          — задачи
├── actions.py        — окна, медиа, печать, буфер, громкость, яркость, раскладка
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
      → _open_fast / voices / packs / timers / tasks
      → _profile_fast / _memory_fast / _system_fast
      → _debug_fast / _undo_fast / _weather_currency_fast
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
   │   (в планах: +Знакомство, +Мои команды, +Режим работы)
   ├── Контент-область (кеш _tabs)
   ├── page.run_task(_process_queue)
   └── page.run_task(_mic_level_loop) — уровень микрофона + смена темы Windows

Jarvis фоновый поток
   ├── listener.phrases()
   └── handler.handle() + say()
```

**Связь:** `queue.Queue()` — Jarvis пишет, GUI читает.
**Важно:** Flet — **в главном потоке** (`gui.run_main()`), Jarvis — **в фоне**.

---

## 📋 Режимы работы

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

### ☁️ Cloud (бесплатно, ключ Groq)

- **LLM:** Llama 3.3 70B через Groq.
- **STT:** Whisper large-v3 через Groq.
- **TTS:** Edge TTS (Microsoft).
- **Погода:** real-time.
- **Fallback:** при ошибке облака — откат на local.

### 💎 Premium (отложено)

- **LLM:** GPT-4o, Claude 3.5.
- **STT:** Whisper API, Deepgram.
- **TTS:** Fish Audio (клон голоса), ElevenLabs.

---

## 📊 ТЕКУЩИЙ СТАТУС

### ✅ Закрыто (35 багов + О)

| № | Баг |
|---|---|
| №1 | `profile._current` гонка |
| №2 | Маша видит диалог Максима |
| №3 | `_awaiting_until` после `say()` |
| №6 | `CANCEL` не первым |
| №8 | `any([...])` в `_do_close` |
| №14 | `brain.parse` без `.strip()` |
| №20 | TTS накладывается |
| №21 | `_profile_fast` не матчит из GUI |
| №24 | Светлая тема ломала GUI |
| №24.5 | Системная тема не автоопределялась |
| №25 | `mic_watchdog` спамил |
| №25.5 | Микрофон не проверить из GUI |
| №26 | «открой стим» → Spotify |
| №28 | «мой город казань» в фактах |
| №29 | «мой город X» → `default_city` |
| №30 | `_match_custom` без логирования |
| №31 | `_match_custom` нечёткий матч |
| №32 | Vosk на Python 3.14 → `.venv311` |
| №33 | `requirements.txt` устарел |
| №34 | `.bat` и doskey под 3.11 |
| №35 | `.venv311` в git → `.gitignore` |
| №36 | `SNAPSHOT.md` 52 МБ → 520 КБ |
| №37 | `.git` 110 МБ → 12 МБ |
| №39 | README: Python 3.10–3.12 |
| №40 | `install.bat` под `.venv311` (проверен) |
| №41 | `commit.bat` + `aliases.cmd` |
| О1 | pip-пакеты |
| О2 | Whisper-модель |
| О3 | `check_cpu()` |
| О4 | `tts_voice_quality` |
| О5 | `_init_piper` fallback |
| О6 | GUI RadioGroup «Качество голоса» |
| О7 | README + `config.example.json` |
| О9 | TTL кэша погоды |
| — | Flet 1.x API (`ElevatedButton` → `Button`) |

### 🔴 Критично (2)

| № | Баг |
|---|---|
| №10 | Порядок импортов глушится |
| №11 | `Vosk.Reset()` не откатывает (проверить) |

### 🟡 Серьёзно (9)

| № | Баг |
|---|---|
| №5 | Факты путают `parse()` |
| №7 | `tasks.find` без lock |
| №9 | `weather._CACHE` без lock (уже есть, проверить) |
| №12 | `learning.add_fact` не проверяет `ok` |
| №13 | `Config.update` без `if ok` |
| №15 | «включи музыку» → `open_app` |
| №16 | `_debug_fast` не тот буфер (из логов — работает) |
| №17 | Макрос забивает стек (`push_macro` уже есть) |
| №18 | Мусор `profiles/maksim.json` |

### 🟢 Мелко (3)

| № | Баг |
|---|---|
| №22 | Падежи в погоде |
| №23 | LLM vs `profile.get("name")` |
| №38 | `requirements-dev.txt` отсутствует |

### 🆕 UI/UX (3)

| № | Задача |
|---|---|
| №42 | Иконка приложения |
| №43 | Сборка `.exe` |
| №44 | Ярлык на рабочем столе |

---

## 🎯 ПОРЯДОК РАБОТЫ

### ЭТАП 0 — Обновления — ✅ 8/8 закрыт

### ЭТАП 1 — Стабилизация (5 ч) — 🚧 21/27

Осталось:
- **Критичные:** №10, №11.
- **Серьёзные:** №5, №7, №9, №12, №13, №15, №16, №17, №18.
- **Мелкие:** №22, №23, №38.

### ЭТАП 1.5 — Знакомство (3.5 ч)

З1–З7.

### ЭТАП 1.6 — Стресс-тест (2 ч)

С1–С3.

### ЭТАП 1.7 — Мои команды (6.5 ч)

М1–М9.

### ЭТАП 1.8 — UI/UX (2 ч)

№42–№44: иконка, `.exe`, ярлык.

### ЭТАП 2 — Бесплатное облако (12 ч)

Ф1–Ф13.

### ЭТАП 3 — Платное облако (8.5 ч, отложено)

Ф14–Ф19.

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

### GUI

1. **Flet — только в главном потоке.**
2. **Связь через `queue.Queue()`.**
3. **Разделы — в `_tabs`.**
4. **Тема — `page.theme_mode` + `PALETTES`.**

### Безопасность

1. **Личные данные — только в `config.json`, `profiles/`, `system_caps.json`.**
2. **Все — в `.gitignore`.**
3. **`config.example.json` — только дефолты.**

### Окружение

1. **Python 3.10–3.12.** Vosk не работает на 3.13/3.14.
2. **`.venv311`** — обязательный venv.
3. **`snapshot.py`** — исключать `.venv311`.

### Git

1. **`git push`** — после `.venv311` в `.gitignore`.
2. **`git filter-repo`** — если venv попал в историю.
3. **`git config --global push.autoSetupRemote true`** — автозапрос upstream.

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