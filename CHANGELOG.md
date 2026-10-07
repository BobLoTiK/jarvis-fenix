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

### Добавлено (сессия 08.10.2026)

#### Поздравление с ДР (`jarvis/celebrations.py`)
- Триггеры: «я папа», «я Александр», «я Саша», «я отец», «я батя», «Александр».
- Двойная цепочка:
  1. TTS: «Поздравляю! С днём рождения!».
  2. Салют #1 (6 сек) + звук ×2.
  3. TTS: полное авторское поздравление.
  4. Салют #2 (10 сек, больше взрывов) + звук ×3.
- Анимация через **Stack + Container** (не Canvas — в Flet 1.0.3 API капризный).
- Звук — `jarvis/sounds/fireworks.wav` или fallback на Beep-и.
- Zero-width space `\u200b` для пустого Reply (чтобы `handle` не шёл в LLM).

#### Аудит Kimi — 23 бага

**Критичные:**
- **K1** — pack-команды с аргументами (`shutdown /s /t 10`, `cmd /k ipconfig`, `rundll32.exe ...`) — раньше шли в `os.startfile` → падали. Фикс: `actions._looks_like_cmd()` + `shlex.split` + subprocess.
- **K2** — `timers.py` / `tasks.py` писали в `BASE_DIR` (папка кода). Фикс: `paths.user_dir()`.
- **K3** — `memory.append` — не атомарный full-file rewrite. Фикс: `mkstemp` + `os.replace`.
- **K4** — `config_manager` дефолтный путь — `BASE_DIR/config.json`. Фикс: `paths.config_path()` + FileLock per-path.
- **K5** — `stt.py` — `HF_HOME` не сбрасывался (Piper качал в whisper-кэш). Фикс: try/finally + восстановление.
- **K6** — `config.DEFAULT_CONFIG["whisper_model"]` — сломанная `coriollon/...`. Фикс: `deepdml/faster-whisper-large-v3-turbo-ct2`.
- **K7** — `config.DEFAULT_CONFIG["gui_theme"]` — `"dark-blue"` (невалидная). Фикс: `"Системная"`.
- **K8** — `_profile_fast` regex — «я хочу спать» создавал профиль. Фикс: тире обязательно (`я\s*[-—]\s*`).
- **K9** — `main.say()` — падал при `listener=None`. Фикс: guard.
- **K10** — `gui._run_command` — гонка с голосовым потоком. Фикс: `cmd_lock` в Jarvis.
- **K11** — `gui._on_mic_test` — `page.update()` из чужого потока. Фикс: результат через очередь.
- **K12** — `recorder.stop()` — безусловный `unhook_all()`. Фикс: только если шла запись.
- **K13** — `launcher.py` — мёртвый код после `return`. Фикс: удалён.
- **K14** — `install.bat` — ссылки на несуществующие `.bat`. Фикс: `start_fenix.bat` / `start_fenix_debug.bat`.
- **K15** — `tray.py` — пути не через `paths.py`. Фикс: `paths.config_path()`, `paths.logs_dir()`.
- **K16** — `intents.py open_config/open_log` — пути не через `paths.py`. Фикс: то же.
- **K17** — `weather.py` — User-Agent `Phoenix/0.2.2`. Фикс: из `__version__`.
- **K18** — `set_llm_model.py` — путь и неатомарность. Фикс: `paths` + `config_manager`.
- **K19** — `start_fenix.bat` / `start_fenix_debug.bat` — хардкод `C:\jarvis`. Фикс: `cd /d "%~dp0"`.
- **K20** — `launcher.py` — Zip Slip при распаковке Vosk. Фикс: `is_relative_to`.
- **K21** — `launcher.py` — мьютекс `Global\` требует админа. Фикс: `Local\`.
- **K22** — `tts.py` — падал на невидимом тексте (`\u200b`). Фикс: пропуск невидимых символов.
- **K23** — `gui.launch_fireworks` — `TypeError` без `duration`. Фикс: принимает параметр.

### Исправлено (сессия 07.10.2026)

- **№99** — Vosk падал на `C:\Users\Максим\...` (`Failed to create a model`). Фикс: `jarvis/paths.py` — PROGRAM_DIR / USER_DIR.
- **№100** — `HF_HOME` глобально ломал Piper (symlinks в degraded mode). Фикс: временная установка.
- **№103** — `sys.stdout = None` под `pythonw`. Фикс: проверка.
- **№104** — `wait_end` бросал `RuntimeError`. Фикс: `is_alive()`.
- **№106** — Дублирование `normalize` / `strip_cjk` / `prepare_text`. Фикс: `jarvis/text_utils.py`.
- **№107** — `libvosk.dll` ACCESS_VIOLATION (`0xc0000015`). Фикс: убран `flush()` из `say()`.
- **№22** — падежи погоды.
- **№23** — LLM видит `name` / `default_city`.

### Добавлено (сессия 07.10.2026)

- **`LICENSE`** (MIT + attribution jsays12).
- **`scripts/make_icon.py`** — иконка.
- **`scripts/build_exe.py`** — `.exe`.
- **`installer.iss`** — установщик.
- **`create_shortcut.bat`** — ярлык.
- **README «Возможные проблемы»** — 10 пунктов.
- **Релиз `v1.0.0`** на GitHub.

---

## [0.3.0] — 2026-10-06 (вечерняя)

### Добавлено

- **`set_profile` / `get_profile`** — универсальные action'ы для LLM.
- **`open_profile`** — Notepad++ → VS Code → системный.
- **Реестр `_fast_handlers()`** в `intents.py`.
- **`launch_mode`** в config.
- **`_activate_window_hard`** в `actions.py`.
- **`Config.unsubscribe`**.
- **`_split_compound`** — многослойные команды.
- **`learning.build_context`** — факты + коррекции.
- **`history.push_macro`**.

### Исправлено

- **№67** — многослойные команды.
- **№68** — «ютуб и …».
- **№69** — «потише на 10».
- **№70** — мусорный ввод.
- **№71** — `scripts/__init__.py`.
- **№72** — `wait_end` → `bool`.
- **№73** — стрим-пузырь не зависает.
- **№74** — TTS не накладывается.
- **№76** — `profile.switch` — один `RLock`.
- **№80** — Groq в README — «🚧 в планах».
- **№84** — `launch_mode` + защита.
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
- **№9** — `weather._CACHE` — лок.
- **№11** — `Vosk.Reset()` — `flush()`.
- **№16** — `_debug_fast` — из `listener.recent_phrases`.
- **№17** — макрос — `push_macro()`.
- **№18** — мусорные профили.
- **№38** — `requirements-dev.txt`.

### Изменено

- `IntentHandler.handle()` → `cmd = normalize(cmd)`.
- `Jarvis.say()` → принимает `Reply`.
- `brain.chat_stream()` — без `[-40:]`.
- `main.py` → Jarvis в фоне, Flet в главном.
- `tts.py` → per-call stop-token.
- `gui.py` → `PALETTES`, `_detect_system_theme`, `_rebuild_ui_for_theme`, `_mic_level_loop`.
- `profile.py` → `_current_lock`, `_listeners`, `subscribe()`, `_on_profile_switch`.

---

## [0.2.2] — 2026-10-05

### Добавлено

- **Этап 0:** `config_manager`, `Config` в памяти, barge-in, CJK-фильтр, few-shot промпт.
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