# 🏗 Архитектура «Феникс»

Документ описывает модули проекта, их роль и связи. Помогает быстро вникнуть в проект — человеку или LLM.

---

## Карта модулей

```
jarvis/
├── main.py           — точка входа, класс Jarvis, barge-in цикл, TTS+STT
├── config.py         — объект Config в памяти + подписки
├── config_manager.py — атомарная запись config.json (один FileLock)
├── brain.py          — LLM (Ollama): parse() интентов, chat_stream() диалога
├── intents.py        — IntentHandler: правила + LLM-разбор, все голосовые команды
├── stt.py            — Vosk (wake) + Whisper (расшифровка), калибровка barge-in
├── tts.py            — Piper / XTTS / WinRT / SAPI, Streaming TTS, _prepare_text
├── modes.py          — режимы commands / llm / combo
├── voices.py         — смена голоса Piper
├── packs.py          — загрузка/выгрузка паков команд
├── profile.py        — user_profile.json (город, имя и т.п.)
├── weather.py        — погода (open-meteo) и курс валют (ЦБ РФ)
├── timers.py         — напоминания, threading.Timer, timers.json
├── tasks.py          — списки задач, tasks.json
├── memory.py         — история диалога, dialog.json
├── actions.py        — низкоуровневые действия: окна, медиа, печать, буфер
├── files.py          — работа с папками (Desktop, Downloads, ...)
├── apps.py           — каталог известных приложений (Discord, Steam, ...)
├── installed.py      — индекс меню «Пуск»
├── steam.py          — индекс игр Steam
├── matching.py       — нечёткое сравнение + транслитерация
├── model.py          — загрузка Vosk-модели
├── recorder.py       — запись макросов (keyboard + mouse)
└── tray.py           — иконка в системном трее
```

---

## Поток обработки фразы

```
Микрофон
   ↓
stt.Listener (Vosk) — ловит wake-слово
   ↓
stt.WhisperTranscriber — уточняет расшифровку
   ↓
main.Jarvis._process → извлекает команду (без wake-слова)
   ↓
intents.IntentHandler.handle(cmd)
   ├── 1. CANCEL (стой, хватит, ...)
   ├── 2. Ответ на уточняющий вопрос (город для погоды)
   ├── 3. Буфер обмена (быстрые правила)
   ├── 4. Режимы (modes.handle_mode_command)
   ├── 5. Custom commands + паки
   ├── 6. Small talk (время, дата, привет)
   ├── 7. Скриншот
   ├── 8. Если режим commands → «не понял»
   ├── 9. brain.parse(cmd) → intent
   │       → _execute_intent → actions / files / timers / tasks / weather
   └── 10. brain.chat_stream() → стриминговый ответ LLM (генератор)
   ↓
main.Jarvis.say(reply)
   ├── если строка → speaker.play_async() + barge-in watchdog
   └── если генератор → speaker.speak_stream() + barge-in watchdog
   ↓
tts.Speaker → Piper / XTTS / WinRT / SAPI
```

---

## Поток конфига

```
config.json (на диске)
   ↓
config.Config.__init__ → config_manager.load() → читает один раз
   ↓
config.Config._data (в памяти) — источник истины
   ↓
Любой модуль: config.get("key")
   ↓
Изменение: config.set("key", value)
   ├── config_manager.save() — атомарная запись на диск
   └── Оповещение подписчиков (main.py подписан)
           ├── "tts_voice" → speaker.set_voice()
           ├── "voice_rate" → speaker.set_rate()
           ├── "mode" → handler.mode
           └── "barge_enabled" → jarvis.barge_enabled
```

**Ключевая идея:** `config.json` читается **один раз при старте**. Все чтения — из памяти. Все записи — через `Config.set()`, который:

1. Пишет на диск (атомарно через `config_manager`).
2. Оповещает подписчиков (мгновенное применение изменений).

---

## Ключевые объекты

| Объект | Модуль | Роль |
|---|---|---|
| `Config` | `config.py` | Конфиг в памяти + подписки |
| `IntentHandler` | `intents.py` | Разбор команд, все интенты |
| `Brain` | `brain.py` | LLM: `parse()` и `chat_stream()` |
| `Speaker` | `tts.py` | Синтез + воспроизведение, barge-in |
| `Listener` | `stt.py` | Микрофон, Vosk, калибровка barge-in |
| `WhisperTranscriber` | `stt.py` | Точная расшифровка через Whisper |
| `Jarvis` | `main.py` | Связка всего, wake-логика, barge-in |

---

## Внешние зависимости (критичные)

| Сервис / модель | URL / имя | Зачем |
|---|---|---|
| Ollama | `http://127.0.0.1:11434` | LLM-фолбэк. Если недоступна — работа на правилах |
| open-meteo.com | `geocoding-api.open-meteo.com` | Геокодинг городов для погоды |
| open-meteo.com | `api.open-meteo.com` | Погода |
| cbr-xml-daily.ru | `www.cbr-xml-daily.ru` | Курс валют ЦБ РФ |
| HuggingFace | `rhasspy/piper-voices` | Голоса Piper (скачиваются при первом использовании) |
| HuggingFace | `deepdml/faster-whisper-large-v3-turbo-ct2` | Модель Whisper (скачивается при первом использовании) |
| alphacephei.com | `vosk-model-small-ru-0.22.zip` | Модель Vosk (~45 МБ) |

---

## Файлы данных (не в гит)

| Файл | Что хранит |
|---|---|
| `config.json` | Личные настройки пользователя |
| `user_profile.json` | Город, имя, прочее |
| `dialog.json` | История диалога (200 последних сообщений) |
| `timers.json` | Активные напоминания |
| `tasks.json` | Список задач |
| `logs/` | Логи (`jarvis.log`, `actions.log`, `errors.log`) |
| `config.json.lock` | FileLock от `config_manager` |

---

## Тесты

- **`test_intents.py`** — 27 сценариев через `IntentHandler` без микрофона. Проверяет режимы, голоса, паки, буфер, погоду, курс, small talk, скриншот.
- **`tests/test_config_manager.py`** — параллельная запись, атомарность, битый JSON.
- **`tests/test_weather.py`** — структура ответов погоды и курса.

---

## Инструменты разработчика

| Скрипт | Что делает |
|---|---|
| `check_syntax.py` | `ast.parse()` по всем `.py` в проекте |
| `snapshot.py` | Собирает проект в `SNAPSHOT.md` |
| `scripts/selftest.py` | Самопроверка TTS → Vosk → разбор |
| `scripts/mics.py` | Выбор микрофона (показывает уровень сигнала) |
| `scripts/wakebench.py` | Бенчмарк wake-слов (TTS → Vosk) |
| `scripts/voicedemo.py` | Прослушка голосов Piper / WinRT |
| `scripts/build_exe.py` | Сборка лаунчера `launcher.py` в `.exe` |

---

## Связи между модулями (кратко)

- **`main.py`** — использует **все**: `config`, `stt`, `tts`, `intents`, `brain`, `timers`, `tray`, `apps`, `model`.
- **`intents.py`** — использует `actions`, `files`, `apps`, `installed`, `steam`, `modes`, `packs`, `memory`, `voices`, `timers`, `tasks`, `weather`, `profile`, `brain`.
- **`tts.py`** — зависит от `config` (через подписку), `piper`, `winrt`, `pyttsx3`, `coqui-tts` (опционально).
- **`stt.py`** — зависит от `vosk`, `faster-whisper`, `sounddevice`.
- **`actions.py`** — базовый слой: `pyautogui`, `pygetwindow`, `pyperclip`, `psutil`, `winrt`.
- **`config_manager.py`** — низкоуровневый: `filelock`, `tempfile`, `os.replace`.
- **`brain.py`** — зависит только от Ollama через HTTP.

---

## Что важно помнить при доработке

1. **Не добавляй `_atomic_write` в новые модули** — используй `config_manager.save()` или `Config.set()`.
2. **Не читай `config.json` напрямую** — используй `config.get()` из объекта `Config`.
3. **Не плоди глобальное состояние** — кроме `Config._GLOBAL`, он один.
4. **Нормализация (города, валюты, паков) — задача LLM**, не добавляй словари синонимов в код.
5. **Не выкидывай ошибки в `errors.log`** — это сигнал, что что-то сломалось, разбирайся.
6. **Логи в `actions.log`** — главный инструмент отладки. Если что-то не работает — смотри туда в первую очередь.
7. **`test_intents.py`** — первое, что надо запустить после любой правки в `intents.py`, `brain.py`, `actions.py`.