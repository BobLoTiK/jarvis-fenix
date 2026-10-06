# Как контрибьютить в Феникс

Документ для себя-будущего и для LLM, которая помогает с проектом.

## 🎯 Главное правило

**Не добавляй костыли.** Если решение «работает, но выглядит грязно» —
это не решение. Лучше потратить час сейчас, чем три — через месяц.

## 📁 Структура

```
jarvis/             — пакет
  reply.py          — тип Reply (text | stream)
  intents.py        — разбор команд, быстрые правила + LLM
  main.py           — точка входа, Jarvis, barge-in
  brain.py          — Ollama: parse() и chat_stream()
  config.py         — Config в памяти + подписки
  config_manager.py — атомарная запись
  tts.py            — Piper / XTTS / WinRT / SAPI + per-call token
  stt.py            — Vosk + Whisper + ring buffer
  gui.py            — Flet GUI + PALETTES + _detect_system_theme()
  ...

tests/              — pytest-тесты
test_intents.py     — интент-тесты (без микрофона)
check_syntax.py     — синтаксис всех .py
snapshot.py         — сборка SNAPSHOT.md

packs/              — JSON-паки команд
scripts/            — утилиты (mics, wakebench, build_exe)
.github/workflows/  — CI
```

## 📝 Правила кода

1. **Не читай `config.json` напрямую** — используй `config.get()` из объекта `Config`.
2. **Не пиши в `config.json` напрямую** — только `Config.set()` или `config_manager.save()`.
3. **Не плоди глобальное состояние** — кроме `Config._GLOBAL`.
4. **Нормализация (города, валюты, паков) — задача LLM.** Не добавляй словари синонимов в код без нужды.
5. **Логи в `actions.log`** — главный инструмент отладки.
6. **Не выбрасывай ошибки в `errors.log`** — это сигнал, что что-то сломалось, разбирайся.
7. **`test_intents.py`** — первое, что запускаешь после правки `intents.py`, `brain.py`, `actions.py`.
8. **`normalize(cmd)` в `IntentHandler.handle()`** — единая точка нормализации для GUI и голоса.
9. **Per-call stop-token в `tts.py`** — не используй общий `_stop_flag`. Каждый вызов `play_async` / `speak_stream` создаёт свой токен.
10. **`PALETTES` в `gui.py`** — две палитры (dark/light), `_detect_system_theme()` для системной темы через реестр Windows.
11. **`ft.Button`** вместо `ft.ElevatedButton` / `ft.TextButton` — в Flet 1.x их удалили.
12. **`weather_cache_ttl_sec`** — читается **на каждый вызов** через `weather._current_ttl()`, не кэшируй TTL.
13. **`snapshot.py`** — исключай `.venv311` из `EXCLUDE_DIRS` (иначе `SNAPSHOT.md` = 52 МБ).

## 🔒 Правила безопасности

**Никогда не упоминай в публичных файлах** (`README.md`, `PLAN.md`, `CHANGELOG.md`, `ARCHITECTURE.md`, `PROMPT.md`, `CONTRIBUTING.md`, `config.example.json`):

- Имя пользователя.
- Город.
- Модель CPU / GPU.
- ОС.

**Всё личное — только в:**
- `config.json`.
- `profiles/`.
- `system_caps.json`.

**И они — в `.gitignore`.**

## 🚀 Рабочий процесс

### 1. Правка

Правь файлы в `jarvis/`. **Один патч — одна задача.**

### 2. Проверка синтаксиса

```bat
python check_syntax.py
```

### 3. Тесты

```bat
python -m pytest tests/ -q
python test_intents.py
```

### 4. Обновление SNAPSHOT

```bat
python snapshot.py
```

### 5. Коммит

```bat
commit "fix: краткое описание"
```

**`commit.bat`** сам:
1. Активирует `.venv311`.
2. Запустит `snapshot.py`.
3. `git add .` → `git commit` → `git push`.

## 🎨 Стиль

### Комментарии

**Хорошо:**
```python
# Per-call stop-token: каждый вызов создаёт свой Event.
# Иначе старый поток не завершится, и будет 2-3 голоса одновременно.
```

**Плохо:**
```python
# создаём токен
token = threading.Event()
```

### Имена

- **Переменные:** `snake_case`.
- **Классы:** `PascalCase`.
- **Константы:** `UPPER_SNAKE`.
- **Приватные методы:** `_method`.

### Логи

**Хорошо:**
```python
log.info("Custom (точно): %r → %r, action=%r", cmd, phrase, action)
```

**Плохо:**
```python
print("custom matched")
```

## 🧪 Тесты

### Что писать

- **Новые интенты** — сценарий в `test_intents.py`.
- **Новые функции** с логикой — `pytest`.
- **Погода/курс** — с моками `_http_get_json`.

### Чего не делать

- **Не тестируй GUI** — Flet требует окно.
- **Не тестируй звук** — в CI нет звуковой карты.
- **Не тестируй сеть** — если тест требует интернет, добавь флаг `--network`.

## ⚠️ Частые ошибки

1. **Читать `config.json` руками** — используй `config.get()`.
2. **Писать в `config.json` руками** — `Config.set()`.
3. **Использовать общий `_stop_flag` в TTS** — per-call токен.
4. **Коммитить `.venv311`** — `.gitignore`.
5. **Коммитить `config.json`, `profiles/`, `system_caps.json`** — личное.
6. **Коммитить `SNAPSHOT.md` > 1 МБ** — исключай `.venv311` в `snapshot.py`.
7. **Использовать Python 3.13/3.14** — Vosk падает. Только 3.10–3.12.
8. **Запускать Flet не в главном потоке** — `signal.signal` не работает.
9. **`ElevatedButton`/`TextButton` в Flet 1.x** — используй `ft.Button`.
10. **Хардкодить пути** — через `BASE_DIR` и `Path.home()`.

## 📦 Как добавить новый интент

### 1. Быстрое правило (без LLM)

В `jarvis/intents.py`, в `_handle_single` — **до** `brain.parse()`:

```python
if cmd == "привет феникс":
    return "Привет!"
```

**Где вставлять:** после `_match_custom`, до `_open_fast`.

### 2. Через LLM

В `jarvis/brain.py`, в `ACTIONS` — добавь action:

```python
ACTIONS = {
    ...,
    "my_new_action",
}
```

В `SYSTEM_SMALL` / `SYSTEM_MEDIUM` / `SYSTEM_LARGE` — добавь описание и пример.

В `IntentHandler._execute_intent` — обработай:

```python
if action == "my_new_action":
    ...
    return "Готово."
```

## 📦 Как добавить новый пак

1. Создай `packs/my_pack.json`:

```json
[
  {"phrases": ["моя команда"], "action": "open_app:discord", "reply": "Открываю."}
]
```

2. В `config.json`:

```json
"active_packs": ["apps", "games", "sites", "system", "work", "my_pack"]
```

3. **Проверь:** «какие паки» → должен появиться `my_pack`.

## 📦 Как добавить свою фразу

1. В `config.json` → `custom_commands`:

```json
{
  "phrases": ["открой мой сайт"],
  "action": "https://example.com",
  "reply": "Открываю."
}
```

2. **Проверь:** скажи «открой мой сайт» → откроется `example.com`.

## 📦 Как добавить новый TTS-голос

1. В `jarvis/voices.py` → `PIPER_VOICES`:

```python
PIPER_VOICES = {
    ...,
    "my_voice": "Мой голос — описание",
}
```

2. Скачай модели с HuggingFace: `rhasspy/piper-voices` → `ru/ru_RU/my_voice/medium/`.

3. **Проверь:** «смени голос на мой голос» → должен переключиться.

## 🚨 Если что-то сломалось

1. **Посмотри `logs/errors.log`** — там трейсбек.
2. **Посмотри `logs/actions.log`** — там команды и интенты.
3. **Запусти `check_syntax.py`** — может, опечатка.
4. **Запусти `test_intents.py`** — может, регрессия.
5. **Откати коммит** — если совсем плохо:

```bat
git reset --hard HEAD~1
```

## 📋 Чек-лист перед коммитом

- [ ] `python check_syntax.py` — без ошибок.
- [ ] `python -m pytest tests/ -q` — все тесты зелёные.
- [ ] `python test_intents.py` — все интенты проходят.
- [ ] **Не коммичу** `.venv311`, `config.json`, `profiles/`, `system_caps.json`.
- [ ] **Проверил** `git status` — нет лишних файлов.
- [ ] **Личные данные** не попали в публичные файлы.
- [ ] **Сообщение коммита** — понятное.

## 🤝 Как задавать вопросы

**Хорошо:**

> Брат, `_open_fast` не срабатывает для «открой спотифай». Вот лог: `...`.
> Где копать?

**Плохо:**

> Ничего не работает, помоги!

**Хорошо:**

> Брат, вот скриншот лога. Вижу `match_score: 0.46` для Spotify. Что делаем?

**Плохо:**

> Посмотри логи.

## 🎯 Философия

1. **Стабильность важнее фич.** Сначала багфиксы, потом новые возможности.
2. **Логи — источник истины.** Если в логе нет — значит не было.
3. **Тесты — страховка.** Не пиши код без тестов, если он трогает интенты.
4. **Простота — залог долговечности.** Если решение сложное — упрости.
5. **Один патч — одна задача.** Не смешивай фикс бага и новую фичу.

---

**Погнали, брат.** 🚀