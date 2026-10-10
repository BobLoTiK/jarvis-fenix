# PROJECT.md — единственный источник правды о «Феникс»

> **Курируемый файл. Не генерируется.** Пишется руками, правится при смене поведения.
>
> **Зачем:** `README.md`, `ARCHITECTURE.md`, `PROMPT.md`, `CONTRIBUTING.md` и `PLAN.md`
> дублируют друг друга (карта модулей есть в четырёх, список правил — в трёх),
> причём местами расходятся. `snapshot.py` печатает **этот** файл вместо тех пяти.
> Если факт ниже устарел — правь **здесь**, а не в пяти местах.
>
> Снапшот = этот файл + карта + смысл из кода + весь код. Этого хватает,
> чтобы вникнуть в проект без интернета и без доп. контекста.

---

## 1. Что это

Локальный голосовой ассистент для Windows. Форк [jsays12/jarvis](https://github.com/jsays12/jarvis),
MIT + attribution (не удалять).

Цепочка: **микрофон → Vosk (wake) → Whisper (уточнение) → разбор команды → TTS-ответ.**
Офлайн всё, кроме погоды и курса валют (с кэшем). LLM (Ollama) опциональна —
без неё ассистент работает на правилах.

---

## 2. Стек (фактические версии из `.venv311`)

| Слой | Решение |
|---|---|
| Python | **3.11.9**, только `.venv311` |
| Wake-слово | Vosk `vosk-model-small-ru-0.22` (~45 МБ) |
| Уточнение | faster-whisper `large-v3-turbo-ct2` (CUDA, иначе CPU+`small`) |
| Синтез | Piper `medium` → XTTS / WinRT / SAPI (fallback) |
| Мозг | Ollama `qwen2.5` (в наличии 1.5b / 7b / 14b) |
| GUI | Flet 1.0.x, **главный поток** |
| Окна | `uiautomation` (20+ браузеров по PID) |
| Сборка | PyInstaller → `Феникс.exe`; Inno Setup → установщик |

**Python 3.13/3.14 не использовать** — `libvosk.dll` падает с access violation.

---

## 3. Инвариант №1 — два корня путей

```
PROGRAM_DIR  C:\ProgramData\Phoenix    ASCII. Модели Vosk, кэш Whisper.
USER_DIR     %APPDATA%\Phoenix         config, profiles, logs, timers, tasks.
```

**Почему:** Vosk — C++ на Kaldi, ломается на путях с кириллицей
(`Failed to create a model`). Личные данные в ASCII-корне не нужны.

- Все пути — через `jarvis/paths.py`. Больше **нигде**.
- `Path.home()` в коде запрещён: есть `paths.user_home()`.
- `HF_HOME` для Whisper ставится **временно**, сбрасывается в `finally`
  (иначе Piper уходит в degraded mode без symlink'ов).

---

## 4. Правила, которые нельзя нарушать

**Конфиг**

1. Не читать и не писать `config.json` напрямую — только `config.get()` / `Config.set()`
   / `config_manager.save()`. `Config` живёт в памяти, подписки рассылают изменения.
2. Глобальное состояние — только `Config._GLOBAL`. Новых модульных синглтонов не заводить
   (`profile._cache` — последнее исключение, и оно под локом).

**Запись на диск**

3. Всюду атомарно: `tempfile.mkstemp` + `os.replace`, плюс `FileLock` per-path.
   Две параллельные записи (голос + GUI) рвут JSON.
4. `os.replace` на Windows ловит `PermissionError` от антивируса — нужен retry.

**Потоки**

5. Flet — **только главный поток**. Связь GUI ↔ Jarvis через `queue.Queue()`.
6. `cmd_lock` в `Jarvis` сериализует `handle()`; `_say_lock` — `say()`.
   Таймеры, `mic_watchdog` и `celebrations` зовут `say()` из своих потоков —
   **без `_say_lock` они режут текущую речь** через `speaker.stop()`.
7. Vosk API — **только из listener-потока**. `flush()` не должен трогать Vosk
   (иначе `libvosk.dll` → `0xc0000015`).
8. TTS — per-call stop-token, а не общий флаг: иначе 2-3 голоса накладываются.
9. UIA требует STA. Вызовы идут из голосового и GUI-потока — держать под `_lock`.

**Безопасность**

10. Распаковка архивов — проверка `is_relative_to` (Zip Slip).
11. Мьютекс `Local\`, не `Global\` — иначе нужны права админа.
12. Пароль — sha256 с префиксом, сравнение через `hmac.compare_digest`.
13. Личное (имя, город, CPU, GPU, ОС) — только в `config.json`, `profiles/`,
    `system_caps.json`, и все три в `.gitignore`.

**Прочее**

14. Pack-команды с аргументами (`shutdown /s /t 10`) — через `_looks_like_cmd`
    + `shlex`, а не `os.startfile`.
15. Нормализация (`normalize`) — **одна** точка, в `IntentHandler.handle()`.
    Она вырезает пунктуацию: для доменов берите **сырой** `intent["target"]`.
16. Attribution `jsays12` не удалять.
---

## 5. Архитектура в одном экране

```
Jarvis (main.py) — cmd_lock, _say_lock, barge-in, стриминг
  └─ IntentHandler.handle(cmd)          ← normalize() единожды
       └─ mood.apply_from_text(cmd)
       └─ Pipeline, 11 стадий, порядок = приоритет:
            cancel → onboarding → correction → password → memory
            → pending → clipboard → modes → compound → fast → llm
       └─ Reply(text | stream)
            └─ Jarvis.say() ← _say_lock → tts.Speaker
```

**Реестр `fast/`** (порядок = приоритет, специфичное выше общего):
`custom → small_talk → music → screenshot → uia → open_profile → open →
voices → packs → timers → tasks → persona → profile → memory → system →
debug → correction → undo → weather_currency`

Исключение внутри обработчика логируется, но **не роняет** команду.

**Модули ядра:** `brain.py` (LLM), `stt.py` (Vosk+Whisper), `tts.py` (Piper),
`gui.py` (Flet), `profile.py` (профили+кэш), `persona.py` (стиль),
`mood.py` (настроение), `observer.py` (факты фоном), `uia.py` (окна),
`history.py` (отмена), `learning.py` (факты+коррекции).

**Профиль читается через кэш в памяти** (`profile._cache`, инвалидация в
`set`/`forget`/`switch`/`delete`). Раньше каждый `get()` лез на диск —
`mood.effective_rate()` дёргается на **каждом** синтезируемом предложении.

---

## 6. Известные баги (аудит 10.10.2026)

Закрыты в этой же сессии: арность `finalize_stream` в тестах, дыра в харнесе
(`expected=[]` маскировал исключения), отсутствующий `_on_profile_switch` в GUI,
потеря вкладки «Персона» при смене темы, хардкод `C:\jarvis` в `packs/work.json`,
`normalize()` ломавший домены (`gismeteoru.ru`), `say()` без лока, `Path.home()`,
`num2words`, мусор в `EXCLUDE_FILES`, дрейф `config.example.json`.

**Осталось (требует живого приложения или отдельной задачи):**

| Что | Где | Почему не сделано |
|---|---|---|
| Мёртвые `debug_*` в LLM-промптах | `brain.py` SYSTEM_* | правка промптов меняет поведение LLM, нужен прогон |
| `uia` без STA-инициализации | `uia.py` | проверить можно только с реальным окном |
| `scan_start_menu()` + `scan_steam_games()` синхронно на старте | `intents/handler.py` | возможны 1-3 с блокировки, надо мерить |
| Трей (`tray_runner.py`) | `tray.py` отключён | pystray требует свой message loop, главный занят Flet |
| GUI: 4 вкладки после смены темы | `gui.py` | **проверить руками** |

---

## 7. Ошибки, которые уже делались (не повторять)

1. `&&` в PowerShell 5.1 **не работает** — только `;`.
2. Правки в терминале портят UTF-8 и BOM. **Только в VS Code.**
   `files.encoding: utf8`, `files.autoGuessEncoding: false`.
3. `ft.ElevatedButton` / `ft.TextButton` удалены в Flet 1.x → `ft.Button`.
4. `FindAll` не существует у `WindowControl` → `EditControl(searchFromControl=...)`,
   `ToolBarControl(searchFromControl=..., Name="Вкладки")`.
5. `uia.ControlTypeName` — не то; сравнивать со строками `"TabItemControl"`.
6. `prevent_close` + `on_event` в Flet 1.0.3 не работает.
7. `sys.stdout is None` под `pythonw.exe` — проверять.
8. `thread.join()` на нестартованном потоке → `RuntimeError`. Проверять `is_alive()`.
9. `wait_end` должна возвращать bool, иначе TTS накладывается.
10. `chat_stream` терял последний чанк — `append` **до** проверки токена.
11. `_small_talk` перехватывал «привет» / «как дела» — отдано LLM.
12. Голое `я ` в regex профиля ловило «я хочу спать». Тире обязательно.
13. `_do_open_folder` передавал `explicit=True`, и «открой музыку» открывала
    папку Music вместо плеера.
14. `snapshot.py` без проверки длины fence ломал markdown: файл, внутри которого
    есть ```` ``` ````, нельзя заворачивать в ```` ```markdown ````.
15. `timers.py` / `tasks.py` писали в папку кода вместо `USER_DIR`.
16. Коммитить `.venv311`, `config.json`, `profiles/`, `system_caps.json`,
    `timers.json`, `tasks.json`, `models/`, `voices/`, `dist/`, `build/`.

---

## 8. Контракт проверки

```bat
python check_syntax.py            :: синтаксис всех .py, включая tests/
python -m pytest tests\ -q        :: 69 тестов
python test_intents.py            :: 32 сценария, без LLM и сети
python test_intents.py --llm --network   :: + LLM (3-8 мин) и погода/курс
```

Все три зелёные → CI пройдёт. Логи: `%APPDATA%\Phoenix\logs\`
(`jarvis.log`, `actions.log`, `errors.log`, `launcher.log`).

**Тесты и CI — святое.** Красный CI = стоп всему. Не тестировать: GUI (нужно окно),
звук (нет карты на CI), сеть без флага `--network`.

---

## 9. Что дальше

По `PLAN.md`: Silero TTS (+6 голосов) → VAD без wake-слова → Prosody →
Vector memory (ChromaDB + RAG) → спрайт-аватар → PyInstaller в один `.exe`.

---

_Последняя правка: 10.10.2026, после аудита на ошибки, гонки и хардкод._

