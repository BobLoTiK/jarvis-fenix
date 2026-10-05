# Changelog

Все значимые изменения проекта. Формат основан на
[Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версии — по [Semantic Versioning](https://semver.org/lang/ru/).

## [Unreleased]

### Добавлено
- `jarvis/reply.py` — явный тип `Reply` (`text` | `stream`) для возврата из `IntentHandler.handle()`.
- Быстрые правила без LLM: голоса, паки, таймеры, задачи, простая погода/курс.
- `_open_fast()` — открытие приложений/сайтов/папок без LLM.
- `tests/test_weather.py` — тесты с моками `_http_get_json`, проверка кэша.
- `.github/workflows/test.yml` — CI на `windows-latest`.
- `requirements-ci.txt` — облегчённые зависимости для CI (без звука и GUI).
- `--llm`, `--network`, `--voice` в `test_intents.py`.
- UTF-8 fix в `check_syntax.py` и `test_intents.py` (`sys.stdout.reconfigure`).
- `PYTHONUTF8=1` в CI — страховка от cp1252-консоли.

### Изменено
- `IntentHandler.handle()` всегда возвращает `Reply` (а не `str | Generator`).
- `Jarvis.say()` принимает `Reply`, а не `str | Generator`.
- `_handle_pending_answer()` — не хватает «как дела» как город.
- `test_intents.py` — тесты 5-полевые: `(name, cmd, expected, requires_llm, requires_network)`.
- `.gitignore` — добавлены `*.lock`, `dist/`, `build/`, `*.spec`, `.coverage`, `htmlcov/`.

### Исправлено
- `open_site` («открой ютуб») без LLM — теперь обрабатывается `_open_fast`.
- `small_talk_how` («как дела») — больше не перехватывается `pending_question`.
- `UnicodeEncodeError` на CI (cp1252) — `reconfigure` + `PYTHONUTF8`.

## [0.2.2] — 2026-10-05

### Добавлено
- Этап 0 (рефакторинг) закрыт:
  - `config_manager.py` — единый FileLock, `mkstemp`, `os.replace`.
  - `Config` в памяти + подписки.
  - Калибровка + адаптивный barge-in.
  - `_prepare_text` + CJK-фильтр.
  - Few-shot промпт + temperature 0.7.
  - Первые тесты (pytest + `test_intents.py`).
- Этап 1: голосовые режимы, паки команд, запись макросов, память диалога, голоса Piper.
- Этап 2: streaming TTS, barge-in, логи по категориям, буфер обмена, погода и курс.

### Исправлено
- `actions.run_spec` — обработка `kind == "cmd"` (Discord).
- `actions.find_process` / `_find_window` — `matching.match_score`.
- `brain.py` — `close_app` в отдельный блок промпта.
- `intents._handle_single` — вызов `memory.handle_memory_command`.
- `tts.Speaker.stop()` — рабочий barge-in через sounddevice.
- `stt._enable_cuda_dlls` — флаг `_CUDA_DLLS_ADDED`.
- `intents._reload_packs` — без `config_copy`.
- `matching.match_score` — защита от ложных срабатываний на коротких словах.

## [0.2.1] и раньше

См. коммиты в репозитории до июня 2026 — от оригинала
[jsays12/jarvis](https://github.com/jsays12/jarvis).