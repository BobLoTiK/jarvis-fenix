# Changelog

Все значимые изменения проекта.
Формат: [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версии: [Semantic Versioning](https://semver.org/lang/ru/).

## [Unreleased]

### Добавлено

- **Flet GUI** (`jarvis/gui.py`):
  - Окно 1100×760, тёмная тема.
  - NavigationRail — разделы: Главная, Микрофон, Настройки.
  - **Статус-сфера** с анимацией (смена цвета и размера).
  - **Чат-пузыри** с аватарами (👤 / 🦅), тенями, fade-in.
  - Поле ввода + кнопки Send / Mic.
  - **Настройки:** модель LLM, Ollama URL, TTS бэкенд, скорость речи (слайдер), тема.
  - **Смена темы на лету** (`Dark` / `Light` / `System`).
  - **Стриминг в GUI** через tee-генератор в `main._say_stream`.
  - **Кеш разделов** — история чата не теряется при переключении.
  - **Микрофон:** выбор устройства + сохранение в config.

- **Системные команды:**
  - **Раскладка RU/EN:** `switch_layout`, `set_layout_ru`, `set_layout_en`, `get_layout`. Через `SendInput` (надёжно).
  - **Громкость в %:** `get_volume` / `set_volume` через `pycaw`.
  - **Яркость в %:** `get_brightness` / `set_brightness` через `screen-brightness-control`.

- **Диагностика:**
  - «Что ты слышал?» — ring buffer последних 10 фраз в `stt.Listener`.
  - «Почему не понял?» — `_last_debug` в `IntentHandler`.

- **Отмена действий (Н1):**
  - `jarvis/history.py` — стек последних 5 действий.
  - «Стоп, не то» / «отмени» — откат.
  - Отмена: `open_app` → `close_app`, `set_mode`, `change_voice`, `set_volume`, `set_brightness`, `switch_layout`.

- **Пароль на опасные (2.13):**
  - `danger_password` в config.
  - «Выключи компьютер» → запрос пароля.
  - Опасные действия: `shutdown`, `reboot`, `kill_process`, `clear_tasks`, `cancel_timers`, `delete_profile`.

- **Мультипрофиль:**
  - `profiles/<user>/profile.json` + `profiles/<user>/dialog.json`.
  - `profile.init()` — инициализация + миграция.
  - `profile.switch()`, `profile.delete()`, `profile.list_all()`.
  - Голосовые: «я — Маша», «кто активен», «список профилей», «запомни: …».

- **Память:** `memory.append(limit)`, `memory.load(limit)`, `memory.clear()`.
- **Лимиты в config:** `memory_max`, `llm_context_messages`, `danger_password`, `gui_enabled`, `gui_theme`, `gui_x`, `gui_y`, `tray_enabled`.
- **CI:** `.github/workflows/test.yml` на `windows-latest`.

### Изменено

- `IntentHandler.handle()` → всегда `Reply`.
- `Jarvis.say()` → принимает `Reply`.
- `brain.chat_stream()` → без `[-40:]` (лимит у вызывающего).
- `_execute_steps` → сохранение `history` для отмены.
- `main.py` → **Jarvis в фоне**, **Flet в главном** (`gui.run_main()`).
- `requirements.txt` → `flet>=1.0.3`, `customtkinter>=5.2`.

### Исправлено

- **Раскладка:** `SendInput` вместо `keybd_event` — работает второй раз.
- **Стриминг в GUI:** tee-генератор — чанки и в TTS, и в GUI.
- **История чата** не теряется при переключении разделов (кеш `_tabs`).
- **`signal only works in main thread`** — Flet в главном потоке.
- `open_site` без LLM через `_open_fast`.
- `small_talk_how` — не перехватывается `pending_question`.
- `UnicodeEncodeError` на CI — `reconfigure` + `PYTHONUTF8`.
- **`удали профиль`** обрабатывается **до** `tasks.handle_task_command`.

---

## [0.2.2] — 2026-10-05

### Добавлено
- Этап 0 (рефакторинг): `config_manager`, `Config` в памяти, barge-in, CJK-фильтр, few-shot промпт.
- Этап 1: голосовые режимы, паки, макросы, память, голоса Piper.
- Этап 2: streaming TTS, barge-in, логи, буфер обмена, погода и курс.
- `test_intents.py` + `pytest tests/`.

### Исправлено
- `actions.run_spec` — `kind == "cmd"`.
- `matching.match_score` — короткие слова.
- `tts.Speaker.stop()` — barge-in через sounddevice.
- `stt._enable_cuda_dlls` — флаг.
- `brain.py` — `close_app` в отдельный блок.

## [0.2.1] и раньше

См. коммиты в репозитории до июня 2026 — от оригинала
[jsays12/jarvis](https://github.com/jsays12/jarvis).