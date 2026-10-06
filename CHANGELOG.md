# Changelog

Все значимые изменения проекта.
Формат: [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версии: [Semantic Versioning](https://semver.org/lang/ru/).

> **Attribution:** этот проект — форк
> [jsays12/jarvis](https://github.com/jsays12/jarvis).
> Коммиты до июня 2026 — от оригинала.
> Оригинальный код — собственность автора `jsays12`.
> См. [LICENSE](LICENSE).

---

## [Unreleased] — 0.4.0

### Добавлено (сессия 07.10.2026)

#### Unicode / пути (критично)

- **`jarvis/paths.py`** — новый модуль. Два корня:
  - `PROGRAM_DIR` → `C:\ProgramData\Phoenix\` (**ASCII**, для Vosk/Whisper).
  - `USER_DIR` → `%APPDATA%\Phoenix\` (личные данные, кириллица ок).
  - Fallback для `PROGRAM_DIR`: `ProgramData` → `C:\Phoenix` → `%TEMP%` → `<рядом с exe>\runtime`.
- **Vosk падал на `C:\Users\Максим\...`** (`Failed to create a model`) — теперь модель всегда в ASCII-пути.
- **`HF_HOME` для Whisper** ставится **временно** на импорт и **сбрасывается** до Piper — иначе Piper качал модели в наш ASCII-кэш в degraded mode (без symlinks).

#### Автолаунчер

- **`launcher.py`** — полный автозапуск:
  - Ищет Python 3.10–3.12 (py launcher, where python, типичные пути).
  - Если нет — `MessageBox` со ссылкой на скачивание `python-3.11.9-amd64.exe`.
  - Создаёт `.venv311`, если нет.
  - Проверяет зависимости (`flet`, `vosk`). Если нет — `pip install`.
  - Проверяет Vosk-модель в `C:\ProgramData\Phoenix\models`. Если нет — качает.
  - Проверяет Ollama (URL + поиск на дисках). Если нет — `MessageBox`.
  - Запускает `.venv311\Scripts\pythonw.exe -m jarvis`.
  - Мьютекс `Global\JarvisPhoenixSingleInstance`.
  - Логи — `logs/launcher.log`.

#### UI/UX

- **`scripts/make_icon.py`** — генерирует `jarvis/icon.ico` (16/24/32/48/64/128/256), синий круг с «J».
- **`scripts/build_exe.py`** — сборка `launcher.py` → `dist/Феникс.exe` (~9 МБ) + копия в корне проекта.
- **`installer.iss`** — Inno Setup → `Феникс_Setup.exe` (~11 МБ). Установка в `C:\ProgramData\Phoenix`.
- **`create_shortcut.bat`** — ярлык на рабочем столе.
- **Иконка окна** в GUI — `page.window.icon`.

#### Модули

- **`jarvis/text_utils.py`** — новый. `normalize()`, `strip_cjk()`, `strip_cjk_chunk()`, `prepare_text()`. Убрано дублирование из `brain.py`, `tts.py`, `intents.py`.

#### Настройки

- `DEFAULT_CONFIG` в `config.py`: модель Whisper — `deepdml/faster-whisper-large-v3-turbo-ct2` (правильная, рабочая).
- `DEFAULT_CONFIG["launch_mode"]: "gui"`.

### Исправлено (сессия 07.10.2026)

- **№99** — Vosk падал на не-ASCII путях. Фикс — `paths.py`.
- **№100** — `HF_HOME` глобально ломал Piper. Фикс — временная установка.
- **№103** — `sys.stdout = None` под `pythonw` ломал `_progress` в `model.py`. Фикс — `if sys.stdout is None: return`.
- **№104** — `wait_end` бросал `RuntimeError: cannot join thread before it is started`. Фикс — проверка `thread.is_alive()` перед `join`.
- **№106** — `normalize` / `strip_cjk` / `prepare_text` дублировались в 3 модулях. Фикс — `text_utils.py`.
- **№22** — падежи погоды.
- **№23** — LLM видит `name` / `default_city`.

### Изменено (сессия 07.10.2026)

- `jarvis/config.py` → `load_config()` возвращает Config с `paths.config_path()`.
- `jarvis/profile.py` → `PROFILES_DIR = paths.profiles_dir()`.
- `jarvis/main.py` → `LOGS_DIR = paths.logs_dir()`, `ensure_model(local_models)`.
- `jarvis/model.py` → всегда копирует/скачивает в `paths.program_models_dir()`.
- `jarvis/stt.py` → `WhisperTranscriber.__init__` ставит `HF_HOME` временно.
- `jarvis/gui.py` → `_mic_level_loop` проверяет тему Windows раз в 5 сек (было 2).
- `jarvis/gui.py` → `page.window.icon` — иконка окна.
- `installer.iss` → `DefaultDirName={commonappdata}\Phoenix`.

### Удалено

- `jarvis/tray_runner.py` — временно не нужен.

---

## [0.3.0] — 2026-10-06 (вечерняя)

### Добавлено

- **`set_profile` / `get_profile`** — универсальные action'ы для LLM. Теперь «меня зовут X», «поменяй город на Y», «как меня зовут», «какой город» — работают **через LLM**, без костылей-`re.match`.
- **`open_profile`** — «открой профиль» → Notepad++ → VS Code → системный. Активация окна через `win32gui` + `AttachThreadInput`.
- **Реестр `_fast_handlers()`** в `intents.py` — вместо 22 `if reply: return reply`. Порядок = приоритет.
- **`launch_mode`** в config — `"gui"` или `"tray"`.
- **`_activate_window_hard`** в `actions.py`.
- **`Config.unsubscribe`** — удаление подписки.
- **`_split_compound`** — многослойные команды («открой стим и запусти доту»).
- **`learning.build_context`** — факты + коррекции в промпт.
- **`history.push_macro`** — макрос как одна запись в стеке отмены.

### Исправлено

- **№67** — «открой стим и запусти доту» — обе части.
- **№68** — «открой ютуб и сделай громче» — не мусорный URL.
- **№69** — «сделай на 10 потише».
- **№70** — «аааааааа» → «Не расслышал».
- **№71** — `scripts/__init__.py`.
- **№72** — `wait_end` → `bool`.
- **№73** — стрим-пузырь не зависает (`try/finally` в `_say_stream`).
- **№74** — TTS не накладывается.
- **№76** — `profile.switch` — один `RLock`.
- **№80** — Groq в README помечен «🚧 в планах».
- **№84** — `launch_mode` + защита от конфликта `tray_enabled`.
- **№88** — `launcher.py` мьютекс держит HANDLE.
- **№89** — `close_browser` убивает все браузеры.
- **№90** — `pystray.SystemExit` ловится.
- **№91** — `profiles/` убран из git.
- **№92** — `_tabs` не теряют историю чата при смене профиля.
- **№93** — `chat_stream` не теряет последний чанк.
- **№94** — `wake_score` — 4 явных сравнения.
- **№95** — `Config.unsubscribe`.
- **№96** — `SITES` из `packs/sites.json`.
- **№97** — `build_context` / `_profile_fast` без дублей.
- **№98** — `check_syntax.bat` — `%~dp0`.
- **№9** — `weather._CACHE` — лок уже был.
- **№11** — `Vosk.Reset()` — `flush()` прогоняет тишину.
- **№16** — `_debug_fast` — берёт из `listener.recent_phrases`.
- **№17** — макрос — `push_macro()`.
- **№18** — мусорные профили удалены.
- **№38** — `requirements-dev.txt` создан.

### Изменено

- `IntentHandler.handle()` → `cmd = normalize(cmd)` в начале.
- `Jarvis.say()` → принимает `Reply`.
- `brain.chat_stream()` → без `[-40:]`.
- `_execute_steps` → сохранение `history` для отмены.
- `main.py` → Jarvis в фоне, Flet в главном.
- `requirements.txt` → `flet>=1.0.3`.
- `tts.py` → per-call stop-token.
- `gui.py` → `PALETTES`, `_detect_system_theme`, `_rebuild_ui_for_theme`, `_mic_level_loop`.
- `profile.py` → `_current_lock`, `_listeners`, `subscribe()`, `_on_profile_switch`.

---

## [0.2.2] — 2026-10-05

### Добавлено

- **Этап 0 (рефакторинг):** `config_manager`, `Config` в памяти, barge-in, CJK-фильтр, few-shot промпт.
- **Этап 1:** голосовые режимы, паки, макросы, память, голоса Piper.
- **Этап 2:** streaming TTS, barge-in, логи, буфер обмена, погода и курс.
- **`test_intents.py`** + **`pytest tests/`**.

### Исправлено

- `actions.run_spec` — `kind == "cmd"`.
- `matching.match_score` — короткие слова.
- `tts.Speaker.stop()` — barge-in через sounddevice.
- `stt._enable_cuda_dlls` — флаг.
- `brain.py` — `close_app` в отдельный блок.

---

## [0.2.1] и раньше

См. коммиты в репозитории до июня 2026 — от оригинала
[jsays12/jarvis](https://github.com/jsays12/jarvis).