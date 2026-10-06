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
├── intents.py        — IntentHandler: правила + LLM-разбор
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
├── actions.py        — окна, медиа, печать, буфер, громкость, яркость, раскладка
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
   ├── 1. Конструктор команд (learn_trigger / learn_action / learn_confirm)
   ├── 2. CANCEL (стой, хватит, ...)
   ├── 3. memory.handle_memory_command
   ├── 4. pending_question (город для погоды, пароль)
   ├── 5. Буфер обмена
   ├── 6. Режимы (modes)
   ├── 7. Custom commands + паки
   ├── 8. Small talk
   ├── 9. Скриншот
   ├── 10. _open_fast (открытие приложений)
   ├── 11. Голоса (voices)
   ├── 12. Паки (packs)
   ├── 13. Таймеры (timers)
   ├── 14. Задачи (tasks)
   ├── 15. Профиль (_profile_fast)
   ├── 16. Память (_memory_fast)
   ├── 17. Системное (_system_fast — раскладка, громкость, яркость)
   ├── 18. Диагностика (_debug_fast — «что слышал», «почему не понял»)
   ├── 19. Отмена (_undo_fast — «стоп, не то»)
   ├── 20. Погода/курс (_weather_currency_fast)
   ├── 21. brain.parse(cmd) → intent → _execute_intent
   └── 22. brain.chat_stream() → генератор
   ↓
main.Jarvis.say(reply)
   ├── если text → speaker.play_async()
   └── если stream → speaker.speak_stream() + tee → gui.add_stream_chunk()
   ↓
tts.Speaker → Piper / XTTS / WinRT / SAPI
```

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
- **`profile.switch(name)`** — переключение («я — Маша»).
- **`profile.subscribe(callback)`** — подписка на смену (old_name, new_name).
- **`IntentHandler._on_profile_switch`** — перечитывает `dialog`.
- **`FenixGUI._on_profile_switch`** (в планах) — открывает вкладку «Знакомство».
- **Миграция** из старого `user_profile.json` при первом запуске.
- **`.gitignore`:** `profiles/`.

### Специальные шаблоны в `_profile_fast`

- «запомни: мой город X» / «мой город X» → `default_city`.
- «запомни: меня зовут X» / «меня зовут X» → `name`.
- «запомни: я живу в X» / «я живу в X» → `default_city`.
- «запомни: X» → `facts["X"] = "да"`.

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

## Ключевые объекты

| Объект | Модуль | Роль |
|---|---|---|
| `Config` | `config.py` | Конфиг в памяти + подписки |
| `IntentHandler` | `intents.py` | Разбор команд |
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
- **`scripts/stress_test.py`** (в планах) — 20 фраз.

---

## Инфраструктура

### `.venv311`

**Python 3.11** в **отдельном venv** — обход падения Vosk на Python 3.13/3.14.

- `.gitignore` — `.venv311/`.
- `snapshot.py` — `EXCLUDE_DIRS` содержит `.venv311`.
- `commit.bat`, `check_all.bat`, `check_syntax.bat` — активируют venv.

### Git

- **`.gitignore`:** `.venv311/`, `*.bak`, `config.json`, `profiles/`, `logs/`, `system_caps.json`, `SNAPSHOT.md` (нет), `models/`, `voices/`.
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
13. **Личные данные — только в `config.json`, `profiles/`, `system_caps.json`** (в `.gitignore`).
14. **`weather_cache_ttl_sec`** — настраиваемый TTL кэша погоды (600 по умолчанию, 86400 для Local-режима).
15. **Python 3.10–3.12** — Vosk не работает на 3.13/3.14. Только `.venv311`.
16. **`snapshot.py`** — исключать `.venv311` (иначе `SNAPSHOT.md` = 52 МБ).
17. **`.venv311` в `.gitignore`** — не коммитить. Если попал — `git rm -r --cached .venv311`.