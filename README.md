# Феникс

[![tests](https://github.com/BobLoTiK/jarvis-fenix/actions/workflows/test.yml/badge.svg)](https://github.com/BobLoTiK/jarvis-fenix/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/BobLoTiK/jarvis-fenix)](https://github.com/BobLoTiK/jarvis-fenix/releases)

Локальный голосовой ассистент для Windows. Форк проекта
[jsays12/jarvis](https://github.com/jsays12/jarvis).

Офлайн для распознавания и синтеза речи (Vosk + Whisper + Piper).
Онлайн — только для погоды и курса валют (с кэшем). Опционально —
Qwen 2.5 через Ollama для свободного диалога и разбора сложных фраз.

---

## Содержание

- [Что добавлено в форке](#что-добавлено-в-форке)
- [Требования](#требования)
- [Установка](#установка)
- [Первый запуск](#первый-запуск)
- [Возможные проблемы](#возможные-проблемы)
- [GUI (Flet)](#gui-flet)
- [Режимы работы](#режимы-работы)
- [Настройка LLM (Ollama)](#настройка-llm-ollama)
- [Паки команд](#паки-команд)
- [Мультипрофиль](#мультипрофиль)
- [Память диалога](#память-диалога)
- [Отмена действий](#отмена-действий)
- [Пароль на опасные](#пароль-на-опасные)
- [Голоса](#голоса)
- [Barge-in (перебивание)](#barge-in-перебивание)
- [Микрофон](#микрофон)
- [Темы GUI](#темы-gui)
- [Поздравление с ДР](#поздравление-с-др)
- [Логи](#логи)
- [Погода и курс валют](#погода-и-курс-валют)
- [Команды](#команды)
- [Свои команды](#свои-команды)
- [Сборка `.exe` и установщик](#сборка-exe-и-установщик)
- [Автозапуск](#автозапуск)
- [Инструменты разработчика](#инструменты-разработчика)
- [CI](#ci)
- [Что в планах](#что-в-планах)
- [Технологии](#технологии)
- [Лицензия](#лицензия)

---

## Что добавлено в форке

### Этап 0: рефакторинг
- Единый `config_manager.py` — `FileLock per-path`, `mkstemp`, `os.replace`.
- Объект `Config` в памяти — подписки.
- Калибровка Barge-in.
- CJK-фильтр.
- Тесты — `test_intents.py` + `pytest`.

### Этап 1: команды
- Голосовые режимы.
- Паки команд.
- Запись действий, память диалога, голоса Piper.

### Этап 2: живой диалог
- Streaming TTS.
- Barge-in.
- Логи по категориям.
- Буфер обмена.
- Погода/курс + настраиваемый TTL.

### Этап 3: Reply + CI
- `jarvis/reply.py`.
- Быстрые правила без LLM.
- GitHub Actions.

### Этап 4: системные команды
- Раскладка RU/EN через `SendInput`.
- Громкость в % через `pycaw`.
- Яркость в % через `screen-brightness-control`.
- Диагностика, отмена, пароль (SHA-256).

### Этап 5: мультипрофиль
- `profiles/<user>/`.
- `profile.subscribe()`.
- Универсальные `set_profile` / `get_profile`.

### Этап 6: Flet GUI
- Окно 1100×760, NavigationRail, статус-сфера, чат-пузыри.
- Темы: Тёмная / Светлая / Системная (на лету).
- Стриминг в GUI через tee-генератор.
- Вкладка «Микрофон».
- Иконка окна.

### Этап 7: реестр + Unicode-пути
- `_fast_handlers()`.
- `open_profile` — Notepad++ → VS Code → системный.
- `jarvis/paths.py` — PROGRAM_DIR (ASCII) / USER_DIR.
- Vosk работает даже на кириллице в `%APPDATA%`.
- `HF_HOME` для Whisper временно.

### Этап 8: автолаунчер и установщик
- `launcher.py` — сам ставит Python/venv/зависимости/Vosk.
- `Феникс.exe` (PyInstaller).
- `Феникс_Setup.exe` (Inno Setup) → `C:\ProgramData\Phoenix`.
- `LICENSE` (MIT + attribution).

### Этап 9: поздравление с ДР
- `jarvis/celebrations.py` — триггер «я папа» / «я Александр».
- Двойная цепочка: короткое поздравление → салют → длинное → финальный салют.
- Анимация через Stack + Container.

### Этап 10: аудит Kimi (23 бага)
- Pack-команды с аргументами теперь работают.
- `timers.py` / `tasks.py` — в USER_DIR.
- Атомарная запись везде.
- `config_manager` — дефолт через `paths`.
- `HF_HOME` — временно.
- Regex профиля — тире обязательно.
- `say()` guard на `listener=None`.
- `cmd_lock` — сериализация GUI↔голос.
- `recorder.stop()` — только если шла запись.
- Zip Slip защита.
- Мьютекс `Local\`.
- `tts.py` — пропуск невидимого текста.

---

## Требования

- Windows 10/11 (x64)
- **Python 3.10–3.12** (3.11 рекомендуется)
  - ⚠️ 3.13/3.14 **не поддерживается** — Vosk падает.
- Микрофон
- **Microsoft Visual C++ 2015-2022 Redistributable** (обычно есть со Steam/Chrome)
- Опционально: NVIDIA GPU (Whisper)
- Опционально: Ollama (LLM)

**Проверить VC++ Redist:** Win+R → `appwiz.cpl`. Если нет — [vc_redist.x64.exe](https://aka.ms/vs/17/release/vc_redist.x64.exe).

---

## Установка

### Автоматическая
1. Скачай `Феникс_Setup.exe` из релизов.
2. Запусти.
3. Запусти ярлык «Феникс». При первом запуске:
   - Проверка Python → скачивание, если нет.
   - Создание `.venv311`.
   - `pip install` (5–10 мин).
   - Скачивание Vosk-модели (~45 МБ).
   - Проверка Ollama.
   - Запуск.

### Ручная (для разработки)
```bat
git clone https://github.com/BobLoTiK/jarvis-fenix.git
cd jarvis-fenix
py -3.11 -m venv .venv311
.venv311\Scripts\activate.bat
pip install -r requirements.txt
python -m jarvis
```

---

## Первый запуск

При первом запуске скачается:
- Vosk (~45 МБ) → `C:\ProgramData\Phoenix\models\`.
- Whisper large-v3-turbo (~1.5 ГБ) → `C:\ProgramData\Phoenix\whisper-cache\`.
- Piper-голос (~60 МБ) → туда же.

---

## Возможные проблемы

### 1. Python installer не запустился
UAC, антивирус. → Скачай вручную: [python-3.11.9-amd64.exe](https://www.python.org/downloads/release/python-3119/).

### 2. `pip install` упал
Нет VC++ Redist. → Установи [vc_redist.x64.exe](https://aka.ms/vs/17/release/vc_redist.x64.exe).

### 3. Whisper не качается
HF тормозит. → Подожди или `"use_whisper": false` в config.

### 4. Ollama не находит модели
`echo %OLLAMA_MODELS%`, `ollama list`. Проверь `ollama_url` в config.

### 5. Vosk падает на кириллице
Не трогай `paths.py`. Модель **всегда** в `C:\ProgramData\Phoenix\models\`.

### 6. `libvosk.dll` ACCESS_VIOLATION
Уже починено (убран `flush` из `say`). Если повторится — `eventvwr.msc`.

### 7. Микрофон молчит
Настройки → Приватность → Микрофон. В GUI: Настройки → Микрофон → «Проверить».

### 8. Голос звучит «механически»
`voice_rate: 1.15` в config. Через GUI: Настройки → Скорость речи.

### 9. «Ollama не установлена»
Скачай [OllamaSetup.exe](https://ollama.com/download), `ollama serve`, `ollama pull qwen2.5:7b-instruct`.

### 10. Окно Феникса не открывается
`%APPDATA%\Phoenix\logs\launcher.log` и `jarvis.log`.

---

## GUI (Flet)

- NavigationRail: Главная / Микрофон / Настройки.
- Статус-сфера.
- Чат-пузыри.
- Поле ввода + Send / Mic.
- Настройки: LLM, Ollama URL, TTS, скорость, тема.
- Микрофон: уровень, тест, выбор устройства.

**Режим запуска:** `"launch_mode": "gui"`.

**Отключить GUI:** `"gui_enabled": false`.
**Отключить трей:** `"tray_enabled": false`.

---

## Режимы работы

### 🏠 Local
LLM: Qwen, STT: Vosk + Whisper small CPU, TTS: Piper medium.

### 🌐 Hybrid
LLM: 14b/32b, STT: Whisper на GPU.

### ☁️ Cloud — 🚧 в планах
Groq, Edge TTS.

### 💎 Premium — ⏸
GPT-4o, Claude, Fish Audio.

---

## Настройка LLM (Ollama)

```json
"llm_model": "qwen2.5:7b-instruct",
"use_llm": true,
"ollama_url": "http://127.0.0.1:11434"
```

| Модель | VRAM | Качество |
|---|---|---|
| `qwen2.5:0.5b` | ~0.5 ГБ | Слабо |
| `qwen2.5:3b-instruct` | ~3 ГБ | Заметно лучше |
| `qwen2.5:7b-instruct` | ~5–6 ГБ | Отличное |
| `qwen2.5:14b-instruct` | ~10 ГБ | Максимум для 12 ГБ |
| `qwen2.5:32b-instruct` | ~20 ГБ | Профессиональное |
| `gemma2:2b` | ~1.5 ГБ | Быстрая |
| `llama3.1:8b` | ~5 ГБ | Многоязычная |
| `mistral:7b` | ~5 ГБ | Быстрая |

---

## Паки команд

Папка `packs/`. Активные — `active_packs`.
Готовые: `games`, `apps`, `sites`, `work`, `system`.

- «загрузи пак игр»
- «выгрузи пак игр»
- «какие паки»

---

## Мультипрофиль

```
%APPDATA%\Phoenix\profiles\
├── maksim/
│   ├── profile.json
│   └── dialog.json
└── masha/
```

Голосом:
- «я — Маша» — создать/переключиться.
- «кто активен?».
- «список профилей».
- «удали профиль Маша» (с паролем).
- «меня зовут X» → `set_profile`.
- «мой город Y» → `set_profile`.
- «как меня зовут» → `get_profile`.
- «открой профиль» → Notepad++ / VS Code.

---

## Память диалога

- «что мы обсуждали».
- «забудь всё».
- «короткая память» → 40.
- «обычная память» → 100.
- «долгая память» → 200.

---

## Отмена действий

- «не то» / «отмени» / «верни как было».
- Стек — 5 действий.

---

## Пароль на опасные

```json
"danger_password": "sha256:..."
```

**Опасные:** выключение, перезагрузка, `kill_process`, `clear_tasks`, `cancel_timers`, `delete_profile`.

---

## Голоса

| Голос | Описание |
|---|---|
| `ruslan` | Мужской, спокойный |
| `dmitri` | Мужской, ниже |
| `irina` | Женский |
| `denis` | Мужской, дикторский |

- «смени голос на Ирину».
- Смена на лету.
- Через GUI.

**Качество:** `medium` (по умолчанию) / `high`.

---

## Barge-in (перебивание)

1. Первые 0.5 сек — слепое окно.
2. Порог = `эхо × 1.8`.
3. Громче порога >100 мс → TTS прерывается.

**Настройка:** `"barge_enabled": true`.

---

## Микрофон

Вкладка «Микрофон»:
- Прогресс-бар уровня.
- Кнопка «Проверить (3 сек)»: ≥500 ✅, ≥100 ⚠️, <100 ❌.
- Выбор устройства.

`mic_watchdog` — одно предупреждение за сессию.

---

## Темы GUI

- Системная (авто через реестр).
- Тёмная.
- Светлая.

Смена — на лету.

---

## Поздравление с ДР

Скажи: «**я папа**» / «**я Александр**» / «**Александр**».

Феникс:
1. «Поздравляю! С днём рождения!» (голос).
2. Салют #1 (6 сек) + звук ×2.
3. Полное поздравление (голос).
4. Салют #2 (10 сек, больше взрывов) + звук ×3.

---

## Логи

`%APPDATA%\Phoenix\logs\`:

| Файл | Что |
|---|---|
| `jarvis.log` | Общий |
| `actions.log` | Команды, интенты |
| `errors.log` | WARNING и ERROR |
| `launcher.log` | Логи лаунчера |
| `test_intents.log` | Логи тестов |

---

## Погода и курс валют

- **Погода:** `open-meteo.com`.
- **Курс:** `cbr-xml-daily.ru`.

```json
"weather_cache_ttl_sec": 600
```

---

## Команды

**Приложения:** «открой стим», «закрой дискорд», «запусти сабнатику».
**Сайты:** «открой ютуб», «открой хабр».
**Поиск:** «загугли погоду», «найди на ютубе лофи».
**Печать:** «напечатай привет мир».
**Окна:** «сверни все окна», «разверни браузер».
**Скриншот:** «сделай скриншот».
**Файлы:** «создай файл список покупок».
**Музыка:** «включи музыку», «пауза».
**Громкость/яркость:** «громкость 50», «яркость 30».
**Раскладка:** «переключи раскладку».
**Время:** «который час».
**Разговор:** «как дела», «расскажи шутку».
**Голос:** «смени голос на Ирину».
**Буфер:** «что в буфере».
**Погода:** «какая погода», «курс доллара».
**Паки:** «загрузи пак игр».
**Профиль:** «я — Маша», «меня зовут X».
**Память:** «что мы обсуждали», «забудь всё».
**Поздравление:** «я папа», «я Александр».
**Отмена:** «не то», «отмени».
**Диагностика:** «что ты слышал», «почему не понял».
**Стоп:** «стой», «хватит», «отбой».

---

## Свои команды

```json
{
  "phrases": ["открой конфиг"],
  "action": "C:\\jarvis\\config.json",
  "reply": "Открываю конфиг."
}
```

**Типы:** путь, `open_app:discord`, `browser`, URL, `steam://`, `{"steps": [...]}`.

**Команды с аргументами:** `"shutdown /s /t 10"`, `"cmd /k ipconfig"`, `"rundll32.exe ..."` — распознаются и идут в subprocess.

---

## Сборка `.exe` и установщик

```bat
python scripts\make_icon.py
python scripts\build_exe.py
REM потом в Inno Setup → Build → Compile
create_shortcut.bat
```

---

## Автозапуск

Win+R → `shell:startup` → Enter → скопировать ярлык.

---

## Инструменты разработчика

| Скрипт | Что |
|---|---|
| `install.bat` | Установка |
| `start_fenix.bat` | Без консоли |
| `start_fenix_debug.bat` | С логами |
| `check_syntax.py` | Синтаксис |
| `test_intents.py` | 40 сценариев |
| `snapshot.py` | `SNAPSHOT.md` |
| `commit.bat` | Автокоммит |
| `scripts/make_icon.py` | Иконка |
| `scripts/build_exe.py` | `.exe` |
| `scripts/mics.py` | Микрофон |
| `scripts/wakebench.py` | Бенчмарк |
| `scripts/voicedemo.py` | Голоса |
| `scripts/check_caps.py` | Возможности системы |
| `create_shortcut.bat` | Ярлык |
| `installer.iss` | Inno Setup |

**Тесты:**
```bat
python check_syntax.py
python -m pytest tests/ -v
python test_intents.py
```

---

## CI

При push:
1. Синтаксис.
2. `pytest`.
3. `test_intents.py`.

**Подробнее** — `CI.md`.

**Локально:**
```bat
python test_intents.py                  # без LLM, без сети
python test_intents.py --llm            # + LLM
python test_intents.py --network        # + погода/курс
python test_intents.py --llm --network  # всё
python test_intents.py --voice          # с озвучкой
python test_intents.py -k weather       # фильтр
```

---

## Что в планах

### 🎯 Этап 1.7 — Красивый установщик (1–2 ч)
Inno Setup с кастомной тёмной темой и лого.

### 🎯 Этап 1.8 — Знакомство (3.5 ч)
Persona, onboarding, «поменяй стиль».

### 🎯 Этап 1.9 — Мои команды (11 ч)
«Феникс, научись новому», рецепты.

### 🎯 Этап 1.10 — UIA (13–19 ч)
`uiautomation`. «Закрой вкладку YouTube», «нажми OK», «что написано в блокноте».

### 🎯 Этап 2 — Бесплатное облако (12 ч)
Groq (Llama 3.3 70B, Whisper), Edge TTS.

### 🎯 Этап 3 — Управление приложениями (8–10 ч)
Глубокое управление.

### 🎯 Этап 7 — Визуализация (8–9 ч)
Живая сфера, спектр, кастомные темы.

### ⏸ Отложено
- Трей (отдельный процесс).
- Платные фичи (GPT-4o, Claude).
- MCP + плагины.
- Telegram + веб.
- Persistent memory.
- Wake-слово (openWakeWord).
- **Сборка в один `.exe`** (PyInstaller) — 20–30 ч.
- **GitHub Actions авторелизы** — 4–6 ч.
- **VLM-зрение** — 6–10 ч.
- **Мост Феникс → Hermes** — 4–6 ч.
- **Приоритеты и очередь** — 3–5 ч.

---

## Технологии

| Компонент | Решение |
|---|---|
| Wake-слово | Vosk |
| Расшифровка | faster-whisper |
| Синтез речи | Piper TTS |
| Streaming TTS | `speak_stream()` + tee |
| Barge-in | Автокалибровка + per-call token |
| LLM | Qwen / Gemma / Llama / Mistral через Ollama |
| GUI | Flet 1.0.3 + PALETTES (3 темы) |
| Мультипрофиль | `profiles/<user>/` + subscribe |
| Универсальный профиль | `set_profile` / `get_profile` через LLM |
| Реестр | `_fast_handlers()` |
| Отмена | `jarvis/history.py` |
| Пароль | SHA-256 |
| Микрофон | sounddevice + прогресс-бар |
| Трей | pystray (отключён) |
| Печать/окна | pyautogui + pygetwindow |
| Активация окон | win32gui + AttachThreadInput |
| Погода | open-meteo.com |
| Курс | cbr-xml-daily.ru |
| Логи | RotatingFileHandler |
| Буфер | pyperclip |
| Атомарная запись | filelock per-path + os.replace |
| Пути | `jarvis/paths.py` |
| Сборка | PyInstaller |
| Установщик | Inno Setup |
| CI | GitHub Actions |
| Сериализация | `cmd_lock` в Jarvis |

---

## Лицензия

MIT License. См. [LICENSE](LICENSE).

Этот проект — **форк** [jsays12/jarvis](https://github.com/jsays12/jarvis).
Оригинальный код — собственность автора `jsays12`.
Части кода использованы с указанием источника.