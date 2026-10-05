# 🏗 Архитектура «Феникс»

Документ описывает модули проекта, их роль и связи.
Помогает быстро вникнуть в проект — человеку или LLM.

---

## Карта модулей

```
jarvis/
├── main.py           — точка входа, класс Jarvis, barge-in цикл
├── config.py         — объект Config в памяти + подписки
├── config_manager.py — атомарная запись config.json (один FileLock)
├── brain.py          — LLM (Ollama): parse() и chat_stream()
├── intents.py        — IntentHandler: правила + LLM-разбор
├── reply.py          — тип Reply (text | stream)
├── gui.py            — Flet GUI (окно, чат, настройки)
├── history.py        — стек отмены («стоп, не то»)
├── stt.py            — Vosk (wake) + Whisper, ring buffer
├── tts.py            — Piper / XTTS / WinRT / SAPI, Streaming TTS
├── modes.py          — режимы commands / llm / combo
├── voices.py         — смена голоса Piper
├── packs.py          — загрузка/выгрузка паков
├── profile.py        — profiles/<user>/profile.json (мультипрофиль)
├── memory.py         — profiles/<user>/dialog.json (история)
├── weather.py        — погода (open-meteo) и курс (ЦБ РФ)
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
   ├── 2. memory.handle_memory_command
   ├── 3. pending_question (город для погоды, пароль)
   ├── 4. Буфер обмена
   ├── 5. Режимы (modes)
   ├── 6. Custom commands + паки
   ├── 7. Small talk
   ├── 8. Скриншот
   ├── 9. _open_fast (открытие приложений)
   ├── 10. Голоса (voices)
   ├── 11. Паки (packs)
   ├── 12. Таймеры (timers)
   ├── 13. Задачи (tasks)
   ├── 14. Профиль (_profile_fast)
   ├── 15. Память (_memory_fast)
   ├── 16. Системное (_system_fast — раскладка, громкость, яркость)
   ├── 17. Диагностика (_debug_fast — «что слышал», «почему не понял»)
   ├── 18. Отмена (_undo_fast — «стоп, не то»)
   ├── 19. Погода/курс (_weather_currency_fast)
   ├── 20. brain.parse(cmd) → intent → _execute_intent
   └── 21. brain.chat_stream() → генератор
   ↓
main.Jarvis.say(reply)
   ├── если text → speaker.play_async()
   └── если stream → speaker.speak_stream() + tee → gui.add_stream_chunk()
   ↓
tts.Speaker → Piper / XTTS / WinRT / SAPI
```

---

## GUI (Flet)

```
Flet Main Thread
   ├── NavigationRail (слева): Главная / Микрофон / Настройки
   ├── Контент-область (переключается):
   │   ├── Главная: статус-сфера, контролы, чат, ввод
   │   ├── Микрофон: dropdown устройств
   │   └── Настройки: LLM / TTS / тема
   └── page.run_task(_process_queue) — читает очередь

Jarvis Thread
   ├── listener.phrases() → _process(cmd)
   ├── handler.handle(cmd) → Reply
   └── say(reply):
       ├── text → gui.add_message("assistant", text)
       └── stream → tee → gui.add_stream_chunk(chunk)
```

**Связь:** `queue.Queue()` → `gui._queue`. `Jarvis` пишет, GUI читает в `_process_queue`.

**Важно:** Flet запускается в **главном потоке** (`gui.run_main()`), потому что ставит `signal.signal(SIGINT, ...)` — работает только в главном. Jarvis — **в фоне**.

---

## Мультипрофиль

```
profiles/
├── maksim/
│   ├── profile.json    ← name, default_city, facts, tts_voice
│   └── dialog.json     ← история диалога
└── masha/
    ├── profile.json
    └── dialog.json
```

- **Активный профиль** — по имени Windows-юзера (`getpass.getuser()`).
- **`profile.switch(name)`** — переключение («я — Маша»).
- **Миграция** из старого `user_profile.json` при первом запуске.
- **`.gitignore`:** `profiles/`.

---

## Поток конфига

```
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
       └── "llm_context_messages" → handler._llm_context
```

---

## Ключевые объекты

| Объект | Модуль | Роль |
|---|---|---|
| `Config` | `config.py` | Конфиг в памяти + подписки |
| `IntentHandler` | `intents.py` | Разбор команд |
| `Brain` | `brain.py` | LLM: `parse()` и `chat_stream()` |
| `Speaker` | `tts.py` | Синтез + воспроизведение, barge-in |
| `Listener` | `stt.py` | Микрофон, Vosk, ring buffer |
| `WhisperTranscriber` | `stt.py` | Точная расшифровка |
| `Jarvis` | `main.py` | Связка всего, wake-логика |
| `FenixGUI` | `gui.py` | Flet GUI |
| `Reply` | `reply.py` | `text` \| `stream` |
| `history` | `history.py` | Стек отмены |

---

## Файлы данных (не в гит)

| Файл | Что хранит |
|---|---|
| `config.json` | Настройки |
| `profiles/<user>/profile.json` | Имя, город, факты |
| `profiles/<user>/dialog.json` | История диалога |
| `timers.json` | Напоминания |
| `tasks.json` | Задачи |
| `logs/` | Логи |
| `config.json.lock` | FileLock |

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

---

## Тесты

- **`test_intents.py`** — 30 сценариев.
- **`tests/test_config_manager.py`** — параллельная запись.
- **`tests/test_weather.py`** — погода/курс с моками.

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