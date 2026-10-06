# Changelog

Все значимые изменения проекта.
Формат: [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версии: [Semantic Versioning](https://semver.org/lang/ru/).

## [Unreleased] — 0.3.0

### Добавлено

- **Flet GUI** (`jarvis/gui.py`):
  - Окно 1100×760, тёмная тема.
  - NavigationRail — разделы: Главная, Микрофон, Настройки.
  - **Статус-сфера** с анимацией (смена цвета и размера).
  - **Чат-пузыри** с аватарами (👤 / 🦅), тенями, fade-in.
  - Поле ввода + кнопки Send / Mic.
  - **Настройки:** модель LLM, Ollama URL, TTS бэкенд, скорость речи (слайдер), тема.
  - **Смена темы на лету** (Тёмная / Светлая / Системная) — `PALETTES` + `_rebuild_ui_for_theme`.
  - **Системная тема** — автоопределение через реестр Windows (`_detect_system_theme`).
  - **Подхват смены темы Windows** — раз в 2 сек в `_mic_level_loop`.
  - **Стриминг в GUI** через tee-генератор в `main._say_stream`.
  - **Кеш разделов** — история чата не теряется при переключении.
  - **Микрофон:** выбор устройства + сохранение в config.
  - **Вкладка «Микрофон»:**
    - Прогресс-бар уровня сигнала в реальном времени.
    - Кнопка «🎙 Проверить микрофон (3 сек)».
    - Статус: ✅ Работает / ⚠️ Тихий / ⏸ Ожидание.
    - Автооткрытие по сигналу `mic_watchdog`.

- **Системные команды:**
  - **Раскладка RU/EN:** `switch_layout`, `set_layout_ru`, `set_layout_en`, `get_layout`. Через `SendInput`.
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

- **Мультипрофиль:**
  - `profiles/<user>/profile.json` + `profiles/<user>/dialog.json`.
  - `profile.init()` — инициализация + миграция.
  - `profile.switch()`, `profile.delete()`, `profile.list_all()`.
  - `profile.subscribe()` — уведомление подписчиков при смене профиля.
  - Голосовые: «я — Маша», «кто активен», «список профилей», «запомни: …».

- **Память:** `memory.append(limit)`, `memory.load(limit)`, `memory.clear()`.
- **Лимиты в config:** `memory_max`, `llm_context_messages`, `danger_password`, `gui_enabled`, `gui_theme`, `gui_x`, `gui_y`, `tray_enabled`, `mic_watchdog_enabled`.
- **CI:** `.github/workflows/test.yml` на `windows-latest`.

- **`mic_watchdog`:**
  - Одно предупреждение за сессию (не спамит).
  - Порог пика ≥ 50 (микрофон живой).
  - Автооткрытие вкладки «Микрофон» в GUI.
  - Опция `mic_watchdog_enabled` в config.

### Изменено

- `IntentHandler.handle()` → **`cmd = normalize(cmd)`** в начале (единая точка нормализации для GUI и голоса).
- `Jarvis.say()` → принимает `Reply`.
- `brain.chat_stream()` → без `[-40:]` (лимит у вызывающего).
- `_execute_steps` → сохранение `history` для отмены.
- `main.py` → **Jarvis в фоне**, **Flet в главном** (`gui.run_main()`).
- `requirements.txt` → `flet>=1.0.3`.
- **`tts.py`:** per-call stop-token вместо общего `_stop_flag`.
- **`gui.py`:** `PALETTES` (две темы), `_detect_system_theme()`, `_rebuild_ui_for_theme()`, `_mic_level_loop()`.
- **`profile.py`:** `_current_lock`, `_listeners`, `subscribe()`, `_on_profile_switch`.

### Исправлено

- **№1** — `profile._current` гонка. `threading.Lock`.
- **№2** — Маша видит диалог Максима. `profile.subscribe()` + `_on_profile_switch`.
- **№3** — `_awaiting_until` после `say()`. Перенесено **до** `say()`.
- **№6** — `CANCEL` не первым. В начало `_handle_single`.
- **№8** — `any([...])` в `_do_close`. Генератор + early exit.
- **№14** — `brain.parse` без `.strip()`. `.strip().lower()`.
- **№20** — TTS накладывается (2–3 голоса). Per-call stop-token.
- **№21** — `_profile_fast` не матчит из GUI. `normalize(cmd)` в `handle()`.
- **№24** — Светлая тема ломала GUI. `PALETTES` + пересборка.
- **№24.5** — Системная тема не автоопределялась. `_detect_system_theme()`.
- **№25** — `mic_watchdog` спамил. Одно предупреждение за сессию.
- **№25.5** — Микрофон не проверить из GUI. Вкладка + прогресс-бар + кнопка.
- **Flet 1.x API** — `ft.ElevatedButton` → `ft.Button`.
- **Раскладка:** `SendInput` вместо `keybd_event` — работает второй раз.
- **Стриминг в GUI:** tee-генератор — чанки и в TTS, и в GUI.
- **История чата** не теряется при переключении разделов (кеш `_tabs`).
- **`signal only works in main thread`** — Flet в главном потоке.
- `open_site` без LLM через `_open_fast`.
- `small_talk_how` — не перехватывается `pending_question`.
- `UnicodeEncodeError` на CI — `reconfigure` + `PYTHONUTF8`.
- **`удали профиль`** обрабатывается **до** `tasks.handle_task_command`.

### Обновления технологий

- ✅ **О1** — `vosk 0.3.45`, `faster-whisper 1.2.1`, `ctranslate2 4.8.2`, `piper-tts 1.8.0`.
- ❌ О2–О7 — в плане (Whisper-модель, `check_cpu`, `tts_voice_quality`, `_init_piper`, GUI RadioGroup, README).

### В планах

- **Ф1–Ф13** — облачные провайдеры (Groq, Edge TTS).
- **З1–З7** — знакомство (persona).
- **С1–С3** — стресс-тест (20 фраз).
- **М1–М9** — мои команды голосом.
- **Ф14–Ф19** — платные провайдеры (OpenAI, Fish Audio).
- **№5, №7, №9–№13, №15–№19, №22, №23** — открытые баги.

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
