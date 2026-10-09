# Changelog

Все значимые изменения проекта.

Формат: [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/).
Версии: [Semantic Versioning](https://semver.org/lang/ru/).

> **Attribution:** этот проект — форк
> [jsays12/jarvis](https://github.com/jsays12/jarvis).
> Коммиты до июня 2026 — от оригинала.
> Оригинальный код — собственность автора `jsays12`.
> См. [LICENSE](LICENSE).

---

## 📑 Содержание

- [Unreleased — 0.4.0](#-unreleased--040)
  - [Сессия 09.10.2026](#сессия-09102026)
  - [Сессия 08.10.2026](#сессия-08102026)
  - [Сессия 07.10.2026](#сессия-07102026)
- [0.3.0 — 2026-10-06](#-030--2026-10-06-вечерняя)
- [0.2.2 — 2026-10-05](#-022--2026-10-05)
- [0.2.1 и раньше](#-021-и-раньше)

---

## 🚧 [Unreleased] — 0.4.0

### 📅 Сессия 09.10.2026

#### ✨ Добавлено

##### 🎭 Персона — `jarvis/persona.py`

- Стили общения: `formal` / `friendly` / `sarcastic` / `brief`.
- Поля: `assistant_name`, `speech_style`, `traits`, `backstory`,
  `onboarding_done`, `onboarding_at`, `onboarding_step`.
- API: `get()`, `set_persona()`, `set_field()`, `normalize_style()`,
  `build_prompt_block()`, `describe()`, `mark_onboarded()`,
  `reset_onboarding()`, `is_onboarded()`.
- В `brain._system_with_context()`:
  `base + persona.build_prompt_block() + learning.build_context()`.
- Команды: «поменяй стиль на строгий», «какой у тебя стиль»,
  «как тебя зовут», «давай заново познакомимся».

##### 🎓 Онбординг через LLM-диалог

- `brain.ONBOARDING_CHAT_PROMPT` — промпт для ведения знакомства.
- `brain.onboarding_chat(user_text, history)` →
  `{reply, name, style, onboarding_done}`.
- `intents._onboarding_chat_step()` — обёртка. Пропускает команды
  (`_looks_like_command`).
- `intents._looks_like_command()` — эвристика «это команда или свободный текст».
- Принудительное завершение: если 6+ фраз от юзера — `mark_done()`.
- `first_run.py` — упрощён до `greeting()`, `is_first_run()`, `mark_done()`.

**❌ Удалено:**

- `_first_run_step`
- `_extract_name`
- `_looks_like_name`
- `_parse_onboarding_answer`
- `_apply_onboarding_parsed`
- `_extract_fact`
- `brain.parse_onboarding`

##### 👁 Observer — `jarvis/observer.py`

- `DialogObserver` — фоновое извлечение фактов из диалога.
- `observe("user"/"assistant", text)` — добавляет в буфер.
- Раз в 30 сек отправляет историю (6 сообщений) в LLM.
- LLM возвращает JSON: `{name, city, age, style, facts}`.
- `_apply()` сохраняет в `profile` / `learning`, если поле пустое.
- **Не блокирует** диалог. Работает параллельно.
- Конфиг: `observer_enabled: true`.

##### 🎨 Красивый установщик — Inno UI

- `scripts/make_installer_images.py` — генерация BMP из `jarvis/icon.ico`.
- `installer_banner.bmp` (164×314) — вертикальный баннер.
- `installer_small.bmp` (55×55) — маленькая иконка вверху справа.

**`installer.iss`:**

| Директива | Значение |
|---|---|
| `WizardStyle` | `modern` — современный вид |
| `WizardImageFile` | `installer_banner.bmp` |
| `WizardSmallImageFile` | `installer_small.bmp` |
| `WizardImageStretch` | `yes` |
| `WizardImageBackColor` | `$00160E0A` |
| `PrivilegesRequired` | `lowest` (было `admin` — не нужен) |
| `ArchitecturesInstallIn64BitMode` | `x64compatible` (было `x64` — deprecated) |
| `Excludes` | `__pycache__,*.pyc` — мусор не тащится |

> ⚠️ **`DarkMode=1`** — **не поддерживается** в Inno Setup 6.7.3.

##### 🛡 Защита от BOM и кракозябр

- **Ошибка №39** — BOM в `intents.py` (`invalid non-printable character U+FEFF`).
  **Фикс:** UTF-8 без BOM.
- **Ошибка №40** — `CHAT_SYSTEM` с `??` от cp1251.
  **Фикс:** правки только в VS Code.
- **Правило:** `files.encoding: utf8`, `files.autoGuessEncoding: false`.

#### 🔧 Исправлено

| № | Что было | Фикс |
|---|---|---|
| №36 | `_small_talk` перехватывал «привет», «как дела» | Убраны из `_small_talk` — LLM отвечает живо |
| №38 | `_small_talk` тест FAIL без LLM (`small_talk_who`) | Вернул «кто ты» в `_small_talk` |
| №41 | `test_intents.py small_talk_who` FAIL в CI | Ответ на «кто ты» без LLM |

---

### 📅 Сессия 08.10.2026

#### ✨ Добавлено

##### 🎉 Поздравление с ДР — `jarvis/celebrations.py`

- **Триггеры:** «я папа», «я Александр», «я Саша», «я отец», «я батя», «Александр».
- **Двойная цепочка:**
  1. TTS: «Поздравляю! С днём рождения!».
  2. Салют #1 (6 сек) + звук ×2.
  3. TTS: полное авторское поздравление.
  4. Салют #2 (10 сек, больше взрывов) + звук ×3.
- Анимация через **Stack + Container** (не Canvas — в Flet 1.0.3 API капризный).
- Звук — `jarvis/sounds/fireworks.wav` или fallback на Beep-и.
- Zero-width space `\u200b` для пустого Reply
  (чтобы `handle` не шёл в LLM).

##### 🔍 Аудит Kimi — 25 багов

**🔴 Критичные:**

| ID | Проблема | Фикс |
|---|---|---|
| **K1** | Pack-команды с аргументами (`shutdown /s /t 10`, `cmd /k ipconfig`, `rundll32.exe ...`) шли в `os.startfile` → падали | `actions._looks_like_cmd()` + `shlex.split` + subprocess |
| **K2** | `timers.py` / `tasks.py` писали в `BASE_DIR` (папка кода) | `paths.user_dir()` |
| **K3** | `memory.append` — не атомарный full-file rewrite | `mkstemp` + `os.replace` |
| **K4** | `config_manager` дефолтный путь — `BASE_DIR/config.json` | `paths.config_path()` + FileLock per-path |
| **K5** | `stt.py` — `HF_HOME` не сбрасывался (Piper качал в whisper-кэш) | try/finally + восстановление |
| **K6** | `config.DEFAULT_CONFIG["whisper_model"]` — сломанная `coriollon/...` | `deepdml/faster-whisper-large-v3-turbo-ct2` |
| **K7** | `config.DEFAULT_CONFIG["gui_theme"]` — `"dark-blue"` (невалидная) | `"Системная"` |
| **K8** | `_profile_fast` regex — «я хочу спать» создавал профиль | Тире обязательно (`я\s*[-—]\s*`) |
| **K9** | `main.say()` — падал при `listener=None` | Guard |
| **K10** | `gui._run_command` — гонка с голосовым потоком | `cmd_lock` в Jarvis |
| **K11** | `gui._on_mic_test` — `page.update()` из чужого потока | Результат через очередь |
| **K12** | `recorder.stop()` — безусловный `unhook_all()` | Только если шла запись |
| **K13** | `launcher.py` — мёртвый код после `return` | Удалён |
| **K14** | `install.bat` — ссылки на несуществующие `.bat` | `start_fenix.bat` / `start_fenix_debug.bat` |
| **K15** | `tray.py` — пути не через `paths.py` | `paths.config_path()`, `paths.logs_dir()` |
| **K16** | `intents.py open_config/open_log` — пути не через `paths.py` | То же |
| **K17** | `weather.py` — User-Agent `Phoenix/0.2.2` | Из `__version__` |
| **K18** | `set_llm_model.py` — путь и неатомарность | `paths` + `config_manager` |
| **K19** | `start_fenix.bat` / `start_fenix_debug.bat` — хардкод `C:\jarvis` | `cd /d "%~dp0"` |
| **K20** | `launcher.py` — Zip Slip при распаковке Vosk | `is_relative_to` |
| **K21** | `launcher.py` — мьютекс `Global\` требует админа | `Local\` |
| **K22** | `tts.py` — падал на невидимом тексте (`\u200b`) | Пропуск невидимых символов |
| **K23** | `gui.launch_fireworks` — `TypeError` без `duration` | Принимает параметр |
| **K24** | `config_manager._get_lock` — tuple без context manager | `_get_locks` + `with t_lock, f_lock` |
| **K25** | `os.replace` — `PermissionError` от антивируса | `_atomic_replace` с retry |

---

### 📅 Сессия 07.10.2026

#### 🔧 Исправлено

| № | Проблема | Фикс |
|---|---|---|
| **№99** | Vosk падал на `C:\Users\Максим\...` (`Failed to create a model`) | `jarvis/paths.py` — PROGRAM_DIR / USER_DIR |
| **№100** | `HF_HOME` глобально ломал Piper (symlinks в degraded mode) | Временная установка |
| **№103** | `sys.stdout = None` под `pythonw` | Проверка |
| **№104** | `wait_end` бросал `RuntimeError` | `is_alive()` |
| **№106** | Дублирование `normalize` / `strip_cjk` / `prepare_text` | `jarvis/text_utils.py` |
| **№107** | `libvosk.dll` ACCESS_VIOLATION (`0xc0000015`) | Убран `flush()` из `say()` |
| **№22** | Падежи погоды | — |
| **№23** | LLM не видит `name` / `default_city` | — |

#### ✨ Добавлено

- **`LICENSE`** — MIT + attribution `jsays12`.
- **`scripts/make_icon.py`** — иконка.
- **`scripts/build_exe.py`** — `.exe`.
- **`installer.iss`** — установщик.
- **`create_shortcut.bat`** — ярлык.
- **README «Возможные проблемы»** — 10 пунктов.
- **Релиз `v1.0.0`** на GitHub.

---

## 🌙 [0.3.0] — 2026-10-06 (вечерняя)

### ✨ Добавлено

- **`set_profile` / `get_profile`** — универсальные action'ы для LLM.
- **`open_profile`** — Notepad++ → VS Code → системный.
- **Реестр `_fast_handlers()`** в `intents.py`.
- **`launch_mode`** в config.
- **`_activate_window_hard`** в `actions.py`.
- **`Config.unsubscribe`**.
- **`_split_compound`** — многослойные команды.
- **`learning.build_context`** — факты + коррекции.
- **`history.push_macro`**.

### 🔧 Исправлено

| № | Что |
|---|---|
| №67 | Многослойные команды |
| №68 | «ютуб и …» |
| №69 | «потише на 10» |
| №70 | Мусорный ввод |
| №71 | `scripts/__init__.py` |
| №72 | `wait_end` → `bool` |
| №73 | Стрим-пузырь не зависает |
| №74 | TTS не накладывается |
| №76 | `profile.switch` — один `RLock` |
| №80 | Groq в README — «🚧 в планах» |
| №84 | `launch_mode` + защита |
| №88 | `launcher.py` мьютекс |
| №89 | `close_browser` все браузеры |
| №90 | `pystray.SystemExit` |
| №91 | `profiles/` из git |
| №92 | `_tabs` не теряют историю |
| №93 | `chat_stream` чанк |
| №94 | `wake_score` |
| №95 | `Config.unsubscribe` |
| №96 | `SITES` из packs |
| №97 | `build_context` / `_profile_fast` |
| №98 | `check_syntax.bat` |
| №9 | `weather._CACHE` — лок |
| №11 | `Vosk.Reset()` — `flush()` |
| №16 | `_debug_fast` — из `listener.recent_phrases` |
| №17 | Макрос — `push_macro()` |
| №18 | Мусорные профили |
| №38 | `requirements-dev.txt` |

### 🔄 Изменено

- `IntentHandler.handle()` → `cmd = normalize(cmd)`.
- `Jarvis.say()` → принимает `Reply`.
- `brain.chat_stream()` — без `[-40:]`.
- `main.py` → Jarvis в фоне, Flet в главном.
- `tts.py` → per-call stop-token.
- `gui.py` → `PALETTES`, `_detect_system_theme`, `_rebuild_ui_for_theme`, `_mic_level_loop`.
- `profile.py` → `_current_lock`, `_listeners`, `subscribe()`, `_on_profile_switch`.

---

## 🌆 [0.2.2] — 2026-10-05

### ✨ Добавлено

- **Этап 0:** `config_manager`, `Config` в памяти, barge-in, CJK-фильтр, few-shot промпт.
- **Этап 1:** голосовые режимы, паки, макросы, память, голоса Piper.
- **Этап 2:** streaming TTS, barge-in, логи, буфер обмена, погода и курс.
- **`test_intents.py`** + **`pytest tests/`**.

### 🔧 Исправлено

- `actions.run_spec` — `kind == "cmd"`.
- `matching.match_score` — короткие слова.
- `tts.Speaker.stop()` — barge-in через `sounddevice`.
- `stt._enable_cuda_dlls` — флаг.
- `brain.py` — `close_app` в отдельный блок.

---

## 📦 [0.2.1] и раньше

См. коммиты в репозитории до июня 2026 — от оригинала
[jsays12/jarvis](https://github.com/jsays12/jarvis).
