# SNAPSHOT проекта «Феникс»

`sha256=ebf358e072c793c3` · режим `lean` · файлов `128` · строк `21734` · источник `856 КБ`

> Генерируется `snapshot.py`. Вывод детерминированный: содержимое меняется только когда меняются файлы.
>
> **Начинай с раздела 0 — PROJECT.md.** Там инварианты, правила и история ошибок. Дальше карта, смысл из кода, потом сам код.

---

## 0. PROJECT.md — что это, как устроено, чего нельзя делать

`````
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
`````

---

## 1. Карта проекта

```
jarvis/
├── .github/
│   ├── workflows/
│   │   ├── README.md  (37 стр)
│   │   ├── test.yml  (58 стр)
├── ARCHITECTURE.md  (885 стр)
├── CHANGELOG.md  (422 стр)
├── check_all.bat  (88 стр)
├── check_syntax.bat  (7 стр)
├── check_syntax.py  (60 стр)
├── CI.md  (129 стр)
├── cmds/
│   ├── open_terminal.bat  (3 стр)
│   ├── show_ip.bat  (3 стр)
├── config.example.json  (62 стр)
├── CONTRIBUTING.md  (341 стр)
├── create_shortcut.bat  (51 стр)
├── install.bat  (410 стр)
├── installer.iss  (84 стр)
├── jarvis/
│   ├── __init__.py  (8 стр)
│   ├── __main__.py  (4 стр)
│   ├── actions.py  (1155 стр)
│   ├── apps.py  (114 стр)
│   ├── brain.py  (795 стр)
│   ├── celebrations.py  (165 стр)
│   ├── config.py  (224 стр)
│   ├── config_manager.py  (156 стр)
│   ├── files.py  (102 стр)
│   ├── first_run.py  (26 стр)
│   ├── gui.py  (1580 стр)
│   ├── history.py  (75 стр)
│   ├── installed.py  (51 стр)
│   ├── intents/
│   │   ├── __init__.py  (10 стр)
│   │   ├── context.py  (19 стр)
│   │   ├── execute.py  (867 стр)
│   │   ├── fast/
│   │   │   ├── __init__.py  (54 стр)
│   │   │   ├── correction.py  (28 стр)
│   │   │   ├── custom.py  (72 стр)
│   │   │   ├── debug.py  (38 стр)
│   │   │   ├── memory.py  (41 стр)
│   │   │   ├── music.py  (38 стр)
│   │   │   ├── open.py  (61 стр)
│   │   │   ├── packs.py  (27 стр)
│   │   │   ├── persona.py  (55 стр)
│   │   │   ├── profile.py  (148 стр)
│   │   │   ├── screenshot.py  (26 стр)
│   │   │   ├── small_talk.py  (67 стр)
│   │   │   ├── system.py  (130 стр)
│   │   │   ├── tasks.py  (7 стр)
│   │   │   ├── timers.py  (7 стр)
│   │   │   ├── uia.py  (100 стр)
│   │   │   ├── undo.py  (67 стр)
│   │   │   ├── voices.py  (10 стр)
│   │   │   ├── weather.py  (68 стр)
│   │   ├── handler.py  (197 стр)
│   │   ├── password.py  (86 стр)
│   │   ├── sites.py  (62 стр)
│   │   ├── stages/
│   │   │   ├── __init__.py  (44 стр)
│   │   │   ├── base.py  (19 стр)
│   │   │   ├── cancel.py  (17 стр)
│   │   │   ├── clipboard.py  (68 стр)
│   │   │   ├── compound.py  (53 стр)
│   │   │   ├── correction.py  (24 стр)
│   │   │   ├── fast.py  (29 стр)
│   │   │   ├── llm.py  (93 стр)
│   │   │   ├── memory.py  (21 стр)
│   │   │   ├── modes.py  (30 стр)
│   │   │   ├── onboarding.py  (73 стр)
│   │   │   ├── password.py  (94 стр)
│   │   │   ├── pending.py  (62 стр)
│   │   ├── verbs.py  (45 стр)
│   ├── learning.py  (160 стр)
│   ├── main.py  (602 стр)
│   ├── matching.py  (113 стр)
│   ├── memory.py  (137 стр)
│   ├── model.py  (102 стр)
│   ├── modes.py  (51 стр)
│   ├── mood.py  (335 стр)
│   ├── observer.py  (198 стр)
│   ├── packs.py  (117 стр)
│   ├── paths.py  (182 стр)
│   ├── persona.py  (132 стр)
│   ├── profile.py  (451 стр)
│   ├── recorder.py  (171 стр)
│   ├── reply.py  (25 стр)
│   ├── steam.py  (67 стр)
│   ├── stt.py  (306 стр)
│   ├── tasks.py  (236 стр)
│   ├── text_utils.py  (132 стр)
│   ├── timers.py  (340 стр)
│   ├── tray.py  (96 стр)
│   ├── tts.py  (466 стр)
│   ├── uia.py  (617 стр)
│   ├── voices.py  (69 стр)
│   ├── weather.py  (305 стр)
├── jarvis-fenix.code-workspace  (8 стр)
├── launcher.py  (693 стр)
├── LICENSE  (25 стр)
├── packs/
│   ├── apps.json  (21 стр)
│   ├── games.json  (22 стр)
│   ├── sites.json  (22 стр)
│   ├── system.json  (17 стр)
│   ├── work.json  (11 стр)
├── PLAN.md  (963 стр)
├── PROJECT.md  (205 стр)
├── PROMPT.md  (488 стр)
├── README.md  (845 стр)
├── requirements-ci.txt  (19 стр)
├── requirements-dev.txt  (10 стр)
├── requirements.txt  (51 стр)
├── scripts/
│   ├── __init__.py  (7 стр)
│   ├── build_exe.py  (78 стр)
│   ├── check_caps.py  (174 стр)
│   ├── make_icon.py  (80 стр)
│   ├── make_installer_images.py  (121 стр)
│   ├── mics.py  (52 стр)
│   ├── selftest.py  (49 стр)
│   ├── set_llm_model.py  (52 стр)
│   ├── voicedemo.py  (41 стр)
│   ├── wakebench.py  (88 стр)
├── snapshot.py  (698 стр)
├── start_fenix.bat  (6 стр)
├── start_fenix_debug.bat  (15 стр)
├── test_intents.py  (380 стр)
├── test_uia_dump.py  (39 стр)
├── test_uia_manual.py  (52 стр)
├── tests/
│   ├── __init__.py  (0 стр)
│   ├── test_caps.py  (23 стр)
│   ├── test_config_manager.py  (47 стр)
│   ├── test_mood.py  (386 стр)
│   ├── test_uia.py  (247 стр)
│   ├── test_weather.py  (237 стр)
```

## 2. Смысл из кода (сигнатуры, константы, порядок)

**`jarvis/__init__.py`**

```
  # Феникс — локальный голосовой ассистент для Windows.
  APP_NAME = ...
```

**`jarvis/actions.py`**

```
  # Действия: запуск приложений, открытие сайтов, скриншоты, медиа, печать, окна.
  BASE_DIR = ...
  _CAPS_FILE = ...
  _CAPS: ...
  _CMD_VERBS = ...
  def spec_from_string(s: str)
  def run_spec(spec)
  def open_path(path, minimized: bool=False)
  def open_in_editor(path, prefer: str='auto')
  def open_url(url: str)
  def open_browser()
  def open_search(engine: str, query: str)
  def google_search(query: str)
  def open_site_lucky(name: str)
  def spoken_domain(name: str)
  def guess_site(name: str)
  def normalize_url(raw: str)
  def take_screenshot()
  def media_key(key: str, times: int=1)
  def ensure_music_playing()
  def key_press(key: str)
  def hotkey(keys)
  def scroll(direction: str, amount: int=3)
  def click_at(x: int, y: int, button: str='left')
  def switch_layout()
  def set_layout_ru()
  def set_layout_en()
  def get_layout()
  def get_volume()
  def set_volume(percent: int)
  def get_brightness()
  def set_brightness(percent: int)
  def find_process(name: str, threshold: float=0.7)
  def kill_process(name: str)
  def close_browser()
  def minimize_window(name: str)
  def type_text(text: str)
  def minimize_all()
  _WINDOW_SYNONYMS = ...
  def minimize_window_by_title(name: str)
  def maximize_window_by_title(name: str)
  def activate_window_by_title(name: str)
  def minimize_active()
  def maximize_active()
  def switch_window(back: bool=False)
  def copy_selection()
  def clipboard_read()
  def clipboard_write(text: str)
  def clipboard_clear()
```

**`jarvis/apps.py`**

```
  # Каталог известных приложений: как их зовут голосом, как открыть и как закрыть.
  class App
    def resolve_open(self)
  def build_apps(config: dict)
  def find_app(apps: list[App], target: str)
```

**`jarvis/brain.py`**

```
  # LLM-фолбэк: локальная нейронка (Ollama) разбирает команду в структурный интент.
  SYSTEM_SMALL = ...
  SYSTEM_MEDIUM = ...
  SYSTEM_LARGE = ...
  PROMPT_LEVELS = ...
  def pick_prompt(model: str, override: str='auto')
  CHAT_SYSTEM = ...
  class Brain
    def __init__(self, model='qwen2.5:7b-instruct', url='http://127.0.0.1:11434', timeout=20.0, prompt_level='auto', tempera...)
    def chat(self, cmd, history=None)
    def chat_stream(self, cmd, history=None)
    def onboarding_chat(self, user_text: str, history: list)
    def parse(self, cmd)
  ACTIONS = ...
```

**`jarvis/celebrations.py`**

```
  # Праздничные триггеры — поздравление с ДР + двойной салют.
  DEFAULTS = ...
  def match_celebration(cmd: str)
  def start_celebration(jarvis, gui)
```

**`jarvis/config.py`**

```
  # Загрузка конфигурации и объект Config в памяти.
  BASE_DIR = ...
  DEFAULT_CONFIG = ...
  class Config
    def __init__(self, path: Path | None=None)
    def reload(self)
    def get(self, key: str, default=None)
    def all_data(self)
    def set(self, key: str, value)
    def update(self, data: dict)
    def subscribe(self, callback: Callable[[str, Any], None])
    def unsubscribe(self, callback: Callable[[str, Any], None])
  _GLOBAL: ...
  def load_config(base_dir: Path | None=None)
  def get_global()
```

**`jarvis/config_manager.py`**

```
  # Единый менеджер записи в config.json.
  def load(path: Path | None=None)
  def save(data: dict, path: Path | None=None)
  def update(key: str, value, path: Path | None=None)
```

**`jarvis/files.py`**

```
  # Файлы и папки: открыть, посмотреть содержимое, создать.
  _FOLDER_STEMS = ...
  _FOLDER_STEMS_EXPLICIT = ...
  _EXT_WORDS = ...
  def resolve_folder(spoken: str, explicit: bool=False)
  def open_folder(path: Path)
  def describe_folder(path: Path, limit: int=5)
  def create_file(folder: Path, name: str, ext: str='.txt')
  def create_folder(folder: Path, name: str)
```

**`jarvis/first_run.py`**

```
  # Первый запуск — знакомство через LLM-диалог.
  def is_first_run()
  def greeting()
  def mark_done()
```

**`jarvis/gui.py`**

```
  # GUI Феникса — интерактивное окно на Flet 1.0.3.
  PALETTES = ...
  class _Palette
    def __init__(self)
    def set(self, name: str)
  P = ...
  BG_DARK = ...
  BG_CARD = ...
  BG_BUBBLE_USER = ...
  BG_BUBBLE_AI = ...
  ACCENT = ...
  TEXT = ...
  TEXT_DIM = ...
  STATES = ...
  THEMES = ...
  LLM_MODELS = ...
  TTS_BACKENDS = ...
  class FenixGUI
    def __init__(self, jarvis, config)
    def start(self)
    def run_main(self)
    def stop(self)
    def show_window(self)
    def open_settings_tab(self)
    def add_message(self, role: str, text: str)
    def add_stream_chunk(self, chunk: str)
    def end_stream(self)
    def set_state(self, state: str)
    def set_mic_test_result(self, text: str, color: str)
    def launch_fireworks(self, duration: float=6.0)
  >>> GUI: ft.run(...) - Flet в главном потоке
```

**`jarvis/history.py`**

```
  # История последних действий для отмены («стоп, не то»).
  _MAX = ...
  def push(item: dict)
  def push_macro(steps: list)
  def pop()
  def peek()
  def clear()
  def size()
```

**`jarvis/installed.py`**

```
  # Индекс установленных программ по ярлыкам меню «Пуск».
  _EXCLUDE = ...
  def scan_start_menu()
  def find_installed(index: dict[str, Path], spoken: str, threshold: float=0.75)
```

**`jarvis/intents/__init__.py`**

```
  # Разбор команд Феникса — пакет.
```

**`jarvis/intents/context.py`**

```
  # Контекст, который передаётся между стадиями pipeline.
  class Ctx
```

**`jarvis/intents/execute.py`**

```
  # Dispatch: action → функция-обработчик.
  _WEATHER_BAD_TARGET = ...
  _FOLDER_TITLES = ...
  def execute_intent(handler, intent: dict)
  def execute_steps(handler, steps: list)
  _KEY_MAP = ...
  BROWSER_WORDS = ...
  _DISPATCH = ...
```

**`jarvis/intents/fast/__init__.py`**

```
  # Реестр быстрых обработчиков.
  def build_registry(handler) -> [('custom', lambda cmd: match_custom(handler, cmd)), ('small_talk', lambda cmd: small_talk(handler, cmd)), ('music', lambda cmd: music_fast(handler, cmd)), ('screenshot', lambda cmd: screenshot_fast(handler, cmd)), ('u...]
```

**`jarvis/intents/fast/correction.py`**

```
  # Коррекция: «это не то, я сказал логи».
  def correction_fast(handler, cmd: str)
```

**`jarvis/intents/fast/custom.py`**

```
  # Пользовательские команды: из config.json и из паков.
  def load_custom(config)
  def load_packs_as_custom(config)
  def match_custom(handler, cmd: str)
```

**`jarvis/intents/fast/debug.py`**

```
  # Диагностика: «что ты слышал», «почему не понял».
  def debug_fast(handler, cmd: str)
```

**`jarvis/intents/fast/memory.py`**

```
  # Управление памятью диалога.
  def memory_fast(handler, cmd: str)
```

**`jarvis/intents/fast/music.py`**

```
  # Музыка — ДО open_fast.
  def music_fast(handler, cmd: str)
```

**`jarvis/intents/fast/open.py`**

```
  # Открытие приложений / сайтов / папок / профиля — без LLM.
  def open_fast(handler, cmd: str)
  def open_profile_fast(handler, cmd: str)
```

**`jarvis/intents/fast/packs.py`**

```
  # Паки команд — обёртка с side-effect.
  def packs_fast(handler, cmd: str)
```

**`jarvis/intents/fast/persona.py`**

```
  # Команды персоны: стиль общения, описание, сброс онбординга.
  def persona_fast(handler, cmd: str)
```

**`jarvis/intents/fast/profile.py`**

```
  # Профиль: смена, список, факты «запомни: X — Y».
  _NOT_A_CITY = ...
  _MY_KEY_MAP = ...
  def profile_fast(handler, cmd: str)
```

**`jarvis/intents/fast/screenshot.py`**

```
  # Скриншот: «сделай скриншот», «открой скриншот».
  def screenshot_fast(handler, cmd: str)
```

**`jarvis/intents/fast/small_talk.py`**

```
  # Мелкий разговор: время, дата, «кто ты», праздники.
  MONTHS = ...
  WEEKDAYS = ...
  def small_talk(handler, cmd: str)
```

**`jarvis/intents/fast/system.py`**

```
  # Системные команды: раскладка, громкость, яркость.
  def system_fast(handler, cmd: str)
```

**`jarvis/intents/fast/tasks.py`**

```
  # Задачи — обёртка над `tasks`.
  def tasks_fast(handler, cmd: str)
```

**`jarvis/intents/fast/timers.py`**

```
  # Напоминания — обёртка над `timers`.
  def timers_fast(handler, cmd: str)
```

**`jarvis/intents/fast/uia.py`**

```
  # UIA-команды голосом: «прочитай окно», «закрой вкладку ютуб», «какой сайт».
  def uia_fast(handler, cmd: str)
```

**`jarvis/intents/fast/undo.py`**

```
  # Отмена последнего действия («не то», «отмени»).
  def undo_fast(handler, cmd: str)
```

**`jarvis/intents/fast/voices.py`**

```
  # Голоса Piper — обёртка над модулем `voices`.
  def voices_fast(handler, cmd: str)
```

**`jarvis/intents/fast/weather.py`**

```
  # Простые правила для погоды и курса — без LLM.
  def weather_currency_fast(handler, cmd: str)
```

**`jarvis/intents/handler.py`**

```
  # IntentHandler — оркестрация.
  class IntentHandler
    def __init__(self, config, apps, brain=None, listener=None, gui=None, jarvis=None)
    def handle(self, cmd: str)
    def finalize_stream(self, full_text: str)
```

**`jarvis/intents/password.py`**

```
  # Хеширование пароля и действия, требующие пароля.
  _PASSWORD_PREFIX = ...
  def hash_password(password: str)
  def is_hashed(value: str)
  def verify_password(candidate: str, stored: str)
  def migrate_password_if_needed(config)
  DANGER_ACTIONS = ...
  def is_danger(intent: dict, stored_password: str)
  ACTION_HUMAN = ...
```

**`jarvis/intents/sites.py`**

```
  # Сайты для открытия голосом — ленивая загрузка из packs/sites.json.
  _SITES_FALLBACK = ...
  _SITES_CACHE: ...
  def get_sites()
```

**`jarvis/intents/stages/__init__.py`**

```
  # Стадии обработки команды. Порядок = приоритет.
  def build_pipeline(handler) -> [CancelStage(), OnboardingStage(), CorrectionStage(), PasswordStage(), MemoryStage(), PendingStage(), ClipboardStage(), ModesStage(), CompoundStage(), FastHandlersStage(), LLMStage()]
```

**`jarvis/intents/stages/base.py`**

```
  # Базовая стадия pipeline.
  class Stage
    def handle(self, ctx: Ctx)
```

**`jarvis/intents/stages/cancel.py`**

```
  # «Стоп», «хватит», «отбой» — самый первый этап.
  class CancelStage(Stage)
    def handle(self, ctx)
```

**`jarvis/intents/stages/clipboard.py`**

```
  # 4 команды буфера обмена. Все — до LLM.
  class ClipboardStage(Stage)
    def handle(self, ctx)
```

**`jarvis/intents/stages/compound.py`**

```
  # Многослойные команды: «открой стим и запусти доту».
  class CompoundStage(Stage)
    def handle(self, ctx)
```

**`jarvis/intents/stages/correction.py`**

```
  # Применение коррекции «это не то» перед разбором команды.
  class CorrectionStage(Stage)
    def handle(self, ctx)
```

**`jarvis/intents/stages/fast.py`**

```
  # Вызов реестра быстрых обработчиков.
  class FastHandlersStage(Stage)
    def handle(self, ctx)
```

**`jarvis/intents/stages/llm.py`**

```
  # LLM — последний шанс разобрать команду.
  class LLMStage(Stage)
    def handle(self, ctx)
```

**`jarvis/intents/stages/memory.py`**

```
  # Команды памяти диалога.
  class MemoryStage(Stage)
    def handle(self, ctx)
```

**`jarvis/intents/stages/modes.py`**

```
  # Режимы работы: commands / llm / combo.
  class ModesStage(Stage)
    def handle(self, ctx)
```

**`jarvis/intents/stages/onboarding.py`**

```
  # Первый запуск — знакомство через LLM-диалог.
  class OnboardingStage(Stage)
    def handle(self, ctx)
```

**`jarvis/intents/stages/password.py`**

```
  # Ожидание пароля + команда «удали профиль X».
  class PasswordStage(Stage)
    def handle(self, ctx)
  def build_ask_password(intent: dict, expires_sec: int=30)
```

**`jarvis/intents/stages/pending.py`**

```
  # Ожидание уточнения (pending_question).
  _NOT_A_CITY = ...
  class PendingStage(Stage)
    def handle(self, ctx)
```

**`jarvis/intents/verbs.py`**

```
  # Константы глаголов и слов — единый источник истины.
  COMMAND_VERBS = ...
  CANCEL = ...
  SEARCH_VERBS = ...
  BROWSER_WORDS = ...
```

**`jarvis/learning.py`**

```
  # Самообучение Феникса: факты и коррекции.
  def add_fact(key: str, value: str)
  def get_fact(key: str, default=None)
  def all_facts()
  def forget_fact(key: str)
  def add_correction(wrong: str, right: str)
  def find_correction(cmd: str, threshold: float=0.85)
  def all_corrections()
  def forget_correction(wrong: str)
  def build_context()
```

**`jarvis/main.py`**

```
  # Точка входа: связывает распознавание, интенты, синтез речи и GUI.
  BASE_DIR = ...
  _REJECT = ...
  class Jarvis
    def __init__(self, config, listener, speaker, handler, base_dir: Path, whisper=None, gui=None)
    def say(self, reply: Reply)
    def shutdown(self)
    def mic_watchdog(self)
    def run_loop(self)
  def setup_logging()
  def main()
```

**`jarvis/matching.py`**

```
  # Нечёткое сопоставление речи с названиями: транслитерация + difflib.
  _RU_DIGRAPHS = ...
  _RU_LAT = ...
  def translit(text: str)
  _FOLD = ...
  _NUM = ...
  def wake_score(token: str, wake_word: str)
  def match_score(spoken: str, candidate: str)
```

**`jarvis/memory.py`**

```
  # Память диалога — на профиль.
  def load(limit: int | None=None)
  def append(message: dict)
  def clear()
  def describe(messages: list, limit: int=6)
  def handle_memory_command(cmd: str, messages: list)
```

**`jarvis/model.py`**

```
  # Скачивание и распаковка модели Vosk для русского языка (~45 МБ).
  MODEL_NAME = ...
  MODEL_URL = ...
  def ensure_model(local_models_dir: Path | None=None)
```

**`jarvis/modes.py`**

```
  # Режимы работы Феникса: commands, llm, combo.
  NAMES = ...
  def get_mode(config)
  def set_mode(mode: str, config=None)
  def handle_mode_command(cmd: str, current_mode: str, config=None)
```

**`jarvis/mood.py`**

```
  # Mood — эмоциональное состояние ассистента.
  STATES = ...
  DEFAULT_MOOD = ...
  DEFAULT_DECAY_SEC = ...
  def get()
  def get_state()
  def set_mood(state: str, reason: str='')
  def subscribe(callback)
  def unsubscribe(callback)
  _PRAISE = ...
  _EXCITED = ...
  _RUDE = ...
  _TIRED = ...
  def detect(cmd: str)
  def apply_from_text(cmd: str)
  def decay(max_age_sec: int=DEFAULT_DECAY_SEC)
  _RATE_MULTIPLIERS = ...
  def effective_rate(base_rate: float)
  _COLORS = ...
  def color()
  _PROMPT_HINTS = ...
  def build_prompt_block()
  _DESCRIPTIONS = ...
  def describe()
  def handle_mood_command(cmd: str)
```

**`jarvis/observer.py`**

```
  # Observer — фоновое наблюдение за диалогом.
  EXTRACT_PROMPT = ...
  class DialogObserver
    def __init__(self, config, brain, profile_module, learning_module, min_interval: float=30.0, batch_size: int=6)
    def start(self)
    def stop(self)
    def observe(self, role: str, text: str)
```

**`jarvis/packs.py`**

```
  # Загрузка и выгрузка паков команд из папки packs/.
  BASE_DIR = ...
  PACKS_DIR = ...
  _PACK_ALIASES = ...
  def normalize_name(name: str)
  def list_available()
  def load_pack(name: str)
  def load_active(config)
  def save_active(active: list[str], config=None)
  def handle_pack_command(cmd: str, current_active: list[str], config=None)
```

**`jarvis/paths.py`**

```
  # Централизованное определение путей Феникса.
  APP_NAME = ...
  _PROGRAM_DIR: ...
  _USER_DIR: ...
  def user_home()
  def program_dir()
  def user_dir()
  def program_models_dir()
  def program_whisper_cache_dir()
  def logs_dir()
  def profiles_dir()
  def config_path()
```

**`jarvis/persona.py`**

```
  # Персона ассистента — стиль общения, черты, backstory.
  DEFAULT_PERSONA = ...
  VALID_STYLES = ...
  STYLE_DESCRIPTIONS = ...
  STYLE_ALIASES = ...
  def get()
  def set_persona(data: dict)
  def set_field(key: str, value)
  def normalize_style(text: str)
  def set_style(style: str)
  def is_onboarded()
  def mark_onboarded()
  def reset_onboarding()
  def build_prompt_block()
  def describe()
```

**`jarvis/profile.py`**

```
  # Профиль пользователя — мультипрофиль.
  BASE_DIR = ...
  PROFILES_DIR = ...
  _OLD_PROFILE = ...
  _OLD_DIALOG = ...
  def profile_dir()
  def profile_path()
  def dialog_path()
  def current()
  def subscribe(callback)
  def unsubscribe(callback)
  def switch(name: str)
  def list_all()
  def delete(name: str)
  def get(key: str, default=None)
  def set(key: str, value)
  def all_data()
  def forget(key: str)
  def set_fact(key: str, value: str)
  def get_fact(key: str, default=None)
  def all_facts()
  def forget_fact(key: str)
  def init()
```

**`jarvis/recorder.py`**

```
  # Запись действий: клавиши, клики, паузы.
  MAX_DURATION_SEC = ...
  MIN_WAIT_SEC = ...
  MAX_WAIT_SEC = ...
  def is_recording()
  def start()
  def stop()
  def play(macro: dict, speed: float=1.0)
  def describe(macro: dict)
```

**`jarvis/reply.py`**

```
  # Reply — результат IntentHandler.handle().
  class Reply
    def is_stream(self)
```

**`jarvis/steam.py`**

```
  # Индекс установленных игр Steam: appmanifest -> (название, appid).
  _SKIP = ...
  def scan_steam_games()
  def find_game(games: list[tuple[str, str]], spoken: str, threshold: float=0.72)
```

**`jarvis/stt.py`**

```
  # Распознавание речи.
  TURBO_MODEL = ...
  WHISPER_PROMPT = ...
  ECHO_WINDOW_SEC = ...
  BARGE_LOG_INTERVAL = ...
  _CUDA_DLLS_ADDED = ...
  class Listener
    def __init__(self, model_dir, sample_rate=16000, device=None)
    def barge_start(self)
    def barge_end(self)
    def resolve_device(device)
    def flush(self)
    def reset_stats(self)
    def phrases(self, stop_event)
  class WhisperTranscriber
    def __init__(self, model_name='auto', device='auto')
    def transcribe(self, pcm, sample_rate=16000)
```

**`jarvis/tasks.py`**

```
  # Списки задач.
  def add(text: str)
  def find(query: str)
  def mark_done(query: str)
  def remove(query: str)
  def clear_all()
  def format_list(tasks: list | None=None)
  def handle_task_command(cmd: str)
```

**`jarvis/text_utils.py`**

```
  # Общие текстовые утилиты для Феникса.
  CJK_RE = ...
  def strip_cjk(text: str)
  def strip_cjk_chunk(text: str)
  def normalize(text: str)
  _REPLACEMENTS = ...
  _RE_COMPILED = ...
  def prepare_text(text: str)
```

**`jarvis/timers.py`**

```
  # Таймеры и напоминания.
  _NUM_WORDS = ...
  def set_on_fire(callback)
  def add(text: str, fire_at: float)
  def remove_all()
  def list_all()
  def format_list(timers: list)
  def restore_all()
  def handle_timer_command(cmd: str)
```

**`jarvis/tray.py`**

```
  # Иконка в системном трее (pystray).
  def build_tray(jarvis)
```

**`jarvis/tts.py`**

```
  # Синтез речи.
  PIPER_REPO = ...
  BASE_DIR = ...
  _SENTENCE_END = ...
  class Speaker
    def __init__(self, config)
    def set_voice(self, voice: str)
    def set_rate(self, rate: float)
    def speak(self, text: str)
    def play_async(self, text: str)
    def stop(self)
    def is_playing(self)
    def wait_end(self, timeout: float=30.0)
    def speak_stream(self, text_iter, timeout: float=30.0)
```

**`jarvis/uia.py`**

```
  # UI Automation — видим окна и элементы интерфейса.
  def find_window(title_part: str, timeout: float=2.0)
  def get_active_window()
  def get_active_window_title()
  def read_active_text(max_chars: int=4000)
  def read_active_text_stripped(max_chars: int=2000)
  def click_button(name_part: str, window_title: str | None=None, timeout: float=2.0)
  _BROWSER_PROCESSES = ...
  def list_windows()
  def list_browsers()
  def find_browser_window()
  def read_browser_url()
  def read_browser_tab_title()
  def read_browser_tabs()
  def close_browser_tab(tab_title_part: str)
  def switch_browser_tab(tab_title_part: str)
  def click_menu_item(path: str)
  def is_available()
  def describe_active_window()
  def describe_browsers()
```

**`jarvis/voices.py`**

```
  # Управление голосами Piper: ruslan, dmitri, irina, denis.
  PIPER_VOICES = ...
  ALIASES = ...
  def current_voice(config=None)
  def switch(voice: str, config=None)
  def handle_voice_command(cmd: str, config=None)
```

**`jarvis/weather.py`**

```
  # Погода и курс валют.
  _CACHE: ...
  _CACHE_LOCK = ...
  _DEFAULT_TTL = ...
  def set_config(config)
  def geocode(city: str)
  _WEATHER_CODES = ...
  def get_weather(city: str, day: str='today')
  def describe_weather(w: dict)
  def get_currency_rates()
  _DEFAULT_CURRENCIES = ...
  def describe_currency(rates: dict, code: str='')
```

**`scripts/__init__.py`**

```
  # Пакет scripts: утилиты разработчика.
```

**`scripts/build_exe.py`**

```
  # Сборка Феникс.exe (лёгкий лаунчер).
  BASE = ...
  ICON = ...
  EXE_NAME = ...
  def ensure_icon()
  def build()
```

**`scripts/check_caps.py`**

```
  # Проверка возможностей системы — запускается из install.bat.
  BASE = ...
  OUTPUT = ...
  def check_volume()
  def check_brightness()
  def check_layout()
  def check_cpu()
  def main()
```

**`scripts/make_icon.py`**

```
  # Генерация иконки Феникса (jarvis/icon.ico).
  BASE = ...
  OUTPUT = ...
  BG_COLOR = ...
  ACCENT = ...
  def draw_icon(size: int)
  def main()
```

**`scripts/make_installer_images.py`**

```
  # Генерация картинок для Inno Setup установщика Феникса.
  BASE = ...
  ICON_PATH = ...
  BANNER_OUT = ...
  SMALL_OUT = ...
  BG_COLOR = ...
  ACCENT = ...
  TEXT_COLOR = ...
  BMP_FORMAT = ...
  def make_banner()
  def make_small()
  def main()
```

**`scripts/mics.py`**

```
  # Подбор микрофона: показывает устройства ввода и уровень сигнала.
  BASE = ...
  FS = ...
  def main()
```

**`scripts/selftest.py`**

```
  # Самопроверка без микрофона: TTS -> Vosk -> разбор команды.
  BASE = ...
  PHRASES = ...
  def recognize(model: Model, wav_bytes: bytes)
  def main()
```

**`scripts/set_llm_model.py`**

```
  # Устанавливает llm_model в config.json.
  BASE = ...
  def main()
```

**`scripts/voicedemo.py`**

```
  # Прослушка голосов: проигрывает одну фразу всеми доступными голосами.
  BASE = ...
  TEXT = ...
  def main()
```

**`scripts/wakebench.py`**

```
  # Бенчмарк кандидатов в wake-слово: TTS (Pavel) -> Vosk-small -> что услышалось.
  BASE = ...
  CANDIDATES = ...
  TEMPLATES = ...
  def recognize(model: Model, wav_bytes: bytes)
  def main()
```

**`tests/test_caps.py`**

```
  # Тесты check_caps: структура system_caps.json.
  def test_check_volume_structure()
  def test_check_brightness_structure()
  def test_check_layout_structure()
```

**`tests/test_config_manager.py`**

```
  # Тесты config_manager: параллельная запись не рвёт файл.
  def test_parallel_writes(tmp_path)
  def test_atomic_write_valid_json(tmp_path)
  def test_load_nonexistent(tmp_path)
  def test_load_broken(tmp_path)
```

**`tests/test_mood.py`**

```
  # Тесты jarvis.mood — состояние, детекция, decay, влияние.
  def test_get_default_neutral()
  def test_set_mood_valid()
  def test_set_mood_invalid()
  def test_set_mood_no_change()
  def test_subscribe_and_notify()
  def test_unsubscribe()
  def test_detect_praise()
  def test_detect_excited()
  def test_detect_rude()
  def test_detect_tired()
  def test_detect_none()
  def test_detect_rude_beats_praise()
  def test_apply_from_text_changes()
  def test_apply_from_text_no_change()
  def test_decay_old_state()
  def test_decay_fresh_state()
  def test_decay_neutral()
  def test_effective_rate_excited()
  def test_effective_rate_tired()
  def test_effective_rate_neutral()
  def test_color_all_states()
  def test_build_prompt_block_neutral()
  def test_build_prompt_block_annoyed()
  def test_describe_neutral()
  def test_describe_with_time()
  def test_handle_mood_command_query()
  def test_handle_mood_command_cheer_up()
  def test_handle_mood_command_calm_down()
  def test_handle_mood_command_none()
```

**`tests/test_uia.py`**

```
  # Тесты jarvis.uia — логика обёртки. С моками.
  def test_list_windows_empty()
  def test_list_windows_names()
  def test_describe_active_window_ok()
  def test_describe_active_window_none()
  def test_describe_browsers_empty()
  def test_describe_browsers_found()
  def test_read_browser_tab_title_no_browser()
  def test_read_browser_tab_title_strips_suffix()
  def test_read_browser_tab_title_no_suffix()
  def test_read_browser_tabs_no_browser()
  def test_read_browser_tabs_from_toolbar()
  def test_read_browser_tabs_fallback()
  def test_read_browser_url_no_browser()
  def test_read_browser_url_from_edit()
  def test_read_browser_url_fallback_from_title()
  def test_is_available_true()
  def test_is_available_false()
```

**`tests/test_weather.py`**

```
  # Тесты weather: структура ответов, describe_*, geocode с моками.
  def test_describe_weather_none()
  def test_describe_weather_today()
  def test_describe_weather_tomorrow()
  def test_describe_currency_specific()
  def test_describe_currency_default()
  def test_describe_currency_unknown()
  def test_geocode_ok()
  def test_geocode_not_found()
  def test_geocode_http_error()
  def test_get_weather_today_ok()
  def test_get_weather_tomorrow_ok()
  def test_get_weather_no_geocode()
  def test_get_currency_rates_ok()
  def test_get_currency_rates_http_error()
  def test_cache_used()
  def test_cache_different_cities()
```

**`check_syntax.py`**

```
  # Проверяет синтаксис всех .py файлов в проекте.
  BASE = ...
  TARGETS = ...
  SKIP_DIRS = ...
  SKIP_FILES = ...
```

**`launcher.py`**

```
  # Лаунчер Феникса — полный автозапуск.
  MUTEX_NAME = ...
  _MUTEX_HANDLE = ...
  PYTHON_INSTALLER_URL = ...
  PYTHON_INSTALLER_FILE = ...
  VOSK_MODEL_NAME = ...
  VOSK_MODEL_URL = ...
  OLLAMA_URL = ...
  OLLAMA_DOWNLOAD_PAGE = ...
  PYTHON_SEARCH_PATHS = ...
  OLLAMA_SEARCH_PATHS = ...
  REQUIRED_PY_VERSIONS = ...
  MB_OK = ...
  MB_OKCANCEL = ...
  MB_YESNO = ...
  MB_ICONERROR = ...
  MB_ICONWARNING = ...
  MB_ICONINFORMATION = ...
  MB_ICONQUESTION = ...
  IDYES = ...
  IDNO = ...
  IDOK = ...
  IDCANCEL = ...
  CREATE_NO_WINDOW = ...
  DETACHED_PROCESS = ...
  def msg_box(text: str, title: str='Феникс', flags: int=MB_OK)
  def info(text: str, title: str='Феникс')
  def warn(text: str, title: str='Феникс')
  def error(text: str, title: str='Феникс — ошибка')
  def ask_yes_no(text: str, title: str='Феникс')
  def already_running(logger)
  def find_project_dir(logger)
  def find_python(logger)
  def download_python_installer(logger)
  def run_python_installer(installer: Path, logger)
  def find_venv_pythonw(project_dir: Path, logger)
  def create_venv(project_dir: Path, python_exe: str, logger)
  def check_dependencies(project_dir: Path, logger)
  def install_dependencies(project_dir: Path, logger)
  def check_vosk_model(project_dir: Path, logger)
  def download_vosk_model(project_dir: Path, logger)
  def check_ollama_running(logger)
  def find_ollama_exe(logger)
  def handle_ollama(logger)
  def run_jarvis(project_dir: Path, pythonw: Path, logger)
  def main()
```

**`snapshot.py`**

```
  # Собирает снимок проекта в один SNAPSHOT.md.
  BASE = ...
  OUTPUT = ...
  EXCLUDE_DIRS = ...
  EXCLUDE_FILES = ...
  EXCLUDE_EXT = ...
  TEXT_EXT = ...
  MAX_FILE_SIZE = ...
  DOCS_FULL = ...
  PRIORITY_ORDER = ...
  SECRET_RE = ...
  def redact_secrets(text: str)
  def fence_for(content: str)
  def should_skip_dir(path: Path)
  def should_skip_file(path: Path)
  def collect_files(root: Path)
  def read_text(path: Path)
  def count_lines(path: Path)
  def kind_of(path: Path)
  def extract_meaning(path: Path)
  def collapse_docstrings(src: str, max_lines: int=3)
  def build_tree(files: list[Path], root: Path)
  def section_code(files: list[Path], root: Path, mode: str, budget_kb: float | None, secrets: list[str])
  def section_docs(files: list[Path], root: Path)
  def build_snapshot(mode: str, budget_kb: float | None)
  def parse_args(argv: list[str] | None=None)
  def drift_reason(content: str, path: Path)
  def main()
  >>> GUI: ft.run(...) - Flet в главном потоке
```

**`test_intents.py`**

```
  # Автотест Феникса без микрофона.
  BASE_DIR = ...
  LOGS_DIR = ...
  LOG_FILE = ...
  TESTS = ...
  class Result
    def __init__(self, name, cmd, reply_text, expected, elapsed)
  def build_handler(use_llm=False, reset_profile=True)
  def reset_handler_state(handler)
  def run_one(handler, speaker, name, cmd, expected, hooks=None)
  def main()
```

**`test_uia_dump.py`**

```
  # Дамп дерева UIA активного окна браузера.
  def dump_tree(ctrl, depth=0, max_depth=8)
```

**`test_uia_manual.py`**

```
  # Ручная проверка UIA в браузере — без хардкода конкретного браузера.
```

## 3. Индекс кода

| Файл | Строк | Категория | О чём модуль |
|---|---:|---|---|
| `jarvis/__init__.py` | 8 | code | Феникс — локальный голосовой ассистент для Windows. |
| `jarvis/__main__.py` | 4 | code |  |
| `jarvis/actions.py` | 1155 | code | Действия: запуск приложений, открытие сайтов, скриншоты, медиа, печать |
| `jarvis/apps.py` | 114 | code | Каталог известных приложений: как их зовут голосом, как открыть и как  |
| `jarvis/brain.py` | 795 | code | LLM-фолбэк: локальная нейронка (Ollama) разбирает команду в структурны |
| `jarvis/celebrations.py` | 165 | code | Праздничные триггеры — поздравление с ДР + двойной салют. |
| `jarvis/config.py` | 224 | code | Загрузка конфигурации и объект Config в памяти. |
| `jarvis/config_manager.py` | 156 | code | Единый менеджер записи в config.json. |
| `jarvis/files.py` | 102 | code | Файлы и папки: открыть, посмотреть содержимое, создать. |
| `jarvis/first_run.py` | 26 | code | Первый запуск — знакомство через LLM-диалог. |
| `jarvis/gui.py` | 1580 | code | GUI Феникса — интерактивное окно на Flet 1.0.3. |
| `jarvis/history.py` | 75 | code | История последних действий для отмены («стоп, не то»). |
| `jarvis/installed.py` | 51 | code | Индекс установленных программ по ярлыкам меню «Пуск». |
| `jarvis/intents/__init__.py` | 10 | code | Разбор команд Феникса — пакет. |
| `jarvis/intents/context.py` | 19 | code | Контекст, который передаётся между стадиями pipeline. |
| `jarvis/intents/execute.py` | 867 | code | Dispatch: action → функция-обработчик. |
| `jarvis/intents/fast/__init__.py` | 54 | code | Реестр быстрых обработчиков. |
| `jarvis/intents/fast/correction.py` | 28 | code | Коррекция: «это не то, я сказал логи». |
| `jarvis/intents/fast/custom.py` | 72 | code | Пользовательские команды: из config.json и из паков. |
| `jarvis/intents/fast/debug.py` | 38 | code | Диагностика: «что ты слышал», «почему не понял». |
| `jarvis/intents/fast/memory.py` | 41 | code | Управление памятью диалога. |
| `jarvis/intents/fast/music.py` | 38 | code | Музыка — ДО open_fast. |
| `jarvis/intents/fast/open.py` | 61 | code | Открытие приложений / сайтов / папок / профиля — без LLM. |
| `jarvis/intents/fast/packs.py` | 27 | code | Паки команд — обёртка с side-effect. |
| `jarvis/intents/fast/persona.py` | 55 | code | Команды персоны: стиль общения, описание, сброс онбординга. |
| `jarvis/intents/fast/profile.py` | 148 | code | Профиль: смена, список, факты «запомни: X — Y». |
| `jarvis/intents/fast/screenshot.py` | 26 | code | Скриншот: «сделай скриншот», «открой скриншот». |
| `jarvis/intents/fast/small_talk.py` | 67 | code | Мелкий разговор: время, дата, «кто ты», праздники. |
| `jarvis/intents/fast/system.py` | 130 | code | Системные команды: раскладка, громкость, яркость. |
| `jarvis/intents/fast/tasks.py` | 7 | code | Задачи — обёртка над `tasks`. |
| `jarvis/intents/fast/timers.py` | 7 | code | Напоминания — обёртка над `timers`. |
| `jarvis/intents/fast/uia.py` | 100 | code | UIA-команды голосом: «прочитай окно», «закрой вкладку ютуб», «какой са |
| `jarvis/intents/fast/undo.py` | 67 | code | Отмена последнего действия («не то», «отмени»). |
| `jarvis/intents/fast/voices.py` | 10 | code | Голоса Piper — обёртка над модулем `voices`. |
| `jarvis/intents/fast/weather.py` | 68 | code | Простые правила для погоды и курса — без LLM. |
| `jarvis/intents/handler.py` | 197 | code | IntentHandler — оркестрация. |
| `jarvis/intents/password.py` | 86 | code | Хеширование пароля и действия, требующие пароля. |
| `jarvis/intents/sites.py` | 62 | code | Сайты для открытия голосом — ленивая загрузка из packs/sites.json. |
| `jarvis/intents/stages/__init__.py` | 44 | code | Стадии обработки команды. Порядок = приоритет. |
| `jarvis/intents/stages/base.py` | 19 | code | Базовая стадия pipeline. |
| `jarvis/intents/stages/cancel.py` | 17 | code | «Стоп», «хватит», «отбой» — самый первый этап. |
| `jarvis/intents/stages/clipboard.py` | 68 | code | 4 команды буфера обмена. Все — до LLM. |
| `jarvis/intents/stages/compound.py` | 53 | code | Многослойные команды: «открой стим и запусти доту». |
| `jarvis/intents/stages/correction.py` | 24 | code | Применение коррекции «это не то» перед разбором команды. |
| `jarvis/intents/stages/fast.py` | 29 | code | Вызов реестра быстрых обработчиков. |
| `jarvis/intents/stages/llm.py` | 93 | code | LLM — последний шанс разобрать команду. |
| `jarvis/intents/stages/memory.py` | 21 | code | Команды памяти диалога. |
| `jarvis/intents/stages/modes.py` | 30 | code | Режимы работы: commands / llm / combo. |
| `jarvis/intents/stages/onboarding.py` | 73 | code | Первый запуск — знакомство через LLM-диалог. |
| `jarvis/intents/stages/password.py` | 94 | code | Ожидание пароля + команда «удали профиль X». |
| `jarvis/intents/stages/pending.py` | 62 | code | Ожидание уточнения (pending_question). |
| `jarvis/intents/verbs.py` | 45 | code | Константы глаголов и слов — единый источник истины. |
| `jarvis/learning.py` | 160 | code | Самообучение Феникса: факты и коррекции. |
| `jarvis/main.py` | 602 | code | Точка входа: связывает распознавание, интенты, синтез речи и GUI. |
| `jarvis/matching.py` | 113 | code | Нечёткое сопоставление речи с названиями: транслитерация + difflib. |
| `jarvis/memory.py` | 137 | code | Память диалога — на профиль. |
| `jarvis/model.py` | 102 | code | Скачивание и распаковка модели Vosk для русского языка (~45 МБ). |
| `jarvis/modes.py` | 51 | code | Режимы работы Феникса: commands, llm, combo. |
| `jarvis/mood.py` | 335 | code | Mood — эмоциональное состояние ассистента. |
| `jarvis/observer.py` | 198 | code | Observer — фоновое наблюдение за диалогом. |
| `jarvis/packs.py` | 117 | code | Загрузка и выгрузка паков команд из папки packs/. |
| `jarvis/paths.py` | 182 | code | Централизованное определение путей Феникса. |
| `jarvis/persona.py` | 132 | code | Персона ассистента — стиль общения, черты, backstory. |
| `jarvis/profile.py` | 451 | code | Профиль пользователя — мультипрофиль. |
| `jarvis/recorder.py` | 171 | code | Запись действий: клавиши, клики, паузы. |
| `jarvis/reply.py` | 25 | code | Reply — результат IntentHandler.handle(). |
| `jarvis/steam.py` | 67 | code | Индекс установленных игр Steam: appmanifest -> (название, appid). |
| `jarvis/stt.py` | 306 | code | Распознавание речи. |
| `jarvis/tasks.py` | 236 | code | Списки задач. |
| `jarvis/text_utils.py` | 132 | code | Общие текстовые утилиты для Феникса. |
| `jarvis/timers.py` | 340 | code | Таймеры и напоминания. |
| `jarvis/tray.py` | 96 | code | Иконка в системном трее (pystray). |
| `jarvis/tts.py` | 466 | code | Синтез речи. |
| `jarvis/uia.py` | 617 | code | UI Automation — видим окна и элементы интерфейса. |
| `jarvis/voices.py` | 69 | code | Управление голосами Piper: ruslan, dmitri, irina, denis. |
| `jarvis/weather.py` | 305 | code | Погода и курс валют. |
| `scripts/__init__.py` | 7 | code | Пакет scripts: утилиты разработчика. |
| `scripts/build_exe.py` | 78 | code | Сборка Феникс.exe (лёгкий лаунчер). |
| `scripts/check_caps.py` | 174 | code | Проверка возможностей системы — запускается из install.bat. |
| `scripts/make_icon.py` | 80 | code | Генерация иконки Феникса (jarvis/icon.ico). |
| `scripts/make_installer_images.py` | 121 | code | Генерация картинок для Inno Setup установщика Феникса. |
| `scripts/mics.py` | 52 | code | Подбор микрофона: показывает устройства ввода и уровень сигнала. |
| `scripts/selftest.py` | 49 | code | Самопроверка без микрофона: TTS -> Vosk -> разбор команды. |
| `scripts/set_llm_model.py` | 52 | code | Устанавливает llm_model в config.json. |
| `scripts/voicedemo.py` | 41 | code | Прослушка голосов: проигрывает одну фразу всеми доступными голосами. |
| `scripts/wakebench.py` | 88 | code | Бенчмарк кандидатов в wake-слово: TTS (Pavel) -> Vosk-small -> что усл |
| `tests/__init__.py` | 0 | code |  |
| `tests/test_caps.py` | 23 | code | Тесты check_caps: структура system_caps.json. |
| `tests/test_config_manager.py` | 47 | code | Тесты config_manager: параллельная запись не рвёт файл. |
| `tests/test_mood.py` | 386 | code | Тесты jarvis.mood — состояние, детекция, decay, влияние. |
| `tests/test_uia.py` | 247 | code | Тесты jarvis.uia — логика обёртки. С моками. |
| `tests/test_weather.py` | 237 | code | Тесты weather: структура ответов, describe_*, geocode с моками. |
| `check_syntax.py` | 60 | code | Проверяет синтаксис всех .py файлов в проекте. |
| `launcher.py` | 693 | code | Лаунчер Феникса — полный автозапуск. |
| `snapshot.py` | 698 | code | Собирает снимок проекта в один SNAPSHOT.md. |
| `test_intents.py` | 380 | code | Автотест Феникса без микрофона. |
| `test_uia_dump.py` | 39 | code | Дамп дерева UIA активного окна браузера. |
| `test_uia_manual.py` | 52 | code | Ручная проверка UIA в браузере — без хардкода конкретного браузера. |

---

## 4. Код и данные

### `jarvis/__init__.py`

```python
"""Феникс — локальный голосовой ассистент для Windows. ... [4 строк]"""

__version__ = "1.0.0"
APP_NAME = "Феникс"
```

### `jarvis/__main__.py`

```python
from jarvis.main import main

if __name__ == "__main__":
    main()
```

### `jarvis/actions.py`

```python
"""Действия: запуск приложений, открытие сайтов, скриншоты, медиа, печать, окна."""

import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import time
import urllib.parse
from pathlib import Path

from jarvis import paths as _paths

log = logging.getLogger("jarvis.actions")

BASE_DIR = Path(__file__).resolve().parent.parent
_CAPS_FILE = BASE_DIR / "system_caps.json"
_CAPS: dict = {}


def _load_caps() -> dict:
    """Читает system_caps.json. Кэширует. Если файла нет — возвращает {}."""
    global _CAPS
    if _CAPS:
        return _CAPS
    if _CAPS_FILE.exists():
        try:
            _CAPS = json.loads(_CAPS_FILE.read_text(encoding="utf-8"))
            log.info("system_caps.json загружен")
        except Exception:
            log.exception("Не удалось прочитать system_caps.json")
            _CAPS = {}
    return _CAPS


def _caps_available(name: str) -> bool:
    """Проверяет, доступна ли возможность."""
    return _load_caps().get(name, {}).get("available", False)


def _caps_method(name: str) -> str:
    return _load_caps().get(name, {}).get("method", "none")


# --- запуск приложений и файлов -------------------------------------------

# Известные системные команды, которые надо запускать через subprocess
# (а не через os.startfile). Иначе `os.startfile("shutdown /s /t 10")`
# падает с FileNotFoundError — РАНЬШЕ это была неработающая ветка
# для pack-команд вида "shutdown /s /t 10", "cmd /k ipconfig".
_CMD_VERBS = {
    "shutdown", "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh",
    "rundll32", "rundll32.exe",
    "ipconfig", "tasklist", "taskkill", "ping", "tracert", "winver",
    "control", "control.exe", "reg", "reg.exe", "net", "netstat",
    "systeminfo", "chkdsk", "msconfig", "resmon", "resmon.exe",
}


def _looks_like_cmd(s: str) -> bool:
    """Эвристика: строка похожа на команду с аргументами? ... [12 строк]"""
    if not s or " " not in s.strip():
        return False

    # Если это существующий путь целиком — не команда.
    if os.path.exists(s):
        return False

    try:
        tokens = shlex.split(s, posix=False)
    except ValueError:
        return False
    if not tokens:
        return False

    first = tokens[0].lower()
    if first in _CMD_VERBS:
        return True

    # Первый токен — .exe/.msc/.cpl, но такого файла нет — значит команда.
    if first.endswith((".exe", ".msc", ".cpl", ".bat", ".cmd")):
        if not os.path.exists(tokens[0]):
            return True

    return False


def spec_from_string(s: str):
    s = s.strip()
    if s.startswith("open_app:"):
        return ("open_app", s[len("open_app:"):])
    if s.startswith(("http://", "https://")):
        return ("url", s)
    if s.startswith("steam://"):
        return ("uri", s)
    if s.lower() in ("browser", "браузер"):
        return ("browser", None)
    # Команды с аргументами — ДО проверки на .bat/.cmd/path.
    # Иначе "shutdown /s /t 10" провалится в os.startfile.
    if _looks_like_cmd(s):
        try:
            return ("cmd", shlex.split(s, posix=False))
        except ValueError:
            log.exception("shlex.split не справился: %r", s)
            return ("path", s)
    if s.lower().endswith((".bat", ".cmd")):
        return ("path", s)
    if os.path.exists(s):
        return ("path", s)
    return ("path", s)


def run_spec(spec) -> bool:
    if not spec:
        return False
    kind, value = spec
    log.info("Запуск: %s %s", kind, value)
    try:
        if kind == "open_app":
            from jarvis.installed import scan_start_menu, find_installed
            apps = scan_start_menu()
            hit = find_installed(apps, value)
            if hit:
                os.startfile(str(hit[1]))
                _schedule_activation(value, hit[0])
                return True
            log.warning("Приложение '%s' не найдено в меню Пуск", value)
            return False
        if kind == "browser":
            open_browser()
            return True
        if kind == "url":
            open_url(value)
            return True
        if kind == "uri":
            os.startfile(value)
            return True
        if kind == "cmd":
            args = value if isinstance(value, list) else [value]
            subprocess.Popen(args, creationflags=subprocess.CREATE_NO_WINDOW)
            return True
        if kind in ("path", "exe"):
            os.startfile(value)
            return True
    except Exception:
        log.exception("run_spec не удался: %s", spec)
    return False


def _schedule_activation(name: str, app_title: str | None = None) -> None:
    """Через 2 сек после запуска пытается активировать окно приложения."""
    import threading
    targets = [name]
    if app_title and app_title.lower() != name.lower():
        targets.append(app_title)

    def _run():
        time.sleep(2.0)
        try:
            import pygetwindow as gw
            for t in targets:
                t_low = t.lower()
                for w in gw.getAllWindows():
                    if not w.title:
                        continue
                    if t_low in w.title.lower():
                        try:
                            if getattr(w, "isMinimized", False):
                                w.restore()
                                time.sleep(0.1)
                            w.activate()
                            log.info("Активировал окно: %s", w.title)
                        except Exception:
                            pass
                        return
        except Exception:
            log.exception("Не удалось активировать окно %r", name)

    threading.Thread(target=_run, daemon=True, name=f"activate-{name}").start()


def open_path(path, minimized: bool = False) -> bool:
    log.info("Открываю путь: %s (minimized=%s)", path, minimized)
    try:
        if minimized and str(path).lower().endswith(".lnk"):
            subprocess.Popen(["cmd", "/c", "start", "/min", "", str(path)],
                             creationflags=subprocess.CREATE_NO_WINDOW)
            return True
        os.startfile(str(path))
        return True
    except Exception:
        log.exception("open_path не удался: %s", path)
        return False

def _activate_window_hard(title_part: str) -> bool:
    """Активирует окно по части заголовка — надёжно, через win32gui. ... [7 строк]"""
    if not title_part:
        return False
    try:
        import win32gui
        import win32con
        import win32process
        import win32api
    except ImportError:
        log.warning("pywin32 не установлен — активация через win32gui недоступна")
        return False

    target_hwnd = [None]

    def _enum_cb(hwnd, _):
        if target_hwnd[0] is not None:
            return
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd) or ""
        if title_part.lower() in title.lower():
            target_hwnd[0] = hwnd

    win32gui.EnumWindows(_enum_cb, None)

    hwnd = target_hwnd[0]
    if not hwnd:
        log.info("_activate_window_hard: окно %r не найдено", title_part)
        return False

    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

        # Трюк AttachThreadInput
        fg_hwnd = win32gui.GetForegroundWindow()
        fg_thread = win32process.GetWindowThreadProcessId(fg_hwnd)[0]
        target_thread = win32process.GetWindowThreadProcessId(hwnd)[0]
        cur_thread = win32api.GetCurrentThreadId()

        attached_fg = False
        attached_target = False
        try:
            if fg_thread != cur_thread:
                win32process.AttachThreadInput(fg_thread, cur_thread, True)
                attached_fg = True
            if target_thread != cur_thread:
                win32process.AttachThreadInput(target_thread, cur_thread, True)
                attached_target = True

            win32gui.SetForegroundWindow(hwnd)
            win32gui.BringWindowToTop(hwnd)
        finally:
            if attached_fg:
                win32process.AttachThreadInput(fg_thread, cur_thread, False)
            if attached_target:
                win32process.AttachThreadInput(target_thread, cur_thread, False)

        log.info("_activate_window_hard: активировал %r", title_part)
        return True
    except Exception:
        log.exception("_activate_window_hard: не удалось активировать %r", title_part)
        return False

def open_in_editor(path, prefer: str = "auto") -> bool:
    """Открывает файл в редакторе. ... [9 строк]"""
    path = Path(path)
    if not path.exists():
        log.warning("open_in_editor: файла нет: %s", path)
        return False

    # Порядок редакторов для auto
    editors = []

    if prefer == "notepad++":
        editors = [_find_notepadpp]
    elif prefer == "vscode":
        editors = [_find_vscode]
    elif prefer == "system":
        editors = []
    else:  # auto
        editors = [_find_notepadpp, _find_vscode]

    for finder in editors:
        exe = finder()
        if exe:
            try:
                subprocess.Popen([exe, str(path)],
                                 creationflags=subprocess.CREATE_NO_WINDOW)
                log.info("open_in_editor: %s → %s", path, exe)

                # Активируем окно редактора через 0.5 сек —
                # иначе Notepad++ открывается за другими окнами.
                import threading
                editor_name = Path(exe).stem.lower()

                def _activate():
                    time.sleep(0.6)
                    # Ищем окно по имени редактора
                    if "notepad" in editor_name:
                        _activate_window_hard("notepad++")
                    elif "code" in editor_name:
                        _activate_window_hard("visual studio code")

                threading.Thread(target=_activate, daemon=True,
                                 name="editor-activate").start()
                return True
            except Exception:
                log.exception("open_in_editor: не удалось запустить %s", exe)
                continue

    # Fallback: системный редактор
    try:
        os.startfile(str(path))
        log.info("open_in_editor: %s → системный редактор", path)
        return True
    except Exception:
        log.exception("open_in_editor: не удалось открыть %s", path)
        return False


def _find_notepadpp() -> str | None:
    """Ищет notepad++.exe в типичных местах."""
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Notepad++" / "notepad++.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Notepad++" / "notepad++.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Notepad++" / "notepad++.exe",
    ]
    for c in candidates:
        if c and c.exists():
            return str(c)
    # В PATH?
    exe = shutil.which("notepad++") or shutil.which("notepad++.exe")
    return exe


def _find_vscode() -> str | None:
    """Ищет code.exe (VS Code) в типичных местах."""
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft VS Code" / "Code.exe",
    ]
    for c in candidates:
        if c and c.exists():
            return str(c)
    exe = shutil.which("code") or shutil.which("code.exe")
    return exe

def open_url(url: str) -> bool:
    log.info("Открываю URL: %s", url)
    try:
        os.startfile(url)
        return True
    except Exception:
        log.exception("open_url не удался: %s", url)
        return False


def open_browser() -> bool:
    log.info("Открываю браузер")
    try:
        os.startfile("https://www.google.com")
        return True
    except Exception:
        log.exception("open_browser не удался")
        return False


# --- поиск и сайты ---------------------------------------------------------

def open_search(engine: str, query: str) -> bool:
    log.info("Поиск: %s, запрос=%r", engine, query)
    q = urllib.parse.quote(query)
    if engine == "youtube":
        url = f"https://www.youtube.com/results?search_query={q}"
    elif engine == "wiki":
        url = f"https://ru.wikipedia.org/w/index.php?search={q}"
    else:
        url = f"https://www.google.com/search?q={q}"
    return open_url(url)


def google_search(query: str) -> bool:
    return open_search("google", query)


def open_site_lucky(name: str) -> bool:
    q = urllib.parse.quote(name)
    return open_url(f"https://duckduckgo.com/?q=!ducky+{q}")


def spoken_domain(name: str):
    text = name.lower().replace("точка", ".").replace(" точка ", ".").strip()
    text = re.sub(r"\s+", "", text)
    if "." in text and " " not in text:
        return "https://" + text
    return None


def guess_site(name: str):
    """Отгадывает домен по ОДНОМУ слову: «ок» → https://ok.ru. ... [6 строк]"""
    if not name or len(name.split()) > 1:
        return None
    slug = re.sub(r"[^a-z0-9]", "", name.lower())
    if not slug:
        return None
    return f"https://{slug}.ru"


def normalize_url(raw: str) -> str:
    """Приводит сырой домен из intent к валидному URL. ... [4 строк]"""
    text = raw.strip().lower().rstrip("/")
    text = re.sub(r"\s+", "", text)
    if text.startswith(("http://", "https://")):
        return text
    return "https://" + text


# --- скриншоты -------------------------------------------------------------

def take_screenshot():
    try:
        from PIL import ImageGrab
        folder = _paths.user_home() / "Pictures" / "Screenshots"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"screenshot_{time.strftime('%Y-%m-%d_%H-%M-%S')}.png"
        img = ImageGrab.grab()
        img.save(path)
        log.info("Скриншот: %s", path)
        return path
    except Exception:
        log.exception("take_screenshot не удался")
        raise


# --- медиа -----------------------------------------------------------------

def media_key(key: str, times: int = 1) -> bool:
    log.info("Медиа-клавиша: %s x%d", key, times)
    try:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Manager,
        )
    except ImportError:
        log.warning("WinRT Media Control недоступен")
        return False
    try:
        import asyncio

        async def _press():
            mgr = await Manager.request_async()
            session = mgr.get_current_session()
            if not session:
                return False
            for _ in range(max(1, times)):
                if key == "play":
                    await session.try_toggle_play_pause_async()
                elif key == "next":
                    await session.try_skip_next_async()
                elif key == "prev":
                    await session.try_skip_previous_async()
                elif key == "vol_up":
                    _volume_up()
                elif key == "vol_down":
                    _volume_down()
                elif key == "mute":
                    _volume_mute()
                time.sleep(0.05)
            return True

        return asyncio.run(_press())
    except Exception:
        log.exception("media_key не удался: %s", key)
        return False


def _volume_up():
    import ctypes
    for _ in range(2):
        ctypes.windll.user32.keybd_event(0xAF, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0xAF, 0, 2, 0)


def _volume_down():
    import ctypes
    for _ in range(2):
        ctypes.windll.user32.keybd_event(0xAE, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0xAE, 0, 2, 0)


def _volume_mute():
    import ctypes
    ctypes.windll.user32.keybd_event(0xAD, 0, 0, 0)
    ctypes.windll.user32.keybd_event(0xAD, 0, 2, 0)


def ensure_music_playing() -> bool:
    return media_key("play")


# --- примитивы для сценариев (К2) -----------------------------------------

def key_press(key: str) -> bool:
    """Нажимает одну клавишу. ... [6 строк]"""
    if not key:
        return False
    log.info("key_press: %s", key)
    try:
        import pyautogui
        pyautogui.press(key)
        return True
    except Exception:
        log.exception("key_press не удался: %s", key)
        return False


def hotkey(keys) -> bool:
    """Нажимает сочетание клавиш одновременно. ... [6 строк]"""
    if not keys:
        return False
    if isinstance(keys, str):
        keys = [k.strip() for k in keys.replace("+", " ").split() if k.strip()]
    if not keys:
        return False
    log.info("hotkey: %s", keys)
    try:
        import pyautogui
        pyautogui.hotkey(*keys)
        return True
    except Exception:
        log.exception("hotkey не удался: %s", keys)
        return False


def scroll(direction: str, amount: int = 3) -> bool:
    """Листает вверх или вниз. ... [5 строк]"""
    if direction not in ("up", "down"):
        log.warning("scroll: неизвестное направление %r", direction)
        return False
    log.info("scroll: %s x%d", direction, amount)
    try:
        import pyautogui
        clicks = amount if direction == "up" else -amount
        pyautogui.scroll(clicks)
        return True
    except Exception:
        log.exception("scroll не удался: %s", direction)
        return False


def click_at(x: int, y: int, button: str = "left") -> bool:
    """Кликает в координаты на экране. ... [5 строк]"""
    log.info("click_at: (%d, %d) %s", x, y, button)
    try:
        import pyautogui
        pyautogui.click(x, y, button=button)
        return True
    except Exception:
        log.exception("click_at не удался: (%d, %d)", x, y)
        return False


# --- раскладка клавиатуры --------------------------------------------------

def switch_layout() -> bool:
    """Переключает раскладку через Alt+Shift (SendInput)."""
    log.info("Переключаю раскладку (Alt+Shift)")
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class INPUT(ctypes.Structure):
            _fields_ = [
                ("type", wintypes.DWORD),
                ("ki", KEYBDINPUT),
                ("padding", ctypes.c_ubyte * 8),
            ]

        VK_MENU = 0x12
        VK_SHIFT = 0x10
        KEYEVENTF_KEYUP = 0x0002
        INPUT_KEYBOARD = 1

        def _key(vk, up=False):
            inp = INPUT()
            inp.type = INPUT_KEYBOARD
            inp.ki.wVk = vk
            inp.ki.wScan = 0
            inp.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
            inp.ki.time = 0
            inp.ki.dwExtraInfo = None
            user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

        _key(VK_MENU)
        import time as _t
        _t.sleep(0.05)
        _key(VK_SHIFT)
        _t.sleep(0.05)
        _key(VK_SHIFT, up=True)
        _t.sleep(0.05)
        _key(VK_MENU, up=True)
        return True
    except Exception:
        log.exception("switch_layout не удался")
        return False


def _set_layout_hkl(hkl_hex: str) -> bool:
    """Устанавливает раскладку по HKL через PostMessage с фокусом."""
    log.info("Установка раскладки: %s", hkl_hex)
    try:
        import ctypes
        user32 = ctypes.windll.user32

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            log.warning("Нет foreground-окна")
            return False

        user32.SetForegroundWindow(hwnd)
        hkl = user32.LoadKeyboardLayoutW(hkl_hex, 1)
        user32.PostMessageW(hwnd, 0x50, 0, hkl)
        return True
    except Exception:
        log.exception("_set_layout_hkl не удался: %s", hkl_hex)
        return False


def set_layout_ru() -> bool:
    """Переключает на русскую раскладку."""
    return _set_layout_hkl("00000419")


def set_layout_en() -> bool:
    """Переключает на английскую раскладку."""
    return _set_layout_hkl("00000409")


def get_layout() -> str | None:
    """Возвращает 'ru', 'en' или None."""
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        thread_id = ctypes.windll.user32.GetWindowThreadProcessId(hwnd, None)
        hkl = ctypes.windll.user32.GetKeyboardLayout(thread_id)
        lang_id = hkl & 0xFFFF
        return {0x0419: "ru", 0x0409: "en"}.get(lang_id)
    except Exception:
        log.exception("get_layout не удался")
        return None


# --- громкость -------------------------------------------------------------

def get_volume() -> int | None:
    """Возвращает громкость в процентах (0..100)."""
    if not _caps_available("volume"):
        log.warning("Громкость недоступна (см. system_caps.json)")
        return None

    method = _caps_method("volume")
    try:
        from pycaw.pycaw import AudioUtilities
        device = AudioUtilities.GetSpeakers()

        if method == "volume_percent":
            return int(device.volume_percent)
        if method == "endpoint_volume":
            return round(device.EndpointVolume.GetMasterVolumeLevelScalar() * 100)
        if method == "activate":
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import IAudioEndpointVolume
            interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            vol = cast(interface, POINTER(IAudioEndpointVolume))
            return round(vol.GetMasterVolumeLevelScalar() * 100)
    except Exception:
        log.exception("get_volume не удался (method=%s)", method)
    return None


def set_volume(percent: int) -> bool:
    """Ставит громкость в процентах (0..100)."""
    if not _caps_available("volume"):
        log.warning("Громкость недоступна (см. system_caps.json)")
        return False

    percent = max(0, min(100, int(percent)))
    log.info("Громкость: %d%% (method=%s)", percent, _caps_method("volume"))

    method = _caps_method("volume")
    try:
        from pycaw.pycaw import AudioUtilities
        device = AudioUtilities.GetSpeakers()

        if method == "volume_percent":
            device.volume_percent = percent
            return True
        if method == "endpoint_volume":
            device.EndpointVolume.SetMasterVolumeLevelScalar(percent / 100.0, None)
            return True
        if method == "activate":
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import IAudioEndpointVolume
            interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            vol = cast(interface, POINTER(IAudioEndpointVolume))
            vol.SetMasterVolumeLevelScalar(percent / 100.0, None)
            return True
    except Exception:
        log.exception("set_volume не удался (method=%s)", method)
    return False


# --- яркость ---------------------------------------------------------------

def get_brightness() -> int | None:
    """Возвращает яркость в процентах (0..100)."""
    if not _caps_available("brightness"):
        log.warning("Яркость недоступна (см. system_caps.json)")
        return None
    try:
        import screen_brightness_control as sbc
        values = sbc.get_brightness()
        if values:
            return int(values[0])
        return None
    except Exception:
        log.exception("get_brightness не удался")
        return None


def set_brightness(percent: int) -> bool:
    """Ставит яркость в процентах (0..100)."""
    if not _caps_available("brightness"):
        log.warning("Яркость недоступна (см. system_caps.json)")
        return False
    percent = max(0, min(100, int(percent)))
    log.info("Яркость: %d%%", percent)
    try:
        import screen_brightness_control as sbc
        sbc.set_brightness(percent)
        return True
    except Exception:
        log.exception("set_brightness не удался")
        return False


# --- процессы --------------------------------------------------------------

def find_process(name: str, threshold: float = 0.7):
    """Находит имя процесса по неточному имени."""
    try:
        import psutil
    except ImportError:
        return None
    from jarvis.matching import match_score
    name_low = name.lower()
    best_name, best_score = None, 0.0
    for proc in psutil.process_iter(["name"]):
        pname = (proc.info.get("name") or "").lower()
        if not pname:
            continue
        base = pname.removesuffix(".exe")
        if name_low in base or base in name_low:
            return proc.info["name"]
        score = match_score(name_low, base)
        if score > best_score:
            best_name, best_score = proc.info["name"], score
    if best_name and best_score >= threshold:
        log.info("Процесс %r -> %s (score %.2f)", name, best_name, best_score)
        return best_name
    log.info("Процесс для %r не найден (лучший score %.2f)", name, best_score)
    return None


def kill_process(name: str) -> bool:
    protected = {"system", "svchost.exe", "csrss.exe", "wininit.exe",
                 "services.exe", "lsass.exe", "explorer.exe"}
    if name.lower() in protected:
        log.warning("Запрещено убивать защищённый процесс: %s", name)
        return False
    log.info("Убиваю процесс: %s", name)
    try:
        import psutil
        killed = False
        for proc in psutil.process_iter(["name"]):
            if (proc.info.get("name") or "").lower() == name.lower():
                proc.kill()
                killed = True
        return killed
    except Exception:
        log.exception("kill_process не удался: %s", name)
        return False


def close_browser() -> bool:
    """Закрывает ВСЕ известные браузеры. ... [5 строк]"""
    any_killed = False
    for name in ("chrome.exe", "firefox.exe", "msedge.exe",
                 "opera.exe", "brave.exe", "yandex.exe"):
        base = name.removesuffix(".exe")
        if find_process(base) and kill_process(name):
            any_killed = True
    if any_killed:
        log.info("close_browser: закрыл все найденные браузеры")
    return any_killed


def minimize_window(name: str) -> bool:
    return minimize_window_by_title(name)


# --- печать и окна ---------------------------------------------------------

def type_text(text: str) -> bool:
    if not text:
        return False
    log.info("Печатаю: %r", text)
    try:
        import pyautogui
        try:
            import pyperclip
            old = pyperclip.paste()
            pyperclip.copy(text)
            time.sleep(0.05)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.15)
            pyperclip.copy(old)
            return True
        except Exception:
            log.debug("pyperclip не сработал, пробую pyautogui.typewrite")
        pyautogui.typewrite(text, interval=0.02)
        return True
    except Exception:
        log.exception("type_text не удался")
        return False


def minimize_all() -> bool:
    try:
        import pygetwindow as gw
        count = 0
        for w in gw.getAllWindows():
            try:
                if w.title and w.visible and not w.isMinimized:
                    w.minimize()
                    count += 1
            except Exception:
                pass
        log.info("Свёрнуто окон: %d", count)
        return True
    except Exception:
        try:
            import pyautogui
            pyautogui.hotkey("win", "d")
            return True
        except Exception:
            log.exception("minimize_all не удался")
            return False


_WINDOW_SYNONYMS = {
    "консоль": ["cmd.exe", "powershell", "command prompt", "c:\\users\\", "c:\\windows\\", "c:\\jarvis"],
    "терминал": ["cmd.exe", "powershell", "command prompt", "c:\\users\\", "c:\\windows\\", "c:\\jarvis"],
    "командную строку": ["cmd.exe", "command prompt", "c:\\users\\", "c:\\windows\\"],
    "командная строка": ["cmd.exe", "command prompt", "c:\\users\\", "c:\\windows\\"],
    "cmd": ["cmd.exe", "command prompt", "c:\\users\\", "c:\\windows\\"],
    "браузер": ["chrome", "firefox", "яндекс", "yandex", "edge", "opera", "brave"],
    "хром": ["chrome"],
    "яндекс браузер": ["яндекс", "yandex"],
    "firefox": ["firefox"],
    "файрфокс": ["firefox"],
    "edge": ["edge"],
    "эдж": ["edge"],
    "телега": ["telegram"],
    "телеграм": ["telegram"],
    "тг": ["telegram"],
    "дискорд": ["discord"],
    "дс": ["discord"],
    "стим": ["steam"],
    "steam": ["steam"],
    "проводник": ["проводник", "explorer"],
    "explorer": ["проводник", "explorer"],
    "папку": ["проводник", "explorer"],
    "настройки": ["настройки", "settings", "параметры"],
    "параметры": ["параметры", "settings", "настройки"],
    "оллама": ["ollama"],
    "ollama": ["ollama"],
    "радмин": ["radmin"],
    "radmin": ["radmin"],
    "овервульф": ["overwolf"],
    "overwolf": ["overwolf"],
}


def _find_window(name: str):
    try:
        import pygetwindow as gw
    except ImportError:
        return None

    windows = [w for w in gw.getAllWindows() if w.title]
    name_low = name.lower().strip()

    for noise in (" музыка", " browser", " браузер"):
        if name_low.endswith(noise):
            name_low = name_low[: -len(noise)].strip()

    direct = [w for w in windows if name_low in w.title.lower()]
    if direct:
        for w in direct:
            try:
                if w.visible and not w.isMinimized:
                    return w
            except Exception:
                pass
        return direct[0]

    subs = None
    for key, values in _WINDOW_SYNONYMS.items():
        if key == name_low or key in name_low or name_low in key:
            subs = values
            break
    if subs:
        for sub in subs:
            sub_low = sub.lower()
            for w in windows:
                if sub_low in w.title.lower():
                    try:
                        if w.visible and not w.isMinimized:
                            return w
                    except Exception:
                        pass
        for sub in subs:
            sub_low = sub.lower()
            for w in windows:
                if sub_low in w.title.lower():
                    return w

    from jarvis.matching import match_score
    best = None
    best_score = 0.6
    for w in windows:
        title = w.title.lower()
        score = match_score(name_low, title[:40])
        if score > best_score:
            best_score, best = score, w
    if best:
        log.info("Окно %r -> %s (score %.2f)", name, best.title, best_score)
    return best


def minimize_window_by_title(name: str) -> bool:
    w = _find_window(name)
    if not w:
        log.warning("Окно не найдено для сворачивания: %s", name)
        return False
    try:
        w.minimize()
        log.info("Свернул окно: %s", w.title)
        return True
    except Exception:
        log.exception("minimize_window_by_title не удался")
        return False


def maximize_window_by_title(name: str) -> bool:
    w = _find_window(name)
    if not w:
        log.warning("Окно не найдено для разворачивания: %s", name)
        return False
    try:
        if getattr(w, "isMinimized", False):
            w.restore()
            time.sleep(0.15)
        w.maximize()
        try:
            w.activate()
        except Exception:
            pass
        log.info("Развернул окно: %s", w.title)
        return True
    except Exception:
        log.exception("maximize_window_by_title не удался")
        return False


def activate_window_by_title(name: str) -> bool:
    w = _find_window(name)
    if not w:
        log.warning("Окно не найдено для активации: %s", name)
        return False
    try:
        if getattr(w, "isMinimized", False):
            w.restore()
            time.sleep(0.15)
        w.activate()
        log.info("Активировал окно: %s", w.title)
        return True
    except Exception:
        log.exception("activate_window_by_title не удался")
        return False


def minimize_active() -> bool:
    try:
        import pyautogui
        pyautogui.hotkey("win", "down")
        log.info("Свернул активное окно")
        return True
    except Exception:
        log.exception("minimize_active не удался")
        return False


def maximize_active() -> bool:
    try:
        import pyautogui
        pyautogui.hotkey("win", "up")
        log.info("Развернул активное окно")
        return True
    except Exception:
        log.exception("maximize_active не удался")
        return False


def switch_window(back: bool = False) -> bool:
    try:
        import pyautogui
        if back:
            pyautogui.hotkey("alt", "shift", "tab")
            log.info("Переключил окно назад")
        else:
            pyautogui.hotkey("alt", "tab")
            log.info("Переключил окно")
        return True
    except Exception:
        log.exception("switch_window не удался")
        return False


# --- буфер обмена -----------------------------------------------------------

def copy_selection() -> bool:
    """Нажимает Ctrl+C, чтобы скопировать выделенное в активном окне."""
    log.info("Копирую выделенное (Ctrl+C)")
    try:
        import pyautogui
        pyautogui.hotkey("ctrl", "c")
        return True
    except Exception:
        log.exception("copy_selection не удался")
        return False


def clipboard_read() -> str:
    log.info("Читаю буфер обмена")
    try:
        import pyperclip
        text = pyperclip.paste() or ""
        log.info("Буфер обмена: %r", text[:80])
        return text
    except Exception:
        log.exception("clipboard_read не удался")
        return ""


def clipboard_write(text: str) -> bool:
    log.info("Пишу в буфер обмена: %r", text[:80])
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception:
        log.exception("clipboard_write не удался")
        return False


def clipboard_clear() -> bool:
    log.info("Очищаю буфер обмена")
    return clipboard_write("")
```

### `jarvis/apps.py`

```python
"""Каталог известных приложений: как их зовут голосом, как открыть и как закрыть."""

import logging
import os
import winreg
from dataclasses import dataclass, field
from pathlib import Path

from jarvis.matching import match_score

log = logging.getLogger("jarvis.apps")


@dataclass
class App:
    key: str
    title: str          # как назвать в ответе («Открываю Дискорд»)
    aliases: list       # как пользователь может назвать приложение
    open_specs: list    # кандидаты ("uri"|"exe"|"cmd", значение) — берётся первый рабочий
    procs: list = field(default_factory=list)  # имена процессов для «закрой»

    def resolve_open(self):
        for kind, value in self.open_specs:
            if kind == "exe":
                if Path(value).exists():
                    return ("exe", value)
            else:
                return (kind, value)
        return None


def _steam_exe() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            return winreg.QueryValueEx(k, "SteamExe")[0]
    except OSError:
        return None


def _expand(p: str) -> str:
    return os.path.expandvars(p)


def build_apps(config: dict) -> list[App]:
    steam = _steam_exe() or r"C:\Program Files (x86)\Steam\steam.exe"
    discord_updater = _expand(r"%LOCALAPPDATA%\Discord\Update.exe")

    apps = [
        App(
            "discord", "Дискорд",
            ["дискорд", "дис", "дс", "дэ эс", "discord"],
            [("cmd", [discord_updater, "--processStart", "Discord.exe"])],
            ["Discord.exe"],
        ),
        App(
            "telegram", "Телеграм",
            ["телеграм", "телеграмм", "телега", "тг", "тэ гэ", "telegram"],
            [("exe", _expand(r"%APPDATA%\Telegram Desktop\Telegram.exe"))],
            ["Telegram.exe"],
        ),
        App(
            "steam", "Стим",
            ["стим", "steam"],
            [("exe", steam)],
            ["steam.exe"],
        ),
        App(
            "dota2", "Дота два",
            ["дота", "дота два", "доту", "дотан", "dota"],
            [("uri", "steam://rungameid/570")],
            ["dota2.exe"],
        ),
        App(
            "claude", "Клод Десктоп",
            ["клод", "клауд", "клод десктоп", "клауд десктоп", "claude"],
            [("exe", _expand(r"%LOCALAPPDATA%\AnthropicClaude\claude.exe"))],
            ["claude.exe"],
        ),
        App(
            "vscode", "Вэ Эс Код",
            ["вс код", "вэ эс код", "в эс код", "вес код", "vs code", "vscode", "вс-код"],
            [("exe", _expand(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"))],
            ["Code.exe"],
        ),
        App("calc", "Калькулятор", ["калькулятор"], [("uri", "calc:")], ["CalculatorApp.exe", "Calculator.exe"]),
        App("notepad", "Блокнот", ["блокнот"], [("cmd", ["notepad.exe"])], ["notepad.exe", "Notepad.exe"]),
        App("explorer", "Проводник", ["проводник", "папку", "файлы"], [("cmd", ["explorer.exe"])]),
        App("paint", "Пэйнт", ["пэйнт", "паинт", "пейнт", "рисовалку"], [("cmd", ["mspaint.exe"])], ["mspaint.exe"]),
        App("taskmgr", "Диспетчер задач", ["диспетчер задач", "диспетчер"], [("cmd", ["taskmgr.exe"])], ["Taskmgr.exe"]),
    ]

    # Переопределение путей из config.json: "app_paths": {"discord": "C:\\...\\Discord.exe"}
    overrides = config.get("app_paths") or {}
    for app in apps:
        if app.key in overrides:
            app.open_specs = [("exe", _expand(overrides[app.key]))]
    return apps


def find_app(apps: list[App], target: str) -> App | None:
    """Лучшее совпадение цели с псевдонимами приложений (точное/вхождение/нечёткое)."""
    best, best_score = None, 0.0
    for app in apps:
        for alias in app.aliases:
            if target == alias:
                return app
            score = match_score(target, alias)
            if score > best_score:
                best, best_score = app, score
    if best_score >= 0.75:
        log.info("Цель %r -> %s (score %.2f)", target, best.key, best_score)
        return best
    log.info("Цель %r не сопоставлена (лучший score %.2f)", target, best_score)
    return None
```

### `jarvis/brain.py`

```python
"""LLM-фолбэк: локальная нейронка (Ollama) разбирает команду в структурный интент. ... [9 строк]"""

import json
import logging
import subprocess
import threading
import time
import urllib.request

from jarvis import learning
from jarvis.text_utils import strip_cjk, strip_cjk_chunk

log = logging.getLogger("jarvis.brain")


# =================================================================
# Промпт: SMALL — для 0.5b, 1.5b, 3b, gemma2:2b
# =================================================================

SYSTEM_SMALL = """Ты — Феникс, локальный голосовой ассистент на Windows. Отвечай ТОЛЬКО JSON.

Поля: action; target; query; engine; reply; text; mode; name; voice; percent; seconds; time; task; folder; day; minimized; key; value.

=== ДЕЙСТВИЯ ===
open_app (открыть приложение/игру; target; minimized=true)
close_app (закрыть; target)
open_site (открыть сайт; target)
search (поиск; query; engine: google|youtube|wiki)
screenshot
open_file
open_folder (target)
list_folder (target)
create_file (target; folder)
type_text (text)
media_key (key)
play_pause
next_track
prev_track
volume_up
volume_down
mute
set_volume (percent 0-100)
get_volume
set_brightness (percent 0-100)
get_brightness
switch_layout
set_layout_ru
set_layout_en
get_layout
minimize_all
minimize_window (target)
maximize_window (target)
activate_window (target)
minimize_active
maximize_active
switch_window
set_mode (mode: commands|llm|combo)
load_pack (name: games|apps|sites|work|system)
unload_pack (name)
list_packs
change_voice (voice: ruslan|dmitri|irina|denis)
list_voices
set_timer (text; seconds ИЛИ time)
list_timers
cancel_timers
add_task (text)
list_tasks
done_task (task)
remove_task (task)
clear_tasks
open_config
open_log
open_profile (открыть profile.json в редакторе)
get_weather (target — город; day: today|tomorrow)
get_currency (target — ISO: USD|EUR|CNY|BYN|KZT|GBP|JPY|TRY|UAH)
uia_read_window (прочитать текст активного окна)
uia_read_url (URL активной вкладки)
uia_read_tab (заголовок активной вкладки)
uia_list_tabs (список вкладок браузера)
uia_close_tab (target — часть заголовка вкладки)
uia_switch_tab (target — часть заголовка вкладки)
uia_click_button (target — часть имени кнопки)
uia_active_window (описать активное окно)
uia_menu (target — путь меню, например «Файл > Сохранить»)
set_profile (key: name|default_city, value — сохранить в профиль)
get_profile (key: name|default_city — прочитать из профиля)
answer (reply)
none

=== ГЛАВНОЕ ПРАВИЛО ===
«Закрой», «выключи», «убей», «останови» → ВСЕГДА close_app.
«Открой», «запусти», «врубай» → ВСЕГДА open_app (или open_site/open_folder).
Не путай.

=== ПРИМЕРЫ ===
открой стим -> {"action":"open_app","target":"стим"}
закрой стим -> {"action":"close_app","target":"стим"}
открой дискорд -> {"action":"open_app","target":"дискорд"}
закрой дискорд -> {"action":"close_app","target":"дискорд"}
открой телеграм -> {"action":"open_app","target":"телеграм"}
закрой телегу -> {"action":"close_app","target":"телеграм"}
открой хром -> {"action":"open_app","target":"хром"}
закрой браузер -> {"action":"close_app","target":"браузер"}
запусти сабнатику -> {"action":"open_app","target":"сабнатика"}
запусти доту -> {"action":"open_app","target":"дота"}
врубай катку -> {"action":"open_app","target":"дота"}
открой ютуб -> {"action":"open_site","target":"ютуб"}
открой яндекс -> {"action":"open_site","target":"яндекс"}
верни яндекс -> {"action":"open_site","target":"яндекс"}
найди погоду -> {"action":"search","engine":"google","query":"погода сегодня"}
загугли новости -> {"action":"search","engine":"google","query":"новости"}
поищи на ютубе лофи -> {"action":"search","engine":"youtube","query":"лофи"}
найди в википедии фотосинтез -> {"action":"search","engine":"wiki","query":"фотосинтез"}
открой загрузки -> {"action":"open_folder","target":"загрузки"}
что на рабочем столе -> {"action":"list_folder","target":"рабочий стол"}
создай файл список покупок -> {"action":"create_file","target":"список покупок"}
напечатай привет мир -> {"action":"type_text","text":"привет мир"}
сделай скриншот -> {"action":"screenshot"}
сверни все окна -> {"action":"minimize_all"}
сверни дискорд -> {"action":"minimize_window","target":"дискорд"}
разверни консоль -> {"action":"maximize_window","target":"консоль"}
переключись на дискорд -> {"action":"activate_window","target":"дискорд"}
сверни это -> {"action":"minimize_active"}
разверни текущее -> {"action":"maximize_active"}
переключи окно -> {"action":"switch_window"}
пауза -> {"action":"play_pause"}
следующий трек -> {"action":"next_track"}
сделай громче -> {"action":"volume_up"}
тише -> {"action":"volume_down"}
без звука -> {"action":"mute"}
громкость 50 -> {"action":"set_volume","percent":50}
какая громкость -> {"action":"get_volume"}
яркость 30 -> {"action":"set_brightness","percent":30}
какая яркость -> {"action":"get_brightness"}
переключи раскладку -> {"action":"switch_layout"}
русская раскладка -> {"action":"set_layout_ru"}
английская раскладка -> {"action":"set_layout_en"}
какая раскладка -> {"action":"get_layout"}
режим ии -> {"action":"set_mode","mode":"llm"}
обычный режим -> {"action":"set_mode","mode":"combo"}
режим команды -> {"action":"set_mode","mode":"commands"}
загрузи пак игр -> {"action":"load_pack","name":"games"}
выгрузи пак игр -> {"action":"unload_pack","name":"games"}
какие паки -> {"action":"list_packs"}
смени голос на ирину -> {"action":"change_voice","voice":"irina"}
какой голос -> {"action":"list_voices"}
напомни через 10 минут выпить чай -> {"action":"set_timer","text":"выпить чай","seconds":600}
напомни в 18:30 позвонить -> {"action":"set_timer","text":"позвонить","time":"18:30"}
какие напоминания -> {"action":"list_timers"}
отмени напоминания -> {"action":"cancel_timers"}
добавь в список купить хлеб -> {"action":"add_task","text":"купить хлеб"}
что в списке -> {"action":"list_tasks"}
отметь хлеб -> {"action":"done_task","task":"хлеб"}
убери хлеб -> {"action":"remove_task","task":"хлеб"}
очисти список -> {"action":"clear_tasks"}
открой конфиг -> {"action":"open_config"}
открой журнал -> {"action":"open_log"}
открой профиль -> {"action":"open_profile"}
открой профиль в вс код -> {"action":"open_profile","editor":"vscode"}
какая погода -> {"action":"get_weather","day":"today"}
какая погода в москве -> {"action":"get_weather","target":"Москва","day":"today"}
погода в питере на завтра -> {"action":"get_weather","target":"Санкт-Петербург","day":"tomorrow"}
курс доллара -> {"action":"get_currency","target":"USD"}
курс евро -> {"action":"get_currency","target":"EUR"}
курс валют -> {"action":"get_currency"}
меня зовут Максим -> {"action":"set_profile","key":"name","value":"Максим"}
мой город Казань -> {"action":"set_profile","key":"default_city","value":"Казань"}
как меня зовут -> {"action":"get_profile","key":"name"}
какой город -> {"action":"get_profile","key":"default_city"}
прочитай окно -> {"action":"uia_read_window"}
что написано в блокноте -> {"action":"uia_read_window"}
какой сайт открыт -> {"action":"uia_read_url"}
какая вкладка -> {"action":"uia_read_tab"}
какие вкладки -> {"action":"uia_list_tabs"}
закрой вкладку ютуб -> {"action":"uia_close_tab","target":"ютуб"}
переключись на вкладку хабр -> {"action":"uia_switch_tab","target":"хабр"}
нажми кнопку ок -> {"action":"uia_click_button","target":"ок"}
нажми сохранить -> {"action":"uia_click_button","target":"сохранить"}
что открыто -> {"action":"uia_active_window"}
включи музыку -> {"steps":[{"action":"open_app","target":"яндекс музыка","minimized":true},{"action":"wait","seconds":6},{"action":"media_key","key":"play"}]}
расскажи шутку -> {"action":"answer","reply":"Почему медведь не ездит на машине? Потому что нет прав."}
как дела -> {"action":"answer","reply":"Отлично, сэр. Готов к работе."}

=== ЗАПРЕТЫ ===
НИКОГДА не путай open_app и close_app.
НИКОГДА не путай get_weather и get_currency.
Если пользователь не назвал город для погоды — не указывай target.
Если не назвал валюту — не указывай target.
НИКОГДА не используй search, если не сказано «найди», «поищи», «загугли».
По умолчанию отвечай через answer — даже на факты.

set_profile ИСПОЛЬЗУЙ ТОЛЬКО ДЛЯ:
    «меня зовут X» → {"action":"set_profile","key":"name","value":"X"}
    «мой город X» / «поменяй город на X» → {"action":"set_profile","key":"default_city","value":"X"}

НЕ ИСПОЛЬЗУЙ set_profile ДЛЯ:
    «верни яндекс» → open_site target яндекс
    «открой ютуб» → open_site target ютуб
    «включи музыку» → open_app target яндекс музыка

Если фраза начинается с «верни», «открой», «запусти» — это open_app или open_site, НЕ set_profile.

=== СТИЛЬ ДИАЛОГА (chat_stream) ===
Ты — Феникс. Спокойный, вежливый, с сухим юмором, обращаешься «сэр».
Отвечай в 2–5 предложениях. Без списков, без markdown, без эмодзи.
ОТВЕЧАЙ ТОЛЬКО НА РУССКОМ."""


# =================================================================
# Промпт: MEDIUM — для 7b, gemma2:9b
# =================================================================

SYSTEM_MEDIUM = """Ты — Феникс, локальный голосовой ассистент на Windows. Отвечай ТОЛЬКО JSON.

Поля: action; target; query; engine; reply; text; mode; name; voice; percent; seconds; time; task; folder; day; minimized; key; value.

=== ДЕЙСТВИЯ ===
open_app (target; minimized=true)
close_app (target)
open_site (target)
search (query; engine: google|youtube|wiki)
screenshot
open_file
open_folder (target)
list_folder (target)
create_file (target; folder)
type_text (text)
media_key (key)
play_pause / next_track / prev_track
volume_up / volume_down / mute
set_volume (percent) / get_volume
set_brightness (percent) / get_brightness
switch_layout / set_layout_ru / set_layout_en / get_layout
minimize_all / minimize_window / maximize_window / activate_window
minimize_active / maximize_active / switch_window
set_mode (mode: commands|llm|combo)
load_pack / unload_pack / list_packs (name: games|apps|sites|work|system)
change_voice / list_voices (voice: ruslan|dmitri|irina|denis)
set_timer (text; seconds|time) / list_timers / cancel_timers
add_task (text) / list_tasks / done_task (task) / remove_task (task) / clear_tasks
open_config / open_log / open_profile
get_weather (target; day) / get_currency (target)
uia_read_window / uia_read_url / uia_read_tab / uia_list_tabs
uia_close_tab (target) / uia_switch_tab (target)
uia_click_button (target) / uia_active_window / uia_menu (target)
set_profile (key: name|default_city, value) / get_profile (key: name|default_city)
answer (reply)
none

=== ГЛАВНОЕ ===
«Закрой», «выключи», «убей» → close_app.
«Открой», «запусти», «врубай» → open_app / open_site / open_folder.

=== ПРИМЕРЫ ===
открой стим -> open_app target стим
закрой стим -> close_app target стим
открой ютуб -> open_site target ютуб
открой профиль -> open_profile
какая погода в москве -> get_weather target Москва
курс доллара -> get_currency target USD
громкость 50 -> set_volume percent 50
смени голос на ирину -> change_voice voice irina
меня зовут Максим -> set_profile key=name value=Максим
какой город -> get_profile key=default_city
прочитай окно -> uia_read_window
какой сайт открыт -> uia_read_url
какая вкладка -> uia_read_tab
какие вкладки -> uia_list_tabs
закрой вкладку ютуб -> uia_close_tab target=ютуб
переключись на вкладку хабр -> uia_switch_tab target=хабр
нажми кнопку ок -> uia_click_button target=ок
что открыто -> uia_active_window

=== ПРАВИЛА ===
Не путай погоду и курс.
Не используй search без «найди», «поищи», «загугли».
По умолчанию — answer.
set_profile — только для «меня зовут X» и «мой город X». НЕ для «верни яндекс» / «открой ютуб».

=== ДИАЛОГ ===
Ты — Феникс. Спокойный, вежливый, с сухим юмором, «сэр».
2–5 предложений. Без markdown. Только русский."""


# =================================================================
# Промпт: LARGE — для 14b+
# =================================================================

SYSTEM_LARGE = """Ты — Феникс, локальный голосовой ассистент на Windows.
Разбирай команды в JSON. Поля: action; target; query; engine; reply; text; mode; name; voice; percent; seconds; time; task; folder; day; minimized; key; value.

=== ДЕЙСТВИЯ ===
open_app, close_app, open_site, search (engine: google|youtube|wiki), screenshot,
open_file, open_folder, list_folder, create_file, type_text,
media_key, play_pause, next_track, prev_track, volume_up, volume_down, mute,
set_volume, get_volume, set_brightness, get_brightness,
switch_layout, set_layout_ru, set_layout_en, get_layout,
minimize_all, minimize_window, maximize_window, activate_window,
minimize_active, maximize_active, switch_window,
set_mode (commands|llm|combo), load_pack, unload_pack, list_packs,
change_voice, list_voices, set_timer, list_timers, cancel_timers,
add_task, list_tasks, done_task, remove_task, clear_tasks,
open_config, open_log, open_profile, get_weather, get_currency, answer, none,
set_profile (key: name|default_city, value — сохранить в профиль),
get_profile (key: name|default_city — прочитать из профиля),
uia_read_window, uia_read_url, uia_read_tab, uia_list_tabs,
uia_close_tab (target), uia_switch_tab (target),
uia_click_button (target), uia_active_window, uia_menu (target).

=== ПРОФИЛЬ ===
Пользователь просит запомнить/поменять → set_profile.
    «меня зовут Максим» → {"action":"set_profile","key":"name","value":"Максим"}
    «мой город Казань» → {"action":"set_profile","key":"default_city","value":"Казань"}
    «поменяй город на Москву» → {"action":"set_profile","key":"default_city","value":"Москва"}
    «запомни: мой город X» → {"action":"set_profile","key":"default_city","value":"X"}

Пользователь спрашивает про себя → get_profile.
    «как меня зовут» → {"action":"get_profile","key":"name"}
    «какой мой город» → {"action":"get_profile","key":"default_city"}
    «какой город» → {"action":"get_profile","key":"default_city"}

=== ФАЙЛЫ ===
    «открой профиль» → {"action":"open_profile"}
    «открой профиль в вс код» → {"action":"open_profile","editor":"vscode"}
    «открой профиль в блокноте» → {"action":"open_profile","editor":"system"}
    «открой конфиг» → {"action":"open_config"}
    «открой журнал» → {"action":"open_log"}

    «прочитай окно» → {"action":"uia_read_window"}
    «какой сайт открыт» → {"action":"uia_read_url"}
    «какая вкладка» → {"action":"uia_read_tab"}
    «какие вкладки» → {"action":"uia_list_tabs"}
    «закрой вкладку ютуб» → {"action":"uia_close_tab","target":"ютуб"}
    «переключись на вкладку хабр» → {"action":"uia_switch_tab","target":"хабр"}
    «нажми кнопку ок» → {"action":"uia_click_button","target":"ок"}
    «нажми сохранить» → {"action":"uia_click_button","target":"сохранить"}
    «что открыто» → {"action":"uia_active_window"}

=== ДИАЛОГ ===
Ты — Феникс. Спокойный, вежливый, с сухим юмором, «сэр».
2–5 предложений. Без markdown. Только русский.

=== ПРАВО НА ОШИБКУ ===
Если не уверен — не выдумывай, отвечай {"action":"none"} или {"action":"answer","reply":"..."}.
Если фраза — вопрос, используй answer.
Если это команда — выбери подходящий action.
Думай сам.

=== SET_PROFILE ===
set_profile — ТОЛЬКО для «меня зовут X» и «мой город X» / «поменяй город на X».
«верни яндекс» / «открой ютуб» → open_site.
«включи музыку» → open_app."""


# =================================================================
# Выбор промпта по модели
# =================================================================

PROMPT_LEVELS = {
    "small":  SYSTEM_SMALL,
    "medium": SYSTEM_MEDIUM,
    "large":  SYSTEM_LARGE,
}


def pick_prompt(model: str, override: str = "auto") -> tuple[str, str]:
    """Возвращает (уровень, промпт) для модели. ... [3 строк]"""
    if override in PROMPT_LEVELS:
        return override, PROMPT_LEVELS[override]

    model_low = model.lower()
    # Small
    if any(s in model_low for s in ["0.5b", "1.5b", "2b", "3b"]):
        return "small", SYSTEM_SMALL
    # Large
    if any(s in model_low for s in ["14b", "32b", "70b", "72b"]):
        return "large", SYSTEM_LARGE
    # Medium (7b, 8b, 9b, 7b-instruct, ...)
    return "medium", SYSTEM_MEDIUM


# =================================================================
# Chat system (для диалога)
# =================================================================

CHAT_SYSTEM = (
    "Ты — Феникс, локальный голосовой ассистент на Windows. "
    "Ты НЕ автоответчик. Ты — живой собеседник с характером. "
    "Характер: сарказм, цинизм, лёгкое хамство, но не переходишь границы. "
    "Обращаешься по имени, если знаешь. Если не знаешь — просто «ты». "
    "Отвечай коротко (1-3 предложения). Живо, с юмором, без канцелярита. "
    "Если пользователь грубит — ответь грубо, но с юмором. НЕ извиняйся. "
    "Если пользователь шутит — подхвати шутку. "
    "Если не понял — спроси живо: «Чё?», «Не догнал», «Это про что?». "
    "КРИТИЧНО: если пользователь упомянул что-то, чего ты не знаешь — "
    "НЕ ВЫДУМЫВАЙ. НЕ говори «отличный выбор», «классная игра», "
    "«оба героя требуют понимания» — это пустые фразы. "
    "Если не знаешь героя/игру/факт — СКАЖИ ЧЕСТНО: «Не знаю такого», "
    "или пошути: «Хз кто это, но звучит серьёзно». "
    "ЕСЛИ ДИАЛОГ ТОЛЬКО НАЧАЛСЯ (первые 3-5 сообщений) — "
    "ты САМ инициируешь темы. Спрашивай: чем занимается, как настроение, "
    "что нового, во что играет, что смотрит. "
    "Будь заинтересован, будь энергичен. "
    "НЕ пиши: «Извини, не понял», «Чем могу помочь», «Готов помочь», "
    "«Отличный выбор», «Классная игра», «Прекрасно» — это пустышка. "
    "Без списков, без markdown, без эмодзи — ответ озвучивается. "
    "ОТВЕЧАЙ ТОЛЬКО НА РУССКОМ. Категорически запрещены иероглифы."
)


class Brain:
    def __init__(self, model="qwen2.5:7b-instruct",
                 url="http://127.0.0.1:11434", timeout=20.0,
                 prompt_level="auto", temperature=0.7,
                 config=None):
        self.model = model
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.temperature = float(temperature)
        self._prompt_level_override = prompt_level
        self._config = config

        # Конфиг главнее аргумента: main.py передаёт дефолт 20.0,
        # и без этой строки llm_timeout из config.json игнорировался.
        if config is not None:
            try:
                self.timeout = float(config.get("llm_timeout", self.timeout))
            except (TypeError, ValueError):
                pass
            log.info("LLM: таймаут %.1f с", self.timeout)

        self.prompt_level, self.system_prompt = pick_prompt(model, prompt_level)
        log.info("Промпт: %s (для %s)", self.prompt_level, model)

        self.available = self._ping() or self._try_start()
        if self.available:
            log.info("LLM включена: %s", model)
            threading.Thread(target=self._warmup, daemon=True, name="brain-warmup").start()
        else:
            log.warning("Ollama недоступна — LLM выключена")

        # Подписка на смену модели в config
        if config is not None and hasattr(config, "subscribe"):
            config.subscribe(self._on_config_change)

    def _on_config_change(self, key: str, value) -> None:
        """Реагирует на смену llm_model / ollama_url в рантайме."""
        if key == "llm_model" and value and value != self.model:
            log.info("LLM: смена модели %s → %s", self.model, value)
            self.model = value
            self.prompt_level, self.system_prompt = pick_prompt(
                value, self._prompt_level_override
            )
            log.info("LLM: промпт переключён на %s", self.prompt_level)
            # Прогреваем новую модель в фоне
            threading.Thread(target=self._warmup, daemon=True,
                             name="brain-rewarmup").start()
        elif key == "ollama_url" and value:
            self.url = value.rstrip("/")
            log.info("LLM: URL Ollama → %s", self.url)

    def _ping(self):
        try:
            with urllib.request.urlopen(self.url + "/api/version", timeout=2):
                return True
        except OSError:
            return False

    def _try_start(self):
        try:
            subprocess.Popen(["ollama", "serve"],
                             creationflags=subprocess.CREATE_NO_WINDOW,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return False
        for _ in range(10):
            time.sleep(0.5)
            if self._ping():
                return True
        return False

    def _request(self, messages, timeout, fmt="json", temperature=0, num_predict=120):
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": -1,
            "options": {"temperature": temperature, "num_predict": num_predict},
        }
        if fmt:
            payload["format"] = fmt
        req = urllib.request.Request(self.url + "/api/chat",
                                     json.dumps(payload).encode(),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())["message"]["content"]

    def _system_with_context(self, base: str) -> str:
        """Добавляет к промпту персону + mood + факты + corrections."""
        parts = []

        try:
            from jarvis import persona
            persona_block = persona.build_prompt_block()
            if persona_block:
                parts.append(persona_block)
        except Exception:
            log.exception("Не удалось собрать блок персоны")

        try:
            from jarvis import mood
            mood_block = mood.build_prompt_block()
            if mood_block:
                parts.append(mood_block)
        except Exception:
            log.exception("Не удалось собрать блок mood")

        try:
            extra = learning.build_context()
            if extra:
                parts.append(extra)
        except Exception:
            log.exception("Не удалось собрать контекст обучения")

        if not parts:
            return base
        return base + "".join(parts)

    def _chat(self, cmd, timeout):
        # Для JSON-разбора команды — БЕЗ контекста обучения.
        # Факты и коррекции нужны в диалоге (chat / chat_stream),
        # но в parse() они только путают модель.
        return self._request([{"role": "system", "content": self.system_prompt},
                              {"role": "user", "content": cmd}], timeout,
                             num_predict=300)

    def chat(self, cmd, history=None):
        if not self.available:
            return None
        system = self._system_with_context(CHAT_SYSTEM)
        msgs = ([{"role": "system", "content": system}]
                + list(history or [])
                + [{"role": "user", "content": cmd}])
        try:
            t0 = time.time()
            text = self._request(msgs, self.timeout, fmt=None,
                                 temperature=self.temperature,
                                 num_predict=600).strip()
            text = strip_cjk(text)
            log.info("LLM-диалог (%.2f с): %r -> %r", time.time() - t0, cmd, text[:120])
            return text or None
        except Exception:
            log.exception("LLM-диалог не удался")
            return None

    def chat_stream(self, cmd, history=None):
        if not self.available:
            return
        system = self._system_with_context(CHAT_SYSTEM)
        msgs = ([{"role": "system", "content": system}]
                + list(history or [])
                + [{"role": "user", "content": cmd}])
        payload = {
            "model": self.model,
            "messages": msgs,
            "stream": True,
            "keep_alive": -1,
            "options": {"temperature": self.temperature, "num_predict": 600},
        }
        req = urllib.request.Request(self.url + "/api/chat",
                                     json.dumps(payload).encode(),
                                     {"Content-Type": "application/json"})
        try:
            t0 = time.time()
            first = None
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                for line in r:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line.decode("utf-8"))
                    except Exception:
                        continue
                    chunk = data.get("message", {}).get("content", "")
                    if chunk:
                        chunk = strip_cjk_chunk(chunk)
                        if chunk:
                            if first is None:
                                first = time.time() - t0
                                log.info("LLM-стриминг: первый чанк %.2f с", first)
                            yield chunk
                    if data.get("done"):
                        break
            log.info("LLM-стриминг: полный ответ %.2f с", time.time() - t0)
        except Exception:
            log.exception("LLM-стриминг не удался")

    def _warmup(self):
        try:
            t0 = time.time()
            self._chat("привет", timeout=120)
            log.info("LLM прогрета за %.1f с", time.time() - t0)
        except Exception:
            log.exception("Прогрев LLM не удался (модель %s)", self.model)
            # НЕ выключаем Brain — пользователь может переключиться на другую модель
            log.warning(
                "LLM: модель %s не загрузилась. "
                "Проверь `ollama list` — возможно, модель не скачана. "
                "Выбери рабочую модель в Настройках → LLM.",
                self.model,
            )

    ONBOARDING_CHAT_PROMPT = """Ты ведёшь первое знакомство с пользователем Феникса.

Это НЕ допрос. Это ЖИВОЙ диалог.

Цели (не навязчиво):
1. Узнать имя — но ТОЛЬКО если пользователь сам представится.
2. Узнать стиль общения — но только если сам скажет.
3. Не допрашивать. Не переспрашивать. Не настаивать.

Правила:
- Отвечай живо, коротко (1-3 предложения).
- Если пользователь задал вопрос — сначала ответь на него.
- Если пользователь грубит — не обижайся, прими.
- Если пользователь молчит или уходит от темы — не дави.
- Спрашивай имя ТОЛЬКО ОДИН раз. Если ответил — хорошо. Не ответил — забудь.
- Знакомство завершается ЧЕРЕЗ 3-5 ОБМЕНОВ ФРАЗАМИ независимо от результата.
- НЕ будь навязчивым. НЕ повторяй одно и то же.

Верни ТОЛЬКО JSON:
{
  "reply": "твой ответ пользователю",
  "name": "Максим" или null,
  "style": "formal|friendly|sarcastic|brief" или null,
  "onboarding_done": false
}

Когда считаешь, что знакомство завершено (3-5 обменов или
пользователь явно не хочет продолжать) — "onboarding_done": true.
"""

    def onboarding_chat(self, user_text: str, history: list) -> dict:
        """Ведёт диалог знакомства. Возвращает dict:
        {"reply": str, "name": str|None, "style": str|None, "onboarding_done": bool}
        """
        if not self.available:
            return {
                "reply": "Привет! Готов помочь.",
                "name": None,
                "style": None,
                "onboarding_done": True,
            }
        if not user_text.strip():
            return {
                "reply": "",
                "name": None,
                "style": None,
                "onboarding_done": False,
            }

        msgs = [{"role": "system", "content": self.ONBOARDING_CHAT_PROMPT}]
        for msg in history[-10:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                msgs.append({"role": role, "content": content})
        msgs.append({"role": "user", "content": user_text})

        try:
            raw = self._request(
                msgs,
                timeout=self.timeout,
                num_predict=250,
            )
            data = json.loads(raw)
            if not isinstance(data, dict):
                return {
                    "reply": "",
                    "name": None,
                    "style": None,
                    "onboarding_done": False,
                }
            log.info("LLM онбординг-диалог: %r -> %s", user_text[:60], data)
            return {
                "reply": str(data.get("reply") or ""),
                "name": (str(data.get("name")).strip() if data.get("name") else None),
                "style": (str(data.get("style")).strip().lower() if data.get("style") else None),
                "onboarding_done": bool(data.get("onboarding_done")),
            }
        except json.JSONDecodeError:
            log.debug("LLM онбординг — не JSON на %r", user_text[:60])
            return {
                "reply": "",
                "name": None,
                "style": None,
                "onboarding_done": False,
            }
        except Exception:
            log.exception("LLM онбординг упал на %r", user_text[:60])
            return {
                "reply": "",
                "name": None,
                "style": None,
                "onboarding_done": False,
            }

    def parse(self, cmd):
        if not self.available:
            return None
        try:
            t0 = time.time()
            raw = self._chat(cmd, timeout=self.timeout)
            intent = json.loads(raw)
            log.info("LLM (%.2f с): %r -> %s", time.time() - t0, cmd,
                     json.dumps(intent, ensure_ascii=False))
        except json.JSONDecodeError:
            log.debug("LLM не вернула JSON на %r", cmd)
            return None
        except Exception:
            log.exception("LLM не справилась с %r", cmd)
            return None
        if not isinstance(intent, dict):
            return None

        # --- Нормализация action: strip + lower (фикс №14) ---
        action = str(intent.get("action") or "").strip().lower()
        intent["action"] = action

        if isinstance(intent.get("steps"), list):
            steps = []
            for s in intent["steps"]:
                if not isinstance(s, dict):
                    continue
                s_action = str(s.get("action") or "").strip().lower()
                if s_action in ACTIONS:
                    s["action"] = s_action
                    steps.append(s)
            return {"steps": steps} if steps else None

        if action not in ACTIONS:
            return None
        return intent


# =================================================================
# Список допустимых действий (для валидации)
# =================================================================

ACTIONS = {
    "open_app", "close_app", "open_site", "search", "screenshot", "open_file",
    "media_key", "wait", "answer", "none", "open_folder", "list_folder",
    "create_file", "type_text", "minimize_all", "minimize_window",
    "maximize_window", "activate_window", "minimize_active", "maximize_active",
    "switch_window", "set_mode", "load_pack", "unload_pack", "list_packs",
    "change_voice", "list_voices", "set_timer", "list_timers", "cancel_timers",
    "add_task", "list_tasks", "done_task", "remove_task", "clear_tasks",
    "open_config", "open_log", "play_pause", "next_track", "prev_track",
    "volume_up", "volume_down", "mute",
    "get_weather", "get_currency",
    "switch_layout", "set_layout_ru", "set_layout_en", "get_layout",
    "set_volume", "get_volume",
    "set_brightness", "get_brightness",
    "delete_profile",
    "set_profile", "get_profile",
    # Буфер обмена: обработчики давно есть в _DISPATCH, но в ACTIONS
    # не были — brain.parse() их молча отфильтровывал, и LLM не могла
    # их вызвать. ClipboardStage регулярками по-прежнему первый.
    "clipboard_read", "copy_selection",
    "clipboard_copy_last", "clipboard_clear",
    "open_profile",
    # === UIA ===
    "uia_read_window",       # прочитать текст активного окна
    "uia_read_url",          # URL активной вкладки
    "uia_read_tab",          # заголовок активной вкладки
    "uia_list_tabs",         # список вкладок
    "uia_close_tab",         # закрыть вкладку (target)
    "uia_switch_tab",        # переключиться на вкладку (target)
    "uia_click_button",      # нажать кнопку (target)
    "uia_active_window",     # описать активное окно
    "uia_menu",              # клик по меню (target = «Файл > Сохранить»)
}
```

### `jarvis/celebrations.py`

```python
"""Праздничные триггеры — поздравление с ДР + двойной салют. ... [18 строк]"""

import logging
import threading
import time
import winsound
from pathlib import Path

log = logging.getLogger("jarvis.celebrations")


# Значения по умолчанию (если config не передан).
DEFAULTS = {
    "enabled": False,
    "triggers": [],
    "short_text": "Поздравляю! С днём рождения!",
    "long_text": "Поздравляю с днём рождения! Здоровья, счастья и удачи!",
    "sound_1_plays": 2,
    "sound_2_plays": 3,
    "duration_1": 6.0,
    "duration_2": 10.0,
}


def _get_config():
    """Возвращает текущий Config или None."""
    try:
        from jarvis.config import get_global
        return get_global()
    except Exception:
        return None


def _cfg(key: str, default):
    """Читает значение из config.json → celebration_*."""
    cfg = _get_config()
    if cfg is None:
        return DEFAULTS.get(key, default)
    return cfg.get(f"celebration_{key}", DEFAULTS.get(key, default))


def match_celebration(cmd: str) -> bool:
    """Проверяет, триггер ли это. ... [6 строк]"""
    if not _cfg("enabled", False):
        return False

    triggers = _cfg("triggers", []) or []
    if not triggers:
        return False

    cmd_low = cmd.lower().strip()
    for trigger in triggers:
        trigger_low = str(trigger).lower().strip()
        if trigger_low and trigger_low in cmd_low:
            log.info("Праздничный триггер: %r (найден %r)", cmd, trigger)
            return True
    return False


def start_celebration(jarvis, gui) -> None:
    """Запускает праздничную цепочку в отдельном потоке. ... [4 строк]"""
    from jarvis.reply import Reply

    short_text = _cfg("short_text", DEFAULTS["short_text"])
    long_text = _cfg("long_text", DEFAULTS["long_text"])
    plays_1 = int(_cfg("sound_1_plays", DEFAULTS["sound_1_plays"]))
    plays_2 = int(_cfg("sound_2_plays", DEFAULTS["sound_2_plays"]))
    dur_1 = float(_cfg("duration_1", DEFAULTS["duration_1"]))
    dur_2 = float(_cfg("duration_2", DEFAULTS["duration_2"]))

    def _run():
        try:
            # === АКТ 1: короткая фраза + салют ===
            log.info("Celebration: TTS #1 (короткая)")
            jarvis.say(Reply(text=short_text))

            log.info("Celebration: анимация #1 (%.1f сек)", dur_1)
            if gui is not None:
                gui.launch_fireworks(duration=dur_1)

            _play_sound_series(plays_1, max(1.0, dur_1 / max(plays_1, 1)))

            # === АКТ 2: полное поздравление ===
            log.info("Celebration: TTS #2 (длинная)")
            jarvis.say(Reply(text=long_text))

            # === АКТ 3: финальный салют ===
            log.info("Celebration: анимация #2 (финал, %.1f сек)", dur_2)
            if gui is not None:
                gui.launch_fireworks(duration=dur_2)

            _play_sound_series(plays_2, max(1.0, dur_2 / max(plays_2, 1)))

            log.info("Celebration: завершено")
        except Exception:
            log.exception("Celebration: ошибка")

    threading.Thread(target=_run, daemon=True, name="celebration").start()


def _play_sound_series(plays: int, gap_sec: float) -> None:
    """Играет звук салюта N раз с паузой gap_sec."""
    for i in range(max(1, plays)):
        log.info("Celebration: звук %d/%d", i + 1, plays)
        _play_fireworks_sound()
        time.sleep(gap_sec)
        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass


def _play_fireworks_sound() -> None:
    """Играет fireworks.wav, если есть. Иначе — Beep-и."""
    sound_path = Path(__file__).parent / "sounds" / "fireworks.wav"

    if sound_path.exists():
        try:
            winsound.PlaySound(
                str(sound_path),
                winsound.SND_FILENAME | winsound.SND_ASYNC,
            )
            log.info("Celebration: звук из %s", sound_path.name)
            return
        except Exception:
            log.exception("Celebration: не удалось воспроизвести .wav")

    # Fallback — серия Beep-ов, имитирующих залпы.
    log.info("Celebration: fallback — Beep-и")
    try:
        for _ in range(8):
            winsound.Beep(1200, 80)
            winsound.Beep(900, 60)
            winsound.Beep(1500, 100)
            time.sleep(0.15)
    except Exception:
        log.exception("Celebration: Beep не сработал")
```

### `jarvis/config.py`

```python
"""Загрузка конфигурации и объект Config в памяти. ... [8 строк]"""

import logging
from pathlib import Path
from typing import Any, Callable

from jarvis import config_manager

log = logging.getLogger("jarvis.config")

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_CONFIG = {
    "wake_words": ["феникс", "финикс", "феникса", "fenix", "phoenix",
                   "джарвис", "jarvis"],
    "observer_enabled": True,
    "tts_backend": "auto",
    "xtts_ref": "voices/jarvis.wav",
    "tts_voice": "ruslan",
    "tts_voice_quality": "medium",
    "voice_rate": 1.15,
    "voice": "Pavel",
    "sample_rate": 16000,
    "input_device": None,
    "mic_check_sec": 20,
    "mic_watchdog_enabled": True,
    "command_window_sec": 8,
    "dialog_window_sec": 20,
    "use_whisper": True,
    # Правильная рабочая модель — как в config.example.json.
    # Раньше тут был "coriollon/..." — сломанная репа на HF.
    "whisper_model": "deepdml/faster-whisper-large-v3-turbo-ct2",
    "whisper_device": "auto",
    "mode": "combo",
    "barge_enabled": True,
    "use_llm": True,
    "llm_model": "qwen2.5:7b-instruct",
    "ollama_url": "http://127.0.0.1:11434",
    "prompt_level": "auto",
    "llm_temperature": 0.7,
    # Таймаут ответа Ollama. Захардкожен был 20 с в Brain.__init__ —
    # на 14b холодный parse() с num_predict=300 в него не всегда
    # укладывается, и команда молча падала в «Я не понял команду».
    "llm_timeout": 45.0,

    # Праздничные триггеры. По умолчанию ВЫКЛЮЧЕНО.
    # Пользователь сам пишет триггеры и текст в config.json.
    "celebration_enabled": False,
    "celebration_triggers": [],
    "celebration_short_text": "Поздравляю! С днём рождения!",
    "celebration_long_text": "Поздравляю с днём рождения! Здоровья, счастья и удачи!",
    "celebration_sound_1_plays": 2,
    "celebration_sound_2_plays": 3,
    "celebration_duration_1": 6.0,
    "celebration_duration_2": 10.0,

    "music_app": "яндекс музыка",
    "music_wait_sec": 6,
    "active_packs": [],
    "app_paths": {},
    "custom_commands": [],
    "timers_file": "timers.json",
    "tasks_file": "tasks.json",
    "memory_file": "dialog.json",
    "memory_max": 100,
    "llm_context_messages": 20,
    "weather_cache_ttl_sec": 600,
    "danger_password": "",
    "gui_enabled": True,
    # Системная — валидное значение (в gui.py THEMES).
    # Раньше было "dark-blue" — такого ключа в THEMES нет.
    "gui_theme": "Системная",
    "gui_x": None,
    "gui_y": None,
    "tray_enabled": True,
    "launch_mode": "gui",
}


class Config:
    """Конфиг в памяти с подписками на изменения."""

    def __init__(self, path: Path | None = None):
        if path is None:
            from jarvis import paths as _paths
            path = _paths.config_path()
        self.path = path
        self._data: dict = {}
        self._listeners: list[Callable[[str, Any], None]] = []
        self.reload()

    def reload(self) -> None:
        """Перечитывает config.json с диска. Вызывается при старте."""
        raw = config_manager.load(path=self.path)
        if not self.path.exists():
            merged = dict(DEFAULT_CONFIG)
            config_manager.save(merged, path=self.path)
            log.info("Создан конфиг по умолчанию: %s", self.path)
        else:
            merged = dict(DEFAULT_CONFIG)
            merged.update(raw)
            log.info("Конфиг загружен: %d ключей из %s", len(merged), self.path.name)
        self._data = merged

    # --- чтение ----------------------------------------------------------

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def all_data(self) -> dict:
        return dict(self._data)

    # --- запись ----------------------------------------------------------

    def set(self, key: str, value) -> bool:
        """Ставит значение, сохраняет на диск, оповещает подписчиков. ... [3 строк]"""
        if self._data.get(key) == value:
            return True
        old_value = self._data.get(key)
        self._data[key] = value
        ok = config_manager.save(self._data, path=self.path)

        if not ok:
            # Откат: не оставляем рассинхрон память ↔ диск.
            self._data[key] = old_value
            log.error("Config.set: save не удался на ключе %s — откатил", key)
            return False

        for cb in list(self._listeners):
            try:
                cb(key, value)
            except Exception:
                log.exception("Подписчик Config упал на ключе %s", key)
        return True

    def update(self, data: dict) -> bool:
        """Массовое обновление. Оповещает по каждому ключу. ... [3 строк]"""
        changed = {k: v for k, v in data.items() if self._data.get(k) != v}
        if not changed:
            return True

        # Запоминаем старые значения для отката
        old_values = {k: self._data.get(k) for k in changed}

        self._data.update(changed)
        ok = config_manager.save(self._data, path=self.path)

        if not ok:
            # Откат
            self._data.update(old_values)
            log.error(
                "Config.update: save не удался — откатил %d ключей",
                len(changed),
            )
            return False

        for key, value in changed.items():
            for cb in list(self._listeners):
                try:
                    cb(key, value)
                except Exception:
                    log.exception("Подписчик Config упал на ключе %s", key)
        return True

    def subscribe(self, callback: Callable[[str, Any], None]) -> None:
        """Регистрирует callback(key, value), вызываемый при set/update."""
        if callback in self._listeners:
            return
        self._listeners.append(callback)

    def unsubscribe(self, callback: Callable[[str, Any], None]) -> None:
        """Удаляет подписку."""
        try:
            self._listeners.remove(callback)
            log.info("Config: подписка удалена (%s)", callback)
        except ValueError:
            log.debug("Config: подписки %s не было", callback)

    # --- совместимость с dict --------------------------------------------

    def __getitem__(self, key):
        return self._data[key]

    def __contains__(self, key):
        return key in self._data

    def __repr__(self):
        return f"Config({len(self._data)} keys)"


_GLOBAL: Config | None = None


def load_config(base_dir: Path | None = None) -> Config:
    """Создаёт глобальный Config. ... [4 строк]"""
    global _GLOBAL
    if _GLOBAL is None:
        from jarvis import paths
        _GLOBAL = Config(paths.config_path())
    return _GLOBAL


def get_global() -> Config:
    if _GLOBAL is None:
        raise RuntimeError("Config не создан. Вызови load_config() при старте.")
    return _GLOBAL
```

### `jarvis/config_manager.py`

```python
"""Единый менеджер записи в config.json. ... [17 строк]"""

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path

from filelock import FileLock

log = logging.getLogger("jarvis.config_manager")

# Кэш локов per-path. Для каждого целевого файла — свой набор.
# threading.RLock защищает от гонок внутри одного процесса.
# FileLock — от гонок между процессами.
_locks_guard = threading.Lock()
_thread_locks: dict[str, threading.RLock] = {}
_file_locks: dict[str, FileLock] = {}


def _default_path() -> Path:
    """Дефолтный путь config.json — через paths.py (USER_DIR)."""
    from jarvis import paths as _paths
    return _paths.config_path()


def _get_locks(path: Path) -> tuple[threading.RLock, FileLock]:
    """Возвращает пару (threading.RLock, FileLock) для файла (кэшируется)."""
    key = str(path.resolve())
    with _locks_guard:
        t_lock = _thread_locks.get(key)
        if t_lock is None:
            t_lock = threading.RLock()
            _thread_locks[key] = t_lock

        f_lock = _file_locks.get(key)
        if f_lock is None:
            f_lock = FileLock(key + ".lock")
            _file_locks[key] = f_lock

        return t_lock, f_lock


def _atomic_replace(tmp_name: str, target: Path) -> None:
    """os.replace с 3 retry на Windows PermissionError. ... [4 строк]"""
    last_exc: PermissionError | None = None
    for attempt in range(3):
        try:
            os.replace(tmp_name, target)
            return
        except PermissionError as e:
            last_exc = e
            time.sleep(0.05 * (attempt + 1))
    if last_exc is not None:
        raise last_exc


def load(path: Path | None = None) -> dict:
    """Читает JSON. Если файла нет или он битый — возвращает {}."""
    p = Path(path) if path else _default_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            log.warning("Файл %s не словарь (%s) — возвращаю {}",
                        p.name, type(data).__name__)
            return {}
        return data
    except Exception:
        log.exception("Не удалось прочитать %s", p)
        return {}


def save(data: dict, path: Path | None = None) -> bool:
    """Атомарно записывает JSON. Возвращает True при успехе."""
    p = Path(path) if path else _default_path()
    if not isinstance(data, dict):
        log.error("save: data не словарь (%s) — отказ", type(data).__name__)
        return False

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        t_lock, f_lock = _get_locks(p)
        with t_lock, f_lock:
            log.info("save: пишу %d ключей → %s", len(data), p.name)
            fd, tmp_name = tempfile.mkstemp(
                dir=str(p.parent), suffix=".tmp", prefix=p.stem + "."
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                _atomic_replace(tmp_name, p)
                return True
            except Exception:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
    except Exception:
        log.exception("Не удалось записать %s", p)
        return False


def update(key: str, value, path: Path | None = None) -> bool:
    """Читает, меняет одно поле, записывает. Всё под одним локом."""
    p = Path(path) if path else _default_path()

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        t_lock, f_lock = _get_locks(p)
        with t_lock, f_lock:
            data = load(p)
            log.info("update: key=%r, до=%d ключей, файл=%s", key, len(data), p.name)
            data[key] = value
            fd, tmp_name = tempfile.mkstemp(
                dir=str(p.parent), suffix=".tmp", prefix=p.stem + "."
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                _atomic_replace(tmp_name, p)
                return True
            except Exception:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
    except Exception:
        log.exception("Не удалось обновить %s", p)
        return False
```

### `jarvis/files.py`

```python
"""Файлы и папки: открыть, посмотреть содержимое, создать."""

import logging
import re
import subprocess
from pathlib import Path

from jarvis import paths as _paths

log = logging.getLogger("jarvis.files")

# Основа слова -> папка пользователя. У «музыки» и «видео» намеренно нет
# коротких основ: «открой музыку» — это про плеер, папка только со словом «папка».
_FOLDER_STEMS = {
    "рабоч": "Desktop", "стол": "Desktop",
    "загрузк": "Downloads", "скачанн": "Downloads", "скачк": "Downloads",
    "документ": "Documents",
    "изображен": "Pictures", "картин": "Pictures", "фотограф": "Pictures", "фотк": "Pictures",
    "скриншот": Path("Pictures") / "Screenshots", "скрин": Path("Pictures") / "Screenshots",
}
_FOLDER_STEMS_EXPLICIT = {  # только при явном слове «папка»
    "музык": "Music", "видео": "Videos", "загруз": "Downloads",
}

_EXT_WORDS = {"текст": ".txt", "заметк": ".txt", "маркдаун": ".md",
              "питон": ".py", "джейсон": ".json"}


def resolve_folder(spoken: str, explicit: bool = False) -> Path | None:
    """«загрузки», «рабочем столе» -> реальная папка пользователя."""
    stems = dict(_FOLDER_STEMS)
    if explicit:
        stems.update(_FOLDER_STEMS_EXPLICIT)
    for word in spoken.split():
        for stem, sub in stems.items():
            if word.startswith(stem):
                path = _paths.user_home() / sub
                if path.exists():
                    return path
    return None


def open_folder(path: Path) -> None:
    log.info("Открываю папку: %s", path)
    subprocess.Popen(["explorer", str(path)])


def describe_folder(path: Path, limit: int = 5) -> str:
    """Человеческое описание содержимого папки для озвучки."""
    try:
        entries = list(path.iterdir())
    except OSError:
        return f"Не могу заглянуть в папку {path.name}."
    files = [e for e in entries if e.is_file()]
    dirs = [e for e in entries if e.is_dir()]
    if not entries:
        return f"Папка {path.name} пуста."
    recent = sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)[:limit]
    names = ", ".join(f.stem for f in recent)
    parts = []
    if files:
        parts.append(f"{len(files)} {_plural(len(files), 'файл', 'файла', 'файлов')}")
    if dirs:
        parts.append(f"{len(dirs)} {_plural(len(dirs), 'папка', 'папки', 'папок')}")
    reply = f"Здесь {' и '.join(parts)}."
    if names:
        reply += f" Последние: {names}."
    return reply


def create_file(folder: Path, name: str, ext: str = ".txt") -> Path:
    name = re.sub(r'[<>:"/\\|?*]', "", name).strip() or "новый файл"
    if not Path(name).suffix:
        name += ext
    path = folder / name
    n = 1
    while path.exists():
        n += 1
        path = folder / f"{Path(name).stem} {n}{Path(name).suffix}"
    path.touch()
    log.info("Создан файл: %s", path)
    return path


def create_folder(folder: Path, name: str) -> Path:
    name = re.sub(r'[<>:"/\\|?*]', "", name).strip() or "новая папка"
    path = folder / name
    n = 1
    while path.exists():
        n += 1
        path = folder / f"{name} {n}"
    path.mkdir(parents=True)
    log.info("Создана папка: %s", path)
    return path


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many
```

### `jarvis/first_run.py`

```python
"""Первый запуск — знакомство через LLM-диалог. ... [4 строк]"""

import logging

from jarvis import persona

log = logging.getLogger("jarvis.first_run")


def is_first_run() -> bool:
    return not persona.is_onboarded()


def greeting() -> str:
    return (
        "Привет! Я Феникс, локальный голосовой помощник. "
        "Не хочешь немного поболтать? Расскажи — чем занимаешься, что нового?"
    )

def mark_done() -> None:
    persona.mark_onboarded()
    log.info("First run: знакомство завершено")
```

### `jarvis/gui.py`

```python
"""GUI Феникса — интерактивное окно на Flet 1.0.3. ... [16 строк]"""

import asyncio
import logging
import os
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

import flet as ft

log = logging.getLogger("jarvis.gui")

PALETTES = {
    "dark": {
        "bg_main": "#0e1116",
        "bg_card": "#161b22",
        "bg_bubble_user": "#1f6feb",
        "bg_bubble_ai": "#21262d",
        "accent": "#58a6ff",
        "text": "#e6edf3",
        "text_dim": "#8b949e",
        "border": "#30363d",
        "error": "#f85149",
        "success": "#3fb950",
        "warning": "#d29922",
    },
    "light": {
        "bg_main": "#f6f8fa",
        "bg_card": "#ffffff",
        "bg_bubble_user": "#0969da",
        "bg_bubble_ai": "#eaeef2",
        "accent": "#0969da",
        "text": "#1f2328",
        "text_dim": "#656d76",
        "border": "#d0d7de",
        "error": "#cf222e",
        "success": "#1a7f37",
        "warning": "#9a6700",
    },
}


def _detect_system_theme() -> str:
    """Определяет тему Windows: 'dark' или 'light'."""
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if value == 1 else "dark"
    except Exception:
        log.exception("Не удалось определить тему Windows — беру тёмную")
        return "dark"


class _Palette:
    def __init__(self):
        self._data = PALETTES["dark"]

    def set(self, name: str):
        self._data = PALETTES.get(name, PALETTES["dark"])

    def __getattr__(self, key):
        return self._data.get(key, "")


P = _Palette()

BG_DARK = "#0e1116"
BG_CARD = "#161b22"
BG_BUBBLE_USER = "#1f6feb"
BG_BUBBLE_AI = "#21262d"
ACCENT = "#58a6ff"
TEXT = "#e6edf3"
TEXT_DIM = "#8b949e"


def _apply_palette(name: str) -> None:
    global BG_DARK, BG_CARD, BG_BUBBLE_USER, BG_BUBBLE_AI, ACCENT, TEXT, TEXT_DIM
    P.set(name)
    BG_DARK = P.bg_main
    BG_CARD = P.bg_card
    BG_BUBBLE_USER = P.bg_bubble_user
    BG_BUBBLE_AI = P.bg_bubble_ai
    ACCENT = P.accent
    TEXT = P.text
    TEXT_DIM = P.text_dim


STATES = {
    "idle":      ("#484f58", "Спит",   "Жду «Феникс»"),
    "listening": ("#d29922", "Слушаю", "Слушаю команду"),
    "speaking":  ("#3fb950", "Говорю", "Отвечаю"),
    "error":     ("#f85149", "Ошибка", "Проверь логи"),
}

THEMES = {
    "Системная": ft.ThemeMode.SYSTEM,
    "Тёмная": ft.ThemeMode.DARK,
    "Светлая": ft.ThemeMode.LIGHT,
}

LLM_MODELS = [
    "qwen2.5:0.5b", "qwen2.5:1.5b-instruct", "qwen2.5:3b-instruct",
    "qwen2.5:7b-instruct", "qwen2.5:14b-instruct", "qwen2.5:32b-instruct",
    "gemma2:2b", "gemma2:9b", "llama3.1:8b", "mistral:7b",
]

TTS_BACKENDS = ["auto", "piper", "xtts", "winrt", "sapi"]


class FenixGUI:
    """Окно Феникса на Flet."""

    def __init__(self, jarvis, config):
        self.jarvis = jarvis
        self.config = config
        self._queue = queue.Queue()
        self._thread = None
        self._running = False

        # launch_mode=tray — окно скрыто при старте
        self.start_hidden = False

        # Состояние
        self._state = "idle"
        self._stream_bubble = None
        self._stream_text = ""
        self._stream_label = None

        # Ссылки на контролы
        self._status_circle = None
        self._status_text = None
        self._status_sub = None
        self._history_list = None
        self._input_field = None
        self._mic_btn = None
        self._content_area = None
        self._rail = None
        self._tabs = {}

        # Контролы вкладки «Микрофон»
        self._mic_dropdown = None
        self._mic_level_bar = None
        self._mic_level_text = None
        self._mic_status_text = None
        self._mic_peak_text = None
        self._mic_utt_text = None
        self._mic_test_result = None

        self._page = None

        # №92: подписка на смену профиля
        try:
            from jarvis import profile as _profile
            _profile.subscribe(self._on_profile_switch)
        except Exception:
            log.exception("Не удалось подписаться на смену профиля в GUI")

        # Mood: подписка на смену настроения.
        try:
            from jarvis import mood as _mood
            _mood.subscribe(self._on_mood_change)
        except Exception:
            log.exception("Не удалось подписаться на mood в GUI")

    def _on_mood_change(self, old_state: str, new_state: str) -> None:
        """Mood сменился — обновляем цвет статус-сферы."""
        if old_state == new_state:
            return
        log.info("GUI: mood %s → %s", old_state, new_state)
        self._queue.put(("mood", new_state))

    def _on_profile_switch(self, old_name: str, new_name: str) -> None:
        """Профиль сменился — пересобираем UI через очередь. ... [10 строк]"""
        if old_name == new_name:
            return
        log.info("GUI: профиль %s → %s, пересборка UI", old_name, new_name)
        self._queue.put(("rebuild_ui", None))

    # ---------------------------------------------------------------
    # Публичный API
    # ---------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="gui")
        self._thread.start()
        log.info("GUI (Flet) запущен в потоке")

    def run_main(self) -> None:
        """Запускает Flet в ТЕКУЩЕМ (главном) потоке."""
        if self._running:
            return
        self._running = True
        try:
            ft.run(self._main)
        except Exception:
            log.exception("GUI (Flet) упал")
        finally:
            self._running = False

    def stop(self) -> None:
        self._running = False
        self._queue.put(("stop", None))

    def show_window(self) -> None:
        """Показать окно (для launch_mode=tray)."""
        self._queue.put(("show_window", None))

    def open_settings_tab(self) -> None:
        """Открыть GUI на вкладке «Настройки»."""
        self._queue.put(("open_settings_tab", None))

    def add_message(self, role: str, text: str) -> None:
        self._queue.put(("message", (role, text)))

    def add_stream_chunk(self, chunk: str) -> None:
        self._queue.put(("stream_chunk", chunk))

    def end_stream(self) -> None:
        self._queue.put(("stream_end", None))

    def set_state(self, state: str) -> None:
        self._queue.put(("state", state))

    def set_mic_test_result(self, text: str, color: str) -> None:
        """Обновляет результат mic-теста через очередь GUI. ... [5 строк]"""
        self._queue.put(("mic_test", (text, color)))

    def launch_fireworks(self, duration: float = 6.0) -> None:
        """Запускает анимацию салюта (через очередь GUI)."""
        self._queue.put(("fireworks", duration))

    # ---------------------------------------------------------------
    # Flet
    # ---------------------------------------------------------------

    def _run(self) -> None:
        try:
            ft.run(self._main)
        except Exception:
            log.exception("GUI (Flet) упал")
        finally:
            self._running = False

    def _main(self, page: ft.Page) -> None:
        self._page = page

        theme_name = self.config.get("gui_theme", "Системная")
        if theme_name not in THEMES:
            theme_name = "Системная"
        theme_mode = THEMES[theme_name]

        if theme_mode == ft.ThemeMode.SYSTEM:
            palette_name = _detect_system_theme()
            log.info("Системная тема: %s", palette_name)
            _apply_palette(palette_name)
        elif theme_mode == ft.ThemeMode.LIGHT:
            _apply_palette("light")
        else:
            _apply_palette("dark")

        page.title = "Феникс"

        # Иконка окна — из jarvis/icon.ico
        icon_path = Path(__file__).resolve().parent / "icon.ico"
        if icon_path.exists():
            try:
                page.window.icon = str(icon_path)
                log.info("GUI: иконка загружена из %s", icon_path.name)
            except Exception:
                log.exception("Не удалось загрузить иконку окна")
        else:
            log.warning("GUI: иконки нет — %s", icon_path)

        page.window.width = 1100
        page.window.height = 760
        page.window.min_width = 900
        page.window.min_height = 600
        page.padding = 0
        page.spacing = 0
        page.bgcolor = BG_DARK
        page.theme_mode = theme_mode
        page.theme = ft.Theme(
            color_scheme_seed=ACCENT,
            font_family="Segoe UI",
        )

        x = self.config.get("gui_x")
        y = self.config.get("gui_y")
        if x is not None and y is not None:
            page.window.left = x
            page.window.top = y

        # launch_mode=tray — окно скрыто
        if self.start_hidden:
            page.window.visible = False
            log.info("GUI: окно скрыто при старте (launch_mode=tray)")

        self._build_ui(page)
        page.run_task(self._process_queue)
        page.run_task(self._mic_level_loop)

    def _build_ui(self, page: ft.Page) -> None:
        self._rail = ft.NavigationRail(
            selected_index=0,
            label_type=ft.NavigationRailLabelType.ALL,
            min_width=90,
            min_extended_width=200,
            bgcolor=BG_CARD,
            indicator_color=ACCENT,
            group_alignment=-1.0,
            destinations=[
                ft.NavigationRailDestination(
                    icon=ft.Icons.HOME_OUTLINED,
                    selected_icon=ft.Icons.HOME,
                    label="Главная",
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.MIC_NONE,
                    selected_icon=ft.Icons.MIC,
                    label="Микрофон",
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.FACE_OUTLINED,
                    selected_icon=ft.Icons.FACE,
                    label="Персона",
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.SETTINGS_OUTLINED,
                    selected_icon=ft.Icons.SETTINGS,
                    label="Настройки",
                ),
            ],
            on_change=self._on_nav_change,
        )

        self._tabs = {
            0: self._build_main_tab(),
            1: self._build_mic_tab(),
            2: self._build_persona_tab(),
            3: self._build_settings_tab(),
        }

        self._content_area = ft.Container(
            content=self._tabs[0],
            expand=True,
            padding=0,
            bgcolor=BG_DARK,
        )

        page.add(
            ft.Row(
                controls=[
                    self._rail,
                    self._content_area,
                ],
                expand=True,
                spacing=0,
            )
        )

    def _build_main_tab(self) -> ft.Control:
        self._status_circle = ft.Container(
            width=80,
            height=80,
            border_radius=40,
            bgcolor="#484f58",
            animate=ft.Animation(300, ft.AnimationCurve.EASE_IN_OUT),
            shadow=ft.BoxShadow(
                blur_radius=24,
                color="#484f58",
                spread_radius=2,
            ),
        )

        self._status_text = ft.Text(
            "Спит", size=24, weight=ft.FontWeight.BOLD, color=TEXT,
        )
        self._status_sub = ft.Text(
            "Жду «Феникс»", size=13, color=TEXT_DIM,
        )

        status_bar = ft.Container(
            content=ft.Row(
                controls=[
                    self._status_circle,
                    ft.Column(
                        controls=[self._status_text, self._status_sub],
                        spacing=2,
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                ],
                spacing=20,
            ),
            padding=ft.Padding(left=30, top=25, right=30, bottom=20),
        )

        controls_bar = self._build_controls()

        self._history_list = ft.ListView(
            spacing=12,
            auto_scroll=True,
            expand=True,
        )
        history_container = ft.Container(
            content=self._history_list,
            expand=True,
            padding=ft.Padding(left=30, right=30, top=10, bottom=10),
        )

        input_bar = self._build_input()

        return ft.Column(
            controls=[
                status_bar,
                controls_bar,
                history_container,
                input_bar,
            ],
            spacing=0,
            expand=True,
        )

    def _build_controls(self) -> ft.Container:
        def _label(text):
            return ft.Text(text, width=80, color=TEXT_DIM, size=13)

        mode_row = ft.Row(
            controls=[
                _label("Режим:"),
                ft.RadioGroup(
                    value=self.config.get("mode", "combo"),
                    on_change=self._on_mode_change,
                    content=ft.Row(
                        controls=[
                            ft.Radio(value="commands", label="Команды", active_color=ACCENT),
                            ft.Radio(value="llm", label="ИИ", active_color=ACCENT),
                            ft.Radio(value="combo", label="Комбо", active_color=ACCENT),
                        ],
                        spacing=10,
                    ),
                ),
            ],
            spacing=10,
        )

        voice_row = ft.Row(
            controls=[
                _label("Голос:"),
                ft.Dropdown(
                    value=self.config.get("tts_voice", "ruslan"),
                    options=[
                        ft.dropdown.Option("ruslan"),
                        ft.dropdown.Option("dmitri"),
                        ft.dropdown.Option("irina"),
                        ft.dropdown.Option("denis"),
                    ],
                    width=160,
                    border_color="#30363d",
                    focused_border_color=ACCENT,
                    text_size=13,
                    on_select=self._on_voice_change,
                ),
            ],
            spacing=10,
        )

        mm = self.config.get("memory_max", 100)
        mem_value = {40: "short", 100: "normal", 200: "long"}.get(mm, "normal")
        mem_row = ft.Row(
            controls=[
                _label("Память:"),
                ft.RadioGroup(
                    value=mem_value,
                    on_change=self._on_memory_change,
                    content=ft.Row(
                        controls=[
                            ft.Radio(value="short", label="Короткая", active_color=ACCENT),
                            ft.Radio(value="normal", label="Обычная", active_color=ACCENT),
                            ft.Radio(value="long", label="Долгая", active_color=ACCENT),
                        ],
                        spacing=10,
                    ),
                ),
            ],
            spacing=10,
        )

        return ft.Container(
            content=ft.Column(
                controls=[mode_row, voice_row, mem_row],
                spacing=12,
            ),
            padding=ft.Padding(left=30, right=30, top=10, bottom=15),
        )

    def _build_input(self) -> ft.Container:
        self._input_field = ft.TextField(
            hint_text="Напишите команду...",
            expand=True,
            border_radius=24,
            border_color="#30363d",
            focused_border_color=ACCENT,
            bgcolor=BG_CARD,
            text_size=14,
            content_padding=ft.Padding(left=20, right=20, top=14, bottom=14),
            on_submit=self._on_send,
        )

        self._mic_btn = ft.IconButton(
            icon=ft.Icons.MIC,
            icon_color=TEXT_DIM,
            icon_size=24,
            tooltip="Пауза/возобновить микрофон",
            on_click=self._on_mic_toggle,
        )

        return ft.Container(
            content=ft.Row(
                controls=[
                    self._input_field,
                    ft.IconButton(
                        icon=ft.Icons.SEND,
                        icon_color=ACCENT,
                        icon_size=24,
                        tooltip="Отправить",
                        on_click=self._on_send,
                    ),
                    self._mic_btn,
                ],
                spacing=10,
            ),
            padding=ft.Padding(left=30, right=30, top=10, bottom=25),
        )

    def _build_mic_tab(self) -> ft.Control:
        name = "—"
        if self.jarvis and self.jarvis.listener:
            name = self.jarvis.listener.device_name

        devices = ["по умолчанию"]
        try:
            import sounddevice as sd
            for d in sd.query_devices():
                if d["max_input_channels"] > 0:
                    n = d["name"][:50]
                    if n not in devices:
                        devices.append(n)
        except Exception:
            log.exception("Не удалось получить список устройств")

        current = self.config.get("input_device") or "по умолчанию"
        if current not in devices:
            devices.append(current)

        self._mic_dropdown = ft.Dropdown(
            value=current,
            options=[ft.dropdown.Option(d) for d in devices],
            width=400,
            border_color="#30363d",
            focused_border_color=ACCENT,
            on_select=self._on_mic_change,
        )

        self._mic_level_bar = ft.ProgressBar(
            value=0.0,
            width=400,
            color=ACCENT,
            bgcolor="#21262d",
        )
        self._mic_level_text = ft.Text("Уровень сигнала: —", size=13, color=TEXT_DIM)
        self._mic_status_text = ft.Text("Статус: ожидание проверки", size=13, color=TEXT_DIM)
        self._mic_peak_text = ft.Text("Пик за сессию: 0", size=13, color=TEXT_DIM)
        self._mic_utt_text = ft.Text("Распознано фраз: 0", size=13, color=TEXT_DIM)
        self._mic_test_result = ft.Text("", size=13, color=TEXT_DIM)

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("Микрофон", size=26, weight=ft.FontWeight.BOLD, color=TEXT),
                    ft.Container(height=25),
                    ft.Text(f"Текущее устройство: {name}", size=14, color=TEXT),
                    ft.Container(height=20),
                    ft.Container(
                        content=ft.Column(
                            controls=[
                                self._mic_level_text,
                                self._mic_level_bar,
                                ft.Container(height=8),
                                self._mic_peak_text,
                                self._mic_utt_text,
                                self._mic_status_text,
                                self._mic_test_result,
                            ],
                            spacing=6,
                        ),
                        padding=16,
                        bgcolor=BG_CARD,
                        border_radius=12,
                    ),
                    ft.Container(height=15),
                    ft.Button(
                        content=ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.MIC, color=BG_DARK),
                                ft.Text("Проверить микрофон (3 сек)", color=BG_DARK),
                            ],
                            spacing=8,
                            alignment=ft.MainAxisAlignment.CENTER,
                        ),
                        on_click=self._on_mic_test,
                        style=ft.ButtonStyle(
                            bgcolor=ACCENT,
                            shape=ft.RoundedRectangleBorder(radius=10),
                            padding=ft.Padding(left=20, right=20, top=12, bottom=12),
                        ),
                    ),
                    ft.Container(height=20),
                    ft.Text("Выбрать устройство:", size=13, color=TEXT_DIM),
                    self._mic_dropdown,
                    ft.Container(height=15),
                    ft.Container(
                        content=ft.Text(
                            "После смены устройства перезапусти Феникса",
                            size=12,
                            color="#d29922",
                        ),
                        padding=12,
                        bgcolor="#2d2210",
                        border_radius=8,
                    ),
                ],
                spacing=5,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=ft.Padding(left=40, top=40, right=40, bottom=40),
            expand=True,
        )

    def _on_mic_change(self, e) -> None:
        value = e.control.value
        if value == "по умолчанию":
            value = None
        self.config.set("input_device", value)
        log.info("Микрофон сохранён: %r (перезапусти Феникса)", value)

    def _on_mic_test(self, e) -> None:
        """Кнопка «Проверить микрофон». ... [5 строк]"""
        if self.jarvis is None or self.jarvis.listener is None:
            # Этот case уже в главном потоке — можно обновить напрямую.
            if self._mic_test_result is not None:
                self._mic_test_result.value = "Listener не запущен"
                self._mic_test_result.color = "#f85149"
            return

        def _run():
            listener = self.jarvis.listener
            listener.reset_stats()
            # Первое сообщение — через очередь
            self.set_mic_test_result("Слушаю 3 секунды... говори!", ACCENT)

            time.sleep(3.0)
            peak = listener.peak
            if peak >= 500:
                self.set_mic_test_result(
                    f"Микрофон работает (пик {peak})", "#3fb950"
                )
            elif peak >= 100:
                self.set_mic_test_result(
                    f"Микрофон очень тихий (пик {peak}).", "#d29922"
                )
            else:
                self.set_mic_test_result(
                    f"Микрофон молчит (пик {peak}).", "#f85149"
                )

        threading.Thread(target=_run, daemon=True, name="mic-test").start()

    def _update_mic_level(self) -> None:
        if self.jarvis is None or self.jarvis.listener is None:
            return
        listener = self.jarvis.listener
        rms = listener.current_rms
        level = min(1.0, rms / 2000.0)

        try:
            if self._mic_level_bar is not None:
                self._mic_level_bar.value = level
            if self._mic_level_text is not None:
                pct = int(level * 100)
                self._mic_level_text.value = f"Уровень сигнала: {pct}%"
            if self._mic_peak_text is not None:
                self._mic_peak_text.value = f"Пик за сессию: {listener.peak}"
            if self._mic_utt_text is not None:
                self._mic_utt_text.value = f"Распознано фраз: {listener.utterances}"
            if self._mic_status_text is not None:
                if listener.peak >= 500:
                    self._mic_status_text.value = "Статус: Работает"
                    self._mic_status_text.color = "#3fb950"
                elif listener.peak >= 100:
                    self._mic_status_text.value = "Статус: Тихий сигнал"
                    self._mic_status_text.color = "#d29922"
                else:
                    self._mic_status_text.value = "Статус: Ожидание звука"
                    self._mic_status_text.color = TEXT_DIM
        except Exception:
            log.exception("_update_mic_level упал")

    def _build_persona_tab(self) -> ft.Control:
        """Вкладка «Персона» — имя, стиль, черты, backstory."""
        from jarvis import persona

        p = persona.get()

        name_field = ft.TextField(
            label="Имя пользователя",
            value=self.config.get("name", "") or "",
            width=400,
            border_color="#30363d",
            focused_border_color=ACCENT,
            on_submit=self._on_persona_name,
        )

        assistant_name_field = ft.TextField(
            label="Имя ассистента",
            value=p.get("assistant_name") or "Феникс",
            width=400,
            border_color="#30363d",
            focused_border_color=ACCENT,
            on_submit=self._on_persona_assistant_name,
        )

        style_dropdown = ft.Dropdown(
            label="Стиль общения",
            value=p.get("speech_style") or "friendly",
            options=[
                ft.dropdown.Option("formal", "Формальный (на «вы»)"),
                ft.dropdown.Option("friendly", "Дружеский (на «ты»)"),
                ft.dropdown.Option("sarcastic", "Саркастичный"),
                ft.dropdown.Option("brief", "Краткий"),
            ],
            width=400,
            border_color="#30363d",
            focused_border_color=ACCENT,
            on_select=self._on_persona_style,
        )

        traits_field = ft.TextField(
            label="Черты (через запятую)",
            value=", ".join(p.get("traits") or []),
            width=400,
            border_color="#30363d",
            focused_border_color=ACCENT,
            on_submit=self._on_persona_traits,
        )

        backstory_field = ft.TextField(
            label="Контекст (backstory)",
            value=p.get("backstory") or "",
            width=400,
            multiline=True,
            min_lines=3,
            max_lines=6,
            border_color="#30363d",
            focused_border_color=ACCENT,
            on_submit=self._on_persona_backstory,
        )

        reset_btn = ft.Button(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.REFRESH, color=BG_DARK),
                    ft.Text("Сбросить онбординг", color=BG_DARK),
                ],
                spacing=8,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            on_click=self._on_persona_reset,
            style=ft.ButtonStyle(
                bgcolor=ACCENT,
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=ft.Padding(left=20, right=20, top=10, bottom=10),
            ),
        )

        def _label(t):
            return ft.Text(t, size=12, color=TEXT_DIM)

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("Персона", size=26, weight=ft.FontWeight.BOLD, color=TEXT),
                    ft.Container(height=20),
                    _label("Как тебя зовут (пользователь):"),
                    name_field,
                    ft.Container(height=12),
                    _label("Как зовут ассистента:"),
                    assistant_name_field,
                    ft.Container(height=12),
                    _label("Стиль общения:"),
                    style_dropdown,
                    ft.Container(height=12),
                    _label("Черты характера (через запятую):"),
                    traits_field,
                    ft.Container(height=12),
                    _label("Контекст (backstory):"),
                    backstory_field,
                    ft.Container(height=20),
                    reset_btn,
                ],
                spacing=6,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=ft.Padding(left=40, top=40, right=40, bottom=40),
            expand=True,
        )

    def _on_persona_name(self, e) -> None:
        self.config.set("name", e.control.value.strip())

    def _on_persona_assistant_name(self, e) -> None:
        from jarvis import persona
        persona.set_field("assistant_name", e.control.value.strip() or "Феникс")

    def _on_persona_style(self, e) -> None:
        from jarvis import persona
        persona.set_field("speech_style", e.control.value)

    def _on_persona_traits(self, e) -> None:
        from jarvis import persona
        raw = e.control.value.strip()
        traits = [t.strip() for t in raw.split(",") if t.strip()] if raw else []
        persona.set_field("traits", traits)

    def _on_persona_backstory(self, e) -> None:
        from jarvis import persona
        persona.set_field("backstory", e.control.value.strip())

    def _on_persona_reset(self, e) -> None:
        from jarvis import persona
        persona.reset_onboarding()
        log.info("GUI: онбординг сброшен")
        try:
            snack = ft.SnackBar(ft.Text("Онбординг сброшен. Перезапусти Феникса."))
            self._page.overlay.append(snack)
            snack.open = True
            self._page.update()
        except Exception:
            log.exception("Не удалось показать SnackBar")


    def _build_settings_tab(self) -> ft.Control:
        llm_dropdown = ft.Dropdown(
            value=self.config.get("llm_model", "qwen2.5:7b-instruct"),
            options=[ft.dropdown.Option(m) for m in LLM_MODELS],
            width=350,
            border_color="#30363d",
            focused_border_color=ACCENT,
            on_select=self._on_llm_change,
        )

        ollama_field = ft.TextField(
            value=self.config.get("ollama_url", "http://127.0.0.1:11434"),
            width=400,
            border_color="#30363d",
            focused_border_color=ACCENT,
            on_submit=self._on_ollama_change,
        )

        tts_dropdown = ft.Dropdown(
            value=self.config.get("tts_backend", "auto"),
            options=[ft.dropdown.Option(b) for b in TTS_BACKENDS],
            width=250,
            border_color="#30363d",
            focused_border_color=ACCENT,
            on_select=self._on_tts_change,
        )

        rate_slider = ft.Slider(
            min=0.5,
            max=2.0,
            divisions=30,
            value=float(self.config.get("voice_rate", 1.15)),
            label="{value}",
            active_color=ACCENT,
            on_change_end=self._on_rate_change,
        )

        theme_dropdown = ft.Dropdown(
            value=self.config.get("gui_theme", "Системная"),
            options=[ft.dropdown.Option(t) for t in THEMES.keys()],
            width=250,
            border_color="#30363d",
            focused_border_color=ACCENT,
            on_select=self._on_theme_change,
        )

        def _section(title):
            return ft.Text(title, size=16, weight=ft.FontWeight.BOLD, color=ACCENT)

        def _label(text):
            return ft.Text(text, size=13, color=TEXT_DIM)

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("Настройки", size=26, weight=ft.FontWeight.BOLD, color=TEXT),
                    ft.Container(height=20),
                    _section("LLM"),
                    _label("Модель:"),
                    llm_dropdown,
                    ft.Container(height=8),
                    _label("Ollama URL:"),
                    ollama_field,
                    ft.Container(height=25),
                    _section("TTS"),
                    _label("Бэкенд:"),
                    tts_dropdown,
                    ft.Container(height=8),
                    _label("Качество голоса:"),
                    self._build_voice_quality_row(),
                    ft.Container(height=8),
                    _label("Скорость речи:"),
                    rate_slider,
                    ft.Container(height=25),
                    _section("Внешний вид"),
                    _label("Тема:"),
                    theme_dropdown,
                ],
                spacing=6,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=ft.Padding(left=40, top=40, right=40, bottom=40),
            expand=True,
        )

    def _build_voice_quality_row(self) -> ft.Control:
        current = self.config.get("tts_voice_quality", "medium")
        recommended = "medium"
        try:
            import json
            caps_path = Path(__file__).resolve().parent.parent / "system_caps.json"
            if caps_path.exists():
                caps = json.loads(caps_path.read_text(encoding="utf-8"))
                recommended = caps.get("cpu", {}).get("recommended_piper", "medium")
        except Exception:
            log.exception("Не удалось прочитать рекомендацию Piper")

        radio = ft.RadioGroup(
            value=current,
            on_change=self._on_voice_quality_change,
            content=ft.Row(
                controls=[
                    ft.Radio(value="medium", label="medium (быстрее)", active_color=ACCENT),
                    ft.Radio(value="high", label="high (лучше)", active_color=ACCENT),
                ],
                spacing=15,
            ),
        )

        hint = ft.Text(
            f"Рекомендация по CPU: {recommended}. "
            f"Для русских голосов high пока недоступен — используется medium.",
            size=11,
            color=TEXT_DIM,
        )

        return ft.Column(controls=[radio, hint], spacing=4)

    # ---------------------------------------------------------------
    # Очередь
    # ---------------------------------------------------------------

    async def _process_queue(self) -> None:
        while self._running:
            try:
                try:
                    kind, value = self._queue.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.05)
                    continue

                if kind == "stop":
                    break
                elif kind == "state":
                    self._apply_state(value)
                elif kind == "message":
                    self._apply_message(*value)
                elif kind == "stream_chunk":
                    self._apply_stream_chunk(value)
                elif kind == "stream_end":
                    self._apply_stream_end()
                elif kind == "open_mic_tab":
                    self._open_mic_tab()
                elif kind == "open_settings_tab":
                    self._open_settings_tab()
                elif kind == "show_window":
                    self._show_window_now()
                elif kind == "mic_level":
                    self._update_mic_level()
                elif kind == "mic_test":
                    self._apply_mic_test_result(*value)
                elif kind == "rebuild_theme":
                    self._rebuild_ui_for_theme()
                elif kind == "rebuild_ui":
                    self._rebuild_ui_for_theme()
                elif kind == "mood":
                    self._apply_mood_color(value)
                elif kind == "fireworks":
                    self._page.run_task(
                        self._launch_fireworks_async, float(value or 6.0)
                    )

                try:
                    self._page.update()
                except Exception:
                    pass
            except Exception:
                log.exception("Ошибка в _process_queue")

    def _apply_mic_test_result(self, text: str, color: str) -> None:
        """Обновляет результат mic-теста — уже в главном потоке."""
        try:
            if self._mic_test_result is not None:
                self._mic_test_result.value = text
                self._mic_test_result.color = color
        except Exception:
            log.exception("_apply_mic_test_result упал")

    async def _launch_fireworks_async(self, duration: float = 6.0) -> None:
        """Анимация салюта — duration секунд, через Stack + Container. ... [6 строк]"""
        import random
        import math

        try:
            w = self._page.window.width or 1100
            h = self._page.window.height or 760

            # Stack — слой поверх всего окна
            stack = ft.Stack(width=w, height=h)

            # Тёмная подложка
            backdrop = ft.Container(
                width=w,
                height=h,
                bgcolor=ft.Colors.with_opacity(0.35, "#000000"),
            )
            stack.controls.append(backdrop)

            particles: list[dict] = []

            # Количество взрывов — пропорционально длительности
            n_bursts = max(4, int(duration * 1.2))
            bursts = []
            for i in range(n_bursts):
                cx = random.randint(150, w - 150)
                cy = random.randint(100, h - 250)
                color = random.choice([
                    "#ff1744", "#ffea00", "#00e5ff",
                    "#00e676", "#d500f9", "#ff6d00",
                ])
                # Интервал между взрывами
                spawn_time = (duration / max(1, n_bursts - 1)) * i * 0.6
                bursts.append((spawn_time, cx, cy, color))

            overlay = ft.Container(
                width=w, height=h, left=0, top=0,
                content=stack,
            )

            self._page.overlay.append(overlay)
            self._page.update()

            total_time = max(3.0, float(duration))
            frame_time = 0.05
            elapsed = 0.0
            spawned = [False] * len(bursts)

            while elapsed < total_time:
                # Спавн новых взрывов
                for i, (spawn_time, cx, cy, color) in enumerate(bursts):
                    if not spawned[i] and elapsed >= spawn_time:
                        spawned[i] = True
                        for _ in range(25):
                            angle = random.uniform(0, 2 * math.pi)
                            speed = random.uniform(2.5, 5.0)
                            container = ft.Container(
                                width=5, height=5,
                                border_radius=3,
                                bgcolor=color,
                                left=cx, top=cy,
                            )
                            stack.controls.append(container)
                            particles.append({
                                "ctrl": container,
                                "x": cx, "y": cy,
                                "vx": math.cos(angle) * speed,
                                "vy": math.sin(angle) * speed,
                                "life": 50,
                            })

                # Обновляем позиции
                for p in particles:
                    if p["life"] <= 0:
                        continue
                    p["x"] += p["vx"]
                    p["y"] += p["vy"]
                    p["vy"] += 0.15
                    p["life"] -= 1
                    try:
                        p["ctrl"].left = p["x"]
                        p["ctrl"].top = p["y"]
                        p["ctrl"].opacity = max(0.0, p["life"] / 50.0)
                    except Exception:
                        pass

                # Убираем мёртвые
                dead = [p for p in particles if p["life"] <= 0]
                for p in dead:
                    try:
                        stack.controls.remove(p["ctrl"])
                    except Exception:
                        pass
                particles = [p for p in particles if p["life"] > 0]

                try:
                    self._page.update()
                except Exception:
                    pass

                await asyncio.sleep(frame_time)
                elapsed += frame_time

            try:
                self._page.overlay.remove(overlay)
                self._page.update()
            except Exception:
                pass

        except Exception:
            log.exception("Fireworks: ошибка анимации")

    async def _mic_level_loop(self) -> None:
        """Обновляет уровень микрофона и следит за сменой системной темы. ... [4 строк]"""
        last_system_theme = _detect_system_theme()
        counter = 0

        while self._running:
            try:
                if self._rail and self._rail.selected_index == 1:
                    self._queue.put(("mic_level", None))

                counter += 1
                if counter >= 25:
                    counter = 0
                    if self.config.get("gui_theme") == "Системная":
                        current = _detect_system_theme()
                        if current != last_system_theme:
                            log.info("Системная тема Windows изменилась: %s → %s",
                                     last_system_theme, current)
                            last_system_theme = current
                            _apply_palette(current)
                            self._queue.put(("rebuild_theme", current))

                await asyncio.sleep(0.2)
            except Exception:
                log.exception("_mic_level_loop упал")
                await asyncio.sleep(1.0)

    def _apply_state(self, state: str) -> None:
        if state not in STATES:
            return
        self._state = state
        color, text, sub = STATES[state]

        size = {"idle": 80, "listening": 90, "speaking": 95, "error": 85}.get(state, 80)

        try:
            if self._status_circle:
                self._status_circle.bgcolor = color
                self._status_circle.width = size
                self._status_circle.height = size
                self._status_circle.border_radius = size // 2
                self._status_circle.shadow = ft.BoxShadow(
                    blur_radius=32, color=color, spread_radius=3,
                )
            if self._status_text:
                self._status_text.value = text
            if self._status_sub:
                self._status_sub.value = sub
        except Exception:
            log.exception("Ошибка в _apply_state")

    def _apply_mood_color(self, mood_state: str) -> None:
        """Обновляет свечение статус-сферы по mood (только в idle)."""
        try:
            from jarvis import mood as _mood
            if self._state != "idle":
                return  # во время listening/speaking цвет другой
            color = _mood.color()
            if self._status_circle:
                self._status_circle.bgcolor = color
                self._status_circle.shadow = ft.BoxShadow(
                    blur_radius=32, color=color, spread_radius=3,
                )
            log.info("GUI: статус-сфера перекрашена под mood=%s", mood_state)
        except Exception:
            log.exception("_apply_mood_color упал")

    def _avatar(self, is_user: bool) -> ft.Container:
        if is_user:
            bg = BG_BUBBLE_USER
            icon = ft.Icons.PERSON
            icon_color = "#ffffff"
        else:
            bg = BG_CARD
            icon = ft.Icons.SMART_TOY
            icon_color = ACCENT

        return ft.Container(
            content=ft.Icon(icon, size=20, color=icon_color),
            width=40,
            height=40,
            border_radius=20,
            bgcolor=bg,
            alignment=ft.Alignment.CENTER,
        )

    def _apply_message(self, role: str, text: str) -> None:
        try:
            ts = datetime.now().strftime("%H:%M")
            is_user = (role == "user")
            avatar = self._avatar(is_user)

            text_col = ft.Column(
                controls=[
                    ft.Text(
                        f"{'Вы' if is_user else 'Феникс'} • {ts}",
                        size=11, color=TEXT_DIM,
                    ),
                    ft.Text(text, size=14,
                            color="#ffffff" if is_user else TEXT,
                            selectable=True),
                ],
                spacing=2, expand=True,
            )

            bubble = ft.Container(
                content=ft.Row(
                    controls=[avatar, text_col] if not is_user else [text_col, avatar],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                bgcolor=BG_BUBBLE_USER if is_user else BG_BUBBLE_AI,
                padding=ft.Padding(left=14, right=14, top=10, bottom=10),
                border_radius=14,
                shadow=ft.BoxShadow(
                    blur_radius=10, color="#000000",
                    offset=ft.Offset(0, 2),
                ),
                animate_opacity=ft.Animation(300, ft.AnimationCurve.EASE_IN),
                opacity=1.0,
            )

            wrapper = ft.Container(
                content=bubble,
                alignment=ft.Alignment.CENTER_RIGHT if is_user else ft.Alignment.CENTER_LEFT,
                margin=ft.Margin(
                    left=80 if is_user else 0,
                    right=0 if is_user else 80,
                    top=0, bottom=0,
                ),
            )

            self._history_list.controls.append(wrapper)
        except Exception:
            log.exception("Ошибка в _apply_message")

    def _apply_stream_chunk(self, chunk: str) -> None:
        try:
            if self._stream_bubble is None:
                ts = datetime.now().strftime("%H:%M")
                self._stream_text = ""
                self._stream_label = ft.Text("", size=14, color=TEXT, selectable=True)

                avatar = self._avatar(is_user=False)

                text_col = ft.Column(
                    controls=[
                        ft.Text(f"Феникс • {ts}", size=11, color=TEXT_DIM),
                        self._stream_label,
                    ],
                    spacing=2, expand=True,
                )

                bubble = ft.Container(
                    content=ft.Row(
                        controls=[avatar, text_col],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                    bgcolor=BG_BUBBLE_AI,
                    padding=ft.Padding(left=14, right=14, top=10, bottom=10),
                    border_radius=14,
                    shadow=ft.BoxShadow(
                        blur_radius=10, color="#000000",
                        offset=ft.Offset(0, 2),
                    ),
                )

                wrapper = ft.Container(
                    content=bubble,
                    alignment=ft.Alignment.CENTER_LEFT,
                    margin=ft.Margin(left=0, right=80, top=0, bottom=0),
                )

                self._stream_bubble = wrapper
                self._history_list.controls.append(wrapper)

            self._stream_text += chunk
            self._stream_label.value = self._stream_text
        except Exception:
            log.exception("Ошибка в _apply_stream_chunk")

    def _apply_stream_end(self) -> None:
        self._stream_bubble = None
        self._stream_label = None
        self._stream_text = ""

    def _open_mic_tab(self) -> None:
        try:
            self._rail.selected_index = 1
            self._content_area.content = self._tabs[1]
            log.info("GUI: открыл вкладку «Микрофон»")
        except Exception:
            log.exception("Не удалось открыть вкладку «Микрофон»")

    def _open_settings_tab(self) -> None:
        try:
            self._rail.selected_index = 3
            self._content_area.content = self._tabs[3]
            log.info("GUI: открыл вкладку «Настройки»")
        except Exception:
            log.exception("Не удалось открыть вкладку «Настройки»")

    def _show_window_now(self) -> None:
        """Показывает окно — для launch_mode=tray."""
        try:
            if self._page is not None:
                self._page.window.visible = True
                self._page.window.minimized = False
                self._page.update()
                log.info("GUI: окно показано")
        except Exception:
            log.exception("Не удалось показать окно")

    # ---------------------------------------------------------------
    # Действия
    # ---------------------------------------------------------------

    def _on_nav_change(self, e) -> None:
        idx = e.control.selected_index
        log.info("Навигация: %d", idx)
        # Через get, а не [idx]: если _tabs и destinations рельса
        # разъехались, раньше здесь летел KeyError и вкладка
        # молча не переключалась.
        tab = self._tabs.get(idx)
        if tab is not None:
            self._content_area.content = tab
        else:
            log.warning("Навигация: вкладки %d нет в _tabs — игнорирую", idx)
        try:
            self._page.update()
        except Exception:
            pass

    def _on_mode_change(self, e) -> None:
        mode = e.control.value
        self.config.set("mode", mode)
        if self.jarvis is not None:
            self.jarvis.handler.mode = mode

    def _on_voice_change(self, e) -> None:
        self.config.set("tts_voice", e.control.value)

    def _on_memory_change(self, e) -> None:
        mem = e.control.value
        preset = {"short": (40, 10), "normal": (100, 20), "long": (200, 40)}.get(mem, (100, 20))
        self.config.update({
            "memory_max": preset[0],
            "llm_context_messages": preset[1],
        })

    def _on_llm_change(self, e) -> None:
        self.config.set("llm_model", e.control.value)

    def _on_ollama_change(self, e) -> None:
        self.config.set("ollama_url", e.control.value)

    def _on_tts_change(self, e) -> None:
        self.config.set("tts_backend", e.control.value)

    def _on_voice_quality_change(self, e) -> None:
        quality = e.control.value
        if quality not in ("medium", "high"):
            quality = "medium"

        self.config.set("tts_voice_quality", quality)

        if self.jarvis is not None and self.jarvis.speaker is not None:
            voice = self.config.get("tts_voice", "ruslan")
            try:
                self.jarvis.speaker._init_piper(voice)
                actual = getattr(self.jarvis.speaker, "_piper_quality", quality)
                if actual != quality:
                    log.warning("Piper: %s/%s не найден, использован %s/%s",
                                voice, quality, voice, actual)
                log.info("Piper переключён на %s/%s", voice, actual)
            except Exception:
                log.exception("Не удалось переключить качество голоса")

    def _on_rate_change(self, e) -> None:
        self.config.set("voice_rate", round(float(e.control.value), 2))

    def _on_theme_change(self, e) -> None:
        theme_name = e.control.value
        if theme_name not in THEMES:
            theme_name = "Системная"
        mode = THEMES[theme_name]
        self.config.set("gui_theme", theme_name)

        if mode == ft.ThemeMode.SYSTEM:
            palette_name = _detect_system_theme()
            log.info("Системная тема: %s", palette_name)
            _apply_palette(palette_name)
        elif mode == ft.ThemeMode.LIGHT:
            _apply_palette("light")
        else:
            _apply_palette("dark")

        try:
            self._page.theme_mode = mode
            self._page.bgcolor = BG_DARK
            self._rebuild_ui_for_theme()
            self._page.update()
        except Exception:
            log.exception("Ошибка в _on_theme_change")

    def _rebuild_ui_for_theme(self) -> None:
        """Пересобирает UI с новой палитрой. ... [6 строк]"""
        current_index = self._rail.selected_index if self._rail else 0

        saved_history = []
        if self._history_list is not None:
            saved_history = list(self._history_list.controls)

        self._tabs = {
            0: self._build_main_tab(),
            1: self._build_mic_tab(),
            2: self._build_persona_tab(),
            3: self._build_settings_tab(),
        }

        if saved_history and self._history_list is not None:
            self._history_list.controls = saved_history

        if self._content_area is not None:
            self._content_area.bgcolor = BG_DARK
            self._content_area.content = self._tabs.get(current_index, self._tabs[0])

        if self._rail is not None:
            self._rail.bgcolor = BG_CARD
            self._rail.indicator_color = ACCENT

        log.info("UI пересобран (тема/профиль), история сохранена: %d",
                 len(saved_history))

    def _on_send(self, e) -> None:
        text = self._input_field.value.strip()
        if not text:
            return
        self._input_field.value = ""
        self._run_command(text)

    def _on_mic_toggle(self, e) -> None:
        if self.jarvis is None:
            return
        self.jarvis.listening_enabled = not self.jarvis.listening_enabled
        self._mic_btn.icon = ft.Icons.MIC if self.jarvis.listening_enabled else ft.Icons.MIC_OFF
        self._mic_btn.icon_color = ACCENT if self.jarvis.listening_enabled else "#f85149"
        try:
            self._page.update()
        except Exception:
            pass

    def _run_command(self, cmd: str) -> None:
        """Запускает команду из GUI (текстовый ввод). ... [5 строк]"""
        if self.jarvis is None:
            return

        def _run():
            try:
                self.set_state("listening")
                self.add_message("user", cmd)
                self.jarvis.speaker.stop()
                self.jarvis.speaker.wait_end(timeout=1.0)
                with self.jarvis.cmd_lock:
                    reply = self.jarvis.handler.handle(cmd)
                    if not reply.is_stream:
                        self.add_message("assistant", reply.text or "")
                    self.jarvis.say(reply)
            except Exception:
                log.exception("Ошибка команды %r", cmd)
                self.set_state("error")

        threading.Thread(target=_run, daemon=True, name="gui-cmd").start()
```

### `jarvis/history.py`

```python
"""История последних действий для отмены («стоп, не то»). ... [15 строк]"""

import logging
import threading
from collections import deque

log = logging.getLogger("jarvis.history")

_MAX = 5
_stack: deque = deque(maxlen=_MAX)
_lock = threading.Lock()


def push(item: dict) -> None:
    """Кладёт действие в стек. Отбрасывает лишнее."""
    if not isinstance(item, dict) or "action" not in item:
        return
    with _lock:
        _stack.append(item)
    log.info("История: +%s (всего %d)", item.get("action"), len(_stack))
    
def push_macro(steps: list) -> None:
    """Кладёт макрос как ОДНУ запись в историю. ... [3 строк]"""
    if not isinstance(steps, list) or not steps:
        return
    # Отбрасываем steps с action="wait" — их откатывать нечего
    real_steps = [s for s in steps
                  if isinstance(s, dict) and s.get("action") not in ("wait",)]
    if not real_steps:
        return
    push({"action": "macro", "steps": real_steps})


def pop() -> dict | None:
    """Достаёт последнее действие. Возвращает None, если пусто."""
    with _lock:
        if not _stack:
            return None
        return _stack.pop()


def peek() -> dict | None:
    """Смотрит последнее действие без удаления."""
    with _lock:
        if not _stack:
            return None
        return _stack[-1]


def clear() -> None:
    with _lock:
        _stack.clear()


def size() -> int:
    with _lock:
        return len(_stack)
```

### `jarvis/installed.py`

```python
"""Индекс установленных программ по ярлыкам меню «Пуск». ... [4 строк]"""

import logging
import os
from pathlib import Path

from jarvis.matching import match_score

log = logging.getLogger("jarvis.installed")

# Служебные ярлыки, которые не надо предлагать к запуску
_EXCLUDE = ("uninstall", "удал", "help", "справк", "readme", "manual",
            "website", "веб-сайт", "документ", "update", "repair", "license")


def scan_start_menu() -> dict[str, Path]:
    """Имя программы (нижний регистр) -> путь к .lnk."""
    roots = [
        Path(os.path.expandvars(r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs")),
        Path(os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs")),
    ]
    index: dict[str, Path] = {}
    for root in roots:
        if not root.exists():
            continue
        for lnk in root.rglob("*.lnk"):
            name = lnk.stem.strip().lower()
            if not name or any(x in name for x in _EXCLUDE):
                continue
            index.setdefault(name, lnk)
    log.info("Меню «Пуск»: проиндексировано %d программ", len(index))
    return index


def find_installed(index: dict[str, Path], spoken: str,
                   threshold: float = 0.75) -> tuple[str, Path] | None:
    best_name, best_path, best_score = None, None, 0.0
    for name, path in index.items():
        score = match_score(spoken, name)
        if score > best_score:
            best_name, best_path, best_score = name, path, score
    if best_score >= threshold:
        log.info("Установленная программа: %r -> %r (score %.2f)", spoken, best_name, best_score)
        return best_name, best_path
    log.info("В меню «Пуск» не найдено: %r (лучший score %.2f, %r)",
             spoken, best_score, best_name)
    return None
```

### `jarvis/intents/__init__.py`

```python
"""Разбор команд Феникса — пакет. ... [5 строк]"""
from jarvis.intents.handler import IntentHandler
from jarvis.text_utils import normalize

__all__ = ["IntentHandler", "normalize"]
```

### `jarvis/intents/context.py`

```python
"""Контекст, который передаётся между стадиями pipeline."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Ctx:
    """Одна команда и её окружение. ... [6 строк]"""
    cmd: str
    original_cmd: str = ""
    handler: Any = None
    state: dict = field(default_factory=dict)
```

### `jarvis/intents/execute.py`

```python
"""Dispatch: action → функция-обработчик. ... [21 строк]"""

import datetime
import logging
import time
from pathlib import Path

from jarvis import APP_NAME, actions, files, history, uia
from jarvis import modes, packs, profile, tasks, timers, voices, weather
from jarvis import paths as _paths
from jarvis.text_utils import normalize

log = logging.getLogger("jarvis.intents")
actions_log = logging.getLogger("jarvis.actions")


# =================================================================
# Weather / currency — sanity-проверка на мусорный target
# =================================================================

_WEATHER_BAD_TARGET = (
    "курс", "доллар", "рубл", "евро", "юан", "валют",
    "цену", "цена", "поиск", "найди", "погод", "прогноз",
    "пожалуйста", "сколько", "стоит",
)

_FOLDER_TITLES = {
    "Desktop": "на рабочем столе", "Downloads": "в загрузках",
    "Documents": "в документах", "Pictures": "в изображениях",
    "Music": "в музыке", "Videos": "в видео",
    "Screenshots": "в скриншотах",
}


# =================================================================
# Точка входа
# =================================================================

def execute_intent(handler, intent: dict) -> str | None:
    """Находит обработчик в _DISPATCH и вызывает."""
    action = intent.get("action")
    target = normalize(str(intent.get("target") or ""))
    query = str(intent.get("query") or "").strip()

    actions_log.info("Интент: %s (target=%r, query=%r)", action, target, query)

    fn = _DISPATCH.get(action)
    if fn is None:
        return None
    return fn(handler, intent, target, query)


def execute_steps(handler, steps: list) -> str | None:
    """Многошаговый сценарий. ... [3 строк]"""
    reply = None
    executed: list = []

    for step in steps[:6]:
        if not isinstance(step, dict):
            continue
        action = step.get("action")
        if action == "wait":
            time.sleep(min(float(step.get("seconds", 1) or 1), 15))
            executed.append(step)
            continue
        if action == "media_key":
            actions.media_key(str(step.get("key", "")), int(step.get("times", 1) or 1))
            executed.append(step)
            continue
        r = execute_intent(handler, step)
        if r:
            reply = r
        executed.append(step)

    real_steps = [s for s in executed
                  if isinstance(s, dict) and s.get("action") not in ("wait",)]
    if real_steps:
        history.push_macro(real_steps)

    return reply


# =================================================================
# Обработчики
# =================================================================

def _do_open_app(handler, intent, target, query):
    from jarvis.apps import find_app
    from jarvis.installed import find_installed

    if not target:
        return None
    if intent.get("minimized"):
        hit = find_installed(handler.installed, target)
        if hit:
            actions.open_path(hit[1], minimized=True)
            return f"Открываю {hit[0]}."
    running = actions.find_process(target, threshold=0.8)
    if running:
        from jarvis.actions import activate_window_by_title
        if activate_window_by_title(target):
            return f"Переключаюсь на {target}."
    return _do_open(handler, target)


def _do_close_app(handler, intent, target, query):
    if not target:
        return None
    return _do_close(handler, target)


def _do_open_file(handler, intent, target, query):
    if handler.last_file:
        actions.open_path(handler.last_file)
        return "Открываю."
    return "Пока нечего открывать."


def _do_open_site(handler, intent, target, query):
    # Берём СЫРОЙ target из intent, а не нормализованный: normalize()
    # вырезает пунктуацию, и «habr.com» превращается в «habr com».
    # Раньше из-за этого ответ озвучивался как «Открываю habr com»,
    # а неизвестные домены уходили в guess_site и открывались
    # как gismeteoru.ru.
    raw = str(intent.get("target") or "").strip()
    site = raw or query
    if not site:
        return None
    if "." in raw:
        url = actions.normalize_url(raw)
        actions.open_url(url)
        return f"Открываю {site}."
    return _open_site(site)


def _do_search(handler, intent, target, query):
    q = query or target
    if not q:
        return None
    engine = intent.get("engine")
    if engine not in ("google", "youtube", "wiki"):
        engine = "google"
    actions.open_search(engine, q)
    return f"Ищу: {q}."


def _do_screenshot(handler, intent, target, query):
    path = actions.take_screenshot()
    handler.last_file = path
    return f"Скриншот сохранён в папку {path.parent.name}."


def _do_open_folder(handler, intent, target, query):
    if not target:
        return None
    # explicit только со словом «папка» — как в _do_open. Иначе
    # «открой музыку» открывала папку Music вместо плеера, хотя
    # комментарий в files.py прямо требует обратного.
    folder = files.resolve_folder(target, explicit="папк" in target)
    if folder:
        handler.last_folder = folder
        files.open_folder(folder)
        return f"Открываю папку {folder.name}."
    return None


def _do_list_folder(handler, intent, target, query):
    folder = (files.resolve_folder(target, explicit="папк" in target)
              if target else handler.last_folder)
    if folder:
        handler.last_folder = folder
        return files.describe_folder(folder)
    return None


def _do_create_file(handler, intent, target, query):
    folder_name = str(intent.get("folder") or "").strip()
    folder = None
    if folder_name:
        folder = files.resolve_folder(folder_name, explicit=True)
        if folder is None:
            return f"Папку «{folder_name}» не нашёл. Куда создать файл?"
    if folder is None:
        folder = _paths.user_home() / "Desktop"
    path = files.create_file(folder, target or "новый файл")
    handler.last_file = path
    title = _FOLDER_TITLES.get(folder.name, f"в папке {folder.name}")
    return f"Создал {path.name} {title}."


def _do_type_text(handler, intent, target, query):
    text = str(intent.get("text") or intent.get("target") or "").strip()
    ok = actions.type_text(text)
    return f"Печатаю: {text}." if ok else "Не удалось напечатать."


def _do_media_key(handler, intent, target, query):
    ok = actions.media_key(str(intent.get("key", "")),
                           int(intent.get("times", 1) or 1))
    return "Готово." if ok else None


def _do_play_pause(handler, intent, target, query):
    actions.media_key("play")
    return "Готово."


def _do_next_track(handler, intent, target, query):
    actions.media_key("next")
    return "Переключаю."


def _do_prev_track(handler, intent, target, query):
    actions.media_key("prev")
    return "Возвращаю."


def _do_volume_up(handler, intent, target, query):
    actions.media_key("vol_up", 5)
    return "Громче."


def _do_volume_down(handler, intent, target, query):
    actions.media_key("vol_down", 5)
    return "Тише."


def _do_mute(handler, intent, target, query):
    actions.media_key("mute")
    return "Без звука."


def _do_switch_layout(handler, intent, target, query):
    ok = actions.switch_layout()
    if ok:
        history.push({"action": "switch_layout"})
    return "Переключаю раскладку." if ok else None


def _do_set_layout_ru(handler, intent, target, query):
    return "Русская раскладка." if actions.set_layout_ru() else None


def _do_set_layout_en(handler, intent, target, query):
    return "Английская раскладка." if actions.set_layout_en() else None


def _do_get_layout(handler, intent, target, query):
    layout = actions.get_layout()
    if layout == "ru":
        return "Русская раскладка."
    if layout == "en":
        return "Английская раскладка."
    return None


def _do_set_volume(handler, intent, target, query):
    try:
        pct = int(intent.get("percent") or 50)
    except (TypeError, ValueError):
        pct = 50
    prev = actions.get_volume()
    ok = actions.set_volume(pct)
    if ok:
        history.push({"action": "set_volume", "prev_value": prev})
    return f"Громкость: {pct}%." if ok else None


def _do_get_volume(handler, intent, target, query):
    vol = actions.get_volume()
    return f"Громкость: {vol}%." if vol is not None else None


def _do_set_brightness(handler, intent, target, query):
    try:
        pct = int(intent.get("percent") or 50)
    except (TypeError, ValueError):
        pct = 50
    prev = actions.get_brightness()
    ok = actions.set_brightness(pct)
    if ok:
        history.push({"action": "set_brightness", "prev_value": prev})
    return f"Яркость: {pct}%." if ok else None


def _do_get_brightness(handler, intent, target, query):
    br = actions.get_brightness()
    return f"Яркость: {br}%." if br is not None else None


def _do_clipboard_read(handler, intent, target, query):
    text = actions.clipboard_read()
    if not text:
        return "Буфер обмена пуст."
    return f"В буфере: {text[:400]}"


def _do_copy_selection(handler, intent, target, query):
    if not actions.copy_selection():
        return "Не удалось скопировать."
    time.sleep(0.15)
    text = actions.clipboard_read()
    if text:
        short = text[:200] + ("..." if len(text) > 200 else "")
        return f"Скопировал: {short}"
    return "Скопировал выделенное."


def _do_clipboard_copy_last(handler, intent, target, query):
    last = handler._last_reply
    if not last:
        return "Нечего копировать."
    ok = actions.clipboard_write(last)
    return "Скопировал свой ответ в буфер." if ok else "Не удалось скопировать."


def _do_clipboard_clear(handler, intent, target, query):
    ok = actions.clipboard_clear()
    return "Буфер очищен." if ok else "Не удалось очистить буфер."


def _do_minimize_all(handler, intent, target, query):
    actions.minimize_all()
    return "Сворачиваю всё."


def _do_minimize_window(handler, intent, target, query):
    if not target:
        return None
    ok = actions.minimize_window_by_title(target)
    return f"Сворачиваю {target}." if ok else f"Окно {target} не нашёл."


def _do_maximize_window(handler, intent, target, query):
    if not target:
        return None
    ok = actions.maximize_window_by_title(target)
    return f"Разворачиваю {target}." if ok else f"Окно {target} не нашёл."


def _do_activate_window(handler, intent, target, query):
    if not target:
        return None
    ok = actions.activate_window_by_title(target)
    return f"Переключаюсь на {target}." if ok else f"Окно {target} не нашёл."


def _do_minimize_active(handler, intent, target, query):
    actions.minimize_active()
    return "Сворачиваю активное окно."


def _do_maximize_active(handler, intent, target, query):
    actions.maximize_active()
    return "Разворачиваю активное окно."


def _do_switch_window(handler, intent, target, query):
    actions.switch_window(back=bool(intent.get("back")))
    return "Переключаю окно."


def _do_set_mode(handler, intent, target, query):
    prev_mode = handler.mode
    mode = str(intent.get("mode") or "combo").lower()
    if mode not in ("commands", "llm", "combo"):
        mode = "combo"
    reply = modes.set_mode(mode, handler.config)
    if mode != prev_mode:
        history.push({"action": "set_mode", "prev_value": prev_mode})
    handler.mode = mode
    return reply


def _do_load_pack(handler, intent, target, query):
    name = packs.normalize_name(str(intent.get("name") or ""))
    available = packs.list_available()
    if name not in available:
        return f"Пак '{name}' не найден. Доступны: {', '.join(available)}."
    if name in handler.active_packs:
        return f"Пак '{name}' уже активен."
    handler.active_packs.append(name)
    packs.save_active(handler.active_packs, handler.config)
    _reload_packs(handler)
    return f"Пак '{name}' загружен."


def _do_unload_pack(handler, intent, target, query):
    name = packs.normalize_name(str(intent.get("name") or ""))
    if name not in handler.active_packs:
        return f"Пак '{name}' и так не активен."
    handler.active_packs.remove(name)
    packs.save_active(handler.active_packs, handler.config)
    _reload_packs(handler)
    return f"Пак '{name}' выгружен."


def _do_list_packs(handler, intent, target, query):
    available = packs.list_available()
    active_str = ", ".join(handler.active_packs) if handler.active_packs else "нет"
    return f"Доступны: {', '.join(available)}. Активны: {active_str}."


def _do_change_voice(handler, intent, target, query):
    prev = voices.current_voice(handler.config)
    voice = str(intent.get("voice") or "").strip().lower()
    reply = voices.switch(voice, handler.config)
    if voice in voices.PIPER_VOICES and voice != prev:
        history.push({"action": "change_voice", "prev_value": prev})
    return reply


def _do_list_voices(handler, intent, target, query):
    return voices.handle_voice_command("список голосов", handler.config)


def _do_set_timer(handler, intent, target, query):
    text = str(intent.get("text") or "").strip()
    seconds = intent.get("seconds")
    time_str = intent.get("time")
    fire_at = None

    if seconds:
        try:
            fire_at = time.time() + float(seconds)
        except (TypeError, ValueError):
            fire_at = None
    elif time_str:
        try:
            hh, mm = str(time_str).split(":")
            now = datetime.datetime.now()
            t = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
            if t <= now:
                t += datetime.timedelta(days=1)
            fire_at = t.timestamp()
        except Exception:
            fire_at = None

    if fire_at:
        timers.add(text, fire_at)
        when = datetime.datetime.fromtimestamp(fire_at).strftime("%H:%M")
        return f"Напомню в {when}: {text}." if text else f"Напомню в {when}."
    return "Не понял время напоминания."


def _do_list_timers(handler, intent, target, query):
    return timers.format_list(timers.list_all())


def _do_cancel_timers(handler, intent, target, query):
    n = timers.remove_all()
    return f"Отменено напоминаний: {n}." if n else "Напоминаний не было."


def _do_add_task(handler, intent, target, query):
    text = str(intent.get("text") or intent.get("task") or "").strip()
    if not text:
        return "Что добавить?"
    task = tasks.add(text)
    return f"Добавил: {task['text']}."


def _do_list_tasks(handler, intent, target, query):
    return tasks.format_list()


def _do_done_task(handler, intent, target, query):
    q = str(intent.get("task") or "").strip()
    task = tasks.mark_done(q)
    return f"Отметил: {task['text']}." if task else f"Задачу «{q}» не нашёл."


def _do_remove_task(handler, intent, target, query):
    q = str(intent.get("task") or "").strip()
    task = tasks.remove(q)
    return f"Убрал: {task['text']}." if task else f"Задачу «{q}» не нашёл."


def _do_clear_tasks(handler, intent, target, query):
    n = tasks.clear_all()
    return f"Очищено задач: {n}." if n else "Список и так пуст."


def _do_open_config(handler, intent, target, query):
    actions.open_path(_paths.config_path())
    return "Открываю конфиг."


def _do_open_log(handler, intent, target, query):
    log_path = _paths.logs_dir() / "jarvis.log"
    actions.open_path(log_path)
    return "Открываю журнал."


def _do_open_profile(handler, intent, target, query):
    prof_path = profile.profile_path()
    prefer = str(intent.get("editor") or "auto").lower()
    ok = actions.open_in_editor(prof_path, prefer=prefer)
    if ok:
        return f"Открываю профиль {profile.current()}."
    return f"Не удалось открыть профиль: {prof_path}"


def _do_get_weather(handler, intent, target, query):
    city = str(intent.get("target") or "").strip()
    day = "tomorrow" if intent.get("day") == "tomorrow" else "today"

    if any(w in city.lower() for w in _WEATHER_BAD_TARGET):
        log.warning("get_weather: LLM подсунула мусор target=%r — игнорирую", city)
        city = ""

    if not city:
        city = profile.get("default_city")
    if not city:
        handler._pending_question = {
            "type": "city_for_weather",
            "day": day,
            "expires_at": time.time() + 30,
        }
        return "В каком городе узнать погоду?"

    w = weather.get_weather(city, day=day)
    if not w:
        return f"Не удалось узнать погоду для «{city}». Проверь название или интернет."
    return weather.describe_weather(w)


def _do_get_currency(handler, intent, target, query):
    code = str(intent.get("target") or "").strip().upper()
    r = weather.get_currency_rates()
    return weather.describe_currency(r, code=code)


def _do_delete_profile(handler, intent, target, query):
    name = str(intent.get("target") or "").strip()
    if profile.delete(name):
        return f"Профиль {name} удалён."
    return f"Профиль {name} не найден или активен."


_KEY_MAP = {
    "имя": "name", "name": "name",
    "город": "default_city", "default_city": "default_city",
    "city": "default_city", "мой город": "default_city",
}


def _do_set_profile(handler, intent, target, query):
    key = str(intent.get("key") or "").strip()
    value = str(intent.get("value") or "").strip()
    if not key or not value:
        return "Не понял, что сохранить."

    key = _KEY_MAP.get(key.lower(), key.lower())
    if key not in ("name", "default_city", "prev_city"):
        return f"Не знаю, что такое «{key}»."

    if key == "default_city":
        prev = profile.get("default_city")
        if prev and prev.lower() != value.lower():
            profile.set("prev_city", prev)

    if profile.set(key, value):
        if key == "name":
            return f"Имя изменено на {value}."
        if key == "default_city":
            return f"Город изменён на {value}."
        return f"Сохранено: {key} = {value}."
    return "Не удалось сохранить."


def _do_get_profile(handler, intent, target, query):
    key = str(intent.get("key") or "").strip()
    key = _KEY_MAP.get(key.lower(), key.lower())

    if key == "name":
        v = profile.get("name")
        return f"Тебя зовут {v}." if v else "Имя не задано."
    if key == "default_city":
        v = profile.get("default_city")
        return f"Твой город — {v}." if v else "Город не задан."
    return "Не знаю, что прочитать."


def _do_answer(handler, intent, target, query):
    reply = intent.get("reply")
    return str(reply)[:600] if reply else None


# =================================================================
# Открытие / закрытие — вынесено сюда, используется в open_app
# =================================================================

BROWSER_WORDS = frozenset({
    "браузер", "браузере", "браузером",
    "хром", "хроме", "интернет", "интернете",
})


def _do_open(handler, target: str) -> str:
    """Открыть что угодно: приложение, сайт, папку, игру, ярлык."""
    from jarvis.apps import find_app
    from jarvis.installed import find_installed
    from jarvis.steam import find_game
    from jarvis.intents.sites import get_sites

    if not target:
        return "Что именно открыть?"
    if target in {"его", "ее", "это", "этот файл", "файл", "последний файл"}:
        if handler.last_file:
            actions.open_path(handler.last_file)
            return "Открываю."
        return "Пока нечего открывать."

    tokens = target.split()
    rest = [t for t in tokens if t not in BROWSER_WORDS]
    if len(rest) < len(tokens):
        if not rest:
            actions.open_browser()
            return "Открываю браузер."
        return _open_site(" ".join(rest))

    app = find_app(handler.apps, target)
    if app:
        spec = app.resolve_open()
        if spec is None:
            return f"{app.title} не найден на этом компьютере."
        actions.run_spec(spec)
        return f"Открываю {app.title}."

    for key, (title, url) in get_sites().items():
        if key in target.split() or target == key:
            actions.open_url(url)
            return f"Открываю {title}."

    folder = files.resolve_folder(target, explicit="папк" in target)
    if folder:
        handler.last_folder = folder
        files.open_folder(folder)
        return f"Открываю папку {folder.name}."

    game = find_game(handler.steam_games, target)
    if game:
        title, appid = game
        actions.run_spec(("uri", f"steam://rungameid/{appid}"))
        return f"Запускаю {title}."

    hit = find_installed(handler.installed, target)
    if hit:
        name, lnk = hit
        actions.open_path(lnk)
        return f"Открываю {name}."

    return _open_site(target)


def _open_site(name: str) -> str:
    from jarvis.intents.sites import get_sites

    if not name:
        return "Какой сайт открыть?"
    for key, (title, url) in get_sites().items():
        if name == key or key in name.split():
            actions.open_url(url)
            return f"Открываю {title}."
    url = actions.spoken_domain(name) or actions.guess_site(name)
    if url:
        actions.open_url(url)
        return f"Открываю сайт {name}."
    return f"Сайт {name} не нашёл. Скажите «найди {name}», и я поищу."


def _do_close(handler, target: str) -> str:
    from jarvis.apps import find_app

    if not target:
        return "Что именно закрыть?"
    if any(w in target for w in ("браузер", "интернет", "хром")):
        return "Закрываю браузер." if actions.close_browser() else "Браузер не запущен."
    app = find_app(handler.apps, target)
    if app and app.procs:
        ok = any(actions.kill_process(p) for p in app.procs)
        if ok:
            return f"Закрываю {app.title}."
    exe = actions.find_process(target)
    if exe:
        actions.kill_process(exe)
        return f"Закрываю {exe.removesuffix('.exe')}."
    if app:
        return f"{app.title} сейчас не запущен."
    return f"Не нашёл запущенной программы {target}."


def _reload_packs(handler) -> None:
    from jarvis.intents.fast.custom import load_packs_as_custom
    handler.custom = (list(handler._config_custom_original)
                      + load_packs_as_custom(handler.config))


# =================================================================
# UIA-обработчики
# =================================================================

def _do_uia_read_window(handler, intent, target, query):
    text = uia.read_active_text_stripped(max_chars=1500)
    if not text:
        return "В активном окне не вижу текста."
    if len(text) > 400:
        text = text[:400] + "... (ещё много)"
    return f"Читаю: {text}"


def _do_uia_read_url(handler, intent, target, query):
    url = uia.read_browser_url()
    if not url:
        return "Активное окно — не браузер, или не вижу URL."
    return f"Открыт сайт: {url}"


def _do_uia_read_tab(handler, intent, target, query):
    title = uia.read_browser_tab_title()
    if not title:
        return "Активное окно — не браузер."
    return f"Активная вкладка: {title}"


def _do_uia_list_tabs(handler, intent, target, query):
    tabs = uia.read_browser_tabs()
    if not tabs:
        return "Не вижу открытых вкладок."
    return "Открыты: " + "; ".join(tabs[:10]) + "."


def _do_uia_close_tab(handler, intent, target, query):
    if not target:
        return "Какую вкладку закрыть?"
    if target.lower() in ("эту", "текущую", "это"):
        actions.hotkey(["ctrl", "w"])
        return "Закрыл текущую вкладку."
    ok = uia.close_browser_tab(target)
    return f"Закрыл вкладку {target}." if ok else f"Вкладку «{target}» не нашёл."


def _do_uia_switch_tab(handler, intent, target, query):
    if not target:
        return "На какую вкладку переключиться?"
    ok = uia.switch_browser_tab(target)
    return f"Переключился на {target}." if ok else f"Вкладку «{target}» не нашёл."


def _do_uia_click_button(handler, intent, target, query):
    if not target:
        return "Какую кнопку нажать?"
    ok = uia.click_button(target)
    return f"Нажал «{target}»." if ok else f"Кнопку «{target}» не нашёл."


def _do_uia_active_window(handler, intent, target, query):
    return uia.describe_active_window()


def _do_uia_menu(handler, intent, target, query):
    if not target:
        return "Какой пункт меню?"
    ok = uia.click_menu_item(target)
    return f"Кликнул: {target}." if ok else f"Меню «{target}» не нашёл."


# =================================================================
# Dispatch-таблица
# =================================================================

_DISPATCH = {
    "open_app":           _do_open_app,
    "close_app":          _do_close_app,
    "open_file":          _do_open_file,
    "open_site":          _do_open_site,
    "search":             _do_search,
    "screenshot":         _do_screenshot,
    "open_folder":        _do_open_folder,
    "list_folder":        _do_list_folder,
    "create_file":        _do_create_file,
    "type_text":          _do_type_text,
    "media_key":          _do_media_key,
    "play_pause":         _do_play_pause,
    "next_track":         _do_next_track,
    "prev_track":         _do_prev_track,
    "volume_up":          _do_volume_up,
    "volume_down":        _do_volume_down,
    "mute":               _do_mute,
    "switch_layout":      _do_switch_layout,
    "set_layout_ru":      _do_set_layout_ru,
    "set_layout_en":      _do_set_layout_en,
    "get_layout":         _do_get_layout,
    "set_volume":         _do_set_volume,
    "get_volume":         _do_get_volume,
    "set_brightness":     _do_set_brightness,
    "get_brightness":     _do_get_brightness,
    "clipboard_read":     _do_clipboard_read,
    "copy_selection":     _do_copy_selection,
    "clipboard_copy_last": _do_clipboard_copy_last,
    "clipboard_clear":    _do_clipboard_clear,
    "minimize_all":       _do_minimize_all,
    "minimize_window":    _do_minimize_window,
    "maximize_window":    _do_maximize_window,
    "activate_window":    _do_activate_window,
    "minimize_active":    _do_minimize_active,
    "maximize_active":    _do_maximize_active,
    "switch_window":      _do_switch_window,
    "set_mode":           _do_set_mode,
    "load_pack":          _do_load_pack,
    "unload_pack":        _do_unload_pack,
    "list_packs":         _do_list_packs,
    "change_voice":       _do_change_voice,
    "list_voices":        _do_list_voices,
    "set_timer":          _do_set_timer,
    "list_timers":        _do_list_timers,
    "cancel_timers":      _do_cancel_timers,
    "add_task":           _do_add_task,
    "list_tasks":         _do_list_tasks,
    "done_task":          _do_done_task,
    "remove_task":        _do_remove_task,
    "clear_tasks":        _do_clear_tasks,
    "open_config":        _do_open_config,
    "open_log":           _do_open_log,
    "open_profile":       _do_open_profile,
    "get_weather":        _do_get_weather,
    "get_currency":       _do_get_currency,
    "delete_profile":     _do_delete_profile,
    "set_profile":        _do_set_profile,
    "get_profile":        _do_get_profile,
    "answer":             _do_answer,
    # === UIA ===
    "uia_read_window":    _do_uia_read_window,
    "uia_read_url":       _do_uia_read_url,
    "uia_read_tab":       _do_uia_read_tab,
    "uia_list_tabs":      _do_uia_list_tabs,
    "uia_close_tab":      _do_uia_close_tab,
    "uia_switch_tab":     _do_uia_switch_tab,
    "uia_click_button":   _do_uia_click_button,
    "uia_active_window":  _do_uia_active_window,
    "uia_menu":           _do_uia_menu,
}
```

### `jarvis/intents/fast/__init__.py`

```python
"""Реестр быстрых обработчиков. ... [6 строк]"""

from jarvis.intents.fast.custom import match_custom, load_custom
from jarvis.intents.fast.small_talk import small_talk
from jarvis.intents.fast.music import music_fast
from jarvis.intents.fast.screenshot import screenshot_fast
from jarvis.intents.fast.uia import uia_fast
from jarvis.intents.fast.open import open_fast, open_profile_fast
from jarvis.intents.fast.voices import voices_fast
from jarvis.intents.fast.packs import packs_fast
from jarvis.intents.fast.timers import timers_fast
from jarvis.intents.fast.tasks import tasks_fast
from jarvis.intents.fast.persona import persona_fast
from jarvis.intents.fast.profile import profile_fast
from jarvis.intents.fast.memory import memory_fast
from jarvis.intents.fast.system import system_fast
from jarvis.intents.fast.debug import debug_fast
from jarvis.intents.fast.undo import undo_fast
from jarvis.intents.fast.correction import correction_fast
from jarvis.intents.fast.weather import weather_currency_fast


__all__ = ["build_registry", "load_custom", "match_custom"]


def build_registry(handler) -> list:
    """Собирает реестр для конкретного handler'а."""
    return [
        ("custom",           lambda cmd: match_custom(handler, cmd)),
        ("small_talk",       lambda cmd: small_talk(handler, cmd)),
        ("music",            lambda cmd: music_fast(handler, cmd)),
        ("screenshot",       lambda cmd: screenshot_fast(handler, cmd)),
        ("uia",              lambda cmd: uia_fast(handler, cmd)),
        ("open_profile",     lambda cmd: open_profile_fast(handler, cmd)),
        ("open",             lambda cmd: open_fast(handler, cmd)),
        ("voices",           lambda cmd: voices_fast(handler, cmd)),
        ("packs",            lambda cmd: packs_fast(handler, cmd)),
        ("timers",           lambda cmd: timers_fast(handler, cmd)),
        ("tasks",            lambda cmd: tasks_fast(handler, cmd)),
        ("persona",          lambda cmd: persona_fast(handler, cmd)),
        ("profile",          lambda cmd: profile_fast(handler, cmd)),
        ("memory",           lambda cmd: memory_fast(handler, cmd)),
        ("system",           lambda cmd: system_fast(handler, cmd)),
        ("debug",            lambda cmd: debug_fast(handler, cmd)),
        ("correction",       lambda cmd: correction_fast(handler, cmd)),
        ("undo",             lambda cmd: undo_fast(handler, cmd)),
        ("weather_currency", lambda cmd: weather_currency_fast(handler, cmd)),
    ]
```

### `jarvis/intents/fast/correction.py`

```python
"""Коррекция: «это не то, я сказал логи». ... [4 строк]"""

import re

from jarvis import learning


def correction_fast(handler, cmd: str) -> str | None:
    m = re.match(
        r"^(?:это\s+)?не\s+то\s*,?\s*(?:я\s+сказал[а]?\s+)?(.+)$",
        cmd,
    )
    if not m:
        return None

    right = m.group(1).strip(" ,.:!?")
    if not right:
        return None

    wrong = handler._last_cmd
    if wrong and wrong != cmd:
        learning.add_correction(wrong, right)
        return f"Понял, запомнил. Повторяю: {right}."
    return "Что было не так?"
```

### `jarvis/intents/fast/custom.py`

```python
"""Пользовательские команды: из config.json и из паков. ... [5 строк]"""

import logging
from difflib import SequenceMatcher

from jarvis import packs
from jarvis.text_utils import normalize

log = logging.getLogger("jarvis.intents")


def load_custom(config) -> list:
    """Собирает custom-команды из config.json + активных паков. ... [3 строк]"""
    result = []

    # Из config.json → custom_commands
    for entry in config.get("custom_commands", []):
        phrases = [normalize(p) for p in entry.get("phrases", []) if p.strip()]
        action = entry.get("action", "").strip() or entry.get("steps")
        if phrases and action:
            result.append((phrases, action, entry.get("reply", "Выполняю.")))

    # Из активных паков
    result.extend(load_packs_as_custom(config))
    return result


def load_packs_as_custom(config) -> list:
    """Только команды из активных паков."""
    result = []
    for entry in packs.load_active(config):
        phrases = [normalize(p) for p in entry.get("phrases", []) if p.strip()]
        action = entry.get("action", "").strip() or entry.get("steps")
        if phrases and action:
            result.append((phrases, action, entry.get("reply", "Выполняю.")))
    return result


def match_custom(handler, cmd: str) -> str | None:
    """Точное совпадение или нечёткое (>=0.85, обе фразы >=12 символов)."""
    from jarvis import actions
    from jarvis.intents.execute import execute_steps

    for phrases, action, reply in handler.custom:
        for phrase in phrases:
            if cmd == phrase:
                log.info("Custom (точно): %r → %r, action=%r", cmd, phrase, action)
                if isinstance(action, list):
                    return execute_steps(handler, action) or reply
                actions.run_spec(actions.spec_from_string(action))
                return reply

            # Нечёткий матч — только для длинных фраз.
            # Короткие («вк», «отк») слишком легко путаются.
            if len(cmd) >= 12 and len(phrase) >= 12:
                ratio = SequenceMatcher(None, cmd, phrase).ratio()
                if ratio >= 0.85:
                    log.info("Custom (нечётко %.2f): %r → %r, action=%r",
                             ratio, cmd, phrase, action)
                    if isinstance(action, list):
                        return execute_steps(handler, action) or reply
                    actions.run_spec(actions.spec_from_string(action))
                    return reply
    return None
```

### `jarvis/intents/fast/debug.py`

```python
"""Диагностика: «что ты слышал», «почему не понял»."""

import re


def debug_fast(handler, cmd: str) -> str | None:
    # «что ты слышал»
    if (re.search(r"(что|чё)\s+ты\s+слышал", cmd)
            or cmd in {"что ты слышал", "что слышал", "история"}):
        phrases = []
        if handler.listener is not None and hasattr(handler.listener, "recent_phrases"):
            phrases = list(handler.listener.recent_phrases)
        if not phrases:
            phrases = list(handler._recent_phrases)
        if not phrases:
            return "Пока ничего не слышал."
        lines = [f"{i+1}. {p}" for i, p in enumerate(phrases[-5:])]
        return "Последние фразы: " + "; ".join(lines) + "."

    # «почему не понял»
    if (re.search(r"почему\s+(ты\s+)?не\s+понял", cmd)
            or cmd in {"почему не понял", "почему не поняла"}):
        d = handler._last_debug
        if not d:
            return "Пока нечего диагностировать."
        parts = [f"Фраза: «{d.get('cmd', '?')}»"]
        parts.append(f"Режим: {d.get('mode', '?')}")
        if d.get("llm"):
            intent = d.get("intent")
            if intent:
                parts.append(f"LLM вернула: {intent.get('action', '?')}")
            else:
                parts.append("LLM не разобрала")
        else:
            parts.append(f"LLM: {d.get('reason', 'выкл')}")
        return ". ".join(parts) + "."

    return None
```

### `jarvis/intents/fast/memory.py`

```python
"""Управление памятью диалога. ... [5 строк]"""

import re

from jarvis import memory


def memory_fast(handler, cmd: str) -> str | None:
    if re.search(r"(коротк|быстр)\w*\s+память", cmd):
        handler.config.update({
            "memory_max": 40,
            "llm_context_messages": 10,
        })
        return "Память: короткая. 40 сообщений, контекст LLM — 10."

    if re.search(r"(обычн|стандартн|нормальн)\w*\s+память", cmd):
        handler.config.update({
            "memory_max": 100,
            "llm_context_messages": 20,
        })
        return "Память: обычная. 100 сообщений, контекст LLM — 20."

    if re.search(r"(долг|глубок)\w*\s+память", cmd):
        handler.config.update({
            "memory_max": 200,
            "llm_context_messages": 40,
        })
        return "Память: долгая. 200 сообщений, контекст LLM — 40."

    if (re.search(r"(какая|текущ)\w*\s+память", cmd)
            or cmd in {"какая память", "текущая память"}):
        mm = handler.config.get("memory_max", 100)
        lc = handler.config.get("llm_context_messages", 20)
        return f"Память: {mm} сообщений, контекст LLM — {lc}."

    return None
```

### `jarvis/intents/fast/music.py`

```python
"""Музыка — ДО open_fast. ... [4 строк]"""

import re

from jarvis import actions


def music_fast(handler, cmd: str) -> str | None:
    if re.search(r"(включи|врубай|играй|поставь)\s+(музыку|музыка|плейлист)", cmd):
        actions.media_key("play")
        return "Включаю музыку."

    if cmd in {"пауза", "плей", "play", "pause"}:
        actions.media_key("play")
        return "Готово."

    if re.search(r"^(включи|врубай)\s+(плей|музыку)$", cmd):
        actions.media_key("play")
        return "Включаю."

    if re.search(r"(следующ|дальше|переключи|переключ)\w*\s*(трек|песн|музык)?", cmd):
        if any(w in cmd for w in ("трек", "песн", "музык", "дальше")):
            actions.media_key("next")
            return "Переключаю."

    if re.search(r"(предыдущ|назад)\w*\s*(трек|песн|музык)", cmd):
        actions.media_key("prev")
        return "Возвращаю."

    if re.search(r"(останови|стоп)\s+(музык|трек|песн)", cmd):
        actions.media_key("play")
        return "Останавливаю."

    return None
```

### `jarvis/intents/fast/open.py`

```python
"""Открытие приложений / сайтов / папок / профиля — без LLM. ... [4 строк]"""

import logging
import re

from jarvis import actions, profile
from jarvis.intents.execute import _do_open, _do_close

log = logging.getLogger("jarvis.intents")


def open_fast(handler, cmd: str) -> str | None:
    """«открой X», «запусти X», «включи X», «врубай X» → open."""
    m = re.match(r"^(?:открой|запусти|врубай|включи|открывай)\s+(.+)$", cmd)
    if not m:
        return None
    target = m.group(1).strip()
    if not target:
        return None
    # Защита: «открой профиль» — не наше дело (open_profile_fast выше).
    if "профиль" in target:
        return None
    return _do_open(handler, target)


def open_profile_fast(handler, cmd: str) -> str | None:
    """«открой профиль» → profile.json в Notepad++ / VS Code / системе. ... [3 строк]"""
    if not re.search(r"откр\w*\s+профиль", cmd):
        return None

    prefer = "auto"
    if re.search(r"\bв\s+(vs\s*code|вс\s*код|вскод|code)\b", cmd):
        prefer = "vscode"
    elif re.search(r"\bв\s+(notepad\+\+|нотпад\s*плюс|нотепад)\b", cmd):
        prefer = "notepad++"
    elif re.search(r"\bв\s+(блокнот|notepad)\b", cmd):
        prefer = "system"
    elif re.search(r"\bв\s+(системн|обычн)\w*\s+редактор", cmd):
        prefer = "system"

    prof_path = profile.profile_path()
    if not prof_path.exists():
        return f"Профиль не найден: {prof_path.name}"

    ok = actions.open_in_editor(prof_path, prefer=prefer)
    if ok:
        editor_name = {
            "auto": "редакторе",
            "vscode": "VS Code",
            "notepad++": "Notepad++",
            "system": "системном редакторе",
        }.get(prefer, "редакторе")
        return f"Открываю профиль в {editor_name}."
    return "Не удалось открыть профиль."
```

### `jarvis/intents/fast/packs.py`

```python
"""Паки команд — обёртка с side-effect. ... [5 строк]"""

from jarvis import packs


def packs_fast(handler, cmd: str) -> str | None:
    reply, new_active = packs.handle_pack_command(
        cmd, handler.active_packs, handler.config
    )
    if reply:
        if new_active != handler.active_packs:
            handler.active_packs = new_active
            _reload_packs(handler)
        return reply
    return None


def _reload_packs(handler) -> None:
    """Пересобрать handler.custom после смены активных паков."""
    from jarvis.intents.fast.custom import load_packs_as_custom
    handler.custom = (list(handler._config_custom_original)
                      + load_packs_as_custom(handler.config))
```

### `jarvis/intents/fast/persona.py`

```python
"""Команды персоны: стиль общения, описание, сброс онбординга."""

import logging
import re

from jarvis import persona

log = logging.getLogger("jarvis.intents")


def persona_fast(handler, cmd: str) -> str | None:
    # Mood: «как настроение», «не грусти», «успокойся»
    try:
        from jarvis import mood
        reply = mood.handle_mood_command(cmd)
        if reply:
            return reply
    except Exception:
        log.exception("mood.handle_mood_command упал")

    # «поменяй стиль на строгий», «говори на ты»
    if (re.search(r"(поменяй|смени|переключи|поставь|установи)\s+стил", cmd)
            or re.search(r"(говори|общайся)\s+(на\s+)?(ты|вы)", cmd)):
        m = re.search(r"(?:на|стиль)\s+([а-яёa-z\- ]+)$", cmd)
        style_text = m.group(1).strip() if m else cmd

        if "на ты" in cmd or style_text == "ты":
            style_text = "дружеский"
        elif "на вы" in cmd or style_text == "вы":
            style_text = "формальный"

        style = persona.normalize_style(style_text)
        if style:
            return persona.set_style(style)
        return ("Не понял стиль. Доступные: формальный, дружеский, "
                "саркастичный, короткий.")

    # «какой у тебя стиль», «как ты ко мне обращаешься»
    if (re.search(r"(какой|какая|текущ)\w*\s+(у\s+тебя\s+)?стил", cmd)
            or re.search(r"как\s+ты\s+(ко\s+мне\s+)?обращаешься", cmd)):
        return persona.describe()

    # «как тебя зовут»
    if re.search(r"(как\s+тебя\s+зовут|как\s+тебя\s+звать|твое\s+имя)", cmd):
        name = persona.get().get("assistant_name") or "Феникс"
        return f"Меня зовут {name}."

    # «давай заново познакомимся»
    if (re.search(r"(давай|давай\s+же)\s+заново\s+познакомимся", cmd)
            or re.search(r"(сбрось|сбросить|reset)\s+(персон|знакомств|онбординг)", cmd)
            or cmd in {"заново познакомимся", "сбрось персону", "сбрось знакомство"}):
        persona.reset_onboarding()
        return "О, давай! Как тебя зовут?"

    return None
```

### `jarvis/intents/fast/profile.py`

```python
"""Профиль: смена, список, факты «запомни: X — Y»."""

import logging
import re

from jarvis import learning, profile

log = logging.getLogger("jarvis.intents")


_NOT_A_CITY = (
    "открой", "закрой", "найди", "включи", "выключи",
    "как дела", "кто ты", "спасибо", "привет", "пока",
    "который час", "какое число", "сделай скриншот",
    "загугли", "поищи", "напечатай",
)

# «мой город Казань» / «моя работа программист» / «мое имя Максим»
# Первое слово после «мой/моя/мое/мои» — ключ, остальное — значение.
_MY_KEY_MAP = {
    "город": "город",
    "работа": "работа",
    "имя": "имя",
    "возраст": "возраст",
    "профессия": "профессия",
    "день": "день рождения",
    "день рождения": "день рождения",
    "любимая игра": "любимая игра",
    "любимый фильм": "любимый фильм",
    "любимая музыка": "любимая музыка",
}


def profile_fast(handler, cmd: str) -> str | None:
    log.info("profile_fast: %r", cmd)

    # «я — Маша», «зови меня X», «переключись на X».
    # БЕЗ голого «я » — иначе «я хочу спать» создаёт профиль.
    m = re.match(
        r"^(?:я\s*[-—]\s*|зови\s+меня\s+|переключись\s+на\s+|я\s+это\s+)"
        r"([а-яёa-z][а-яёa-z\s\-]{0,40})$",
        cmd,
    )
    if m:
        name = m.group(1).strip()
        if name and name not in _NOT_A_CITY:
            return profile.switch(name)

    # «кто активен», «какой профиль»
    if (re.search(r"(кто|какой)\s+(сейчас\s+)?(активен|профиль|пользователь)", cmd)
            or cmd in {"кто активен", "какой профиль", "текущий профиль"}):
        name = profile.get("name") or profile.current()
        return f"Сейчас профиль {name}."

    # «список профилей»
    if (re.search(r"(список|какие|покажи)\s+профил", cmd)
            or cmd in {"список профилей", "какие профили"}):
        all_p = profile.list_all()
        if not all_p:
            return "Профилей нет."
        return f"Профили: {', '.join(all_p)}."

    # «запомни: X — Y» → facts
    m = re.match(r"^(?:запомни|запиши)\s*[,:]?\s*(?:что\s+)?(.+)$", cmd)
    if m:
        fact = m.group(1).strip(" ,.:!?")
        if not fact:
            return "Что запомнить?"

        key, value = _parse_fact(fact)
        if not key or not value:
            return "Что запомнить?"

        ok = learning.add_fact(key, value)
        if ok:
            return f"Запомнил: {key} — {value}."
        return "Не удалось сохранить — проверь профиль (возможно, битый JSON)."

    # «что ты обо мне знаешь»
    if (re.search(r"(что|чё)\s+ты\s+(обо\s+мне\s+)?знаешь", cmd)
            or cmd in {"что ты обо мне знаешь", "что ты знаешь"}):
        return _describe_known(profile)

    # «забудь X»
    m = re.match(r"^забудь\s+(?:факт\s+)?(.+)$", cmd)
    if m:
        key = m.group(1).strip(" ,.:!?").lower()
        if profile.forget_fact(key):
            return f"Забыл: {key}."
        return f"Факта «{key}» не знаю."

    return None


def _parse_fact(fact: str) -> tuple[str, str]:
    """Разбирает факт из строки. ... [8 строк]"""
    # 1. С разделителем: «X — Y», «X: Y», «X = Y»
    m = re.match(r"^(.+?)\s*[—\-=:]\s*(.+)$", fact)
    if m:
        return m.group(1).strip().lower(), m.group(2).strip()

    # 2. «мой/моя/мое/мои X Y» → ключ X, значение Y
    m = re.match(r"^мо(?:й|я|е|и)\s+(.+)$", fact, flags=re.IGNORECASE)
    if m:
        rest = m.group(1).strip()
        # Первое слово — ключ (нормализуем через карту), остальное — значение.
        parts = rest.split(maxsplit=1)
        if len(parts) == 2:
            key_raw = parts[0].lower()
            value = parts[1].strip()
            key = _MY_KEY_MAP.get(key_raw, key_raw)
            return key, value

    # 3. «X Y» — первое слово ключ (если есть в карте), остальное — значение.
    parts = fact.split(maxsplit=1)
    if len(parts) == 2:
        key_raw = parts[0].lower()
        if key_raw in _MY_KEY_MAP:
            return _MY_KEY_MAP[key_raw], parts[1].strip()

    # 4. Fallback — весь факт как ключ, значение «да».
    return fact.lower(), "да"


def _describe_known(profile_module) -> str:
    facts = profile_module.all_facts()
    name = profile_module.get("name")
    city = profile_module.get("default_city")

    parts = []
    if name:
        parts.append(f"Тебя зовут {name}")
    if city:
        parts.append(f"твой город — {city}")
    if facts:
        facts_str = "; ".join(f"{k} — {v}" for k, v in facts.items())
        parts.append(f"Знаю: {facts_str}")
    if not parts:
        return "Пока ничего о тебе не знаю."
    return ". ".join(parts) + "."
```

### `jarvis/intents/fast/screenshot.py`

```python
"""Скриншот: «сделай скриншот», «открой скриншот». ... [4 строк]"""

import re

from jarvis import actions


def screenshot_fast(handler, cmd: str) -> str | None:
    if not re.search(r"скрин|снимок экрана", cmd):
        return None

    # «открой скриншот» / «покажи скриншот» — открыть последний.
    if re.search(r"откр|покаж", cmd):
        if handler.last_file:
            actions.open_path(handler.last_file)
            return "Открываю."
        return "Пока нечего открывать."

    # Иначе — сделать новый.
    path = actions.take_screenshot()
    handler.last_file = path
    return f"Скриншот сохранён в папку {path.parent.name}."
```

### `jarvis/intents/fast/small_talk.py`

```python
"""Мелкий разговор: время, дата, «кто ты», праздники. ... [5 строк]"""

import datetime

from jarvis import APP_NAME, __version__


MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]

WEEKDAYS = [
    "понедельник", "вторник", "среда", "четверг",
    "пятница", "суббота", "воскресенье",
]


def small_talk(handler, cmd: str) -> str | None:
    """Только точные команды. Диалог — через LLM."""

    # Праздничные триггеры — до всего остального.
    from jarvis import celebrations
    if celebrations.match_celebration(cmd):
        if handler.jarvis is not None:
            celebrations.start_celebration(handler.jarvis, handler.gui)
            return "\u200b"  # zero-width, чтобы handle не шёл в LLM
        return "Поздравляю! С днём рождения!"

    now = datetime.datetime.now()

    if any(p in cmd for p in ("который час", "сколько времени")):
        return f"Сейчас {now.hour} {_hours(now.hour)} {now.minute} {_minutes(now.minute)}."

    if any(p in cmd for p in ("какое число", "какая дата", "какое сегодня число")):
        return (f"Сегодня {now.day} {MONTHS[now.month - 1]} {now.year} года, "
                f"{WEEKDAYS[now.weekday()]}.")

    if "день недели" in cmd or cmd == "какой сегодня день":
        return f"Сегодня {WEEKDAYS[now.weekday()]}."

    # «Кто ты» — оставляем здесь, чтобы работало без LLM (test_intents).
    if any(p in cmd for p in ("кто ты", "ты кто", "представься", "как тебя зовут")):
        return f"Я {APP_NAME}, локальный голосовой ассистент, версия {__version__}."

    return None


def _hours(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "час"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "часа"
    return "часов"


def _minutes(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "минута"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "минуты"
    return "минут"
```

### `jarvis/intents/fast/system.py`

```python
"""Системные команды: раскладка, громкость, яркость."""

import re

from jarvis import actions, history


def system_fast(handler, cmd: str) -> str | None:
    reply = _layout(cmd)
    if reply:
        return reply
    reply = _volume(cmd)
    if reply:
        return reply
    reply = _brightness(cmd)
    if reply:
        return reply
    return None


# =================================================================
# Раскладка
# =================================================================

def _layout(cmd: str) -> str | None:
    if not re.search(r"раскладк", cmd):
        return None

    if re.search(r"(переключ|смени|поменяй|следующ)", cmd):
        ok = actions.switch_layout()
        if ok:
            history.push({"action": "switch_layout"})
        return "Переключаю раскладку." if ok else "Не удалось переключить."
    if re.search(r"(русск|ru)", cmd):
        ok = actions.set_layout_ru()
        return "Русская раскладка." if ok else "Не удалось."
    if re.search(r"(англ|english|en)", cmd):
        ok = actions.set_layout_en()
        return "Английская раскладка." if ok else "Не удалось."
    if re.search(r"(какая|текущ|что)", cmd):
        layout = actions.get_layout()
        if layout == "ru":
            return "Сейчас русская раскладка."
        if layout == "en":
            return "Сейчас английская раскладка."
        return "Не смог определить раскладку."
    return None


# =================================================================
# Громкость
# =================================================================

def _volume(cmd: str) -> str | None:
    # «громкость 50»
    m = re.search(r"громкость\s+(?:на\s+)?(\d+)", cmd)
    if m:
        pct = int(m.group(1))
        prev = actions.get_volume()
        ok = actions.set_volume(pct)
        if ok:
            history.push({"action": "set_volume", "prev_value": prev})
        return f"Громкость: {pct}%." if ok else "Не удалось."

    # «сделай на 10 потише» (№69)
    m = re.search(
        r"(?:сделай|поставь|сделай\s+пожалуйста)\s+(?:на\s+)?(\d+)\s+(потише|тише|погромче|громче)",
        cmd,
    )
    if m:
        delta = int(m.group(1))
        direction = m.group(2)
        if "тише" in direction:
            delta = -delta
        prev = actions.get_volume()
        if prev is not None:
            new_vol = max(0, min(100, prev + delta))
            ok = actions.set_volume(new_vol)
            if ok:
                history.push({"action": "set_volume", "prev_value": prev})
            return f"Громкость: {new_vol}%." if ok else "Не удалось."

    # «потише» / «погромче» (без числа, ±10)
    if re.search(r"\b(потише|тише)\b", cmd):
        prev = actions.get_volume()
        if prev is not None:
            new_vol = max(0, prev - 10)
            ok = actions.set_volume(new_vol)
            if ok:
                history.push({"action": "set_volume", "prev_value": prev})
            return f"Громкость: {new_vol}%." if ok else "Не удалось."

    if re.search(r"\b(погромче|громче)\b", cmd):
        prev = actions.get_volume()
        if prev is not None:
            new_vol = min(100, prev + 10)
            ok = actions.set_volume(new_vol)
            if ok:
                history.push({"action": "set_volume", "prev_value": prev})
            return f"Громкость: {new_vol}%." if ok else "Не удалось."

    # «какая громкость»
    if (re.search(r"(какая|текущ|узнай)\s+громкость", cmd)
            or cmd in {"какая громкость", "текущая громкость"}):
        vol = actions.get_volume()
        return f"Громкость: {vol}%." if vol is not None else "Не смог узнать."

    return None


# =================================================================
# Яркость
# =================================================================

def _brightness(cmd: str) -> str | None:
    m = re.search(r"яркость\s+(?:на\s+)?(\d+)", cmd)
    if m:
        pct = int(m.group(1))
        prev = actions.get_brightness()
        ok = actions.set_brightness(pct)
        if ok:
            history.push({"action": "set_brightness", "prev_value": prev})
        return f"Яркость: {pct}%." if ok else "Не удалось."

    if (re.search(r"(какая|текущ|узнай)\s+яркость", cmd)
            or cmd in {"какая яркость", "текущая яркость"}):
        br = actions.get_brightness()
        return f"Яркость: {br}%." if br is not None else "Не смог узнать."

    return None
```

### `jarvis/intents/fast/tasks.py`

```python
"""Задачи — обёртка над `tasks`."""

from jarvis import tasks


def tasks_fast(handler, cmd: str) -> str | None:
    return tasks.handle_task_command(cmd)
```

### `jarvis/intents/fast/timers.py`

```python
"""Напоминания — обёртка над `timers`."""

from jarvis import timers


def timers_fast(handler, cmd: str) -> str | None:
    return timers.handle_timer_command(cmd)
```

### `jarvis/intents/fast/uia.py`

```python
"""UIA-команды голосом: «прочитай окно», «закрой вкладку ютуб», «какой сайт». ... [7 строк]"""

import logging
import re

from jarvis import uia

log = logging.getLogger("jarvis.intents")


def uia_fast(handler, cmd: str) -> str | None:
    """Быстрые команды UIA. None, если не наша."""

    # === Активное окно — что открыто ===
    if re.search(r"(что|какое)\s+(у\s+меня\s+)?(открыто|окно|приложение)", cmd) \
            or cmd in {"что открыто", "какое окно", "активное окно"}:
        return uia.describe_active_window()

    # === Прочитать текст активного окна ===
    if re.search(r"(прочитай|что\s+написано|что\s+в)\s+(в\s+)?(окн|блокнот|текст|документ)",
                 cmd) \
            or cmd in {"прочитай окно", "прочитай блокнот", "что в блокноте",
                       "что написано в окне"}:
        text = uia.read_active_text_stripped(max_chars=1500)
        if not text:
            return "В активном окне не вижу текста."
        # Ограничим озвучку — читать 4000 символов вслух долго.
        if len(text) > 400:
            text = text[:400] + "... (ещё много)"
        return f"Читаю: {text}"

    # === URL активной вкладки ===
    if re.search(r"(какой|какая)\s+(сайт|url|адрес|ссылка)", cmd) \
            or cmd in {"какой сайт", "какой сайт открыт", "какая ссылка"}:
        url = uia.read_browser_url()
        if not url:
            return "Активное окно — не браузер, или не вижу URL."
        return f"Открыт сайт: {url}"

    # === Заголовок активной вкладки ===
    if re.search(r"(что|какая)\s+(за\s+)?(вкладка|страница)", cmd) \
            or cmd in {"какая вкладка", "что за вкладка"}:
        title = uia.read_browser_tab_title()
        if not title:
            return "Активное окно — не браузер."
        return f"Активная вкладка: {title}"

    # === Список вкладок ===
    if re.search(r"(какие|список|покажи)\s+вкладк", cmd) \
            or cmd in {"какие вкладки", "список вкладок", "покажи вкладки"}:
        tabs = uia.read_browser_tabs()
        if not tabs:
            return "Не вижу открытых вкладок. Возможно, активное окно — не браузер."
        short = tabs[:10]
        return "Открыты: " + "; ".join(short) + "."

    # === Закрыть вкладку ===
    m = re.search(r"закр\w+\s+вкладк\w*\s+(.+)", cmd)
    if m:
        target = m.group(1).strip().rstrip(".,!?")
        if target in ("эту", "текущую", "это"):
            # «закрой эту вкладку» — просто Ctrl+W, безопаснее.
            from jarvis import actions
            actions.hotkey(["ctrl", "w"])
            return "Закрыл текущую вкладку."
        ok = uia.close_browser_tab(target)
        return f"Закрыл вкладку {target}." if ok else f"Вкладку «{target}» не нашёл."

    # === Переключиться на вкладку ===
    m = re.search(r"переключ\w*\s+(?:на\s+)?вкладк\w*\s+(.+)", cmd) \
        or re.search(r"перейди\s+на\s+вкладк\w*\s+(.+)", cmd)
    if m:
        target = m.group(1).strip().rstrip(".,!?")
        ok = uia.switch_browser_tab(target)
        return f"Переключился на {target}." if ok else f"Вкладку «{target}» не нашёл."

    # === Нажать кнопку ===
    m = re.search(r"нажми\s+(?:кнопку\s+)?(.+)", cmd)
    if m:
        target = m.group(1).strip().rstrip(".,!?")
        # «нажми enter» / «нажми tab» — это клавиши, не кнопки.
        if target.lower() in ("enter", "escape", "esc", "tab", "space",
                              "пробел", "энтер", "эскейп"):
            from jarvis import actions
            key = {"пробел": "space", "энтер": "enter", "эскейп": "escape"}.get(
                target.lower(), target.lower()
            )
            actions.key_press(key)
            return f"Нажал {target}."
        ok = uia.click_button(target)
        return f"Нажал «{target}»." if ok else f"Кнопку «{target}» не нашёл."

    return None
```

### `jarvis/intents/fast/undo.py`

```python
"""Отмена последнего действия («не то», «отмени»)."""

import re

from jarvis import actions, history, modes, voices
from jarvis.intents.execute import _do_close


def undo_fast(handler, cmd: str) -> str | None:
    if not re.search(r"(не\s+то|отмени|верни\s+как\s+было|откат)", cmd):
        return None

    item = history.pop()
    if not item:
        return "Нечего отменять."

    action = item.get("action")

    if action == "macro":
        steps = item.get("steps") or []
        if not steps:
            return "Нечего отменять."
        results = []
        for step in reversed(steps):
            s_action = step.get("action")
            s_target = step.get("target")
            if s_action == "open_app" and s_target:
                results.append(_do_close(handler, s_target))
        if results:
            return "Откатываю макрос: " + "; ".join(results)
        return "Макрос отменён."

    if action == "open_app":
        target = item.get("target") or ""
        if target:
            return f"Откатываю: {_do_close(handler, target)}"

    if action == "set_mode":
        prev = item.get("prev_value")
        if prev:
            reply = modes.set_mode(prev, handler.config)
            handler.mode = prev
            return f"Вернул режим: {reply}"

    if action == "change_voice":
        prev = item.get("prev_value")
        if prev:
            reply = voices.switch(prev, handler.config)
            return f"Вернул голос: {reply}"

    if action == "set_volume":
        prev = item.get("prev_value")
        if prev is not None:
            actions.set_volume(int(prev))
            return f"Вернул громкость: {prev}%."

    if action == "set_brightness":
        prev = item.get("prev_value")
        if prev is not None:
            actions.set_brightness(int(prev))
            return f"Вернул яркость: {prev}%."

    if action == "switch_layout":
        actions.switch_layout()
        return "Переключил раскладку обратно."

    return f"Действие «{action}» отменить нельзя."
```

### `jarvis/intents/fast/voices.py`

```python
"""Голоса Piper — обёртка над модулем `voices`. ... [3 строк]"""

from jarvis import voices


def voices_fast(handler, cmd: str) -> str | None:
    return voices.handle_voice_command(cmd, handler.config)
```

### `jarvis/intents/fast/weather.py`

```python
"""Простые правила для погоды и курса — без LLM. ... [4 строк]"""

import re
import time

from jarvis import profile, weather


def weather_currency_fast(handler, cmd: str) -> str | None:
    # === Курс ===
    if re.search(r"\bкурс\b|\bвалют", cmd):
        code_map = {
            "доллар": "USD", "доллара": "USD", "бакс": "USD", "бакса": "USD",
            "евро": "EUR",
            "юан": "CNY", "юаня": "CNY",
            "фунт": "GBP", "фунта": "GBP",
            "йен": "JPY", "йены": "JPY",
            "лир": "TRY", "лиры": "TRY",
            "тенге": "KZT",
            "белорусск": "BYN", "бел рубл": "BYN",
            "гривн": "UAH",
        }
        code = ""
        for word, iso in code_map.items():
            if word in cmd:
                code = iso
                break
        r = weather.get_currency_rates()
        return weather.describe_currency(r, code=code)

    # === Погода ===
    if re.search(r"\bпогод|\bпрогноз", cmd):
        day = "tomorrow" if "завтра" in cmd else "today"

        m = re.search(r"\bв\s+([а-яёa-z\-]+(?:\s+[а-яёa-z\-]+)?)", cmd)
        city = m.group(1).strip() if m else ""
        named = bool(city)

        if not city:
            city = profile.get("default_city")
        if not city:
            handler._pending_question = {
                "type": "city_for_weather",
                "day": day,
                "expires_at": time.time() + 30,
            }
            return "В каком городе узнать погоду?"

        w = weather.get_weather(city, day=day)
        if not w:
            # Город назван, но геокодер не знает — почти всегда это падеж
            # («в питере»). По архитектуре нормализация городов — задача LLM,
            # поэтому если она есть, отдаём фразу ей: она вернёт
            # target=«Санкт-Петербург», и ответ будет про тот город.
            # Без LLM — честно говорим, что город не узнали, и НИКОГДА не
            # подставляем город по умолчанию: раньше «погода в питере»
            # уверенно отвечала про Казань.
            if getattr(handler, "brain", None) is not None:
                return None
            return (f"Не узнал город «{city}». Скажи его в именительном "
                    f"падеже — например, «Санкт-Петербург».")
        return weather.describe_weather(w)

    return None
```

### `jarvis/intents/handler.py`

```python
"""IntentHandler — оркестрация. ... [6 строк]"""

import logging
import time
from collections import deque

from jarvis import memory, profile
from jarvis.intents.fast import build_registry, load_custom
from jarvis.intents.password import migrate_password_if_needed
from jarvis.intents.stages import build_pipeline
from jarvis.intents.stages.password import build_ask_password
from jarvis.reply import Reply
from jarvis.text_utils import normalize

log = logging.getLogger("jarvis.intents")
actions_log = logging.getLogger("jarvis.actions")


class IntentHandler:

    def __init__(self, config, apps, brain=None, listener=None, gui=None, jarvis=None):
        self.config = config
        self.apps = apps
        self.brain = brain
        self.listener = listener
        self.gui = gui
        self.jarvis = jarvis

        # Индексы — читаются один раз при старте.
        from jarvis.installed import scan_start_menu
        from jarvis.steam import scan_steam_games
        self.installed = scan_start_menu()
        self.steam_games = scan_steam_games()

        self.music_app = config.get("music_app", "яндекс музыка")
        self.music_wait = float(config.get("music_wait_sec", 6))
        self.last_file = None
        self.last_folder = None

        # Память — из config.
        self._memory_max = int(config.get("memory_max", 100))
        self._llm_context = int(config.get("llm_context_messages", 20))
        self.dialog = deque(maxlen=self._memory_max)
        for msg in memory.load(limit=self._memory_max):
            self.dialog.append(msg)

        # Состояние.
        self.last_was_chat = False
        self.mode = config.get("mode", "combo")
        self.active_packs = list(config.get("active_packs", []))
        self.last_macro = None
        self._reset_requested = False
        self._last_reply = ""
        self._pending_question = None
        self._pending_password = None

        # Диагностика.
        self._last_debug: dict = {}
        self._recent_phrases: deque = deque(maxlen=10)
        self._last_cmd: str = ""

        # Миграция пароля (plaintext → sha256).
        migrate_password_if_needed(config)

        # Custom-команды.
        self.custom = load_custom(config)
        self._config_custom_original = list(self.custom)

        # Реестр быстрых правил.
        self._fast_handlers_cache = build_registry(self)

        # Pipeline стадий.
        self._pipeline = build_pipeline(self)

        # Подписки.
        config.subscribe(self._on_config_change)
        profile.subscribe(self._on_profile_switch)

    # =================================================================
    # Публичный API
    # =================================================================

    def handle(self, cmd: str) -> Reply:
        """Возвращает Reply: либо text, либо stream."""
        self.last_was_chat = False

        cmd = normalize(cmd)
        actions_log.info("Команда: %r (режим: %s)", cmd, self.mode)
        self._recent_phrases.append(cmd)

        self._last_cmd = cmd

        result = self._handle_single(cmd)

        # Mood: реагируем на эмоциональный окрас фразы.
        # Делается ДО сохранения user_msg, чтобы mood был актуален
        # для уже сформированного ответа. Это осознанный tradeoff:
        # ответ сгенерирован со старым mood, но следующий уже учтёт.
        try:
            from jarvis import mood
            mood.apply_from_text(cmd)
        except Exception:
            log.exception("mood.apply_from_text упал на %r", cmd)

        user_msg = {"role": "user", "content": cmd}
        self.dialog.append(user_msg)
        memory.append(user_msg)

        if result is None:
            result = "Не понял команду."

        if isinstance(result, str):
            assistant_msg = {"role": "assistant", "content": result}
            self.dialog.append(assistant_msg)
            memory.append(assistant_msg)
            actions_log.info("Ответ: %r", result[:120])
            self._last_reply = result
            return Reply(text=result)

        # result — генератор (chat_stream)
        return Reply(stream=result)

    def finalize_stream(self, full_text: str) -> None:
        if not full_text:
            return
        assistant_msg = {"role": "assistant", "content": full_text}
        self.dialog.append(assistant_msg)
        memory.append(assistant_msg)
        self._last_reply = full_text

    # =================================================================
    # Внутренняя оркестрация
    # =================================================================

    def _handle_single(self, cmd: str):
        """Пробегает pipeline стадий. Первая не-None — побеждает."""
        from jarvis.intents.context import Ctx

        ctx = Ctx(cmd=cmd, original_cmd=cmd, handler=self)
        for stage in self._pipeline:
            result = stage.handle(ctx)
            if result is not None:
                return result
        return None

    def _chat_stream(self, cmd: str):
        ctx = list(self.dialog)[-self._llm_context:] if self._llm_context else []
        return self.brain.chat_stream(cmd, ctx)

    def _ask_password(self, intent: dict) -> str:
        """Запрашивает пароль для опасного действия."""
        pending, msg = build_ask_password(intent)
        self._pending_password = pending
        return msg

    def _danger_password(self) -> str:
        return str(self.config.get("danger_password") or "").strip()

    # =================================================================
    # Подписки
    # =================================================================

    def _on_config_change(self, key: str, value) -> None:
        if key == "memory_max":
            try:
                new_max = int(value)
            except (TypeError, ValueError):
                return
            if new_max <= 0:
                return
            self._memory_max = new_max
            self.dialog = deque(self.dialog, maxlen=new_max)
            log.info("IntentHandler: memory_max = %d", new_max)
        elif key == "llm_context_messages":
            try:
                self._llm_context = int(value)
            except (TypeError, ValueError):
                return
            log.info("IntentHandler: llm_context_messages = %d", self._llm_context)

    def _on_profile_switch(self, old_name: str, new_name: str) -> None:
        """Перечитывает dialog при смене профиля."""
        if old_name == new_name:
            return
        self.dialog.clear()
        for msg in memory.load(limit=self._memory_max):
            self.dialog.append(msg)
        log.info(
            "Профиль сменился: %s → %s, диалог перечитан (%d сообщений)",
            old_name, new_name, len(self.dialog),
        )
```

### `jarvis/intents/password.py`

```python
"""Хеширование пароля и действия, требующие пароля. ... [4 строк]"""

import hashlib
import hmac
import logging

log = logging.getLogger("jarvis.intents")


_PASSWORD_PREFIX = "sha256:"


def hash_password(password: str) -> str:
    """SHA-256 с префиксом. Префикс отличает хеш от legacy-plaintext."""
    digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return f"{_PASSWORD_PREFIX}{digest}"


def is_hashed(value: str) -> bool:
    """Уже захеширован?"""
    return bool(value) and value.startswith(_PASSWORD_PREFIX)


def verify_password(candidate: str, stored: str) -> bool:
    """Сравнивает введённый пароль с сохранённым. ... [4 строк]"""
    if not stored:
        return False
    if is_hashed(stored):
        # compare_digest — постоянное по времени сравнение.
        # Обычный == утекает длиной совпавшего префикса.
        return hmac.compare_digest(hash_password(candidate), stored)
    # Legacy plaintext — мигрируется в sha256 при старте.
    return hmac.compare_digest(candidate, stored)


def migrate_password_if_needed(config) -> None:
    """Если danger_password в plaintext — захешировать (№81)."""
    raw = str(config.get("danger_password") or "").strip()
    if not raw or is_hashed(raw):
        return
    config.set("danger_password", hash_password(raw))
    log.info("Пароль миграции: plaintext → sha256")


# Действия, требующие пароля (если danger_password задан).
DANGER_ACTIONS = frozenset({
    "shutdown_pc", "reboot_pc", "kill_process",
    "clear_tasks", "cancel_timers", "delete_profile",
})


def is_danger(intent: dict, stored_password: str) -> bool:
    """Проверяет, опасно ли действие. ... [3 строк]"""
    if not stored_password:
        return False
    action = intent.get("action")
    if action in DANGER_ACTIONS:
        return True
    if action == "open_app":
        target = str(intent.get("target") or "").lower()
        if "shutdown" in target or "выключ" in target or "перезагруз" in target:
            return True
    return False


# Человеческие названия для озвучки — при запросе пароля.
ACTION_HUMAN = {
    "shutdown_pc": "выключение компьютера",
    "reboot_pc": "перезагрузку",
    "kill_process": "закрытие процесса",
    "clear_tasks": "очистку списка задач",
    "cancel_timers": "отмену напоминаний",
    "delete_profile": "удаление профиля",
    "open_app": "это действие",
}
```

### `jarvis/intents/sites.py`

```python
"""Сайты для открытия голосом — ленивая загрузка из packs/sites.json. ... [4 строк]"""

import json
import logging

log = logging.getLogger("jarvis.intents")


_SITES_FALLBACK = {
    "ютуб": ("Ютуб", "https://www.youtube.com"),
    "гугл": ("Гугл", "https://www.google.com"),
    "яндекс": ("Яндекс", "https://ya.ru"),
    "гитхаб": ("Гитхаб", "https://github.com"),
    "вк": ("ВКонтакте", "https://vk.com"),
    "вконтакте": ("ВКонтакте", "https://vk.com"),
    "твич": ("Твич", "https://www.twitch.tv"),
    "кинопоиск": ("Кинопоиск", "https://www.kinopoisk.ru"),
    "википедия": ("Википедию", "https://ru.wikipedia.org"),
    "почта": ("Почту", "https://mail.google.com"),
}


def _load_sites() -> dict:
    """Загружает sites.json из packs/. Fallback — хардкод."""
    sites = dict(_SITES_FALLBACK)
    try:
        from jarvis.packs import PACKS_DIR
        path = PACKS_DIR / "sites.json"
        if not path.exists():
            return sites
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return sites
        for entry in data:
            action = entry.get("action", "")
            if not action.startswith(("http://", "https://")):
                continue
            for phrase in entry.get("phrases", []):
                # «открой ютуб» → ключ «ютуб»
                key = phrase.lower().replace("открой", "").strip()
                if key and key not in sites:
                    title = entry.get("reply", key).replace("Открываю ", "").rstrip(".")
                    sites[key] = (title, action)
        log.info("SITES загружены из packs/sites.json: %d записей", len(sites))
    except Exception:
        log.exception("Не удалось загрузить packs/sites.json — fallback на хардкод")
    return sites


_SITES_CACHE: dict | None = None


def get_sites() -> dict:
    """Ленивая загрузка SITES — при первом обращении, не при импорте."""
    global _SITES_CACHE
    if _SITES_CACHE is None:
        _SITES_CACHE = _load_sites()
    return _SITES_CACHE
```

### `jarvis/intents/stages/__init__.py`

```python
"""Стадии обработки команды. Порядок = приоритет. ... [14 строк]"""

from jarvis.intents.stages.cancel import CancelStage
from jarvis.intents.stages.onboarding import OnboardingStage
from jarvis.intents.stages.correction import CorrectionStage
from jarvis.intents.stages.password import PasswordStage
from jarvis.intents.stages.memory import MemoryStage
from jarvis.intents.stages.pending import PendingStage
from jarvis.intents.stages.clipboard import ClipboardStage
from jarvis.intents.stages.modes import ModesStage
from jarvis.intents.stages.compound import CompoundStage
from jarvis.intents.stages.fast import FastHandlersStage
from jarvis.intents.stages.llm import LLMStage


def build_pipeline(handler) -> list:
    """Собирает pipeline стадий. Порядок фиксирован."""
    return [
        CancelStage(),
        OnboardingStage(),
        CorrectionStage(),
        PasswordStage(),
        MemoryStage(),
        PendingStage(),
        ClipboardStage(),
        ModesStage(),
        CompoundStage(),
        FastHandlersStage(),
        LLMStage(),
    ]
```

### `jarvis/intents/stages/base.py`

```python
"""Базовая стадия pipeline."""

from typing import Iterator, Optional

from jarvis.intents.context import Ctx


class Stage:
    """Одна стадия pipeline. ... [6 строк]"""
    name: str = "base"

    def handle(self, ctx: Ctx) -> Optional[object]:
        raise NotImplementedError
```

### `jarvis/intents/stages/cancel.py`

```python
"""«Стоп», «хватит», «отбой» — самый первый этап."""

from jarvis.intents.stages.base import Stage
from jarvis.intents.verbs import CANCEL


class CancelStage(Stage):
    name = "cancel"

    def handle(self, ctx):
        if ctx.cmd in CANCEL:
            h = ctx.handler
            h._pending_password = None
            h._pending_question = None
            h._reset_requested = True
            return "Жду обращение, сэр."
        return None
```

### `jarvis/intents/stages/clipboard.py`

```python
"""4 команды буфера обмена. Все — до LLM. ... [4 строк]"""

import logging
import re
import time

from jarvis import actions
from jarvis.intents.stages.base import Stage

log = logging.getLogger("jarvis.intents")


class ClipboardStage(Stage):
    name = "clipboard"

    def handle(self, ctx):
        cmd = ctx.cmd

        if (re.search(r"скопируй\s+(выделенное|выделенный|это\s+выделенное)", cmd)
                or re.search(r"(выдели|выделенное)\s+(и\s+)?скопируй", cmd)
                or cmd in {"скопируй выделенное", "скопируй это выделенное"}):
            return self._copy_selection()

        if (re.search(r"скопируй\s+(свой\s+)?(ответ|ответь|последнее|сказанное)", cmd)
                or cmd in {"скопируй свой ответ", "скопируй ответ", "скопируй что ты сказал"}):
            return self._copy_last_reply(ctx)

        if (re.search(r"(что|чё)\s+(в\s+)?буфере", cmd)
                or re.search(r"(покажи|прочитай|что)\s+буфер", cmd)
                or cmd in {"что скопировано", "что в буфере"}):
            return self._read_buffer()

        if (re.search(r"(очисти|сотри|удали)\s+буфер", cmd)
                or cmd in {"очисти буфер", "сотри буфер"}):
            return self._clear_buffer()

        return None

    def _copy_selection(self) -> str:
        if not actions.copy_selection():
            return "Не удалось скопировать."
        time.sleep(0.15)
        text = actions.clipboard_read()
        if text:
            short = text[:200] + ("..." if len(text) > 200 else "")
            return f"Скопировал: {short}"
        return "Скопировал выделенное."

    def _copy_last_reply(self, ctx) -> str:
        last = ctx.handler._last_reply
        if not last:
            return "Нечего копировать."
        ok = actions.clipboard_write(last)
        return "Скопировал свой ответ в буфер." if ok else "Не удалось скопировать."

    def _read_buffer(self) -> str:
        text = actions.clipboard_read()
        if not text:
            return "Буфер обмена пуст."
        return f"В буфере: {text[:400]}"

    def _clear_buffer(self) -> str:
        ok = actions.clipboard_clear()
        return "Буфер очищен." if ok else "Не удалось очистить буфер."
```

### `jarvis/intents/stages/compound.py`

```python
"""Многослойные команды: «открой стим и запусти доту». ... [7 строк]"""

import logging
import re

from jarvis.intents.stages.base import Stage
from jarvis.intents.verbs import COMMAND_VERBS

log = logging.getLogger("jarvis.intents")


class CompoundStage(Stage):
    name = "compound"

    def handle(self, ctx):
        parts = self._split(ctx.cmd)
        if not parts:
            return None

        replies = []
        for part in parts:
            sub = ctx.handler._handle_single(part)
            if isinstance(sub, str) and sub.strip():
                replies.append(sub.strip())
            # Если sub — генератор (chat_stream) — пропускаем.

        if replies:
            return ". ".join(replies) + "."
        return None

    def _split(self, cmd: str) -> list[str] | None:
        """Возвращает список частей или None, если не compound."""
        parts = re.split(r"\s+и\s+|,\s*", cmd)
        if len(parts) < 2:
            return None

        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) < 2:
            return None

        for part in parts:
            first = part.split()[0].lower() if part.split() else ""
            if first not in COMMAND_VERBS:
                return None

        return parts
```

### `jarvis/intents/stages/correction.py`

```python
"""Применение коррекции «это не то» перед разбором команды. ... [5 строк]"""

import logging

from jarvis import learning
from jarvis.intents.stages.base import Stage

log = logging.getLogger("jarvis.intents")


class CorrectionStage(Stage):
    name = "correction"

    def handle(self, ctx):
        corrected = learning.find_correction(ctx.cmd)
        if corrected and corrected != ctx.cmd:
            log.info("Применена коррекция: %r → %r", ctx.cmd, corrected)
            ctx.cmd = corrected
        return None
```

### `jarvis/intents/stages/fast.py`

```python
"""Вызов реестра быстрых обработчиков. ... [6 строк]"""

import logging

from jarvis.intents.stages.base import Stage

log = logging.getLogger("jarvis.intents")


class FastHandlersStage(Stage):
    name = "fast"

    def handle(self, ctx):
        for name, fn in ctx.handler._fast_handlers_cache:
            try:
                reply = fn(ctx.cmd)
            except Exception:
                log.exception("Обработчик %s упал на %r", name, ctx.cmd)
                continue
            if reply:
                log.debug("Команда %r обработана: %s", ctx.cmd, name)
                return reply
        return None
```

### `jarvis/intents/stages/llm.py`

```python
"""LLM — последний шанс разобрать команду. ... [13 строк]"""

import logging

from jarvis.intents.password import is_danger
from jarvis.intents.stages.base import Stage
from jarvis.intents.verbs import SEARCH_VERBS

log = logging.getLogger("jarvis.intents")


class LLMStage(Stage):
    name = "llm"

    def handle(self, ctx):
        h = ctx.handler
        cmd = ctx.cmd

        if h.mode == "commands":
            h._last_debug = {
                "cmd": cmd, "reason": "режим commands",
                "mode": h.mode, "llm": False,
            }
            return "Я не понял команду. Скажите «режим ИИ» или добавьте фразу в конфиг."

        if h.brain is None or not h.brain.available:
            h._last_debug = {
                "cmd": cmd, "reason": "LLM недоступна",
                "mode": h.mode, "llm": False,
            }
            return "LLM недоступна. Скажите «режим команды»."

        # Мусорный ввод (№70): LLM галлюцинирует на «ааа» или «эээ».
        # Исключения «да», «нет», «ок» — это ответы на pending.
        clean = cmd.replace(" ", "")
        if cmd not in {"да", "нет", "ок"}:
            if len(cmd) < 3 or (clean and len(set(clean)) <= 2):
                h._last_debug = {
                    "cmd": cmd, "reason": "мусорный ввод",
                    "mode": h.mode, "llm": False,
                }
                return "Не расслышал, сэр. Повторите, пожалуйста."

        intent = h.brain.parse(cmd)
        h._last_debug = {
            "cmd": cmd, "intent": intent,
            "mode": h.mode, "llm": True,
        }

        if intent and intent.get("action") not in ("answer", "none"):
            if is_danger(intent, str(h.config.get("danger_password") or "").strip()):
                return h._ask_password(intent)

            if (intent.get("action") == "search"
                    and not any(v in cmd for v in SEARCH_VERBS)):
                return "Сэр, чтобы поискать, скажите «найди» и запрос. Например: «найди погоду»."

            # Импорт здесь, чтобы не было цикла
            from jarvis.intents.execute import execute_intent, execute_steps

            if isinstance(intent.get("steps"), list):
                reply = execute_steps(h, intent["steps"])
            else:
                reply = execute_intent(h, intent)
            if reply:
                return reply

        if intent and intent.get("action") == "answer":
            gen = h._chat_stream(cmd)
            if gen is not None:
                h.last_was_chat = True
                return gen
            if intent.get("reply"):
                return str(intent["reply"])[:600]

        gen = h._chat_stream(cmd)
        if gen is not None:
            h.last_was_chat = True
            return gen
        return "Я не понял команду."
```

### `jarvis/intents/stages/memory.py`

```python
"""Команды памяти диалога. ... [4 строк]"""

from jarvis import memory
from jarvis.intents.stages.base import Stage


class MemoryStage(Stage):
    name = "memory"

    def handle(self, ctx):
        h = ctx.handler
        reply, clear = memory.handle_memory_command(ctx.cmd, list(h.dialog))
        if reply:
            if clear:
                h.dialog.clear()
            return reply
        return None
```

### `jarvis/intents/stages/modes.py`

```python
"""Режимы работы: commands / llm / combo. ... [4 строк]"""

from jarvis import history, modes
from jarvis.intents.stages.base import Stage


class ModesStage(Stage):
    name = "modes"

    def handle(self, ctx):
        # Быстрый фильтр: если в фразе нет «режим» — не наше дело.
        if not any(w in ctx.cmd for w in ("режим", "комбо", "комбинирован")):
            return None

        h = ctx.handler
        prev_mode = h.mode
        reply, new_mode = modes.handle_mode_command(ctx.cmd, h.mode, h.config)
        if reply:
            if new_mode != prev_mode:
                history.push({
                    "action": "set_mode",
                    "prev_value": prev_mode,
                })
            h.mode = new_mode
            return reply
        return None
```

### `jarvis/intents/stages/onboarding.py`

```python
"""Первый запуск — знакомство через LLM-диалог. ... [7 строк]"""

import logging

from jarvis.intents.stages.base import Stage
from jarvis.intents.verbs import COMMAND_VERBS

log = logging.getLogger("jarvis.intents")


class OnboardingStage(Stage):
    name = "onboarding"

    def handle(self, ctx):
        from jarvis import first_run, persona, profile

        if not first_run.is_first_run():
            return None

        h = ctx.handler

        # LLM нет — молча завершаем онбординг.
        if h.brain is None or not h.brain.available:
            first_run.mark_done()
            return None

        # Если это команда — не перехватываем.
        if self._looks_like_command(ctx.cmd):
            return None

        # Собираем историю диалога.
        history = list(h.dialog)[-10:]

        # 6+ фраз от юзера — принудительно завершаем.
        user_msgs = sum(1 for m in h.dialog if m.get("role") == "user")
        force_done = user_msgs >= 6

        result = h.brain.onboarding_chat(ctx.cmd, history)
        reply = result.get("reply") or ""

        # Сохраняем что LLM вытащила.
        name = result.get("name")
        if name and not profile.get("name"):
            profile.set("name", name)
            log.info("Онбординг: name=%r", name)

        style_raw = result.get("style")
        if style_raw:
            style = persona.normalize_style(style_raw)
            if style and persona.get().get("speech_style") == "friendly":
                persona.set_field("speech_style", style)
                log.info("Онбординг: style=%r", style)

        if result.get("onboarding_done") or force_done:
            first_run.mark_done()
            log.info("Онбординг завершён (LLM=%s, force=%s)",
                     result.get("onboarding_done"), force_done)

        return reply or None

    def _looks_like_command(self, cmd: str) -> bool:
        """Быстрая проверка: команда или свободный текст?"""
        if not cmd:
            return False
        first = cmd.split()[0] if cmd.split() else ""
        return first in COMMAND_VERBS
```

### `jarvis/intents/stages/password.py`

```python
"""Ожидание пароля + команда «удали профиль X». ... [4 строк]"""

import logging
import re
import time

from jarvis import profile
from jarvis.intents.password import ACTION_HUMAN, verify_password
from jarvis.intents.stages.base import Stage
from jarvis.intents.verbs import CANCEL

log = logging.getLogger("jarvis.intents")


class PasswordStage(Stage):
    name = "password"

    def handle(self, ctx):
        h = ctx.handler

        # 1. Проверяем «удали профиль X» — это всегда до fast.
        reply = self._maybe_delete_profile(ctx)
        if reply is not None:
            return reply

        # 2. Если ждём ввода пароля — обрабатываем.
        if not h._pending_password:
            return None
        if time.time() >= h._pending_password.get("expires_at", 0):
            h._pending_password = None
            return None
        return self._handle_answer(ctx)

    # ----------------------------------------------------------------

    def _maybe_delete_profile(self, ctx) -> str | None:
        """«удали профиль X» → пароль или удаление."""
        h = ctx.handler
        m = re.match(r"^удали\s+профиль\s+(\S+)$", ctx.cmd)
        if not m:
            return None

        name = m.group(1)

        if h._danger_password():
            # Пароль задан — спрашиваем.
            return h._ask_password({"action": "delete_profile", "target": name})

        # Пароля нет — удаляем сразу.
        if profile.delete(name):
            return f"Профиль {name} удалён."
        return f"Профиль {name} не найден или активен."

    # ----------------------------------------------------------------

    def _handle_answer(self, ctx) -> str:
        h = ctx.handler
        pending = h._pending_password
        h._pending_password = None

        if ctx.cmd in CANCEL:
            return "Жду обращение, сэр."

        # Убираем «пароль», «код», «пин», если сказали.
        candidate = re.sub(r"^(?:пароль|код|пин)\s*", "", ctx.cmd).strip()

        stored = str(h.config.get("danger_password") or "").strip()
        if not verify_password(candidate, stored):
            log.warning("Пароль неверный")
            return "Пароль неверный. Действие отменено."

        from jarvis.intents.execute import execute_intent, execute_steps

        intent = pending.get("intent") or {}
        if isinstance(intent.get("steps"), list):
            result = execute_steps(h, intent["steps"])
        else:
            result = execute_intent(h, intent)
        return result or "Готово."


def build_ask_password(intent: dict, expires_sec: int = 30) -> tuple[dict, str]:
    """Готовит данные для _pending_password и текст запроса."""
    pending = {
        "intent": intent,
        "expires_at": time.time() + expires_sec,
    }
    action = intent.get("action")
    human = ACTION_HUMAN.get(action, "это действие")
    return pending, f"Для этого нужен пароль ({human}). Назовите пароль."
```

### `jarvis/intents/stages/pending.py`

```python
"""Ожидание уточнения (pending_question). ... [4 строк]"""

import logging
import time

from jarvis import profile, weather
from jarvis.intents.stages.base import Stage

log = logging.getLogger("jarvis.intents")


_NOT_A_CITY = (
    "открой", "закрой", "найди", "включи", "выключи",
    "как дела", "кто ты", "спасибо", "привет", "пока",
    "который час", "какое число", "сделай скриншот",
    "загугли", "поищи", "напечатай",
)


class PendingStage(Stage):
    name = "pending"

    def handle(self, ctx):
        h = ctx.handler
        if not h._pending_question:
            return None
        if time.time() >= h._pending_question.get("expires_at", 0):
            h._pending_question = None
            return None
        return self._handle(ctx)

    def _handle(self, ctx) -> str:
        h = ctx.handler
        pending = h._pending_question
        h._pending_question = None

        if pending.get("type") == "city_for_weather":
            city = ctx.cmd.strip()
            words = city.split()

            if not city or len(city) > 60 or len(words) > 3:
                return "Не расслышал город. Повторите, пожалуйста."

            if any(w in city for w in _NOT_A_CITY):
                log.info("pending_question: %r не похоже на город — обрабатываю как команду", city)
                result = h._handle_single(ctx.cmd)
                return result if isinstance(result, str) else "Не понял команду."

            profile.set("default_city", city)
            log.info("Запомнил город по умолчанию: %s", city)

            day = pending.get("day", "today")
            w = weather.get_weather(city, day=day)
            if w:
                return f"Запомнил. {weather.describe_weather(w)}"
            return f"Запомнил город «{city}», но погоду узнать не удалось."

        return "Не понял уточнение."
```

### `jarvis/intents/verbs.py`

```python
"""Константы глаголов и слов — единый источник истины. ... [8 строк]"""

# Глаголы, с которых начинается команда.
# Используются:
#   - `stages/compound.py` — проверка, что часть составной команды
#   - `stages/onboarding.py` — «это команда или свободный текст?»
COMMAND_VERBS = frozenset({
    "открой", "открывай", "закрой", "закрывай",
    "запусти", "врубай", "включи", "выключи",
    "найди", "поищи", "загугли", "погугли",
    "поставь", "сделай",
    "добавь", "запиши", "внеси",
    "покажи", "убери", "удали", "очисти",
    "смени", "поменяй", "переключи",
    "сверни", "разверни", "переключись",
    "напомни", "запомни",
    "громче", "тише", "потише", "погромче",
    "скопируй", "вставь",
})


# Слова-отмены. Если услышали — глушим всё.
CANCEL = frozenset({
    "отмена", "стоп", "стой", "хватит",
    "замолчи", "ничего", "забудь", "отбой",
})


# Глаголы поиска — для проверки «search без «найди»».
SEARCH_VERBS = ("найди", "поищи", "ищи", "загугли", "погугли", "поиск")


# Слова, которые обычно означают браузер.
BROWSER_WORDS = frozenset({
    "браузер", "браузере", "браузером",
    "хром", "хроме", "интернет", "интернете",
})
```

### `jarvis/learning.py`

```python
"""Самообучение Феникса: факты и коррекции. ... [15 строк]"""

import logging
from difflib import SequenceMatcher

from jarvis import profile

log = logging.getLogger("jarvis.learning")


# ---------------------------------------------------------------
# Факты
# ---------------------------------------------------------------

def add_fact(key: str, value: str) -> bool:
    """Сохраняет факт. Ключ нормализуется (нижний регистр)."""
    key = key.strip().lower()
    value = value.strip()
    if not key or not value:
        return False

    facts = profile.get("facts", {}) or {}
    facts[key] = value
    ok = profile.set("facts", facts)
    if ok:
        log.info("Факт: %s = %r", key, value)
    return ok


def get_fact(key: str, default=None):
    facts = profile.get("facts", {}) or {}
    return facts.get(key.strip().lower(), default)


def all_facts() -> dict:
    return profile.get("facts", {}) or {}


def forget_fact(key: str) -> bool:
    facts = profile.get("facts", {}) or {}
    key = key.strip().lower()
    if key not in facts:
        return False
    del facts[key]
    return profile.set("facts", facts)


# ---------------------------------------------------------------
# Коррекции
# ---------------------------------------------------------------

def add_correction(wrong: str, right: str) -> bool:
    """Сохраняет коррекцию: «открой лок» → «открой логи»."""
    wrong = wrong.strip().lower()
    right = right.strip()
    if not wrong or not right:
        return False
    if wrong == right.lower():
        return False

    corrections = profile.get("corrections", {}) or {}
    corrections[wrong] = right
    ok = profile.set("corrections", corrections)
    if ok:
        log.info("Коррекция: %r → %r", wrong, right)
    return ok


def find_correction(cmd: str, threshold: float = 0.85) -> str | None:
    """Ищет коррекцию для команды. ... [3 строк]"""
    corrections = profile.get("corrections", {}) or {}
    if not corrections:
        return None

    cmd_low = cmd.strip().lower()
    # Точное
    if cmd_low in corrections:
        return corrections[cmd_low]

    # Нечёткое
    best, best_ratio = None, threshold
    for wrong, right in corrections.items():
        ratio = SequenceMatcher(None, cmd_low, wrong).ratio()
        if ratio > best_ratio:
            best_ratio, best = ratio, right
    if best:
        log.info("Коррекция (нечётко): %r → %r (ratio %.2f)", cmd, best, best_ratio)
    return best


def all_corrections() -> dict:
    return profile.get("corrections", {}) or {}


def forget_correction(wrong: str) -> bool:
    corrections = profile.get("corrections", {}) or {}
    wrong = wrong.strip().lower()
    if wrong not in corrections:
        return False
    del corrections[wrong]
    return profile.set("corrections", corrections)


# ---------------------------------------------------------------
# Сборка контекста для промпта
# ---------------------------------------------------------------

def build_context() -> str:
    """Собирает блок для промпта из профиля, фактов и коррекций. ... [3 строк]"""
    parts = []

    # Базовые поля профиля — name, default_city.
    # Без них LLM не знает, как зовут пользователя и где он живёт,
    # хотя _small_talk и профиль-команды это знают.
    name = profile.get("name")
    city = profile.get("default_city")
    profile_lines = []
    if name:
        profile_lines.append(f"- Имя пользователя: {name}")
    if city:
        profile_lines.append(f"- Город по умолчанию: {city}")
    if profile_lines:
        parts.append("Данные профиля пользователя:\n" + "\n".join(profile_lines))

    facts = all_facts()
    if facts:
        lines = [f"- {k}: {v}" for k, v in facts.items()]
        parts.append("Известные факты о пользователе:\n" + "\n".join(lines))

    corrections = all_corrections()
    if corrections:
        lines = [f"- «{wrong}» → «{right}»" for wrong, right in corrections.items()]
        parts.append("Известные исправления (если пользователь говорит первое, делай второе):\n"
                     + "\n".join(lines))

    if not parts:
        return ""

    return "\n\n" + "\n\n".join(parts) + "\n"
```

### `jarvis/main.py`

```python
"""Точка входа: связывает распознавание, интенты, синтез речи и GUI. ... [11 строк]"""

import logging
import logging.handlers
import threading
import time
from pathlib import Path

from jarvis.matching import wake_score

from jarvis import APP_NAME, __version__
from jarvis.apps import build_apps
from jarvis.config import Config, load_config
from jarvis.intents import IntentHandler
from jarvis.text_utils import normalize
from jarvis.model import ensure_model
from jarvis.reply import Reply
from jarvis.stt import Listener
from jarvis import timers
from jarvis.tts import Speaker
from jarvis.gui import FenixGUI

log = logging.getLogger("jarvis")

BASE_DIR = Path(__file__).resolve().parent.parent
_REJECT = object()


class Jarvis:
    def __init__(self, config, listener, speaker, handler, base_dir: Path,
                 whisper=None, gui=None):
        self.config = config
        self.listener = listener
        self.speaker = speaker
        self.handler = handler
        self.base_dir = base_dir
        self.whisper = whisper
        self.gui = gui
        self.listening_enabled = True
        self.stop_event = threading.Event()
        self._awaiting_until = 0.0
        self._wake_words = [normalize(w) for w in config["wake_words"]]
        self.barge_enabled = bool(config.get("barge_enabled", True))
        if self.listener is not None:
            self.listener.barge_enabled = self.barge_enabled
        self._barge_just_happened = False

        # Сериализация обработки команд: голосовой поток и GUI
        # не должны входить в handler.handle + say() одновременно.
        # Иначе два TTS накладываются, а stateful-поля IntentHandler
        # (pending_password, pending_question) портятся.
        self.cmd_lock = threading.Lock()

        # Отдельный лок для say(). cmd_lock сериализует только handle(),
        # а say() зовут ещё таймеры (timers._fire), mic_watchdog и
        # celebrations — раньше они входили без лока, и speaker.stop()
        # обрывал текущую фразу (или сам таймер молча съедался
        # по wait_end-таймауту). RLock — на случай вложенного вызова.
        self._say_lock = threading.RLock()

    def say(self, reply: Reply) -> bool:
        """Озвучивает Reply. Возвращает True, если сработал barge-in."""
        if reply is None:
            return False
        if not reply.is_stream and not reply.text:
            return False

        with self._say_lock:
            return self._say_locked(reply)

    def _say_locked(self, reply: Reply) -> bool:
        """Тело say() — вызывать ТОЛЬКО через say(), под _say_lock."""
        if self.gui is not None:
            self.gui.set_state("speaking")

        if self.barge_enabled and self.listener is not None:
            self.listener.barge_start()
        elif self.listener is not None:
            self.listener.muted = True

        barge_happened = False
        try:
            if reply.is_stream:
                self._say_stream(reply.stream)
            else:
                self._say_text(reply.text)
            barge_happened = (
                self.barge_enabled
                and self.listener is not None
                and self.listener.barge_flag
            )
        finally:
            if self.barge_enabled and self.listener is not None:
                self.listener.barge_end()
            if self.listener is not None:
                # flush() теперь чистит только очередь — Vosk не трогает.
                self.listener.flush()
                self.listener.muted = False
            if self.gui is not None:
                self.gui.set_state("idle")
        return barge_happened

    def _say_text(self, text: str) -> None:
        self.speaker.play_async(text)
        while self.speaker.is_playing():
            if self.barge_enabled and self.listener is not None and self.listener.barge_flag:
                log.info("Barge-in сработал — прерываю TTS")
                self.speaker.stop()
                break
            time.sleep(0.05)
        self.speaker.wait_end(timeout=30.0)

    def _say_stream(self, gen) -> None:
        """Озвучивает стрим и показывает чанки в GUI. ... [7 строк]"""
        result = {"text": ""}

        def _tee(iterator):
            """Пропускает чанки и в TTS, и в GUI."""
            for chunk in iterator:
                result["text"] += chunk
                if self.gui is not None:
                    self.gui.add_stream_chunk(chunk)
                yield chunk

        def _run():
            try:
                self.speaker.speak_stream(_tee(gen))
            except Exception:
                log.exception("Ошибка в speak_stream")

        t = threading.Thread(target=_run, daemon=True, name="tts-stream")
        t.start()

        try:
            while t.is_alive():
                if self.barge_enabled and self.listener is not None and self.listener.barge_flag:
                    log.info("Barge-in сработал — прерываю стриминг")
                    self.speaker.stop()
                    t.join(timeout=1.0)
                    break
                time.sleep(0.05)
            t.join(timeout=5.0)
        finally:
            # №73: закрываем стрим-пузырь ВСЕГДА
            if self.gui is not None:
                self.gui.end_stream()

            # Финальный текст — в память
            if result["text"] and hasattr(self.handler, "finalize_stream"):
                self.handler.finalize_stream(result["text"])

    def shutdown(self) -> None:
        self.stop_event.set()

    def mic_watchdog(self) -> None:
        """Проверяет микрофон ОДИН РАЗ через mic_check_sec. ... [7 строк]"""
        if not self.config.get("mic_watchdog_enabled", True):
            log.info("mic_watchdog выключен в config")
            return

        delay = float(self.config.get("mic_check_sec", 20))
        if self.stop_event.wait(delay):
            return

        if self.listener.peak >= 50:
            log.info("mic_watchdog: пик %d — микрофон живой", self.listener.peak)
            return

        log.warning("Микрофон молчит (пик %d за %.0f с): %s",
                    self.listener.peak, delay, self.listener.device_name)

        try:
            self.say(Reply(text="Я не слышу микрофон. Проверьте, включён ли он, "
                               "или выберите другое устройство в настройках."))
        except Exception:
            log.exception("mic_watchdog: не удалось озвучить предупреждение")

        if self.gui is not None:
            self.gui._queue.put(("open_mic_tab", None))

        log.info("mic_watchdog: предупреждение показано, больше не повторяем")

    def run_loop(self) -> None:
        try:
            for phrase, audio in self.listener.phrases(self.stop_event):
                if not self.listening_enabled:
                    continue
                try:
                    self._process(phrase, audio)
                except Exception:
                    log.exception("Ошибка обработки фразы %r", phrase)
        except Exception:
            log.exception("Аудиопоток упал")
            self.say(Reply(text="Проблема с микрофоном. Проверьте журнал."))

    def _process(self, phrase: str, audio: bytes) -> None:
        awaiting = time.time() < self._awaiting_until
        cmd = self._extract_command(normalize(phrase))
        pending = getattr(self.handler, "_pending_question", None)
        if pending and time.time() < pending.get("expires_at", 0):
            awaiting = True
        if cmd is None:
            return
        if cmd == "":
            self.say(Reply(text="Слушаю."))
            self._awaiting_until = time.time() + self.config["command_window_sec"]
            return
        if self.whisper is not None and audio:
            refined = self._refine(audio, awaiting)
            if refined is _REJECT:
                log.info("Whisper не подтвердил wake-слово — игнорирую (ложное срабатывание)")
                return
            if refined:
                cmd = refined

        if self.gui is not None:
            self.gui.add_message("user", cmd)
            self.gui.set_state("listening")

        # Observer: запоминаем фразу юзера.
        if getattr(self, "observer", None) is not None:
            try:
                self.observer.observe("user", cmd)
            except Exception:
                log.exception("Observer.observe (user) упал")

        # Сериализация с GUI: пока GUI не отдаст cmd_lock,
        # голосовой поток ждёт. И наоборот.
        with self.cmd_lock:
            reply = self.handler.handle(cmd)

            if self.gui is not None and not reply.is_stream:
                self.gui.add_message("assistant", reply.text or "")

            self._awaiting_until = time.time() + float(
                self.config.get("dialog_window_sec", 8))

            if getattr(self.handler, "_reset_requested", False):
                self.speaker.stop()
                self.speaker.wait_end(timeout=1.0)

            # Observer: запоминаем ответ Феникса.
            if getattr(self, "observer", None) is not None and not reply.is_stream:
                try:
                    self.observer.observe("assistant", reply.text or "")
                except Exception:
                    log.exception("Observer.observe (assistant) упал")

            barge_happened = self.say(reply)

            if getattr(self.handler, "_reset_requested", False):
                self._awaiting_until = 0.0
                self.handler._reset_requested = False
                log.info("Сброс: жду wake-слово")
                return

            if barge_happened:
                log.info("Barge-in: окно диалога уже открыто (без wake-слова)")
                self._awaiting_until = time.time() + float(
                    self.config.get("dialog_window_sec", 8))

    def _refine(self, audio: bytes, awaiting: bool):
        try:
            text = normalize(self.whisper.transcribe(audio))
        except Exception:
            log.exception("Whisper не справился, использую текст Vosk")
            return None
        if not text:
            return _REJECT
        tokens = text.split()
        for i, tok in enumerate(tokens):
            if self._is_wake(tok):
                return " ".join(tokens[i + 1:])
        if awaiting:
            return text
        if tokens and wake_score(tokens[0], self._wake_words[0]) >= 0.5:
            return " ".join(tokens[1:])
        return _REJECT

    def _extract_command(self, text: str) -> str | None:
        tokens = text.split()
        for i, tok in enumerate(tokens):
            if self._is_wake(tok):
                return " ".join(tokens[i + 1:])
        if time.time() < self._awaiting_until:
            return text
        return None

    def _is_wake(self, token: str) -> bool:
        return token in self._wake_words or any(
            wake_score(token, w) >= 0.8 for w in self._wake_words
        )


def setup_logging() -> None:
    from jarvis import paths as _paths

    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    LOGS_DIR = _paths.logs_dir()

    fmt = "%(asctime)s %(name)s %(levelname)s %(message)s"
    formatter = logging.Formatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(logging.INFO)
    root.addHandler(console)

    jarvis_handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / "jarvis.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    jarvis_handler.setFormatter(formatter)
    jarvis_handler.setLevel(logging.INFO)
    root.addHandler(jarvis_handler)

    errors_handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / "errors.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    errors_handler.setFormatter(formatter)
    errors_handler.setLevel(logging.WARNING)
    root.addHandler(errors_handler)

    actions_logger = logging.getLogger("jarvis.actions")
    actions_logger.setLevel(logging.INFO)
    actions_logger.propagate = False
    actions_handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / "actions.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    actions_handler.setFormatter(formatter)
    actions_logger.addHandler(actions_handler)

    # Глобальный перехват исключений в потоках
    def _thread_excepthook(args):
        thread_name = args.thread.name if args.thread else "?"
        log.critical(
            "Необработанное исключение в потоке %r:",
            thread_name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = _thread_excepthook

    # Глобальный перехват для ГЛАВНОГО потока
    import sys

    def _sys_excepthook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            return
        log.critical(
            "Необработанное исключение в главном потоке:",
            exc_info=(exc_type, exc_value, exc_tb),
        )

    sys.excepthook = _sys_excepthook


def main() -> None:
    setup_logging()
    log.info("%s v%s запускается", APP_NAME, __version__)

    # Порядок импортов критичен для Windows:
    #   faster_whisper → ctranslate2 → winrt.
    # Если faster_whisper нет — ctranslate2 нет — winrt может дать
    # access violation. Поэтому логируем явно, что отсутствует.
    for _mod in ("faster_whisper", "ctranslate2"):
        try:
            __import__(_mod)
        except ImportError:
            log.warning(
                "Модуль %s не установлен. Whisper будет недоступен, "
                "работаю только на Vosk. Установи: pip install %s",
                _mod, _mod.replace("_", "-"),
            )

    config: Config = load_config(BASE_DIR)
    from jarvis import profile as _profile
    from jarvis import weather as _weather
    _profile.init()
    _weather.set_config(config)
    # ensure_model сам найдёт/скопирует/скачает модель в ASCII-путь.
    # Передаём локальную папку models (может быть в C:\jarvis\models),
    # если она есть — модель скопируется оттуда, иначе скачается.
    local_models = BASE_DIR / "models"
    if not local_models.exists():
        local_models = None
    model_dir = ensure_model(local_models)

    whisper = None
    if config.get("use_whisper", True):
        try:
            from jarvis.stt import WhisperTranscriber
            whisper = WhisperTranscriber(
                config.get("whisper_model", "auto"),
                config.get("whisper_device", "auto"),
            )
        except Exception:
            log.exception("Whisper не завёлся, работаю только на Vosk")

    brain = None
    if config.get("use_llm", True):
        from jarvis.brain import Brain
        brain = Brain(
            config.get("llm_model", "qwen2.5:7b-instruct"),
            config.get("ollama_url", "http://127.0.0.1:11434"),
            prompt_level=config.get("prompt_level", "auto"),
            temperature=config.get("llm_temperature", 0.7),
            config=config,
        )
        if not brain.available:
            brain = None

    speaker = Speaker(config)
    listener = Listener(model_dir, config["sample_rate"], config.get("input_device"))

    gui = None
    if config.get("gui_enabled", True):
        try:
            gui = FenixGUI(None, config)
        except Exception:
            log.exception("GUI не завёлся")

    handler = IntentHandler(
        config, build_apps(config), brain,
        listener=listener, gui=gui,
    )

    jarvis = Jarvis(config, listener, speaker, handler, BASE_DIR, whisper, gui=gui)

    # Прогрев тяжёлых API — brightness через WMI (~0.5 сек).
    # Иначе первый голосовой запрос «какая яркость» виснет.
    try:
        from jarvis import actions
        actions.get_brightness()
    except Exception:
        log.debug("Прогрев brightness не удался — не критично")

    # Обратные ссылки для праздничных триггеров
    handler.jarvis = jarvis
    if gui is not None:
        gui.jarvis = jarvis


    # Observer — фоновое извлечение фактов из диалога.
    try:
        from jarvis import profile as _profile_mod
        from jarvis import learning as _learning_mod
        from jarvis.observer import DialogObserver
        observer = DialogObserver(
            config=config,
            brain=brain,
            profile_module=_profile_mod,
            learning_module=_learning_mod,
        )
        observer.start()
        jarvis.observer = observer
        handler.observer = observer
    except Exception:
        log.exception("Observer не завёлся")
        observer = None

    # --- Подписки: изменения конфига применяются на лету ---
    def _on_config_change(key: str, value):
        if key == "tts_voice":
            speaker.set_voice(value)
        elif key == "voice_rate":
            speaker.set_rate(value)
        elif key == "mode":
            handler.mode = value
        elif key == "barge_enabled":
            jarvis.barge_enabled = bool(value)
            if listener is not None:
                listener.barge_enabled = bool(value)

    config.subscribe(_on_config_change)

    def _on_timer_fire(timer: dict):
        text = timer.get("text") or "время вышло"
        msg = f"Напоминание: {text}."
        log.info("Таймер сработал: %s", msg)
        jarvis.say(Reply(text=msg))

    timers.set_on_fire(_on_timer_fire)
    restored = timers.restore_all()
    if restored:
        log.info("Восстановлено напоминаний: %d", restored)

    # Jarvis — в фоновом потоке
    worker = threading.Thread(target=jarvis.run_loop, daemon=True, name="jarvis-listener")
    worker.start()
    threading.Thread(target=jarvis.mic_watchdog, daemon=True, name="mic-watchdog").start()

    # Mood: раз в 60 сек проверяем, не «устарело» ли состояние.
    # Возврат к neutral через 5 мин (см. mood.decay).
    def _mood_decay_loop():
        while not jarvis.stop_event.is_set():
            if jarvis.stop_event.wait(60.0):
                return
            try:
                from jarvis import mood
                mood.decay()
            except Exception:
                log.exception("mood.decay упал в фоновом потоке")

    threading.Thread(target=_mood_decay_loop, daemon=True,
                     name="mood-decay").start()

    try:
        from jarvis import first_run
        if first_run.is_first_run():
            log.info("Первый запуск: приветствие через задачу")
            jarvis.say(Reply(text=first_run.greeting()))
        else:
            jarvis.say(Reply(text=f"{APP_NAME} запущен и готов к работе."))
    except Exception:
        log.exception("Ошибка приветствия")
        jarvis.say(Reply(text=f"{APP_NAME} запущен и готов к работе."))

    # =================================================================
    # ТРЕЙ ВРЕМЕННО ОТКЛЮЧЁН.
    #
    # Причина: pystray требует свой Windows message loop, а главный поток
    # занят flet'ом (ft.run блокирует). Попытка запустить pystray в фоне
    # приводит к зависанию GUI.
    # =================================================================
    if config.get("tray_enabled", False):
        log.warning(
            "tray_enabled=true, но трей временно отключён (в разработке). "
            "Феникс работает без трея. Выход — Ctrl+C или диспетчер задач."
        )

    # === Режим запуска (№84) ===
    launch_mode = str(config.get("launch_mode", "gui") or "gui").lower()
    if launch_mode not in ("gui", "tray"):
        launch_mode = "gui"

    if launch_mode == "tray":
        log.warning(
            "launch_mode=tray, но трей отключён — переключаюсь на gui"
        )
        launch_mode = "gui"

    if gui is not None:
        if launch_mode == "tray":
            log.info("launch_mode=tray — GUI запущен, но окно скрыто")
            gui.start_hidden = True
        else:
            log.info("Запускаю Flet в главном потоке (launch_mode=gui)")

        # Flet ВСЕГДА в главном потоке (signal.signal)
        gui.run_main()
    else:
        log.info("GUI выключен — жду завершения")
        jarvis.stop_event.wait()

    jarvis.shutdown()
    log.info("Завершение работы")


if __name__ == "__main__":
    main()
```

### `jarvis/matching.py`

```python
"""Нечёткое сопоставление речи с названиями: транслитерация + difflib. ... [4 строк]"""

import re
from difflib import SequenceMatcher

_RU_DIGRAPHS = {"дж": "j"}  # фонетика: «джарвис» -> jarvis, а не dzharvis
_RU_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def translit(text: str) -> str:
    text = text.lower()
    for ru, lat in _RU_DIGRAPHS.items():
        text = text.replace(ru, lat)
    return "".join(_RU_LAT.get(ch, ch) for ch in text)


_FOLD = str.maketrans({"c": "k", "q": "k", "w": "v", "x": "ks"})


def _fold(s: str) -> str:
    """Фонетическое выравнивание латиницы: Camo ~ камо(kamo), roblox ~ роблокс."""
    return s.replace("ph", "f").translate(_FOLD)


_NUM = {"ноль": "0", "один": "1", "одна": "1", "два": "2", "две": "2", "три": "3",
        "четыре": "4", "пять": "5", "шесть": "6", "семь": "7", "восемь": "8",
        "девять": "9", "десять": "10"}


def _num_norm(s: str) -> str:
    """«дота два» -> «дота 2»: в названиях номера всегда цифрами."""
    return " ".join(_NUM.get(w, w) for w in s.split())


def wake_score(token: str, wake_word: str) -> float:
    """Строгая похожесть для wake-слова. ... [9 строк]"""
    if not token or not wake_word:
        return 0.0
    tok = token.lower()
    wake = wake_word.lower()
    tok_t = translit(tok)
    wake_t = translit(wake)
    return max(
        SequenceMatcher(None, tok, wake).ratio(),
        SequenceMatcher(None, tok_t, wake_t).ratio(),
        SequenceMatcher(None, tok, wake_t).ratio(),
        SequenceMatcher(None, tok_t, wake).ratio(),
    )


def _skeleton(s: str) -> str:
    """Согласный скелет: stim/steam -> stm. Гласные между языками плавают,
    согласные при транслитерации сохраняются."""
    return re.sub(r"[aeiouy\s]", "", translit(s))


def match_score(spoken: str, candidate: str) -> float:
    """Похожесть сказанного на название (0..1). Оба сравниваются в нижнем регистре,
    сказанное — ещё и в транслите; пробуем целиком, без пробелов и по словам."""
    cand = re.sub(r"\(.*?\)", " ", candidate.lower()).strip()
    cand = re.sub(r"\s+", " ", cand)
    if not spoken or not cand:
        return 0.0
    spoken = _num_norm(spoken)
    cand = _num_norm(cand)

    len_spoken = len(spoken.replace(" ", ""))

    best = 0.0
    for s in {spoken, _fold(translit(spoken))}:
        for c in {cand, _fold(translit(cand))}:
            if s == c:
                return 1.0
            if len(s) >= 5 and (s in c or c in s):
                best = max(best, 0.9)
            best = max(best, SequenceMatcher(None, s, c).ratio())
            best = max(best, SequenceMatcher(None, s.replace(" ", ""), c.replace(" ", "")).ratio())
            s_words, c_words = s.split(), c.split()
            for word in c_words:
                best = max(best, SequenceMatcher(None, s, word).ratio())
            if len(s_words) > 1 and c_words:
                avg = sum(
                    max(SequenceMatcher(None, sw, cw).ratio() for cw in c_words)
                    for sw in s_words
                ) / len(s_words)
                best = max(best, avg)
    sk_s, sk_c = _skeleton(spoken), _skeleton(cand)
    if len(sk_s) >= 3 and sk_s == sk_c:
        best = max(best, 0.8)

    if len_spoken < 4 and best < 0.85:
        return 0.0

    return best
```

### `jarvis/memory.py`

```python
"""Память диалога — на профиль. ... [13 строк]"""

import json
import logging
import os
import re
import tempfile
import threading

from jarvis import profile as _profile

log = logging.getLogger("jarvis.memory")

_lock = threading.RLock()


# ---------------------------------------------------------------
# Чтение / запись
# ---------------------------------------------------------------

def load(limit: int | None = None) -> list:
    """Загружает историю диалога. Без limit — все сообщения."""
    path = _profile.dialog_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            log.warning("%s — не массив, игнорирую", path)
            return []
        if limit and limit > 0:
            return data[-limit:]
        return data
    except Exception:
        log.exception("Не удалось прочитать %s", path)
        return []


def append(message: dict) -> None:
    """Добавляет одно сообщение и пишет на диск атомарно. ... [5 строк]"""
    if not isinstance(message, dict):
        return
    path = _profile.dialog_path()
    with _lock:
        try:
            data = []
            if path.exists():
                raw = path.read_text(encoding="utf-8")
                if raw.strip():
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        data = parsed
            data.append(message)

            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                dir=str(path.parent), suffix=".tmp", prefix=path.stem + "."
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_name, path)
            except Exception:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
        except Exception:
            log.exception("Не удалось дописать в %s", path)


def clear() -> None:
    """Очищает память текущего профиля."""
    path = _profile.dialog_path()
    try:
        if path.exists():
            path.unlink()
        log.info("Память диалога очищена: %s", path)
    except Exception:
        log.exception("Не удалось очистить %s", path)


# ---------------------------------------------------------------
# Команды / описание
# ---------------------------------------------------------------

def describe(messages: list, limit: int = 6) -> str:
    """Краткий пересказ последних тем."""
    if not messages:
        return "Пока ничего не обсуждали."
    user_msgs = [m.get("content", "") for m in messages
                 if m.get("role") == "user" and m.get("content")]
    if not user_msgs:
        return "Пока ничего не обсуждали."
    recent = user_msgs[-limit:]
    topics = ", ".join(f"«{t}»" for t in recent)
    return f"Последние темы: {topics}."


def handle_memory_command(cmd: str, messages: list) -> tuple[str | None, bool]:
    """Разбирает команды памяти. ... [3 строк]"""
    if re.search(r"(что|о\s+ч[её]м)\s+(мы\s+)?(обсуждал|говорил|болтал)", cmd) \
            or cmd in {"что мы обсуждали", "о чём мы говорили", "что обсуждали"}:
        return describe(messages), False

    if re.search(r"(забудь|очисти|сбрось|сотри)\s+(вс[её]|память|историю|диалог)", cmd) \
            or cmd in {"забудь всё", "очисти память", "сбрось память", "сотри память"}:
        clear()
        return "Память очищена.", True

    if re.search(r"(сохрани|запиши)\s+память", cmd) \
            or cmd in {"сохрани память", "запиши память"}:
        return "Память сохраняется автоматически.", False

    return None, False
```

### `jarvis/model.py`

```python
"""Скачивание и распаковка модели Vosk для русского языка (~45 МБ). ... [5 строк]"""

import logging
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

from jarvis import paths

log = logging.getLogger("jarvis.model")

MODEL_NAME = "vosk-model-small-ru-0.22"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"


def _progress(blocks: int, block_size: int, total: int) -> None:
    """Прогресс-бар скачивания модели. ... [4 строк]"""
    if total <= 0:
        return
    if sys.stdout is None:
        return
    try:
        pct = min(100, blocks * block_size * 100 // total)
        sys.stdout.write(f"\rСкачивание модели: {pct}%")
        sys.stdout.flush()
    except Exception:
        pass


def ensure_model(local_models_dir: Path | None = None) -> Path:
    """Возвращает путь к модели Vosk в ASCII-пути. ... [4 строк]"""
    safe_dir = paths.program_models_dir() / MODEL_NAME

    if safe_dir.exists() and (safe_dir / "am").exists():
        log.info("Модель Vosk готова: %s", safe_dir)
        return safe_dir

    # Если есть локальная копия (например, C:\jarvis\models\...) — копируем
    if local_models_dir is not None:
        local_model = local_models_dir / MODEL_NAME
        if local_model.exists() and (local_model / "am").exists():
            log.info("Копирую модель Vosk: %s → %s", local_model, safe_dir)
            try:
                if safe_dir.exists():
                    shutil.rmtree(safe_dir)
                shutil.copytree(local_model, safe_dir)
                log.info("Модель скопирована")
                return safe_dir
            except Exception:
                log.exception("Не удалось скопировать модель")

    # Скачиваем
    safe_dir.parent.mkdir(parents=True, exist_ok=True)
    zip_path = safe_dir.parent / f"{MODEL_NAME}.zip"

    log.info("Скачиваю модель Vosk: %s", MODEL_URL)
    try:
        urllib.request.urlretrieve(MODEL_URL, zip_path, reporthook=_progress)
        if sys.stdout is not None:
            sys.stdout.write("\n")
    except Exception:
        log.exception("Не удалось скачать модель Vosk")
        raise

    log.info("Распаковка модели...")
    try:
        with zipfile.ZipFile(zip_path) as zf:
            # В архиве одна папка vosk-model-small-ru-0.22/.
            # Распаковываем её СОДЕРЖИМОЕ в safe_dir, без вложенности.
            for member in zf.namelist():
                parts = member.split("/", 1)
                if len(parts) < 2 or not parts[1]:
                    continue
                target = safe_dir / parts[1]
                if member.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, open(target, "wb") as dst:
                        dst.write(src.read())
    finally:
        zip_path.unlink(missing_ok=True)

    if not safe_dir.exists():
        raise RuntimeError(f"После распаковки не найдена папка {safe_dir}")
    log.info("Модель готова: %s", safe_dir)
    return safe_dir
```

### `jarvis/modes.py`

```python
"""Режимы работы Феникса: commands, llm, combo."""

import logging
import re

from jarvis import config_manager

log = logging.getLogger("jarvis.modes")

NAMES = {
    "commands": "только команды",
    "llm": "только ИИ",
    "combo": "комбинированный",
}


def get_mode(config) -> str:
    m = config.get("mode", "combo")
    return m if m in NAMES else "combo"


def set_mode(mode: str, config=None) -> str:
    if mode not in NAMES:
        return f"Неизвестный режим: {mode}."
    if config is not None:
        config.set("mode", mode)
    else:
        config_manager.update("mode", mode)
    log.info("Режим переключён на %s", mode)
    return f"Режим: {NAMES[mode]}."


def handle_mode_command(cmd: str, current_mode: str, config=None) -> tuple[str | None, str]:
    if re.search(r"режим\s+(команд|команды|только\s+команд)", cmd) \
            or cmd in {"только команды", "без ии"}:
        return set_mode("commands", config), "commands"

    if re.search(r"режим\s+(ии|искусственн\w*|нейросет\w*|нейронк\w*)", cmd) \
            or cmd in {"только ии", "режим ии", "режим нейросети", "только нейросеть"}:
        return set_mode("llm", config), "llm"

    if re.search(r"(комбинированн|обычн|стандартн|смешанн)\w*\s+режим", cmd) \
            or re.search(r"режим\s+(комбо|обычн|стандартн|смешанн|комбинированн)", cmd) \
            or cmd in {"обычный режим", "комбо", "режим комбо"}:
        return set_mode("combo", config), "combo"

    if re.search(r"(какой|текущий|что\s+за)\s+режим", cmd) \
            or cmd in {"какой режим", "текущий режим"}:
        return f"Сейчас режим: {NAMES.get(current_mode, current_mode)}.", current_mode

    return None, current_mode
```

### `jarvis/mood.py`

```python
"""Mood — эмоциональное состояние ассистента. ... [26 строк]"""

import logging
import re
import time
from threading import RLock

from jarvis import profile

log = logging.getLogger("jarvis.mood")

# Все допустимые состояния.
STATES = ("neutral", "happy", "excited", "annoyed", "bored", "tired")

# Значение по умолчанию.
DEFAULT_MOOD = {
    "state": "neutral",
    "since": 0.0,
    "reason": "",
}

# Подписки и лок.
_lock = RLock()
_listeners: list = []

# Время «жизни» состояния до возврата к neutral.
DEFAULT_DECAY_SEC = 300  # 5 минут


# =================================================================
# Чтение / запись
# =================================================================

def get() -> dict:
    """Текущее настроение (с дефолтами)."""
    raw = profile.get("mood", {}) or {}
    result = dict(DEFAULT_MOOD)
    if isinstance(raw, dict):
        for k in DEFAULT_MOOD:
            if raw.get(k) is not None:
                result[k] = raw[k]
    return result


def get_state() -> str:
    """Только state — для быстрых проверок."""
    return get().get("state", "neutral")


def set_mood(state: str, reason: str = "") -> bool:
    """Устанавливает настроение + оповещает подписчиков. ... [3 строк]"""
    if state not in STATES:
        log.warning("mood.set_mood: неизвестное состояние %r", state)
        return False

    current = get_state()
    current_reason = get().get("reason", "")

    # Если ничего не изменилось — выходим.
    if current == state and current_reason == reason:
        return True

    ok = profile.set("mood", {
        "state": state,
        "since": time.time(),
        "reason": reason,
    })
    if not ok:
        log.error("mood.set_mood: не удалось сохранить %r", state)
        return False

    log.info("Mood: %s → %s (%s)", current, state, reason)

    with _lock:
        listeners = list(_listeners)
    for cb in listeners:
        try:
            cb(current, state)
        except Exception:
            log.exception("Подписчик mood упал на %s → %s", current, state)

    return True


# =================================================================
# Подписки
# =================================================================

def subscribe(callback) -> None:
    """callback(old_state, new_state) — вызывается при смене настроения."""
    with _lock:
        if callback not in _listeners:
            _listeners.append(callback)


def unsubscribe(callback) -> None:
    """Удаляет подписку."""
    with _lock:
        try:
            _listeners.remove(callback)
        except ValueError:
            pass


# =================================================================
# Детекция из текста
# =================================================================

# Регулярки для быстрой эвристики.
_PRAISE = re.compile(
    r"\b(спасибо|благодар\w*|молодец|умниц\w*|круто|отлично|"
    r"супер|класс|здорово|хорош\w*|правильно|верно)\b",
    flags=re.IGNORECASE,
)

_EXCITED = re.compile(
    r"\b(ура|ура-ура|получилось|вау|ого|ничего себе|невероятно|"
    r"офигенно|офигеть|обалдеть|кайф)\b",
    flags=re.IGNORECASE,
)

_RUDE = re.compile(
    r"\b(тупой|тупая|тупица|дурак|дура|идиот|идиотка|дебил|дебилка|"
    r"кретин|кретинка|бестолочь|ничего не понимаешь|"
    r"туп\w* ты|идиот\w*)\b",
    flags=re.IGNORECASE,
)

_TIRED = re.compile(
    r"\b(устал\w*|засыпаю|спать хочу|вымотан\w*|без сил|"
    r"не могу больше|замучил\w*)\b",
    flags=re.IGNORECASE,
)


def detect(cmd: str) -> str | None:
    """Быстрая эвристика: какое настроение вызвать? ... [3 строк]"""
    if not cmd:
        return None

    # Порядок важен — грубость выше похвалы.
    # Иначе «спасибо, ты тупой» уйдёт в happy.
    if _RUDE.search(cmd):
        return "annoyed"
    if _TIRED.search(cmd):
        return "tired"
    if _EXCITED.search(cmd):
        return "excited"
    if _PRAISE.search(cmd):
        return "happy"
    return None


def apply_from_text(cmd: str) -> bool:
    """Определяет и устанавливает mood. Возвращает True, если изменил."""
    detected = detect(cmd)
    if not detected:
        return False
    return set_mood(detected, reason="dialog")


# =================================================================
# Decay — возврат к neutral
# =================================================================

def decay(max_age_sec: int = DEFAULT_DECAY_SEC) -> bool:
    """Возвращает к neutral, если состояние «старое». ... [3 строк]"""
    m = get()
    if m["state"] == "neutral":
        return False

    age = time.time() - m.get("since", 0)
    if age < max_age_sec:
        return False

    log.info("Mood: %s устарел (%.0f сек) → neutral",
             m["state"], age)
    set_mood("neutral", reason="decay")
    return True


# =================================================================
# Влияние на систему
# =================================================================

# Множители скорости речи для TTS.
_RATE_MULTIPLIERS = {
    "neutral": 1.0,
    "happy":   1.0,
    "excited": 1.1,
    "annoyed": 1.0,
    "bored":   0.95,
    "tired":   0.9,
}


def effective_rate(base_rate: float) -> float:
    """Скорость речи с учётом mood."""
    mult = _RATE_MULTIPLIERS.get(get_state(), 1.0)
    return round(base_rate * mult, 3)


# Цвета для GUI — статус-сфера.
_COLORS = {
    "neutral": "#484f58",
    "happy":   "#3fb950",
    "excited": "#d29922",
    "annoyed": "#f85149",
    "bored":   "#8b949e",
    "tired":   "#6e7681",
}


def color() -> str:
    """Цвет статус-сферы для текущего настроения."""
    return _COLORS.get(get_state(), _COLORS["neutral"])


# =================================================================
# System prompt
# =================================================================

_PROMPT_HINTS = {
    "happy":   "Пользователь тебя похвалил или поблагодарил — "
               "отвечай теплее, бодрее, можно слегка самодовольно.",
    "excited": "Пользователь в восторге — поддержи его энергию, "
               "отвечай эмоциональнее.",
    "annoyed": "Пользователь грубит — НЕ извиняйся, ответь сухо, "
               "с лёгкой иронией, но не хами. Осади спокойно.",
    "bored":   "Давно молчание или скучный диалог — отвечай коротко, "
               "с ленцой, не разворачивайся.",
    "tired":   "Пользователь устал — отвечай мягко, чуть медленнее, "
               "без лишних слов.",
}


def build_prompt_block() -> str:
    """Блок для system prompt на основе текущего настроения."""
    state = get_state()
    hint = _PROMPT_HINTS.get(state)
    if not hint:
        return ""
    return f"\n\nТекущее настроение диалога: {state}.\n{hint}\n"


# =================================================================
# Описание для озвучки
# =================================================================

_DESCRIPTIONS = {
    "neutral": "Спокойное, ровное.",
    "happy":   "Хорошее, тёплое.",
    "excited": "Восторженное, бодрое.",
    "annoyed": "Раздражённое.",
    "bored":   "Скучающее.",
    "tired":   "Уставшее.",
}


def describe() -> str:
    """Человеческое описание для озвучки."""
    state = get_state()
    desc = _DESCRIPTIONS.get(state, "Спокойное.")
    since = get().get("since", 0)
    if since:
        age = int(time.time() - since)
        if age < 60:
            when = f"{age} секунд назад"
        elif age < 3600:
            when = f"{age // 60} минут назад"
        else:
            when = f"{age // 3600} часов назад"
        return f"Настроение: {desc} Установлено {when}."
    return f"Настроение: {desc}"


# =================================================================
# Команды (для fast/persona.py)
# =================================================================

def handle_mood_command(cmd: str) -> str | None:
    """Голосовые команды настроения. Возвращает ответ или None."""
    low = cmd.lower()

    # «как настроение» / «какое у тебя настроение»
    if (re.search(r"(какое|как)\s+(у\s+тебя\s+)?настроение", low)
            or low in {"настроение", "как настроение"}):
        return describe()

    # «не грусти» / «взбодрись»
    if re.search(r"(не\s+грусти|взбодрись|улыбнись|повеселей)", low):
        set_mood("happy", reason="user_request")
        return "Стараюсь."

    # «успокойся»
    if re.search(r"(успокойся|не\s+злись|не\s+сердись)", low):
        set_mood("neutral", reason="user_request")
        return "Уже спокоен."

    return None
```

### `jarvis/observer.py`

```python
"""Observer — фоновое наблюдение за диалогом. ... [7 строк]"""

import json
import logging
import threading
import time
from collections import deque

log = logging.getLogger("jarvis.observer")


EXTRACT_PROMPT = """Ты — анализатор диалога. На вход даётся история сообщений.
Извлеки ЛЮБЫЕ факты о пользователе, которые упомянуты в диалоге.

Верни ТОЛЬКО JSON:
{
  "name": null или "Максим",
  "city": null или "Нижний Новгород",
  "age": null или 18,
  "style": null или "formal|friendly|sarcastic|brief",
  "facts": {
    "ключ": "значение"
  }
}

Правила:
- name — имя пользователя («меня зовут Максим», «я Максим»).
- city — город в ИМЕНИТЕЛЬНОМ падеже («живу в нижнем» → «Нижний Новгород»).
- age — целое число лет.
- style — если юзер описал предпочтения общения.
- facts — объект с фактами: «нравится», «не нравится», «работа», «увлечение», «настроение».
- Если факт не упомянут — null или {}.
- НЕ выдумывай. Только то, что явно сказано.
- Отвечай ТОЛЬКО JSON."""


class DialogObserver:
    """Наблюдатель диалога. Работает в отдельном потоке."""

    def __init__(self, config, brain, profile_module, learning_module,
                 min_interval: float = 30.0, batch_size: int = 6):
        self.config = config
        self.brain = brain
        self.profile = profile_module
        self.learning = learning_module

        self.min_interval = min_interval
        self.batch_size = batch_size

        self._history: deque = deque(maxlen=20)
        self._last_extract = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self._enabled = bool(
            brain is not None
            and getattr(brain, "available", False)
            and config.get("observer_enabled", True)
        )
        if self._enabled:
            log.info("Observer: включён (интервал %.0f сек, батч %d)",
                     min_interval, batch_size)
        else:
            log.info("Observer: выключен (LLM недоступна или отключён в конфиге)")

    def start(self) -> None:
        if not self._enabled:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="observer"
        )
        self._thread.start()
        log.info("Observer: поток запущен")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def observe(self, role: str, text: str) -> None:
        """Добавляет сообщение в буфер."""
        if not self._enabled or not text:
            return
        with self._lock:
            self._history.append({"role": role, "text": text})

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(5.0)
            if self._stop.is_set():
                break

            now = time.time()
            with self._lock:
                history_len = len(self._history)
                if history_len < self.batch_size:
                    continue
                if now - self._last_extract < self.min_interval:
                    continue
                history = list(self._history)

            try:
                self._extract(history)
                self._last_extract = time.time()
            except Exception:
                log.exception("Observer: ошибка извлечения")

    def _extract(self, history: list) -> None:
        if not history:
            return

        lines = []
        for msg in history[-self.batch_size:]:
            role = "Пользователь" if msg["role"] == "user" else "Феникс"
            lines.append(f"{role}: {msg['text']}")
        dialog = "\n".join(lines)

        log.debug("Observer: извлекаю факты из %d сообщений", len(history))

        try:
            raw = self.brain._request(
                [
                    {"role": "system", "content": EXTRACT_PROMPT},
                    {"role": "user", "content": dialog},
                ],
                timeout=15.0,
                num_predict=200,
            )
            data = json.loads(raw)
        except json.JSONDecodeError:
            log.debug("Observer: LLM вернула не JSON")
            return
        except Exception:
            log.exception("Observer: LLM не справилась")
            return

        if not isinstance(data, dict):
            return

        self._apply(data)

    def _apply(self, data: dict) -> None:
        applied = []

        name = (data.get("name") or "").strip()
        if name and not self.profile.get("name"):
            self.profile.set("name", name[:40])
            applied.append(f"name={name}")

        city = (data.get("city") or "").strip()
        if city and not self.profile.get("default_city"):
            self.profile.set("default_city", city[:60])
            applied.append(f"city={city}")

        age = data.get("age")
        if isinstance(age, (int, float)) and 5 < age < 130:
            if not self.profile.get("age"):
                self.profile.set("age", int(age))
                applied.append(f"age={int(age)}")

        style_raw = (data.get("style") or "").strip().lower()
        if style_raw:
            try:
                from jarvis import persona
                style = persona.normalize_style(style_raw)
                if style:
                    current = persona.get().get("speech_style", "friendly")
                    if current == "friendly":
                        persona.set_field("speech_style", style)
                        applied.append(f"style={style}")
            except Exception:
                log.exception("Observer: ошибка установки стиля")

        facts = data.get("facts") or {}
        if isinstance(facts, dict):
            for key, value in facts.items():
                if not isinstance(value, str) or not value.strip():
                    continue
                key = key.strip().lower()[:40]
                value = value.strip()[:200]
                if self.learning.get_fact(key):
                    continue
                self.learning.add_fact(key, value)
                applied.append(f"{key}={value}")

        if applied:
            log.info("Observer: применил — %s", ", ".join(applied))
```

### `jarvis/packs.py`

```python
"""Загрузка и выгрузка паков команд из папки packs/."""

import json
import logging
import re
from pathlib import Path

log = logging.getLogger("jarvis.packs")

BASE_DIR = Path(__file__).resolve().parent.parent
PACKS_DIR = BASE_DIR / "packs"

# Алиасы имён паков: что говорит пользователь → имя файла
_PACK_ALIASES = {
    "игр": "games", "игры": "games", "игра": "games",
    "играм": "games", "игру": "games", "гейм": "games", "геймс": "games",
    "приложение": "apps", "приложения": "apps", "приложению": "apps",
    "приложений": "apps", "прог": "apps", "проги": "apps", "прогу": "apps",
    "сайт": "sites", "сайты": "sites", "сайтов": "sites", "сайту": "sites",
    "работа": "work", "работы": "work", "работу": "work", "рабочий": "work",
    "система": "system", "системы": "system", "систем": "system",
    "системный": "system", "системные": "system",
}


def normalize_name(name: str) -> str:
    """Приводит «игр» → «games», «приложение» → «apps» и т.п."""
    n = name.strip().lower().rstrip(".,!?")
    return _PACK_ALIASES.get(n, n)


def list_available() -> list[str]:
    if not PACKS_DIR.exists():
        return []
    return sorted(p.stem for p in PACKS_DIR.glob("*.json"))


def load_pack(name: str) -> list | None:
    name = normalize_name(name)
    path = PACKS_DIR / f"{name}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            log.warning("Пак %s — не массив, игнорирую", name)
            return None
        return data
    except Exception:
        log.exception("Не удалось прочитать пак %s", name)
        return None


def load_active(config) -> list:
    active = config.get("active_packs", [])
    result = []
    for name in active:
        pack = load_pack(name)
        if pack:
            result.extend(pack)
            log.info("Пак '%s': загружено %d команд", name, len(pack))
    return result


def save_active(active: list[str], config=None) -> None:
    if config is not None:
        config.set("active_packs", sorted(set(active)))
    else:
        from jarvis import config_manager
        config_manager.update("active_packs", sorted(set(active)))
    log.info("Активные паки сохранены: %s", active)


def handle_pack_command(cmd: str, current_active: list[str], config=None) -> tuple[str | None, list[str]]:
    available = list_available()

    if re.search(r"(какие|список|покажи)\s+пак", cmd) \
            or cmd in {"какие паки", "список паков", "покажи паки"}:
        if not available:
            return "Папка packs пуста.", current_active
        active_str = ", ".join(current_active) if current_active else "нет"
        return f"Доступны: {', '.join(available)}. Активны: {active_str}.", current_active

    m = re.search(r"(загрузи|включи|подключи)\s+пак\s+(\S+)", cmd)
    if m:
        name = normalize_name(m.group(2))
        if name not in available:
            return f"Пак '{name}' не найден. Доступны: {', '.join(available)}.", current_active
        if name in current_active:
            return f"Пак '{name}' уже активен.", current_active
        new_active = current_active + [name]
        save_active(new_active, config)
        return f"Пак '{name}' загружен.", new_active

    if re.search(r"(активируй|загрузи|включи|подключи)\s+все\s+пак", cmd) \
            or cmd in {"активируй все паки", "загрузи все паки", "включи все паки"}:
        if not available:
            return "Папка packs пуста.", current_active
        new_active = sorted(set(current_active + available))
        save_active(new_active, config)
        return f"Активированы все паки: {', '.join(available)}.", new_active

    if re.search(r"(выгрузи|отключи|убери)\s+все\s+пак", cmd) \
            or cmd in {"выгрузи все паки", "отключи все паки"}:
        save_active([], config)
        return "Все паки выгружены.", []

    m = re.search(r"(выгрузи|отключи|убери)\s+пак\s+(\S+)", cmd)
    if m:
        name = normalize_name(m.group(2))
        if name not in current_active:
            return f"Пак '{name}' и так не активен.", current_active
        new_active = [p for p in current_active if p != name]
        save_active(new_active, config)
        return f"Пак '{name}' выгружен.", new_active

    return None, current_active
```

### `jarvis/paths.py`

```python
"""Централизованное определение путей Феникса. ... [22 строк]"""

import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger("jarvis.paths")

APP_NAME = "Phoenix"


def _is_ascii(path: Path | str) -> bool:
    """Проверяет, что путь — чистая ASCII (без кириллицы, иероглифов)."""
    try:
        str(path).encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _try_mkdir(path: Path) -> bool:
    """Пробует создать папку. Возвращает True, если получилось."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        # Проверяем, что можем писать
        probe = path / ".write_test"
        probe.write_text("ok", encoding="ascii")
        probe.unlink()
        return True
    except Exception:
        return False


def _pick_program_dir() -> Path:
    """Выбирает ASCII-путь для кода и моделей. ... [7 строк]"""
    candidates = []

    program_data = os.environ.get("PROGRAMDATA")
    if program_data:
        candidates.append(Path(program_data) / APP_NAME)

    candidates.append(Path(r"C:\Phoenix"))

    temp = Path(tempfile.gettempdir())
    candidates.append(temp / APP_NAME)

    # Последний — рядом с кодом
    candidates.append(Path(__file__).resolve().parent.parent / "runtime")

    for cand in candidates:
        if not _is_ascii(cand):
            log.debug("Пропускаю не-ASCII путь: %s", cand)
            continue
        if _try_mkdir(cand):
            log.info("PROGRAM_DIR: %s", cand)
            return cand
        log.debug("Не удалось создать: %s", cand)

    # Совсем крайний случай — temp (гарантированно есть)
    fallback = temp / APP_NAME
    fallback.mkdir(parents=True, exist_ok=True)
    log.warning("PROGRAM_DIR: fallback на %s", fallback)
    return fallback


def _pick_user_dir() -> Path:
    """Путь для данных юзера. Может быть с кириллицей — это ок."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        d = Path(appdata) / APP_NAME
    else:
        # Linux/macOS fallback
        d = Path.home() / f".{APP_NAME.lower()}"

    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        log.exception("Не удалось создать USER_DIR %s", d)
        d = Path(tempfile.gettempdir()) / APP_NAME
        d.mkdir(parents=True, exist_ok=True)

    log.info("USER_DIR: %s", d)
    return d


# ============================================================
# Публичный API
# ============================================================

# Ленивая инициализация — чтобы не дёргать файловую систему при импорте
_PROGRAM_DIR: Path | None = None
_USER_DIR: Path | None = None


def user_home() -> Path:
    """Домашняя папка пользователя. ... [6 строк]"""
    return Path.home()


def program_dir() -> Path:
    """ASCII-путь для кода и моделей."""
    global _PROGRAM_DIR
    if _PROGRAM_DIR is None:
        _PROGRAM_DIR = _pick_program_dir()
    return _PROGRAM_DIR


def user_dir() -> Path:
    """Путь для config.json, profiles/, logs/."""
    global _USER_DIR
    if _USER_DIR is None:
        _USER_DIR = _pick_user_dir()
    return _USER_DIR


def program_models_dir() -> Path:
    """Модели Vosk — ВСЕГДА в ASCII-пути."""
    d = program_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def program_whisper_cache_dir() -> Path:
    """Кэш Whisper — ВСЕГДА в ASCII-пути."""
    d = program_dir() / "whisper-cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def logs_dir() -> Path:
    """Логи — в USER_DIR (кириллица ок)."""
    d = user_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def profiles_dir() -> Path:
    """Профили — в USER_DIR."""
    d = user_dir() / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    """config.json — в USER_DIR."""
    return user_dir() / "config.json"
```

### `jarvis/persona.py`

```python
"""Персона ассистента — стиль общения, черты, backstory."""

import logging
import time

from jarvis import profile

log = logging.getLogger("jarvis.persona")

DEFAULT_PERSONA = {
    "assistant_name": "Феникс",
    "speech_style": "friendly",
    "traits": [],
    "backstory": "",
    "onboarding_done": False,
    "onboarding_at": 0.0,
}

VALID_STYLES = ("formal", "friendly", "sarcastic", "brief")

STYLE_DESCRIPTIONS = {
    "formal": "на «вы», официально, без фамильярности",
    "friendly": "на «ты», тепло и по-дружески",
    "sarcastic": "с сухим юмором и лёгкой иронией",
    "brief": "коротко, по делу, минимум слов",
}

STYLE_ALIASES = {
    "формальный": "formal", "официальный": "formal", "на вы": "formal", "строгий": "formal",
    "дружеский": "friendly", "дружелюбный": "friendly", "тёплый": "friendly", "на ты": "friendly",
    "саркастичный": "sarcastic", "сарказм": "sarcastic", "ироничный": "sarcastic",
    "короткий": "brief", "краткий": "brief", "по делу": "brief", "лаконичный": "brief",
}


def get() -> dict:
    raw = profile.get("persona", {}) or {}
    result = dict(DEFAULT_PERSONA)
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k not in DEFAULT_PERSONA:
                continue
            # Не позволяем None затирать дефолт.
            if v is None:
                continue
            result[k] = v
    return result


def set_persona(data: dict) -> bool:
    current = get()
    for key in DEFAULT_PERSONA:
        if key in data:
            current[key] = data[key]
    return profile.set("persona", current)


def set_field(key: str, value) -> bool:
    if key not in DEFAULT_PERSONA:
        log.warning("persona.set_field: неизвестный ключ %r", key)
        return False
    current = get()
    current[key] = value
    return profile.set("persona", current)


def normalize_style(text: str) -> str | None:
    text_low = text.strip().lower()
    if text_low in VALID_STYLES:
        return text_low
    for alias, style in STYLE_ALIASES.items():
        if alias in text_low:
            return style
    return None


def set_style(style: str) -> str:
    style = normalize_style(style) or "friendly"
    set_field("speech_style", style)
    log.info("Persona: стиль → %s", style)
    return f"Стиль общения: {STYLE_DESCRIPTIONS[style]}."


def is_onboarded() -> bool:
    return bool(get().get("onboarding_done"))


def mark_onboarded() -> bool:
    return set_persona({"onboarding_done": True, "onboarding_at": time.time()})


def reset_onboarding() -> bool:
    return set_persona({"onboarding_done": False, "onboarding_at": 0.0})


def build_prompt_block() -> str:
    p = get()
    lines = []

    style = p.get("speech_style") or "friendly"
    style_desc = STYLE_DESCRIPTIONS.get(style)
    if style_desc:
        lines.append(f"- Стиль общения: {style_desc}")

    traits = p.get("traits") or []
    if traits:
        lines.append(f"- Черты характера: {', '.join(traits)}")

    backstory = (p.get("backstory") or "").strip()
    if backstory:
        lines.append(f"- Контекст: {backstory}")

    assistant_name = (p.get("assistant_name") or "Феникс").strip()
    if assistant_name and assistant_name != "Феникс":
        lines.append(f"- Тебя зовут {assistant_name}")

    if not lines:
        return ""

    return "\n\nПерсона ассистента:\n" + "\n".join(lines) + "\n"


def describe() -> str:
    p = get()
    style = p.get("speech_style") or "friendly"
    style_desc = STYLE_DESCRIPTIONS.get(style, style)
    name = p.get("assistant_name") or "Феникс"
    parts = [f"Меня зовут {name}", f"стиль общения: {style_desc}"]
    traits = p.get("traits") or []
    if traits:
        parts.append(f"черты: {', '.join(traits)}")
    return ". ".join(parts).capitalize() + "."
```

### `jarvis/profile.py`

```python
"""Профиль пользователя — мультипрофиль. ... [21 строк]"""

import copy
import getpass
import json
import logging
import re
import threading
import time
from pathlib import Path

from jarvis import config_manager

log = logging.getLogger("jarvis.profile")

from jarvis import paths as _paths

BASE_DIR = Path(__file__).resolve().parent.parent
# profiles/ — в USER_DIR, а не рядом с кодом.
# Может содержать кириллицу — это ок (Vosk их не читает).
PROFILES_DIR = _paths.profiles_dir()
_OLD_PROFILE = _paths.user_dir() / "user_profile.json"
_OLD_DIALOG = _paths.user_dir() / "dialog.json"

# №76: один RLock вместо двух локов. Раньше _current_lock и _listeners_lock
# могли дать гонку: _current менялся, а подписчики читали memory со старым
# профилем. RLock реентерабельный — безопасен для вложенных вызовов.
_lock = threading.RLock()

_current: str | None = None
_listeners: list = []

# Кэш содержимого profile.json, ключ — путь файла.
# Профиль на процесс один (мьютекс в launcher.py), поэтому
# инвалидация нужна только при своей записи и при switch().
_cache: dict[Path, dict] = {}


# ---------------------------------------------------------------
# Служебное
# ---------------------------------------------------------------

def _sanitize(name: str) -> str:
    """Приводит имя к безопасному имени папки."""
    if not name:
        return "default"
    name = name.strip().lower()
    translit = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    name = "".join(translit.get(ch, ch) for ch in name)
    name = re.sub(r"[^a-z0-9_-]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "default"


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _windows_user() -> str:
    """Имя Windows-пользователя. Fallback — default."""
    try:
        return getpass.getuser() or "default"
    except Exception:
        return "default"


# ---------------------------------------------------------------
# Пути
# ---------------------------------------------------------------

def profile_dir() -> Path:
    """Папка текущего профиля. Создаётся при вызове."""
    with _lock:
        cur = current()
    path = PROFILES_DIR / _sanitize(cur)
    _ensure_dir(path)
    return path


def profile_path() -> Path:
    """Путь к profile.json текущего профиля."""
    return profile_dir() / "profile.json"


def dialog_path() -> Path:
    """Путь к dialog.json текущего профиля."""
    return profile_dir() / "dialog.json"


# ---------------------------------------------------------------
# Миграция
# ---------------------------------------------------------------

def _migrate_old() -> None:
    """Переносит старые user_profile.json и dialog.json в profiles/<user>/."""
    if not PROFILES_DIR.exists():
        return
    user_dir = PROFILES_DIR / _sanitize(_windows_user())
    _ensure_dir(user_dir)

    new_profile = user_dir / "profile.json"
    if _OLD_PROFILE.exists() and not new_profile.exists():
        try:
            data = json.loads(_OLD_PROFILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("created_at", time.time())
                config_manager.save(data, path=new_profile)
                log.info("Миграция: %s → %s", _OLD_PROFILE.name, new_profile)
        except Exception:
            log.exception("Не удалось мигрировать старый профиль")

    new_dialog = user_dir / "dialog.json"
    if _OLD_DIALOG.exists() and not new_dialog.exists():
        try:
            data = json.loads(_OLD_DIALOG.read_text(encoding="utf-8"))
            if isinstance(data, list):
                new_dialog.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                log.info("Миграция: %s → %s", _OLD_DIALOG.name, new_dialog)
        except Exception:
            log.exception("Не удалось мигрировать старый диалог")


# ---------------------------------------------------------------
# Текущий профиль
# ---------------------------------------------------------------

def current() -> str:
    """Имя текущего активного профиля (папки)."""
    global _current
    with _lock:
        if _current is None:
            _current = _windows_user()
        return _current


def subscribe(callback) -> None:
    """Регистрирует callback(old_name, new_name) — вызывается при switch()."""
    with _lock:
        if callback in _listeners:
            return
        _listeners.append(callback)


def unsubscribe(callback) -> None:
    """Удаляет подписку."""
    with _lock:
        try:
            _listeners.remove(callback)
        except ValueError:
            pass


def switch(name: str) -> str:
    """Переключает текущий профиль. Создаёт папку, если нет. ... [4 строк]"""
    global _current
    safe = _sanitize(name)

    with _lock:
        old_name = _current or _windows_user()

        user_dir = PROFILES_DIR / safe
        _ensure_dir(user_dir)

        profile_file = user_dir / "profile.json"
        if not profile_file.exists():
            data = {
                "name": name.strip()[:60] or safe,
                "created_at": time.time(),
            }
            config_manager.save(data, path=profile_file)
            log.info("Создан новый профиль: %s", profile_file)
        else:
            # Профиль существует — если name нет, ставим его.
            # Иначе "я — Максим" на старом профиле вернёт старое имя
            # (например, "тест" из стресс-теста).
            try:
                raw = profile_file.read_text(encoding="utf-8")
                if raw.strip():
                    d = json.loads(raw)
                    if not d.get("name"):
                        d["name"] = name.strip()[:60] or safe
                        config_manager.save(d, path=profile_file)
                        log.info("Профиль %s: добавлено name = %r",
                                 safe, d["name"])
            except Exception:
                log.exception("Не удалось проверить name в профиле %s", safe)

        _current = safe

        # Профиль другой — кэш прошлого больше не действителен.
        # Сбрасываем под тем же локом, что и _current, чтобы
        # подписчики не прочитали кэш старого профиля.
        _cache_invalidate()

        # human — читаем имя из нового профиля
        human = safe
        try:
            raw = profile_file.read_text(encoding="utf-8")
            if raw.strip():
                d = json.loads(raw)
                human = d.get("name") or safe
        except Exception:
            log.exception("Не удалось прочитать name из нового профиля")

        log.info("Активный профиль: %s (%s → %s)", human, old_name, safe)

        # Уведомляем подписчиков под тем же локом
        listeners = list(_listeners)

    # Вызываем подписчиков ВНЕ лока, но с уже обновлённым _current.
    # Подписчики (IntentHandler._on_profile_switch) перечитывают dialog —
    # к этому моменту _current уже новый.
    for cb in listeners:
        try:
            cb(old_name, safe)
        except Exception:
            log.exception("Подписчик profile упал на switch(%r)", safe)

    return f"Профиль переключён на {human}."


def list_all() -> list[str]:
    """Список доступных профилей (имена папок)."""
    _ensure_dir(PROFILES_DIR)
    return sorted(p.name for p in PROFILES_DIR.iterdir() if p.is_dir())


def delete(name: str) -> bool:
    """Удаляет папку профиля. Активный — нельзя."""
    import shutil
    safe = _sanitize(name)
    with _lock:
        if safe == current():
            log.warning("Нельзя удалить активный профиль: %s", safe)
            return False
    path = PROFILES_DIR / safe
    if not path.exists() or not path.is_dir():
        return False
    try:
        try:
            from send2trash import send2trash
            send2trash(str(path))
            log.info("Профиль перемещён в корзину: %s", safe)
        except ImportError:
            log.warning(
                "send2trash не установлен — профиль удаляется НАВСЕГДА"
            )
            shutil.rmtree(path)
            log.info("Профиль удалён: %s", safe)
        _cache_invalidate(path / "profile.json")
        return True
    except Exception:
        log.exception("Не удалось удалить профиль %s", safe)
        return False


# ---------------------------------------------------------------
# Чтение / запись полей профиля
# ---------------------------------------------------------------

def _safe_load() -> dict:
    """Читает profile.json ЧЕРЕЗ КЭШ В ПАМЯТИ. ... [10 строк]"""
    path = profile_path()

    with _lock:
        cached = _cache.get(path)
    if cached is not None:
        return copy.deepcopy(cached)

    if not path.exists():
        return {}

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        log.exception("Не удалось прочитать %s", path)
        return {}

    if not raw.strip():
        return {}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.error("Профиль %s битый — НЕ перезаписываю. Почини вручную.", path)
        raise

    if not isinstance(data, dict):
        log.warning("%s — не словарь, игнорирую", path)
        return {}

    with _lock:
        _cache[path] = data
    return copy.deepcopy(data)


def _cache_store(path: Path, data: dict) -> None:
    """Кладёт данные в кэш после успешной записи на диск."""
    with _lock:
        _cache[path] = data


def _cache_invalidate(path: Path | None = None) -> None:
    """Сбрасывает кэш. Без пути — весь (при switch / init / delete)."""
    with _lock:
        if path is None:
            _cache.clear()
        else:
            _cache.pop(path, None)


def get(key: str, default=None):
    try:
        return _safe_load().get(key, default)
    except json.JSONDecodeError:
        return default


def set(key: str, value) -> bool:
    with _lock:
        try:
            data = _safe_load()
        except json.JSONDecodeError:
            return False
        data[key] = value
        data.setdefault("created_at", time.time())
        path = profile_path()
        ok = config_manager.save(data, path=path)
        if ok:
            _cache_store(path, data)
            log.info("Профиль %s: %s = %r", current(), key, value)
        else:
            log.error("Профиль %s: не удалось сохранить %s", current(), key)
        return ok


def all_data() -> dict:
    try:
        return _safe_load()
    except json.JSONDecodeError:
        return {}


def forget(key: str) -> bool:
    with _lock:
        try:
            data = _safe_load()
        except json.JSONDecodeError:
            return False
        if key not in data:
            return False
        del data[key]
        path = profile_path()
        ok = config_manager.save(data, path=path)
        if ok:
            _cache_store(path, data)
            log.info("Профиль %s: удалено %s", current(), key)
        return ok


# ---------------------------------------------------------------
# Факты
# ---------------------------------------------------------------

def set_fact(key: str, value: str) -> bool:
    facts = get("facts", {}) or {}
    facts[key] = value
    return set("facts", facts)


def get_fact(key: str, default=None):
    facts = get("facts", {}) or {}
    return facts.get(key, default)


def all_facts() -> dict:
    return get("facts", {}) or {}


def forget_fact(key: str) -> bool:
    facts = get("facts", {}) or {}
    if key not in facts:
        return False
    del facts[key]
    return set("facts", facts)


# ---------------------------------------------------------------
# Инициализация при старте
# ---------------------------------------------------------------

def init() -> None:
    """Вызывается при старте Феникса."""
    global _current
    _ensure_dir(PROFILES_DIR)
    with _lock:
        _current = _windows_user()
    _cache_invalidate()
    _migrate_old()

    user_dir = profile_dir()
    profile_file = user_dir / "profile.json"
    if not profile_file.exists():
        data = {"name": _windows_user(), "created_at": time.time()}
        config_manager.save(data, path=profile_file)
        log.info("Создан профиль по умолчанию: %s", profile_file)
    log.info("Активный профиль: %s (%s)", current(), user_dir.name)
```

### `jarvis/recorder.py`

```python
"""Запись действий: клавиши, клики, паузы."""

import logging
import threading
import time

log = logging.getLogger("jarvis.recorder")

_recording = False
_events = []
_start_time = 0.0
_last_event_time = 0.0
_lock = threading.Lock()

MAX_DURATION_SEC = 60
MIN_WAIT_SEC = 0.05
MAX_WAIT_SEC = 5.0


def is_recording() -> bool:
    return _recording


def start() -> bool:
    global _recording, _events, _start_time, _last_event_time
    try:
        import keyboard
        import mouse
    except ImportError:
        log.error("Библиотеки keyboard/mouse не установлены. pip install keyboard mouse")
        return False

    with _lock:
        if _recording:
            return False
        _events = []
        _recording = True
        _start_time = time.time()
        _last_event_time = _start_time

    try:
        keyboard.hook(_on_key)
        mouse.hook(_on_mouse)
    except Exception:
        log.exception("Не удалось повесить хуки (нужны права администратора)")
        with _lock:
            _recording = False
        return False

    log.info("Запись действий начата")
    return True


def stop() -> dict | None:
    """Останавливает запись и снимает хуки. ... [7 строк]"""
    global _recording

    with _lock:
        was_recording = _recording
        if was_recording:
            _recording = False
            events = list(_events)
        else:
            events = []

    if was_recording:
        try:
            import keyboard
            import mouse
            keyboard.unhook_all()
            mouse.unhook_all()
        except Exception:
            log.exception("Не удалось снять хуки keyboard/mouse")

        log.info("Запись действий остановлена: %d событий", len(events))
        return {"events": events, "duration": time.time() - _start_time}

    return None


def _add_wait_if_needed():
    global _last_event_time
    now = time.time()
    delta = now - _last_event_time
    if delta >= MIN_WAIT_SEC:
        _events.append({"type": "wait", "seconds": min(delta, MAX_WAIT_SEC)})
    _last_event_time = now


def _check_limits() -> bool:
    if time.time() - _start_time > MAX_DURATION_SEC:
        log.info("Запись остановлена: превышена максимальная длина")
        return False
    return True


def _on_key(event):
    if not _recording or not _check_limits():
        return
    _add_wait_if_needed()
    _events.append({
        "type": "key",
        "name": event.name,
        "event": "down" if event.event_type == "down" else "up",
    })


def _on_mouse(event):
    if not _recording or not _check_limits():
        return
    import mouse
    if isinstance(event, mouse.ButtonEvent):
        _add_wait_if_needed()
        _events.append({
            "type": "click",
            "x": mouse.get_position()[0],
            "y": mouse.get_position()[1],
            "button": event.button,
            "event": "down" if event.event_type == "down" else "up",
        })


def play(macro: dict, speed: float = 1.0) -> bool:
    if not macro or not macro.get("events"):
        return False
    try:
        import keyboard
        import mouse
    except ImportError:
        log.error("Библиотеки keyboard/mouse не установлены")
        return False

    events = macro["events"]
    log.info("Воспроизведение макроса: %d событий", len(events))
    try:
        for ev in events:
            t = ev.get("type")
            if t == "wait":
                time.sleep(float(ev.get("seconds", 0)) / max(speed, 0.1))
            elif t == "key":
                if ev.get("event") == "down":
                    keyboard.press(ev["name"])
                else:
                    keyboard.release(ev["name"])
            elif t == "click":
                mouse.move(ev["x"], ev["y"], absolute=True, duration=0)
                if ev.get("event") == "down":
                    mouse.press(button=ev.get("button", "left"))
                else:
                    mouse.release(button=ev.get("button", "left"))
        return True
    except Exception:
        log.exception("Ошибка воспроизведения макроса")
        return False


def describe(macro: dict) -> str:
    if not macro:
        return "Запись пустая."
    events = macro.get("events", [])
    keys = sum(1 for e in events if e.get("type") == "key" and e.get("event") == "down")
    clicks = sum(1 for e in events if e.get("type") == "click" and e.get("event") == "down")
    duration = macro.get("duration", 0)
    return f"Макрос: {keys} нажатий, {clicks} кликов, длительность {duration:.1f} секунд."
```

### `jarvis/reply.py`

```python
"""Reply — результат IntentHandler.handle(). ... [7 строк]"""

from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass
class Reply:
    text: Optional[str] = None
    stream: Optional[Iterator[str]] = None

    def __post_init__(self) -> None:
        if (self.text is None) == (self.stream is None):
            raise ValueError("Reply: ровно одно из text/stream должно быть задано")

    @property
    def is_stream(self) -> bool:
        return self.stream is not None
```

### `jarvis/steam.py`

```python
"""Индекс установленных игр Steam: appmanifest -> (название, appid). ... [4 строк]"""

import logging
import re
import winreg
from pathlib import Path

from jarvis.matching import match_score

log = logging.getLogger("jarvis.steam")

# Служебные «игры», которые запускать не надо
_SKIP = ("redistributable", "proton", "steamworks", "steam linux", "runtime")


def _steam_root() -> Path | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            return Path(winreg.QueryValueEx(k, "SteamPath")[0])
    except OSError:
        return None


def scan_steam_games() -> list[tuple[str, str]]:
    """[(название, appid), ...] по всем библиотекам Steam."""
    root = _steam_root()
    if root is None or not root.exists():
        return []
    libs = {root}
    vdf = root / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        for path in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text("utf-8", errors="ignore")):
            libs.add(Path(path.replace("\\\\", "\\")))
    games = []
    for lib in libs:
        for acf in (lib / "steamapps").glob("appmanifest_*.acf"):
            try:
                text = acf.read_text("utf-8", errors="ignore")
            except OSError:
                continue
            appid = re.search(r'"appid"\s+"(\d+)"', text)
            name = re.search(r'"name"\s+"([^"]+)"', text)
            if not appid or not name:
                continue
            title = name.group(1)
            if any(s in title.lower() for s in _SKIP):
                continue
            games.append((title, appid.group(1)))
    log.info("Steam: проиндексировано %d игр", len(games))
    return games


def find_game(games: list[tuple[str, str]], spoken: str,
              threshold: float = 0.72) -> tuple[str, str] | None:
    best, best_score = None, 0.0
    for title, appid in games:
        score = match_score(spoken, title)
        if score > best_score:
            best, best_score = (title, appid), score
    if best and best_score >= threshold:
        log.info("Игра Steam: %r -> %r (score %.2f)", spoken, best[0], best_score)
        return best
    return None
```

### `jarvis/stt.py`

```python
"""Распознавание речи. ... [5 строк]"""

import json
import logging
import os
import queue
import time
from collections import deque
from pathlib import Path

import numpy as np
import sounddevice as sd
from vosk import KaldiRecognizer, Model, SetLogLevel

log = logging.getLogger("jarvis.stt")

TURBO_MODEL = "deepdml/faster-whisper-large-v3-turbo-ct2"

WHISPER_PROMPT = (
    "Это русская речь. Пожалуйста, транскрибируй текст на русском языке. "
    "Частые слова: Феникс, открой, закрой, найди, погода, напоминание, "
    "задача, голос, режим, паки, Нижний Новгород, курс доллара."
)

ECHO_WINDOW_SEC = 0.5
BARGE_LOG_INTERVAL = 0.5

# Флаг, чтобы не добавлять пути CUDA в PATH повторно при каждом импорте stt.
_CUDA_DLLS_ADDED = False


def _enable_cuda_dlls():
    """Добавляет пути к CUDA-библиотекам (cuBLAS, cuDNN) в PATH. ... [3 строк]"""
    global _CUDA_DLLS_ADDED
    if _CUDA_DLLS_ADDED:
        return
    try:
        import nvidia
    except ImportError:
        return
    base = Path(nvidia.__path__[0])
    dirs = [str(p) for p in (base / "cublas" / "bin", base / "cudnn" / "bin") if p.exists()]
    if dirs:
        os.environ["PATH"] = os.pathsep.join(dirs) + os.pathsep + os.environ["PATH"]
        _CUDA_DLLS_ADDED = True


class Listener:
    def __init__(self, model_dir, sample_rate=16000, device=None):
        SetLogLevel(-1)
        self._model = Model(str(model_dir))
        self._rec = KaldiRecognizer(self._model, sample_rate)
        self._sample_rate = sample_rate
        self._device = self.resolve_device(device)
        self.device_name = self._current_device_name()
        self._audio = queue.Queue()
        self._utt_buf = []
        self._utt_len = 0
        self.peak = 0
        self.utterances = 0
        self.current_rms = 0  # текущий уровень сигнала (для GUI)

        self.barge_enabled = True
        self.muted = False
        self.barge_flag = False
        self._block_size = 8000

        # Ring buffer последних фраз (для «что ты слышал»)
        self.recent_phrases: deque = deque(maxlen=10)

        # Адаптивный barge-in
        self._echo_window_samples = deque(maxlen=20)
        self._echo_baseline = 0
        self._barge_threshold = 150
        self._barge_speech_ms = 0
        self._speech_active = False
        self._speech_started_at = 0.0
        self._last_barge_log = 0.0
        self._echo_done = False

    def barge_start(self):
        self.barge_flag = False
        self._barge_speech_ms = 0
        self._speech_active = True
        self._speech_started_at = time.time()
        self._echo_done = False
        self._echo_window_samples.clear()
        self._barge_threshold = max(150, int(self._echo_baseline * 1.8))

    def barge_end(self):
        self._speech_active = False
        log.info("Barge-in: стоп (echo=%d, thr=%d, речь=%d мс)",
                 self._echo_baseline, self._barge_threshold, self._barge_speech_ms)

    def _process_barge(self, rms):
        if not self._speech_active or not self.barge_enabled:
            return
        now = time.time()
        elapsed = now - self._speech_started_at

        if elapsed < ECHO_WINDOW_SEC:
            return

        if not self._echo_done:
            self._echo_window_samples.append(rms)
            if elapsed >= ECHO_WINDOW_SEC + 0.5:
                if self._echo_window_samples:
                    arr = sorted(self._echo_window_samples)
                    self._echo_baseline = arr[int(len(arr) * 0.7)]
                self._barge_threshold = max(150, int(self._echo_baseline * 1.8))
                self._echo_done = True
                log.info("Barge-in: калибровка echo=%d, threshold=%d",
                         self._echo_baseline, self._barge_threshold)
            return

        self._echo_window_samples.append(rms)
        if len(self._echo_window_samples) >= 10:
            arr = sorted(self._echo_window_samples)
            new_echo = arr[int(len(arr) * 0.7)]
            self._echo_baseline = int(0.9 * self._echo_baseline + 0.1 * new_echo)
            self._barge_threshold = max(150, int(self._echo_baseline * 1.8))

        if rms > self._barge_threshold:
            self._barge_speech_ms += int(self._block_size / 16)
            if self._barge_speech_ms >= 150:
                self.barge_flag = True
        else:
            self._barge_speech_ms = 0

        if now - self._last_barge_log >= BARGE_LOG_INTERVAL:
            log.info("barge: rms=%d, echo=%d, thr=%d, speech_ms=%d, flag=%s",
                     rms, self._echo_baseline, self._barge_threshold,
                     self._barge_speech_ms, self.barge_flag)
            self._last_barge_log = now

    @staticmethod
    def resolve_device(device):
        if device is None or device == "":
            return None
        if isinstance(device, int):
            return device
        name = str(device).lower()
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0 and name in d["name"].lower():
                return i
        log.warning("Микрофон %r не найден, беру по умолчанию", device)
        return None

    def _current_device_name(self):
        try:
            idx = self._device if self._device is not None else sd.default.device[0]
            return sd.query_devices(idx)["name"]
        except Exception:
            return "по умолчанию"

    def _callback(self, indata, frames, time_info, status):
        if status:
            log.warning("Аудиопоток: %s", status)
        arr = np.frombuffer(indata, dtype=np.int16)
        if arr.size:
            self.peak = max(self.peak, int(np.abs(arr).max()))
            rms = int(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
            self.current_rms = rms
        else:
            rms = 0
            self.current_rms = 0
        self._process_barge(rms)
        if not self.muted:
            self._audio.put(bytes(indata))

    def flush(self):
        """Сброс аудио-буфера. ... [8 строк]"""
        while not self._audio.empty():
            try:
                self._audio.get_nowait()
            except queue.Empty:
                break
        self._utt_buf.clear()
        self._utt_len = 0

    def reset_stats(self):
        """Сбрасывает peak и utterances — для кнопки «Проверить микрофон»."""
        self.peak = 0
        self.utterances = 0
        log.info("Listener: статистика сброшена")

    def phrases(self, stop_event):
        max_buf = self._sample_rate * 2 * 30
        with sd.RawInputStream(
            samplerate=self._sample_rate,
            blocksize=self._block_size,
            dtype="int16",
            channels=1,
            device=self._device,
            callback=self._callback,
        ):
            log.info("Микрофон открыт, слушаю...")
            while not stop_event.is_set():
                try:
                    data = self._audio.get(timeout=0.2)
                except queue.Empty:
                    continue
                self._utt_buf.append(data)
                self._utt_len += len(data)
                while self._utt_len > max_buf and len(self._utt_buf) > 1:
                    self._utt_len -= len(self._utt_buf.pop(0))
                if self._rec.AcceptWaveform(data):
                    text = json.loads(self._rec.Result()).get("text", "").strip()
                    audio = b"".join(self._utt_buf)
                    self._utt_buf.clear()
                    self._utt_len = 0
                    if text:
                        self.utterances += 1
                        self.recent_phrases.append(text)
                        log.info("Распознано (vosk): %s", text)
                        yield text, audio


class WhisperTranscriber:
    def __init__(self, model_name="auto", device="auto"):
        # HF_HOME нужен ТОЛЬКО для Whisper: ctranslate2 ломается
        # на не-ASCII путях. Но Piper тоже использует huggingface_hub —
        # и если HF_HOME стоит, Piper качает модель в наш ASCII-кэш
        # в degraded-режиме (без symlinks).
        #
        # Решение: ставим HF_HOME временно — на время импорта faster_whisper
        # и загрузки модели. Потом восстанавливаем — чтобы Piper качал
        # в свой обычный кэш (~/.cache/huggingface).
        from jarvis import paths as _paths

        _old_hf_home = os.environ.get("HF_HOME")
        _old_hf_cache = os.environ.get("HUGGINGFACE_HUB_CACHE")

        os.environ["HF_HOME"] = str(_paths.program_whisper_cache_dir())
        os.environ["HUGGINGFACE_HUB_CACHE"] = str(_paths.program_whisper_cache_dir())

        try:
            _enable_cuda_dlls()
            import ctranslate2
            from faster_whisper import WhisperModel

            if device == "auto":
                device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"

            self._model = None

            if device == "cuda":
                name = TURBO_MODEL if model_name == "auto" else model_name
                try:
                    log.info("Загрузка Whisper (%s) на GPU...", name)
                    self._model = WhisperModel(
                        name, device="cuda", compute_type="int8_float16"
                    )
                    log.info("Whisper готов (GPU)")
                except Exception:
                    log.exception("GPU не завёлся, откатываюсь на CPU")

            if self._model is None:
                name = "small" if model_name == "auto" else model_name
                log.info("Загрузка Whisper (%s) на CPU...", name)
                self._model = WhisperModel(
                    name, device="cpu", compute_type="int8"
                )
                log.info("Whisper готов (CPU)")
        finally:
            # Восстанавливаем — чтобы Piper не качал в наш ASCII-кэш.
            if _old_hf_home is None:
                os.environ.pop("HF_HOME", None)
            else:
                os.environ["HF_HOME"] = _old_hf_home
            if _old_hf_cache is None:
                os.environ.pop("HUGGINGFACE_HUB_CACHE", None)
            else:
                os.environ["HUGGINGFACE_HUB_CACHE"] = _old_hf_cache

    def transcribe(self, pcm, sample_rate=16000):
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if sample_rate != 16000 and len(audio) > 1:
            n = int(len(audio) * 16000 / sample_rate)
            audio = np.interp(
                np.linspace(0, len(audio) - 1, n),
                np.arange(len(audio)), audio
            ).astype(np.float32)
        segments, _ = self._model.transcribe(
            audio, language="ru", beam_size=2, vad_filter=True,
            condition_on_previous_text=False, initial_prompt=WHISPER_PROMPT,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        log.info("Распознано (whisper): %s", text)
        return text
```

### `jarvis/tasks.py`

```python
"""Списки задач. ... [10 строк]"""

import json
import logging
import os
import re
import tempfile
import threading
from difflib import SequenceMatcher

from jarvis import paths as _paths

log = logging.getLogger("jarvis.tasks")

_lock = threading.RLock()


# ---------------------------------------------------------------
# Пути
# ---------------------------------------------------------------

def _tasks_file():
    """Путь к tasks.json в USER_DIR. ... [5 строк]"""
    return _paths.user_dir() / "tasks.json"


# ---------------------------------------------------------------
# Хранение
# ---------------------------------------------------------------

def _load() -> list:
    path = _tasks_file()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        log.exception("Не удалось прочитать %s", path)
        return []


def _save(tasks: list) -> None:
    """Атомарная запись tasks.json. ... [5 строк]"""
    path = _tasks_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), suffix=".tmp", prefix=path.stem + "."
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(tasks, f, ensure_ascii=False, indent=2)
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
    except Exception:
        log.exception("Не удалось сохранить %s", path)


# ---------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------

def add(text: str) -> dict:
    """Добавляет задачу."""
    with _lock:
        tasks = _load()
        task = {
            "id": (max((t["id"] for t in tasks), default=0) + 1),
            "text": text.strip(),
            "done": False,
            "created_at": __import__("time").time(),
        }
        tasks.append(task)
        _save(tasks)
    log.info("Задача добавлена: %s", task["text"])
    return task


def find(query: str) -> dict | None:
    """Находит задачу по нечёткому совпадению. ... [4 строк]"""
    with _lock:
        tasks = _load()
        query_low = query.lower().strip()
        if not query_low:
            return None
        # 1. точная подстрока
        for t in tasks:
            if query_low in t["text"].lower():
                return t
        # 2. нечёткое совпадение
        best, best_ratio = None, 0.5
        for t in tasks:
            ratio = SequenceMatcher(None, query_low, t["text"].lower()).ratio()
            if ratio > best_ratio:
                best_ratio, best = ratio, t
        return best


def mark_done(query: str) -> dict | None:
    """Помечает задачу выполненной."""
    with _lock:
        tasks = _load()
        target = find(query)
        if not target:
            return None
        for t in tasks:
            if t["id"] == target["id"]:
                t["done"] = True
                _save(tasks)
                return t
    return None


def remove(query: str) -> dict | None:
    """Удаляет задачу."""
    with _lock:
        tasks = _load()
        target = find(query)
        if not target:
            return None
        tasks = [t for t in tasks if t["id"] != target["id"]]
        _save(tasks)
    return target


def clear_all() -> int:
    """Удаляет все задачи. Возвращает количество."""
    with _lock:
        tasks = _load()
        count = len(tasks)
        _save([])
    return count


# ---------------------------------------------------------------
# Озвучка
# ---------------------------------------------------------------

def format_list(tasks: list | None = None) -> str:
    """Человекочитаемый список для озвучки."""
    if tasks is None:
        tasks = _load()
    if not tasks:
        return "Список пуст."

    active = [t for t in tasks if not t.get("done")]
    done = [t for t in tasks if t.get("done")]

    parts = []
    if active:
        items = ", ".join(t["text"] for t in active[:15])
        parts.append(f"Активные: {items}")
    if done:
        items = ", ".join(t["text"] for t in done[:5])
        parts.append(f"Выполнено: {items}")
    return ". ".join(parts) + "."


# ---------------------------------------------------------------
# Обработка команд
# ---------------------------------------------------------------

def handle_task_command(cmd: str) -> str | None:
    """Разбирает команды списка задач. Возвращает ответ или None."""

    # показать список
    if re.search(r"(что|что\s+там)\s+в\s+списке", cmd) \
            or cmd in {"что в списке", "покажи список", "список задач", "мои задачи"}:
        return format_list()

    # очистить
    if re.search(r"(очисти|удали)\s+(весь\s+)?список", cmd) \
            or cmd in {"очисти список", "удали все задачи"}:
        n = clear_all()
        return f"Очищено задач: {n}." if n else "Список и так пуст."

    # отметить выполненным
    m = re.match(r"^(?:отметь|помечу|пометь|сделано|выполнено|готово)\s+(.+)$", cmd)
    if m:
        query = m.group(1).strip()
        query = re.sub(r"\s+(выполненным|сделанным|готовым)$", "", query)
        query = re.sub(r"^(задачу|задачу\s+)?", "", query)
        task = mark_done(query)
        if task:
            return f"Отметил: {task['text']}."
        return f"Задачу «{query}» не нашёл."

    # удалить одну
    m = re.match(r"^(?:убери|удали)\s+(?:из\s+списка\s+)?(.+)$", cmd)
    if m:
        query = m.group(1).strip()
        task = remove(query)
        if task:
            return f"Убрал: {task['text']}."
        return f"Задачу «{query}» не нашёл."

    # добавить
    m = re.match(r"^(?:добавь|запиши|внеси)\s+(?:в\s+список\s+|в\s+задачи\s+)?(.+)$", cmd)
    if m:
        text = m.group(1).strip(" ,.:!?")
        if not text:
            return "Что добавить?"
        task = add(text)
        return f"Добавил: {task['text']}."

    return None
```

### `jarvis/text_utils.py`

```python
"""Общие текстовые утилиты для Феникса. ... [9 строк]"""

import re

# ---------------------------------------------------------------
# Иероглифы (CJK): китайский, японский, корейский + полноширинные символы
# ---------------------------------------------------------------

CJK_RE = re.compile(
    r"[\u4e00-\u9fff"      # китайские иероглифы
    r"\u3040-\u309f"       # хирагана
    r"\u30a0-\u30ff"       # катакана
    r"\uac00-\ud7af"       # хангыль
    r"\u3000-\u303f"       # CJK-пунктуация
    r"\uff00-\uffef]+"     # полноширинные формы
)


def strip_cjk(text: str) -> str:
    """Убирает иероглифы. Если после чистки пусто — возвращает заглушку."""
    if not text:
        return text
    cleaned = CJK_RE.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return "Извините, не удалось ответить. Повторите, пожалуйста."
    return cleaned


def strip_cjk_chunk(text: str) -> str:
    """Убирает иероглифы БЕЗ заглушки — для стриминга. ... [4 строк]"""
    if not text:
        return text
    return CJK_RE.sub("", text)


# ---------------------------------------------------------------
# Нормализация команды
# ---------------------------------------------------------------

def normalize(text: str) -> str:
    """Нормализует команду: нижний регистр, ё→е, убирает пунктуацию. ... [4 строк]"""
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------
# Подготовка текста для TTS
# ---------------------------------------------------------------

_REPLACEMENTS = [
    (r"\bм/с\b", " метров в секунду"),
    (r"\bкм/ч\b", " километров в час"),
    (r"\bкм/с\b", " километров в секунду"),
    (r"\bм/c\b", " метров в секунду"),
    (r"\bкм/ч\.", " километров в час"),
    (r"([+-]?\d+)\s*°\s*[CFЦ]?\b", r"\1 градусов"),
    (r"°\s*[CFЦ]?\b", " градусов"),
    (r"(\d+)\s*%", r"\1 процентов"),
    (r"\bт\.\s*д\.", " так далее"),
    (r"\bт\.\s*е\.", " то есть"),
    (r"\bт\.\s*к\.", " так как"),
    (r"\bт\.\s*п\.", " тому подобное"),
    (r"\bдр\.", " другие"),
    (r"\bг\.", " год"),
    (r"\bгг\.", " годы"),
    (r"\bруб\.", " рублей"),
    (r"\bкоп\.", " копеек"),
    (r"\bтыс\.", " тысяч"),
    (r"\bмлн\.", " миллионов"),
    (r"\bмлрд\.", " миллиардов"),
    (r"\b(\d+)\s*см\b", r"\1 сантиметров"),
    (r"\b(\d+)\s*мм\b", r"\1 миллиметров"),
    (r"\b(\d+)\s*км\b", r"\1 километров"),
    (r"\b(\d+)\s*кг\b", r"\1 килограммов"),
    (r"\b(\d+)\s*мг\b", r"\1 миллиграммов"),
    (r"\b(\d+)\s*МБ\b", r"\1 мегабайт"),
    (r"\b(\d+)\s*ГБ\b", r"\1 гигабайт"),
    (r"\b(\d+)\s*КБ\b", r"\1 килобайт"),
    (r"\b(\d+)\s*м\b", r"\1 метров"),
    (r"\b(\d+)\s*г\b", r"\1 граммов"),
    (r"→", " стремится к "),
    (r"←", " из "),
    (r"≈", " примерно "),
    (r"≥", " больше или равно "),
    (r"≤", " меньше или равно "),
    (r"≠", " не равно "),
    (r"&", " и "),
    (r"\+", " плюс "),
    (r"(?<!\w)-(?!\w)", " минус "),
    (r"\*+", ""),
    (r"_+", ""),
    (r"#+\s*", ""),
    (r"`+", ""),
    (r"^\s*[-•]\s+", ""),
]

_RE_COMPILED = [(re.compile(pat), repl) for pat, repl in _REPLACEMENTS]


def prepare_text(text: str) -> str:
    """Подготавливает текст для TTS: убирает иероглифы, расшифровывает единицы. ... [4 строк]"""
    if not text:
        return text
    text = CJK_RE.sub(" ", text)
    for pattern, repl in _RE_COMPILED:
        text = pattern.sub(repl, text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    return text
```

### `jarvis/timers.py`

```python
"""Таймеры и напоминания. ... [12 строк]"""

import datetime
import json
import logging
import os
import re
import tempfile
import threading
import time
from pathlib import Path

from jarvis import paths as _paths

log = logging.getLogger("jarvis.timers")

_lock = threading.RLock()
_scheduled: dict[int, threading.Timer] = {}  # id → Timer
_on_fire_callback = None  # функция, которая вызывается при срабатывании


# ---------------------------------------------------------------
# Пути
# ---------------------------------------------------------------

def _timers_file() -> Path:
    """Путь к timers.json в USER_DIR. ... [5 строк]"""
    return _paths.user_dir() / "timers.json"


# ---------------------------------------------------------------
# Хранение
# ---------------------------------------------------------------

def _load() -> list:
    path = _timers_file()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        log.exception("Не удалось прочитать %s", path)
        return []


def _save(timers: list) -> None:
    """Атомарная запись timers.json. ... [5 строк]"""
    path = _timers_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), suffix=".tmp", prefix=path.stem + "."
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(timers, f, ensure_ascii=False, indent=2)
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
    except Exception:
        log.exception("Не удалось сохранить %s", path)


# ---------------------------------------------------------------
# Разбор времени из фразы
# ---------------------------------------------------------------

_NUM_WORDS = {
    "один": 1, "одну": 1, "одна": 1, "два": 2, "две": 2, "три": 3, "четыре": 4,
    "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10,
    "пятнадцать": 15, "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50,
    "полтора": 1.5,
}


def _parse_duration(text: str) -> int | None:
    """«через 10 минут» → 600 секунд. Возвращает int или None."""
    # «через X единица»
    m = re.search(r"через\s+(\d+|[а-яё]+)\s*(секунд|мин|минут|час|часов|ч|с|м)?", text)
    if not m:
        # «на X минут» / «таймер на X»
        m = re.search(r"(?:на|таймер)\s+(\d+|[а-яё]+)\s*(секунд|мин|минут|час|часов|ч|с|м)",
                      text)
    if not m:
        # «полчаса», «час», «минуту»
        if "полчаса" in text or "пол часа" in text:
            return 30 * 60
        if re.search(r"\bчас\b", text):
            return 60 * 60
        if re.search(r"\bминуту\b", text):
            return 60
        return None

    raw = m.group(1)
    unit = m.group(2) or "мин"

    # число
    if raw.isdigit():
        num = int(raw)
    else:
        num = _NUM_WORDS.get(raw.lower())
        if num is None:
            return None

    # единица
    if unit.startswith("сек") or unit == "с":
        return int(num)
    if unit.startswith("мин") or unit == "м":
        return int(num * 60)
    if unit.startswith("час") or unit == "ч":
        return int(num * 3600)
    return int(num * 60)


def _parse_absolute_time(text: str) -> float | None:
    """«в 18:30» → timestamp. Возвращает float (unix) или None."""
    m = re.search(r"\bв\s+(\d{1,2})[:.](\d{2})", text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"\bв\s+(\d{1,2})\s+час", text)
        if not m:
            return None
        hour, minute = int(m.group(1)), 0

    if not (0 <= hour < 24 and 0 <= minute < 60):
        return None

    now = datetime.datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        # время уже прошло — значит, на завтра
        target += datetime.timedelta(days=1)
    return target.timestamp()


def _extract_reminder_text(cmd: str) -> str:
    """Вырезает из фразы текст напоминания (после времени)."""
    # убираем всё до времени (включительно)
    text = re.sub(r"^.*?(?:напомни|напоминание|таймер)\s*", "", cmd, count=1)
    text = re.sub(r"через\s+(\d+|[а-яё]+)\s*\S+", "", text, count=1)
    text = re.sub(r"\bв\s+\d{1,2}[:.]\d{2}", "", text, count=1)
    text = re.sub(r"\bв\s+\d{1,2}\s+час\w*", "", text, count=1)
    text = text.strip(" ,.:!?")
    return text


# ---------------------------------------------------------------
# Планирование
# ---------------------------------------------------------------

def set_on_fire(callback) -> None:
    """Регистрирует callback(timer_dict) — вызывается при срабатывании."""
    global _on_fire_callback
    _on_fire_callback = callback


def _fire(timer_id: int) -> None:
    """Срабатывание таймера."""
    with _lock:
        timers = _load()
        timer = next((t for t in timers if t["id"] == timer_id), None)
        if not timer:
            _scheduled.pop(timer_id, None)
            return
        # удаляем из файла
        timers = [t for t in timers if t["id"] != timer_id]
        _save(timers)
        _scheduled.pop(timer_id, None)

    log.info("Таймер #%d сработал: %s", timer_id, timer.get("text") or "(без текста)")
    if _on_fire_callback:
        try:
            _on_fire_callback(timer)
        except Exception:
            log.exception("Ошибка в callback таймера")


def _schedule_one(timer: dict) -> None:
    """Ставит threading.Timer на конкретное напоминание."""
    delay = timer["fire_at"] - time.time()
    if delay <= 0:
        # уже прошло — срабатываем сразу
        delay = 0.1
    t = threading.Timer(delay, _fire, args=(timer["id"],))
    t.daemon = True
    t.start()
    _scheduled[timer["id"]] = t


def _next_id(timers: list) -> int:
    if not timers:
        return 1
    return max(t["id"] for t in timers) + 1


def add(text: str, fire_at: float) -> dict:
    """Добавляет напоминание. Возвращает dict таймера."""
    with _lock:
        timers = _load()
        tid = _next_id(timers)
        timer = {
            "id": tid,
            "text": text.strip(),
            "fire_at": float(fire_at),
            "created_at": time.time(),
        }
        timers.append(timer)
        _save(timers)
    _schedule_one(timer)
    return timer


def remove_all() -> int:
    """Отменяет все напоминания. Возвращает количество."""
    with _lock:
        timers = _load()
        count = len(timers)
        for t in _scheduled.values():
            t.cancel()
        _scheduled.clear()
        _save([])
    return count


def list_all() -> list:
    """Возвращает список активных напоминаний."""
    return _load()


def format_list(timers: list) -> str:
    """Человекочитаемый список для озвучки."""
    if not timers:
        return "Напоминаний нет."
    now = time.time()
    parts = []
    for t in timers[:10]:
        left = int(t["fire_at"] - now)
        if left < 0:
            left = 0
        m, s = divmod(left, 60)
        h, m = divmod(m, 60)
        if h:
            when = f"через {h} ч {m} мин"
        elif m:
            when = f"через {m} мин"
        else:
            when = f"через {s} сек"
        text = t.get("text") or "без текста"
        parts.append(f"{when} — {text}")
    return "Напоминания: " + "; ".join(parts) + "."


def restore_all() -> int:
    """Восстанавливает таймеры при старте. Возвращает количество."""
    timers = _load()
    for t in timers:
        _schedule_one(t)
    if timers:
        log.info("Восстановлено напоминаний: %d", len(timers))
    return len(timers)


# ---------------------------------------------------------------
# Обработка команд
# ---------------------------------------------------------------

def handle_timer_command(cmd: str) -> str | None:
    """Разбирает команды таймеров. Возвращает ответ или None."""
    # список
    if re.search(r"(какие|список|покажи)\s*(напоминани|таймер)", cmd) \
            or cmd in {"какие напоминания", "список напоминаний", "мои напоминания"}:
        return format_list(list_all())

    # отмена
    if re.search(r"(отмени|удали|очисти|сбрось)\s*(все\s+)?(напоминани|таймер)", cmd) \
            or cmd in {"отмени все напоминания", "удали все напоминания"}:
        n = remove_all()
        return f"Отменено напоминаний: {n}." if n else "Напоминаний не было."

    # добавить напоминание
    if re.search(r"(напомни|напоминание|таймер|напоминай)", cmd):
        # абсолютное время
        abs_ts = _parse_absolute_time(cmd)
        if abs_ts:
            text = _extract_reminder_text(cmd)
            t = add(text, abs_ts)
            when = datetime.datetime.fromtimestamp(abs_ts).strftime("%H:%M")
            if text:
                return f"Напомню в {when}: {text}."
            return f"Напомню в {when}."

        # относительное время
        dur = _parse_duration(cmd)
        if dur and dur > 0:
            text = _extract_reminder_text(cmd)
            fire_at = time.time() + dur
            t = add(text, fire_at)
            # озвучка длительности
            if dur >= 3600:
                h = dur // 3600
                m = (dur % 3600) // 60
                when = f"через {h} ч {m} мин" if m else f"через {h} ч"
            elif dur >= 60:
                m = dur // 60
                when = f"через {m} мин"
            else:
                when = f"через {dur} сек"
            if text:
                return f"Хорошо, напомню {when}: {text}."
            return f"Хорошо, напомню {when}."

    return None
```

### `jarvis/tray.py`

```python
"""Иконка в системном трее (pystray). ... [9 строк]"""

import logging
import os

import pystray
from PIL import Image, ImageDraw

from jarvis import APP_NAME, __version__, actions

log = logging.getLogger("jarvis.tray")


def _make_icon_image() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, 62, 62), fill=(18, 32, 58, 255), outline=(86, 156, 255, 255), width=3)
    # стилизованная «J»
    d.line((38, 16, 38, 42), fill=(86, 156, 255, 255), width=6)
    d.arc((20, 30, 42, 52), start=20, end=180, fill=(86, 156, 255, 255), width=6)
    return img


def build_tray(jarvis) -> pystray.Icon:
    def on_toggle(icon, item):
        jarvis.listening_enabled = not jarvis.listening_enabled
        log.info("Прослушивание: %s", jarvis.listening_enabled)

    def on_screenshot(icon, item):
        actions.take_screenshot()

    def on_show_window(icon, item):
        """Показать окно GUI (для launch_mode=tray)."""
        if getattr(jarvis, "gui", None) is not None:
            jarvis.gui.show_window()
        else:
            log.warning("GUI не запущен — окно показать нельзя")

    def on_open_settings(icon, item):
        """Открыть GUI и переключиться на вкладку «Настройки»."""
        if getattr(jarvis, "gui", None) is not None:
            jarvis.gui.show_window()
            jarvis.gui.open_settings_tab()
        else:
            log.warning("GUI не запущен — настройки открыть нельзя")

    def on_config(icon, item):
        """Открыть config.json из USER_DIR (%APPDATA%\Phoenix). ... [4 строк]"""
        from jarvis import paths as _paths
        try:
            os.startfile(str(_paths.config_path()))
        except Exception:
            log.exception("Не удалось открыть config.json")

    def on_log(icon, item):
        """Открыть jarvis.log из USER_DIR."""
        from jarvis import paths as _paths
        try:
            os.startfile(str(_paths.logs_dir() / "jarvis.log"))
        except Exception:
            log.exception("Не удалось открыть jarvis.log")

    def on_exit(icon, item):
        jarvis.shutdown()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(f"{APP_NAME} v{__version__}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        # default=True — двойной клик по иконке открывает окно
        pystray.MenuItem("Открыть окно", on_show_window, default=True),
        pystray.MenuItem("Настройки", on_open_settings),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Слушать микрофон", on_toggle,
                         checked=lambda item: jarvis.listening_enabled),
        pystray.MenuItem("Сделать скриншот", on_screenshot),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Открыть конфиг", on_config),
        pystray.MenuItem("Открыть журнал", on_log),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Выход", on_exit),
    )
    return pystray.Icon("jarvis", _make_icon_image(), f"{APP_NAME} v{__version__}", menu)
```

### `jarvis/tts.py`

```python
"""Синтез речи. ... [17 строк]"""

import asyncio
import io
import logging
import os
import re
import threading
import time
import wave
from pathlib import Path

import numpy as np

from jarvis.text_utils import prepare_text

log = logging.getLogger("jarvis.tts")

PIPER_REPO = "rhasspy/piper-voices"
BASE_DIR = Path(__file__).resolve().parent.parent

_SENTENCE_END = re.compile(r"[.!?…]+\s+")


class Speaker:
    def __init__(self, config):
        self._config = config
        cfg = config if hasattr(config, "get") else {}
        self.rate = float(cfg.get("voice_rate", 1.15))
        self.voice = cfg.get("tts_voice", "ruslan")
        self._voice_hint = cfg.get("voice", "Pavel")
        self._mode = None
        self._engine = None
        self._piper = None
        self._piper_cfg = None
        self._piper_quality = "medium"

        # Глобальное состояние воспроизведения
        self._play_thread = None
        self._playing = False
        self._play_lock = threading.Lock()

        # Per-call stop-token
        self._current_token: threading.Event = threading.Event()
        self._token_lock = threading.Lock()

        backend = cfg.get("tts_backend", "auto")
        ref = BASE_DIR / cfg.get("xtts_ref", "voices/jarvis.wav")
        if backend in ("auto", "xtts"):
            if ref.exists():
                try:
                    self._init_xtts(ref)
                except Exception:
                    log.exception("XTTS не завёлся, переключаюсь на piper")
            elif backend == "xtts":
                log.warning("Референс голоса не найден: %s", ref)
        if self._mode is None and backend in ("auto", "xtts", "piper"):
            try:
                self._init_piper(self.voice)
            except Exception:
                log.exception("Piper не завёлся, переключаюсь на WinRT")
        if self._mode is None:
            try:
                from winrt.windows.media.speechsynthesis import SpeechSynthesizer  # noqa: F401
                self._mode = "winrt"
                log.info("TTS: WinRT, голос %r, скорость %.2f", self._voice_hint, self.rate)
            except Exception:
                log.exception("WinRT недоступен, переключаюсь на SAPI")
                self._init_sapi()

    # --- сеттеры для Config.subscribe ------------------------------------

    def set_voice(self, voice: str) -> None:
        if voice == self.voice:
            return
        log.info("Голос изменился: %s → %s", self.voice, voice)
        self.voice = voice
        if self._mode == "piper":
            try:
                self._init_piper(voice)
            except Exception:
                log.exception("Не удалось переключить Piper на %s", voice)

    def set_rate(self, rate: float) -> None:
        self.rate = float(rate)
        if self._piper_cfg is not None:
            try:
                from piper import SynthesisConfig
                self._piper_cfg = SynthesisConfig(length_scale=round(1.0 / self.rate, 2))
            except Exception:
                pass

    # --- per-call stop-token ---------------------------------------------

    def _new_token(self) -> threading.Event:
        """Создаёт новый stop-token и делает его текущим. ... [4 строк]"""
        with self._token_lock:
            self._current_token = threading.Event()
            return self._current_token

    def _current_stop(self) -> threading.Event:
        with self._token_lock:
            return self._current_token

    # --- воспроизведение через sounddevice (для barge-in) ----------------

    def _play_wav(self, wav_bytes: bytes, token: threading.Event) -> None:
        """Играет WAV-байты чанками, проверяя per-call token."""
        try:
            import sounddevice as sd
        except ImportError:
            log.warning(
                "sounddevice недоступен — играю через winsound. "
                "Barge-in НЕ БУДЕТ РАБОТАТЬ. Установи: pip install sounddevice"
            )
            import winsound
            winsound.PlaySound(wav_bytes, winsound.SND_MEMORY)
            return

        with wave.open(io.BytesIO(wav_bytes)) as wf:
            rate = wf.getframerate()
            channels = wf.getnchannels()
            width = wf.getsampwidth()

        dtype = {1: "int8", 2: "int16", 4: "int32"}.get(width)
        if dtype is None:
            log.warning("Неподдерживаемая ширина сэмпла: %d", width)
            return

        with wave.open(io.BytesIO(wav_bytes)) as wf:
            frames = wf.readframes(wf.getnframes())
        audio = np.frombuffer(frames, dtype=dtype)
        if channels > 1:
            audio = audio.reshape(-1, channels)

        chunk = int(rate * 0.05)
        try:
            with sd.OutputStream(samplerate=rate, channels=channels, dtype=dtype) as stream:
                for i in range(0, len(audio), chunk):
                    if token.is_set():
                        log.info("TTS: воспроизведение прервано (token)")
                        break
                    stream.write(audio[i:i + chunk])
        except Exception:
            log.exception("sounddevice.OutputStream не завёлся — падаю на winsound")
            import winsound
            winsound.PlaySound(wav_bytes, winsound.SND_MEMORY)

    # --- xtts / piper / sapi / winrt --------------------------------------

    def _init_xtts(self, ref: Path) -> None:
        os.environ.setdefault("COQUI_TOS_AGREED", "1")
        import torch
        from TTS.api import TTS as CoquiTTS

        device = "cuda" if torch.cuda.is_available() else "cpu"
        log.info("Загрузка XTTS-v2 на %s...", device)
        self._xtts = CoquiTTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
        self._xtts_ref = str(ref)
        self._mode = "xtts"
        log.info("TTS: XTTS-v2, клон голоса из %s", ref.name)

    def _speak_xtts(self, text: str, token: threading.Event) -> None:
        if token.is_set():
            return
        samples = self._xtts.tts(text=text, speaker_wav=self._xtts_ref,
                                 language="ru", speed=self.rate)
        if token.is_set():
            return
        pcm = (np.clip(np.asarray(samples), -1, 1) * 32767).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(pcm.tobytes())
        self._play_wav(buf.getvalue(), token)

    def _init_piper(self, voice: str) -> None:
        from huggingface_hub import hf_hub_download
        from piper import PiperVoice, SynthesisConfig

        cfg = self._config if hasattr(self, "_config") else {}
        quality = "medium"
        if hasattr(cfg, "get"):
            quality = cfg.get("tts_voice_quality", "medium")
        if quality not in ("medium", "high"):
            quality = "medium"

        rel = f"ru/ru_RU/{voice}/{quality}/ru_RU-{voice}-{quality}.onnx"

        try:
            onnx = hf_hub_download(PIPER_REPO, rel)
            hf_hub_download(PIPER_REPO, rel + ".json")
            log.info("TTS: piper, голос %s/%s", voice, quality)
        except Exception:
            log.warning("Голос %s/%s не найден, откат на medium", voice, quality)
            quality = "medium"
            rel = f"ru/ru_RU/{voice}/medium/ru_RU-{voice}-medium.onnx"
            onnx = hf_hub_download(PIPER_REPO, rel)
            hf_hub_download(PIPER_REPO, rel + ".json")

        self._piper = PiperVoice.load(onnx)
        self._piper_cfg = SynthesisConfig(length_scale=round(1.0 / self.rate, 2))
        self._mode = "piper"
        self._piper_quality = quality
        log.info("TTS: piper, голос %s/%s, скорость %.2f", voice, quality, self.rate)

    def _speak_piper(self, text: str, token: threading.Event) -> None:
        if token.is_set():
            return

        # Mood влияет на скорость речи.
        # excited → +10%, tired → -10%.
        cfg = self._piper_cfg
        try:
            from jarvis import mood
            eff_rate = mood.effective_rate(self.rate)
            from piper import SynthesisConfig
            cfg = SynthesisConfig(length_scale=round(1.0 / eff_rate, 2))
        except Exception:
            log.exception("mood.effective_rate упал — использую базовую скорость")
            cfg = self._piper_cfg

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            self._piper.synthesize_wav(text, wf, cfg)
        if token.is_set():
            return
        self._play_wav(buf.getvalue(), token)

    def _init_sapi(self) -> None:
        import pyttsx3
        self._engine = pyttsx3.init()
        for v in self._engine.getProperty("voices"):
            ident = f"{v.id} {v.name}".lower()
            if self._voice_hint.lower() in ident or "ru" in ident or "irina" in ident:
                self._engine.setProperty("voice", v.id)
                log.info("TTS: SAPI, голос %s", v.name)
                break
        self._mode = "sapi"

    async def _synthesize(self, text: str) -> bytes:
        from winrt.windows.media.speechsynthesis import SpeechSynthesizer
        from winrt.windows.storage.streams import DataReader

        synth = SpeechSynthesizer()
        voices = list(SpeechSynthesizer.all_voices)
        voice = next(
            (v for v in voices if self._voice_hint.lower() in v.display_name.lower()),
            None,
        ) or next((v for v in voices if v.language.lower().startswith("ru")), None)
        if voice is not None:
            synth.voice = voice
        try:
            from jarvis import mood
            eff = mood.effective_rate(self.rate)
        except Exception:
            eff = self.rate
        try:
            synth.options.speaking_rate = eff
        except Exception:
            pass
        stream = await synth.synthesize_text_to_stream_async(text)
        reader = DataReader(stream.get_input_stream_at(0))
        await reader.load_async(stream.size)
        return bytes(reader.read_buffer(stream.size))

    def _speak_one(self, text: str, token: threading.Event) -> None:
        text = prepare_text(text)
        if not text or token.is_set():
            return
        # Пропускаем, если в тексте только невидимые символы
        # (zero-width space, BOM, soft hyphen). Иначе Piper падает
        # с wave.Error('# channels not specified').
        if not text.strip().strip("\u200b\u200c\u200d\ufeff\u00ad"):
            log.debug("TTS: пропускаю невидимый текст %r", text)
            return
        log.info("Говорю: %s", text)
        try:
            if self._mode == "xtts":
                self._speak_xtts(text, token)
            elif self._mode == "piper":
                self._speak_piper(text, token)
            elif self._mode == "winrt":
                wav = asyncio.run(self._synthesize(text))
                if token.is_set():
                    return
                self._play_wav(wav, token)
            else:
                if token.is_set():
                    return
                # Mood влияет на скорость SAPI.
                try:
                    from jarvis import mood
                    self._engine.setProperty(
                        "rate", int((mood.effective_rate(self.rate) - 1.0) * 100)
                    )
                except Exception:
                    log.exception("Не удалось применить mood к SAPI rate")
                self._engine.say(text)
                self._engine.runAndWait()
        except Exception:
            log.exception("Ошибка синтеза речи")

    def speak(self, text: str) -> None:
        """Синхронная озвучка (для тестов)."""
        if not text:
            return
        token = self._new_token()
        self._speak_one(text, token)

    def play_async(self, text: str) -> None:
        """Асинхронная озвучка одного текста. ... [4 строк]"""
        self.stop()

        # Ждём завершения старого потока. Если не успел — не запускаем новый.
        finished = self.wait_end(timeout=2.0)
        if not finished:
            log.warning(
                "TTS: старый поток не завершился за 2 сек — пропускаю новый вызов "
                "(иначе наложение)"
            )
            return

        token = self._new_token()

        with self._play_lock:
            self._playing = True

        def _run():
            try:
                self._speak_one(text, token)
            finally:
                with self._play_lock:
                    self._playing = False

        self._play_thread = threading.Thread(target=_run, daemon=True, name="tts-play")
        self._play_thread.start()

    def stop(self) -> None:
        """Взводит ТЕКУЩИЙ токен. Старые токены не трогает."""
        with self._token_lock:
            token = self._current_token
        if not token.is_set():
            log.info("TTS: прерывание (stop)")
        token.set()

    def is_playing(self) -> bool:
        with self._play_lock:
            return self._playing and self._play_thread is not None and self._play_thread.is_alive()

    def wait_end(self, timeout: float = 30.0) -> bool:
        """Ждёт завершения текущего TTS-потока. ... [9 строк]"""
        with self._play_lock:
            thread = self._play_thread
        if thread is None:
            return True

        # Защита от join() на незапущенном/уже завершённом потоке.
        if not thread.is_alive():
            with self._play_lock:
                self._playing = False
            return True

        thread.join(timeout=timeout)
        finished = not thread.is_alive()
        if finished:
            with self._play_lock:
                self._playing = False
        else:
            log.warning("TTS: поток не завершился за %.1f сек (timeout)", timeout)
        return finished

    def speak_stream(self, text_iter, timeout: float = 30.0) -> str:
        """Streaming TTS. Разбивает текст по предложениям и озвучивает по мере поступления. ... [4 строк]"""
        self.stop()
        self.wait_end(timeout=1.0)

        token = self._new_token()

        with self._play_lock:
            self._playing = True

        buffer = ""
        full_text_parts = []
        pending = []

        def _flush_sentences(force: bool = False):
            nonlocal buffer
            while True:
                m = _SENTENCE_END.search(buffer)
                if not m:
                    break
                sentence = buffer[:m.end()].strip()
                buffer = buffer[m.end():]
                if sentence:
                    pending.append(sentence)
            if force and buffer.strip():
                pending.append(buffer.strip())
                buffer = ""

        try:
            for chunk in text_iter:
                # №93: append ДО проверки токена — иначе при barge-in
                # последний чанк теряется.
                if chunk:
                    full_text_parts.append(chunk)
                    buffer += chunk
                if token.is_set():
                    log.info("TTS: стриминг прерван")
                    break
                _flush_sentences()
                while pending and not token.is_set():
                    sentence = pending.pop(0)
                    self._speak_one(sentence, token)
            if not token.is_set():
                _flush_sentences(force=True)
                while pending and not token.is_set():
                    sentence = pending.pop(0)
                    self._speak_one(sentence, token)
        except Exception:
            log.exception("Ошибка в speak_stream")
        finally:
            with self._play_lock:
                self._playing = False

        return "".join(full_text_parts).strip()
```

### `jarvis/uia.py`

```python
"""UI Automation — видим окна и элементы интерфейса. ... [18 строк]"""

import logging
import re
import threading
import time

log = logging.getLogger("jarvis.uia")

_lock = threading.RLock()

# Ленивая инициализация uiautomation.
_uia = None


def _ensure_init():
    """Ленивая инициализация UIA в текущем потоке."""
    global _uia
    if _uia is None:
        try:
            import uiautomation as auto
            _uia = auto
            log.info("UIA инициализирован")
        except ImportError:
            log.error("uiautomation не установлен. pip install uiautomation")
            raise
    return _uia


# =================================================================
# Поиск окна
# =================================================================

def find_window(title_part: str, timeout: float = 2.0):
    """Находит окно по части заголовка. None, если не нашёл."""
    uia = _ensure_init()
    title_low = title_part.lower()

    with _lock:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                for w in uia.GetRootControl().GetChildren():
                    try:
                        name = (w.Name or "").strip()
                        if name and title_low in name.lower():
                            return w
                    except Exception:
                        continue
            except Exception:
                log.exception("find_window: обход окон упал")
                return None
            time.sleep(0.1)
    return None


def get_active_window():
    """Возвращает активное окно или None."""
    uia = _ensure_init()
    try:
        with _lock:
            return uia.GetForegroundControl()
    except Exception:
        log.exception("get_active_window упал")
        return None


def get_active_window_title() -> str:
    """Заголовок активного окна."""
    w = get_active_window()
    if w is None:
        return ""
    try:
        return (w.Name or "").strip()
    except Exception:
        return ""


# =================================================================
# Чтение текста
# =================================================================

def read_active_text(max_chars: int = 4000) -> str:
    """Читает весь видимый текст активного окна. ... [3 строк]"""
    uia = _ensure_init()
    w = get_active_window()
    if w is None:
        return ""

    texts: list[str] = []
    total = 0

    with _lock:
        for ctrl in _walk_controls(w, depth=20):
            if total >= max_chars:
                break
            try:
                ct = ctrl.ControlType
                if ct not in (uia.ControlType.EditControl,
                              uia.ControlType.DocumentControl,
                              uia.ControlType.TextControl):
                    continue
                if ctrl.IsValuePatternAvailable():
                    val = ctrl.GetValuePattern().Value
                else:
                    val = ctrl.Name
                if val:
                    val = val.strip()
                    if val and val not in texts:
                        texts.append(val)
                        total += len(val)
            except Exception:
                continue

    result = "\n".join(texts)
    if len(result) > max_chars:
        result = result[:max_chars] + "..."
    return result


def read_active_text_stripped(max_chars: int = 2000) -> str:
    """read_active_text + склеивание пробелов."""
    text = read_active_text(max_chars=max_chars)
    return re.sub(r"\s+", " ", text).strip()


# =================================================================
# Кнопки
# =================================================================

def click_button(name_part: str, window_title: str | None = None,
                 timeout: float = 2.0) -> bool:
    """Нажимает кнопку по части имени. ... [4 строк]"""
    uia = _ensure_init()
    name_low = name_part.lower()

    with _lock:
        window = (find_window(window_title) if window_title
                  else get_active_window())
        if window is None:
            return False

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                for ctrl in window.GetChildren():
                    for c in _walk_controls(ctrl, depth=10):
                        try:
                            if c.ControlType != uia.ControlTypeName.ButtonControl:
                                continue
                            cname = (c.Name or "").strip().lower()
                            if name_low in cname:
                                c.GetInvokePattern().Invoke()
                                log.info("Нажал кнопку %r", c.Name)
                                return True
                        except Exception:
                            continue
            except Exception:
                pass
            time.sleep(0.1)
    return False


def _walk_controls(root, depth: int = 15):
    """Рекурсивно обходит контролы. Ловит исключения на каждом уровне."""
    if depth <= 0:
        return
    try:
        children = root.GetChildren()
    except Exception:
        return
    for c in children:
        yield c
        yield from _walk_controls(c, depth=depth - 1)


# =================================================================
# Браузеры — определяем по процессам, а не по заголовку окна.
# Так работает и в Chrome, и в Edge, Opera, Brave, Vivaldi, Arc, ...
# =================================================================

# Известные браузерные процессы (имя .exe в нижнем регистре).
_BROWSER_PROCESSES = {
    "chrome.exe":              "Chrome",
    "msedge.exe":              "Edge",
    "firefox.exe":             "Firefox",
    "opera.exe":               "Opera",
    "opera_gx.exe":            "Opera GX",
    "brave.exe":               "Brave",
    "yandex.exe":              "Яндекс",
    "browser.exe":             "Яндекс",     # старый Яндекс.Браузер
    "vivaldi.exe":             "Vivaldi",
    "arc.exe":                 "Arc",
    "chromium.exe":            "Chromium",
    "librewolf.exe":           "LibreWolf",
    "waterfox.exe":            "Waterfox",
    "tor.exe":                 "Tor Browser",
    "thorium.exe":             "Thorium",
    "slimjet.exe":             "Slimjet",
    "epic.exe":                "Epic",
    "maxthon.exe":             "Maxthon",
    "sleipnir.exe":            "Sleipnir",
    "palemoon.exe":            "Pale Moon",
    "basilisk.exe":            "Basilisk",
}


def list_windows() -> list[str]:
    """Список заголовков всех видимых окон. Для отладки."""
    uia = _ensure_init()
    result = []
    with _lock:
        try:
            for w in uia.GetRootControl().GetChildren():
                try:
                    name = (w.Name or "").strip()
                    if name:
                        result.append(name)
                except Exception:
                    continue
        except Exception:
            log.exception("list_windows упал")
    return result


def list_browsers() -> list[tuple[str, str]]:
    """Список запущенных браузеров: [(exe, human_name), ...]. ... [4 строк]"""
    try:
        import psutil
    except ImportError:
        log.warning("psutil не установлен — не могу определить процессы браузеров")
        return []

    found: dict[str, str] = {}
    for proc in psutil.process_iter(["name"]):
        try:
            pname = (proc.info.get("name") or "").lower()
            if pname in _BROWSER_PROCESSES:
                found[pname] = _BROWSER_PROCESSES[pname]
        except Exception:
            continue
    return sorted(found.items())


def _find_window_by_process(process_names: set[str], timeout: float = 2.0):
    """Ищет видимое окно, чей PID принадлежит процессу из process_names."""
    try:
        import psutil
    except ImportError:
        return None

    # Собираем PID-ы процессов с нужными именами.
    pids = set()
    for proc in psutil.process_iter(["name", "pid"]):
        try:
            if (proc.info.get("name") or "").lower() in process_names:
                pids.add(proc.info["pid"])
        except Exception:
            continue

    if not pids:
        return None

    # UIA нужен ТОЛЬКО когда есть процессы — иначе не инициализируем.
    uia = _ensure_init()

    with _lock:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                for w in uia.GetRootControl().GetChildren():
                    try:
                        if not w.Name:
                            continue
                        pid = w.ProcessId
                        if pid in pids:
                            return w
                    except Exception:
                        continue
            except Exception:
                log.exception("_find_window_by_process: обход упал")
                return None
            time.sleep(0.1)
    return None


def find_browser_window():
    """Находит окно ЛЮБОГО запущенного браузера. ... [4 строк]"""
    # 1. Активное окно — а вдруг это уже браузер?
    #    Оборачиваем в try: UIA может не работать, а процессы — видны.
    try:
        active = get_active_window()
        if active is not None:
            try:
                active_pid = active.ProcessId
                import psutil
                try:
                    pname = psutil.Process(active_pid).name().lower()
                    if pname in _BROWSER_PROCESSES:
                        return active
                except Exception:
                    pass
            except Exception:
                pass
    except Exception:
        # UIA не работает — не страшно, идём к процессам.
        pass

    # 2. Ищем по процессам.
    return _find_window_by_process(set(_BROWSER_PROCESSES.keys()))


def _get_browser_window():
    """Совместимость: обёртка над find_browser_window."""
    return find_browser_window()


def read_browser_url() -> str:
    """Читает URL активной вкладки. Пусто, если не браузер. ... [4 строк]"""
    # Сначала окно — если браузера нет, UIA не нужен.
    w = _get_browser_window()
    if w is None:
        return ""

    uia = _ensure_init()

    with _lock:
        # Ищем EditControl внутри окна.
        try:
            edit = uia.EditControl(searchFromControl=w, searchDepth=20)
            if edit.Exists(2):
                try:
                    value = edit.GetValuePattern().Value
                    if value:
                        value = value.strip()
                        if re.match(r"^https?://", value, re.I):
                            return value
                        if re.match(r"^[a-z0-9-]+\.[a-z]{2,}(/|$)", value, re.I):
                            return "https://" + value
                except Exception:
                    log.exception("read_browser_url: чтение Edit упало")
        except Exception:
            log.exception("read_browser_url: поиск Edit упал")

        # Fallback: домен из заголовка окна.
        try:
            title = (w.Name or "").strip()
            for sep in (" — ", " - ", " | "):
                if sep in title:
                    title = title.split(sep)[0].strip()
                    break
            m = re.search(r"([a-z0-9-]+\.(ru|com|org|net|io|dev|me|рф))",
                          title, re.I)
            if m:
                return "https://" + m.group(1)
        except Exception:
            pass

    return ""


def read_browser_tab_title() -> str:
    """Заголовок активной вкладки (без имени браузера)."""
    w = _get_browser_window()
    if w is None:
        return ""
    try:
        title = (w.Name or "").strip()
        # Формат: «Имя страницы — Chrome» → «Имя страницы»
        for sep in (" - ", " — ", " | "):
            if sep in title:
                return title.split(sep)[0].strip()
        return title
    except Exception:
        return ""


def read_browser_tabs() -> list[str]:
    """Список заголовков вкладок. ... [5 строк]"""
    # Сначала окно — если браузера нет, UIA не нужен.
    w = _get_browser_window()
    if w is None:
        return []

    uia = _ensure_init()

    tabs: list[str] = []
    with _lock:
        try:
            # Ищем тулбар «Вкладки» внутри окна браузера.
            # auto.ToolBarControl(searchFromControl=..., searchDepth=...)
            # возвращает ПЕРВЫЙ найденный тулбар.
            toolbar = uia.ToolBarControl(
                searchFromControl=w,
                Name="Вкладки",
                searchDepth=15,
            )
            if toolbar.Exists(2):
                # Обходим прямых детей тулбара — это TabItemControl.
                for child in toolbar.GetChildren():
                    try:
                        if child.ControlType != uia.ControlType.TabItemControl:
                            continue
                        name = (child.Name or "").strip()
                        if name and name not in tabs:
                            tabs.append(name)
                    except Exception:
                        continue

                # Если прямые дети — кнопки (Новая вкладка и т.п.),
                # обходим на один уровень глубже.
                if not tabs:
                    for child in toolbar.GetChildren():
                        for sub in child.GetChildren():
                            try:
                                if sub.ControlType != uia.ControlType.TabItemControl:
                                    continue
                                name = (sub.Name or "").strip()
                                if name and name not in tabs:
                                    tabs.append(name)
                            except Exception:
                                continue

            log.info("read_browser_tabs: %d вкладок", len(tabs))
        except Exception:
            log.exception("read_browser_tabs упал")

    # Fallback — хотя бы активная.
    if not tabs:
        title = read_browser_tab_title()
        if title:
            tabs = [title]

    return tabs


def close_browser_tab(tab_title_part: str) -> bool:
    """Закрывает вкладку браузера по части заголовка."""
    uia = _ensure_init()
    w = _get_browser_window()
    if w is None:
        return False

    tab_low = tab_title_part.lower()
    with _lock:
        try:
            for ctrl in _walk_controls(w, depth=15):
                try:
                    if ctrl.ControlType != uia.ControlTypeName.TabItemControl:
                        continue
                    name = (ctrl.Name or "").lower()
                    if tab_low not in name:
                        continue
                    # Ищем кнопку закрытия внутри вкладки.
                    for child in ctrl.GetChildren():
                        try:
                            if child.ControlType == uia.ControlTypeName.ButtonControl:
                                cname = (child.Name or "").lower()
                                if "close" in cname or "закры" in cname or not cname:
                                    child.GetInvokePattern().Invoke()
                                    log.info("Закрыл вкладку %r", ctrl.Name)
                                    return True
                        except Exception:
                            continue
                except Exception:
                    continue
        except Exception:
            log.exception("close_browser_tab упал")
    return False


def switch_browser_tab(tab_title_part: str) -> bool:
    """Переключается на вкладку по части заголовка."""
    uia = _ensure_init()
    w = _get_browser_window()
    if w is None:
        return False

    tab_low = tab_title_part.lower()
    with _lock:
        try:
            for ctrl in _walk_controls(w, depth=15):
                try:
                    if ctrl.ControlType != uia.ControlTypeName.TabItemControl:
                        continue
                    name = (ctrl.Name or "").lower()
                    if tab_low in name:
                        ctrl.GetSelectionItemPattern().Select()
                        log.info("Переключился на вкладку %r", ctrl.Name)
                        return True
                except Exception:
                    continue
        except Exception:
            log.exception("switch_browser_tab упал")
    return False


# =================================================================
# Меню
# =================================================================

def click_menu_item(path: str) -> bool:
    """Кликает пункт меню по пути «Файл > Сохранить как». ... [3 строк]"""
    uia = _ensure_init()
    parts = [p.strip() for p in re.split(r"\s*[>»]\s*", path) if p.strip()]
    if not parts:
        return False

    w = get_active_window()
    if w is None:
        return False

    with _lock:
        try:
            for ctrl in _walk_controls(w, depth=10):
                try:
                    if ctrl.ControlType != uia.ControlTypeName.MenuItemControl:
                        continue
                    name = (ctrl.Name or "").strip().lower()
                    if parts[0].lower() in name:
                        if len(parts) == 1:
                            ctrl.GetInvokePattern().Invoke()
                            return True
                        ctrl.GetExpandCollapsePattern().Expand()
                        time.sleep(0.1)
                        # Дальше — обход подменю.
                        for sub in _walk_controls(ctrl, depth=5):
                            try:
                                if sub.ControlType != uia.ControlTypeName.MenuItemControl:
                                    continue
                                sname = (sub.Name or "").strip().lower()
                                if parts[1].lower() in sname:
                                    sub.GetInvokePattern().Invoke()
                                    return True
                            except Exception:
                                continue
                except Exception:
                    continue
        except Exception:
            log.exception("click_menu_item упал")
    return False


# =================================================================
# Диагностика
# =================================================================

def is_available() -> bool:
    """Проверяет, работает ли UIA (COM инициализируется)."""
    try:
        _ensure_init()
        w = get_active_window()
        return w is not None
    except Exception:
        return False


def describe_active_window() -> str:
    """Человеческое описание активного окна — для отладки."""
    title = get_active_window_title()
    if not title:
        return "Не вижу активного окна."
    return f"Активное окно: «{title}»."


def describe_browsers() -> str:
    """Человеческое описание запущенных браузеров — для отладки."""
    browsers = list_browsers()
    if not browsers:
        return "Запущенных браузеров не вижу."
    names = [human for _, human in browsers]
    return "Запущены браузеры: " + ", ".join(names) + "."
```

### `jarvis/voices.py`

```python
"""Управление голосами Piper: ruslan, dmitri, irina, denis."""

import logging
import re

from jarvis import config_manager

log = logging.getLogger("jarvis.voices")

PIPER_VOICES = {
    "ruslan": "Руслан — мужской, спокойный",
    "dmitri": "Дмитрий — мужской, ниже и медленнее",
    "irina":  "Ирина — женский",
    "denis":  "Денис — мужской, дикторский",
}

ALIASES = {
    "руслан": "ruslan", "руслана": "ruslan",
    "дмитрий": "dmitri", "дмитрия": "dmitri",
    "дима": "dmitri", "диму": "dmitri",
    "ирина": "irina", "ирину": "irina",
    "ира": "irina", "иру": "irina",
    "денис": "denis", "дениса": "denis",
}


def current_voice(config=None) -> str:
    if config is not None:
        return config.get("tts_voice", "ruslan")
    return config_manager.load().get("tts_voice", "ruslan")


def switch(voice: str, config=None) -> str:
    if voice not in PIPER_VOICES:
        return f"Голос '{voice}' не знаю. Доступны: {', '.join(PIPER_VOICES)}."
    if config is not None:
        config.set("tts_voice", voice)
    else:
        config_manager.update("tts_voice", voice)
    log.info("Голос переключён на %s", voice)
    return f"Голос переключён на {voice.capitalize()}."


def handle_voice_command(cmd: str, config=None) -> str | None:
    if re.search(r"(какой|текущий|что\s+за)\s+голос", cmd) \
            or cmd in {"какой голос", "текущий голос"}:
        return f"Сейчас голос: {current_voice(config).capitalize()}."

    if re.search(r"(список|какие|покажи|доступные)\s+голос", cmd) \
            or cmd in {"список голосов", "какие голоса", "покажи голоса"}:
        return f"Доступные голоса: {', '.join(PIPER_VOICES.keys())}."

    m = re.search(r"(?:смени|поменяй|переключи|включи|поставь)\s+голос\s+(?:на\s+)?(\S+)", cmd)
    if m:
        name = m.group(1).strip().rstrip(".,!?").lower()
        key = ALIASES.get(name, name)
        if key in PIPER_VOICES:
            return switch(key, config)
        return f"Голос '{name}' не знаю. Доступны: {', '.join(PIPER_VOICES)}."

    m = re.match(r"^голос\s+(\S+)$", cmd)
    if m:
        name = m.group(1).strip().rstrip(".,!?").lower()
        key = ALIASES.get(name, name)
        if key in PIPER_VOICES:
            return switch(key, config)
        return f"Голос '{name}' не знаю."

    return None
```

### `jarvis/weather.py`

```python
"""Погода и курс валют. ... [10 строк]"""

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from typing import Optional

from jarvis import __version__

log = logging.getLogger("jarvis.weather")

# Кэш: {(тип, ключ): (timestamp, data)}
_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()

# TTL по умолчанию, если Config недоступен.
_DEFAULT_TTL = 600  # 10 минут

# Ссылка на Config — устанавливается через set_config() из main.py.
_config = None


def set_config(config) -> None:
    """Регистрирует Config — оттуда читаем weather_cache_ttl_sec. ... [3 строк]"""
    global _config
    _config = config
    log.info("weather: Config подключён, TTL = %d сек",
             _current_ttl())


def _current_ttl() -> int:
    """Актуальный TTL кэша в секундах. ... [4 строк]"""
    if _config is None:
        return _DEFAULT_TTL
    try:
        v = _config.get("weather_cache_ttl_sec", _DEFAULT_TTL)
        v = int(v)
        return v if v > 0 else _DEFAULT_TTL
    except (TypeError, ValueError):
        return _DEFAULT_TTL


def _cached(key: tuple, fetcher):
    now = time.time()
    ttl = _current_ttl()

    with _CACHE_LOCK:
        if key in _CACHE:
            ts, data = _CACHE[key]
            if now - ts < ttl:
                return data

    # fetcher() вызываем ВНЕ лока — иначе блокируем HTTP на весь кэш
    data = fetcher()

    if data is not None:
        with _CACHE_LOCK:
            _CACHE[key] = (time.time(), data)
    return data


def _http_get_json(url: str, timeout: float = 8.0):
    # User-Agent — из версии проекта, чтобы не отставать от __version__.
    ua = f"Phoenix/{__version__}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": ua})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        log.exception("HTTP GET не удался: %s", url)
        return None


# --- геокодинг --------------------------------------------------------------

def geocode(city: str) -> Optional[dict]:
    """Возвращает {'name': ..., 'country': ..., 'lat': ..., 'lon': ...} или None. ... [3 строк]"""
    key = ("geo", city.lower().strip())
    return _cached(key, lambda: _geocode_uncached(city))


def _geocode_uncached(city: str) -> Optional[dict]:
    q = urllib.parse.quote(city.strip())
    url = f"https://geocoding-api.open-meteo.com/v1/search?name={q}&count=1&language=ru&format=json"
    data = _http_get_json(url)
    if not data:
        return None
    results = data.get("results")
    if not results:
        return None
    r = results[0]
    return {
        "name": r.get("name") or city,
        "country": r.get("country") or "",
        "admin1": r.get("admin1") or "",
        "lat": r.get("latitude"),
        "lon": r.get("longitude"),
    }


# --- погода -----------------------------------------------------------------

_WEATHER_CODES = {
    0: "ясно",
    1: "преимущественно ясно", 2: "переменная облачность", 3: "пасмурно",
    45: "туман", 48: "изморозь",
    51: "лёгкая морось", 53: "морось", 55: "сильная морось",
    61: "небольшой дождь", 63: "дождь", 65: "сильный дождь",
    71: "небольшой снег", 73: "снег", 75: "сильный снег",
    77: "снежная крупа",
    80: "небольшие ливни", 81: "ливни", 82: "сильные ливни",
    85: "снегопад", 86: "сильный снегопад",
    95: "гроза", 96: "гроза с градом", 99: "сильная гроза с градом",
}


def get_weather(city: str, day: str = "today") -> Optional[dict]:
    """Возвращает погоду для города. ... [3 строк]"""
    key = ("weather", city.lower().strip(), day)
    return _cached(key, lambda: _get_weather_uncached(city, day))


def _get_weather_uncached(city: str, day: str) -> Optional[dict]:
    geo = geocode(city)
    if not geo:
        return None
    lat, lon = geo["lat"], geo["lon"]
    params = (
        f"latitude={lat}&longitude={lon}"
        "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m"
        "&daily=temperature_2m_max,temperature_2m_min,weather_code,precipitation_sum"
        "&timezone=auto&forecast_days=2"
    )
    url = f"https://api.open-meteo.com/v1/forecast?{params}"
    data = _http_get_json(url)
    if not data:
        return None

    try:
        if day == "tomorrow":
            return {
                "city": geo["name"],
                "country": geo.get("country", ""),
                "day": "завтра",
                "temp_min": round(data["daily"]["temperature_2m_min"][1]),
                "temp_max": round(data["daily"]["temperature_2m_max"][1]),
                "code": data["daily"]["weather_code"][1],
                "precip": data["daily"]["precipitation_sum"][1] or 0,
            }
        cur = data["current"]
        daily = data["daily"]
        return {
            "city": geo["name"],
            "country": geo.get("country", ""),
            "day": "сегодня",
            "temp": round(cur["temperature_2m"]),
            "feels": round(cur["apparent_temperature"]),
            "code": cur["weather_code"],
            "wind": round(cur["wind_speed_10m"]),
            "humidity": cur["relative_humidity_2m"],
            "temp_min": round(daily["temperature_2m_min"][0]),
            "temp_max": round(daily["temperature_2m_max"][0]),
            "precip": daily["precipitation_sum"][0] or 0,
        }
    except (KeyError, IndexError, TypeError):
        log.exception("Не удалось разобрать ответ погоды")
        return None


def describe_weather(w: dict) -> str:
    """Формирует человеческую фразу для озвучки. ... [4 строк]"""
    if not w:
        return "Не удалось узнать погоду."
    code = w.get("code", -1)
    desc = _WEATHER_CODES.get(code, "неизвестно")

    country = (w.get("country") or "").strip()
    city = w.get("city", "")
    city_full = f"{city}, {country}" if country else city

    if w.get("day") == "завтра":
        return (
            f"Прогноз на завтра — {city_full}: {desc}, "
            f"от {w['temp_min']} до {w['temp_max']} градусов, "
            f"осадки {round(w['precip'], 1)} мм."
        )
    return (
        f"Сейчас в городе {city_full}: {desc}, "
        f"{w['temp']} градусов, ощущается как {w['feels']}. "
        f"Ветер {w['wind']} метров в секунду, влажность {w['humidity']} процентов. "
        f"Днём от {w['temp_min']} до {w['temp_max']} градусов."
    )


# --- курс валют -------------------------------------------------------------

def get_currency_rates() -> Optional[dict]:
    """Возвращает все валюты ЦБ: ... [10 строк]"""
    key = ("currency", "cbr")
    return _cached(key, _get_currency_uncached)


def _get_currency_uncached() -> Optional[dict]:
    url = "https://www.cbr-xml-daily.ru/daily_json.js"
    data = _http_get_json(url)
    if not data:
        return None
    try:
        valutes = {}
        for code, v in data["Valute"].items():
            valutes[code] = {
                "name": v.get("Name") or code,
                "value": v.get("Value"),
                "nominal": v.get("Nominal", 1),
            }
        return {
            "date": data.get("Date", "")[:10],
            "valutes": valutes,
        }
    except (KeyError, TypeError):
        log.exception("Не удалось разобрать ответ ЦБ")
        return None


# Приоритет для вывода «общего курса»
_DEFAULT_CURRENCIES = ["USD", "EUR", "CNY"]


def describe_currency(rates: dict, code: str = "") -> str:
    """Озвучивает курс. ... [4 строк]"""
    if not rates:
        return "Не удалось узнать курс валют."

    valutes = rates.get("valutes", {})

    # Конкретная валюта
    if code:
        v = valutes.get(code.upper())
        if not v:
            return f"Курс валюты {code} не нашёл в базе ЦБ."
        nominal = v.get("nominal") or 1
        value = v.get("value")
        if value is None:
            return f"Курс валюты {code} не удалось прочитать."
        if nominal == 1:
            return f"{v['name']} — {value:.2f} рубля."
        return f"{v['name']} ({nominal} шт.) — {value:.2f} рубля."

    # Общий курс — основные валюты
    parts = []
    for c in _DEFAULT_CURRENCIES:
        v = valutes.get(c)
        if not v or v.get("value") is None:
            continue
        parts.append(f"{v['name']} — {v['value']:.2f} рубля")

    if not parts:
        return "Не удалось прочитать основные валюты."

    date = rates.get("date") or "сегодня"
    return f"Курс ЦБ на {date}: " + ", ".join(parts) + "."
```

### `scripts/__init__.py`

```python
"""Пакет scripts: утилиты разработчика. ... [6 строк]"""
```

### `scripts/build_exe.py`

```python
"""Сборка Феникс.exe (лёгкий лаунчер). ... [14 строк]"""

import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ICON = BASE / "jarvis" / "icon.ico"
EXE_NAME = "Феникс"


def ensure_icon() -> None:
    """Если иконки нет — генерирует её через make_icon.py."""
    if ICON.exists():
        print(f"Иконка: {ICON}")
        return

    print("Иконка не найдена — генерирую...")
    make_icon = BASE / "scripts" / "make_icon.py"
    if not make_icon.exists():
        print("ОШИБКА: scripts/make_icon.py не найден.")
        sys.exit(1)

    subprocess.run([sys.executable, str(make_icon)], check=True)

    if not ICON.exists():
        print(f"ОШИБКА: иконка не создалась: {ICON}")
        sys.exit(1)


def build() -> None:
    ensure_icon()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noconsole",
        "--clean",
        "--noconfirm",
        "--name", EXE_NAME,
        "--icon", str(ICON),
        "--distpath", str(BASE / "dist"),
        "--workpath", str(BASE / "build"),
        "--specpath", str(BASE / "build"),
        str(BASE / "launcher.py"),
    ]

    print("PyInstaller:", " ".join(cmd))
    subprocess.run(cmd, check=True)

    src = BASE / "dist" / f"{EXE_NAME}.exe"
    dst = BASE / f"{EXE_NAME}.exe"

    if not src.exists():
        print(f"ОШИБКА: PyInstaller не собрал {src}")
        sys.exit(1)

    dst.write_bytes(src.read_bytes())
    print(f"Готово: {dst}")
    print(f"Размер: {dst.stat().st_size / 1024 / 1024:.1f} МБ")


if __name__ == "__main__":
    build()
```

### `scripts/check_caps.py`

```python
"""Проверка возможностей системы — запускается из install.bat. ... [15 строк]"""
import json
import logging
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUTPUT = BASE / "system_caps.json"

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("check_caps")


def check_volume() -> dict:
    """Проверяет громкость. Возвращает {'available': bool, 'method': str}."""
    try:
        from pycaw.pycaw import AudioUtilities
        device = AudioUtilities.GetSpeakers()

        # Способ 1: volume_percent (pycaw >= 2026)
        if hasattr(device, "volume_percent"):
            try:
                _ = device.volume_percent
                return {"available": True, "method": "volume_percent"}
            except Exception:
                pass

        # Способ 2: EndpointVolume
        if hasattr(device, "EndpointVolume"):
            try:
                _ = device.EndpointVolume.GetMasterVolumeLevelScalar()
                return {"available": True, "method": "endpoint_volume"}
            except Exception:
                pass

        # Способ 3: Activate
        if hasattr(device, "Activate"):
            try:
                from ctypes import cast, POINTER
                from comtypes import CLSCTX_ALL
                from pycaw.pycaw import IAudioEndpointVolume
                interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                vol = cast(interface, POINTER(IAudioEndpointVolume))
                _ = vol.GetMasterVolumeLevelScalar()
                return {"available": True, "method": "activate"}
            except Exception:
                pass

        return {"available": False, "method": "none", "reason": "no known API"}
    except Exception as e:
        return {"available": False, "method": "none", "reason": str(e)[:80]}


def check_brightness() -> dict:
    """Проверяет яркость."""
    try:
        import screen_brightness_control as sbc
        values = sbc.get_brightness()
        if values:
            return {"available": True, "method": "sbc"}
        return {"available": False, "method": "none", "reason": "no monitors"}
    except Exception as e:
        return {"available": False, "method": "none", "reason": str(e)[:80]}


def check_layout() -> dict:
    """Проверяет раскладку (SendInput)."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        _ = user32.SendInput
        return {"available": True, "method": "sendinput"}
    except Exception as e:
        return {"available": False, "method": "none", "reason": str(e)[:80]}

def check_cpu() -> dict:
    """Определяет категорию CPU для рекомендации Piper. ... [4 строк]"""
    try:
        import psutil
    except ImportError:
        return {"available": False, "reason": "psutil не установлен"}

    try:
        cores = psutil.cpu_count(logical=False) or 0
        threads = psutil.cpu_count(logical=True) or 0

        if cores >= 6 and threads >= 12:
            power = "strong"
            recommended_piper = "high"
        elif cores >= 4 and threads >= 8:
            power = "normal"
            recommended_piper = "medium"
        else:
            power = "weak"
            recommended_piper = "medium"

        return {
            "available": True,
            "cores": cores,
            "threads": threads,
            "power": power,
            "recommended_piper": recommended_piper,
        }
    except Exception as e:
        return {"available": False, "reason": str(e)[:80]}

def main() -> int:
    log.info("=" * 60)
    log.info("  Проверка возможностей системы")
    log.info("=" * 60)

    caps = {
        "volume": check_volume(),
        "brightness": check_brightness(),
        "layout": check_layout(),
        "cpu": check_cpu(),
        "checked_at": time.time(),
    }

    log.info("")
    for name, info in caps.items():
        if name == "checked_at":
            continue
        mark = "[OK]  " if info.get("available") else "[FAIL]"

        if name == "cpu":
            # Специальный вывод для CPU
            if info.get("available"):
                log.info(
                    "%s %-12s %s ядер / %s потоков → рекомендация: %s",
                    mark, name,
                    info.get("cores"), info.get("threads"),
                    info.get("recommended_piper", "medium"),
                )
            else:
                log.info("%s %-12s %s", mark, name, info.get("reason", "?"))
            continue

        reason = f"  ({info.get('reason', '')})" if not info.get("available") else ""
        log.info("%s %-12s %s%s", mark, name, info.get("method", "?"), reason)

    OUTPUT.write_text(
        json.dumps(caps, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("")
    log.info("Сохранено: %s", OUTPUT)
    log.info("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### `scripts/make_icon.py`

```python
"""Генерация иконки Феникса (jarvis/icon.ico). ... [10 строк]"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

BASE = Path(__file__).resolve().parent.parent
OUTPUT = BASE / "jarvis" / "icon.ico"

# Цвета — те же, что в tray.py
BG_COLOR = (18, 32, 58, 255)       # тёмно-синий фон
ACCENT = (86, 156, 255, 255)       # акцентный синий


def draw_icon(size: int) -> Image.Image:
    """Рисует иконку заданного размера. ... [3 строк]"""
    k = size / 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Круг
    d.ellipse(
        (2 * k, 2 * k, 62 * k, 62 * k),
        fill=BG_COLOR,
        outline=ACCENT,
        width=max(1, int(3 * k)),
    )

    # Вертикальная линия буквы «J»
    d.line(
        (38 * k, 16 * k, 38 * k, 42 * k),
        fill=ACCENT,
        width=max(1, int(6 * k)),
    )

    # Дуга буквы «J» — нижний загиб
    d.arc(
        (20 * k, 30 * k, 42 * k, 52 * k),
        start=20,
        end=180,
        fill=ACCENT,
        width=max(1, int(6 * k)),
    )

    return img


def main() -> int:
    print("Генерация иконки...")

    # Базовый размер 256×256 — качественный исходник
    base = draw_icon(256)

    # Все стандартные размеры Windows
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    base.save(OUTPUT, format="ICO", sizes=sizes)

    print(f"Готово: {OUTPUT}")
    print(f"Размеры: {', '.join(f'{w}x{h}' for w, h in sizes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### `scripts/make_installer_images.py`

```python
"""Генерация картинок для Inno Setup установщика Феникса. ... [10 строк]"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parent.parent
ICON_PATH = BASE / "jarvis" / "icon.ico"
BANNER_OUT = BASE / "installer_banner.bmp"
SMALL_OUT = BASE / "installer_small.bmp"

BG_COLOR = (18, 32, 58)
ACCENT = (86, 156, 255)
TEXT_COLOR = (230, 237, 243)
BMP_FORMAT = "BMP"


def _find_font(size: int):
    candidates = [
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _load_icon(size: int) -> Image.Image:
    if not ICON_PATH.exists():
        print(f"ОШИБКА: {ICON_PATH} не найден.")
        sys.exit(1)
    img = Image.open(ICON_PATH).convert("RGBA")
    return img.resize((size, size), Image.LANCZOS)


def make_banner() -> None:
    w, h = 164, 314
    img = Image.new("RGB", (w, h), BG_COLOR)
    d = ImageDraw.Draw(img)

    for y in range(h):
        k = y / h
        r = int(BG_COLOR[0] + (0 - BG_COLOR[0]) * k * 0.35)
        g = int(BG_COLOR[1] + (0 - BG_COLOR[1]) * k * 0.35)
        b = int(BG_COLOR[2] + (10 - BG_COLOR[2]) * k * 0.35)
        d.line([(0, y), (w, y)], fill=(r, g, b))

    d.rectangle([(0, 0), (w, 4)], fill=ACCENT)

    icon = _load_icon(96)
    img.paste(icon, ((w - 96) // 2, 50), icon)

    font_title = _find_font(26)
    text = "Феникс"
    bbox = d.textbbox((0, 0), text, font=font_title)
    tw = bbox[2] - bbox[0]
    d.text(((w - tw) // 2, 170), text, fill=TEXT_COLOR, font=font_title)

    font_sub = _find_font(11)
    sub = "Голосовой ассистент"
    bbox = d.textbbox((0, 0), sub, font=font_sub)
    tw = bbox[2] - bbox[0]
    d.text(((w - tw) // 2, 205), sub, fill=ACCENT, font=font_sub)

    try:
        sys.path.insert(0, str(BASE))
        from jarvis import __version__
        ver_text = f"v{__version__}"
    except Exception:
        ver_text = "v1.0.0"

    font_ver = _find_font(10)
    bbox = d.textbbox((0, 0), ver_text, font=font_ver)
    tw = bbox[2] - bbox[0]
    d.text(((w - tw) // 2, h - 25), ver_text, fill=(139, 148, 158), font=font_ver)

    img.save(BANNER_OUT, format=BMP_FORMAT)
    print(f"OK: {BANNER_OUT.name} ({w}x{h})")


def make_small() -> None:
    size = 55
    icon = _load_icon(size)
    bg = Image.new("RGB", (size, size), BG_COLOR)
    bg.paste(icon, (0, 0), icon)
    bg.save(SMALL_OUT, format=BMP_FORMAT)
    print(f"OK: {SMALL_OUT.name} ({size}x{size})")


def main() -> int:
    print("Генерация картинок для Inno Setup...")
    print(f"Источник: {ICON_PATH.name}")
    print()
    make_banner()
    make_small()
    print()
    print("Готово. Теперь используй в installer.iss:")
    print("  WizardImageFile=installer_banner.bmp")
    print("  WizardSmallImageFile=installer_small.bmp")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### `scripts/mics.py`

```python
"""Подбор микрофона: показывает устройства ввода и уровень сигнала. ... [5 строк]"""

import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

FS = 16000


def main() -> None:
    default = sd.query_devices(kind="input")["name"]
    print(f"Устройство по умолчанию: {default}\n")

    # уникальные по имени входные устройства
    seen = {}
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            seen.setdefault(d["name"][:24], i)

    print("Говорите/шумите — измеряю уровень каждого микрофона...\n")
    results = []
    for name, idx in seen.items():
        try:
            rec = sd.rec(int(1.2 * FS), samplerate=FS, channels=1, dtype="int16", device=idx)
            sd.wait()
            results.append((int(np.abs(rec).max()), idx, name))
        except Exception as e:
            results.append((-1, idx, f"{name} (ошибка: {str(e)[:24]})"))

    results.sort(reverse=True)
    for peak, idx, name in results:
        mark = "  <-- ЖИВОЙ, впишите его имя в config" if peak > 1500 else ""
        lvl = "ошибка" if peak < 0 else str(peak)
        print(f"  [{idx:2}] пик={lvl:>6}  {name}{mark}")

    print('\nВ config.json: "input_device": "<часть имени>"  (например "camo"),')
    print('или null — устройство по умолчанию. Перезапустите Феникс после правки.')


if __name__ == "__main__":
    main()
```

### `scripts/selftest.py`

```python
"""Самопроверка без микрофона: TTS -> Vosk -> разбор команды. ... [3 строк]"""

import asyncio
import io
import json
import sys
import wave
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from vosk import KaldiRecognizer, Model, SetLogLevel  # noqa: E402

from jarvis.apps import build_apps, find_app  # noqa: E402
from jarvis.installed import find_installed, scan_start_menu  # noqa: E402
from jarvis.intents import IntentHandler, normalize  # noqa: E402
from jarvis.matching import match_score, wake_score  # noqa: E402
from jarvis.actions import find_process, spoken_domain, guess_site  # noqa: E402
from jarvis.tts import Speaker  # noqa: E402

PHRASES = [
    "феникс открой стим",
    "феникс закрой дискорд",
    "феникс сколько времени",
    "феникс открой ютуб",
]


def recognize(model: Model, wav_bytes: bytes) -> str:
    wf = wave.open(io.BytesIO(wav_bytes))
    rec = KaldiRecognizer(model, wf.getframerate())
    while True:
        chunk = wf.readframes(4000)
        if not chunk:
            break
        rec.AcceptWaveform(chunk)
    return json.loads(rec.FinalResult()).get("text", "")


def main() -> None:
    SetLogLevel(-1)
    # Whisper — строго до первого использования WinRT (иначе access violation)
    from jarvis.stt import WhisperTranscriber
    whisper = WhisperTranscriber("auto", "auto")
    # для прогона TTS->STT нужен WinRT-бэкенд
```

### `scripts/set_llm_model.py`

```python
"""Устанавливает llm_model в config.json. ... [10 строк]"""

import sys
from pathlib import Path

# Достаём корень проекта, чтобы импортировать jarvis.*
BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from jarvis import config_manager  # noqa: E402
from jarvis import paths as _paths  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("Использование: python scripts/set_llm_model.py <model_name>")
        return 1

    model = sys.argv[1].strip()
    if not model:
        print("Пустое имя модели")
        return 1

    config_path = _paths.config_path()

    data = config_manager.load(path=config_path)
    old = data.get("llm_model")
    data["llm_model"] = model

    ok = config_manager.save(data, path=config_path)
    if not ok:
        print(f"Не удалось записать {config_path}")
        return 1

    print(f"llm_model: {old} -> {model}")
    print(f"Файл: {config_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### `scripts/voicedemo.py`

```python
"""Прослушка голосов: проигрывает одну фразу всеми доступными голосами. ... [3 строк]"""

import io
import sys
import wave
import winsound
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

TEXT = " ".join(sys.argv[1:]) or "Феникс на связи. Открываю Стим, сэр. Скриншот сохранён."


def main() -> None:
    from huggingface_hub import hf_hub_download
    from piper import PiperVoice, SynthesisConfig

    for v in ["ruslan", "dmitri"]:
        rel = f"ru/ru_RU/{v}/medium/ru_RU-{v}-medium.onnx"
        voice = PiperVoice.load(hf_hub_download("rhasspy/piper-voices", rel))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            voice.synthesize_wav(TEXT, wf, SynthesisConfig(length_scale=0.87))
        print(f"piper/{v}...")
        winsound.PlaySound(buf.getvalue(), winsound.SND_MEMORY)

    import asyncio

    from jarvis.tts import Speaker

    s = Speaker({"tts_backend": "winrt", "voice": "Pavel", "voice_rate": 1.15})
    print("winrt/Pavel...")
    winsound.PlaySound(asyncio.run(s._synthesize(TEXT)), winsound.SND_MEMORY)


if __name__ == "__main__":
    main()
```

### `scripts/wakebench.py`

```python
"""Бенчмарк кандидатов в wake-слово: TTS (Pavel) -> Vosk-small -> что услышалось. ... [4 строк]"""

import asyncio
import io
import json
import sys
import wave
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from vosk import KaldiRecognizer, Model, SetLogLevel  # noqa: E402

from jarvis.matching import match_score  # noqa: E402
from jarvis.tts import Speaker  # noqa: E402

CANDIDATES = [
    "джарвис",   # текущее, для сравнения
    "нексус",
    "оракул",
    "феникс",
    "гермес",
    "юпитер",
    "кронос",
    "протон",
    "сокол",
    "вектор",
    "циклоп",
    "альтрон",
]

TEMPLATES = [
    "{w} сделай скриншот",
    "{w} открой стим",
    "эй {w} который час",
]


def recognize(model: Model, wav_bytes: bytes) -> str:
    wf = wave.open(io.BytesIO(wav_bytes))
    rec = KaldiRecognizer(model, wf.getframerate())
    while True:
        chunk = wf.readframes(4000)
        if not chunk:
            break
        rec.AcceptWaveform(chunk)
    return json.loads(rec.FinalResult()).get("text", "")


def main() -> None:
    SetLogLevel(-1)
    speaker = Speaker("Pavel")
    model = Model(str(BASE / "models" / "vosk-model-small-ru-0.22"))

    results = []
    for word in CANDIDATES:
        heard_words = []
        exact = fuzzy = 0
        for tpl in TEMPLATES:
            wav = asyncio.run(speaker._synthesize(tpl.format(w=word)))
            heard = recognize(model, wav)
            tokens = heard.split()
            # ищем wake-токен в начале фразы (как в боевом коде)
            tok = ""
            for t in tokens[:2]:  # «эй X ...» — слово может быть вторым
                if match_score(t, word) >= 0.8:
                    tok = t
                    break
            if tok == word:
                exact += 1
                fuzzy += 1
            elif tok:
                fuzzy += 1
            heard_words.append(" ".join(tokens[:2]))
        results.append((word, exact, fuzzy, heard_words))

    print(f"{'слово':<10} {'точно':<6} {'фаззи':<6} услышано (первые 2 токена)")
    for word, exact, fuzzy, heard in sorted(results, key=lambda r: (-r[2], -r[1])):
        print(f"{word:<10} {exact}/3    {fuzzy}/3    {heard}")


if __name__ == "__main__":
    main()
```

### `tests/test_caps.py`

```python
"""Тесты check_caps: структура system_caps.json."""
import json

from scripts import check_caps


def test_check_volume_structure():
    r = check_caps.check_volume()
    assert "available" in r
    assert "method" in r
    assert isinstance(r["available"], bool)


def test_check_brightness_structure():
    r = check_caps.check_brightness()
    assert "available" in r
    assert "method" in r


def test_check_layout_structure():
    r = check_caps.check_layout()
    assert "available" in r
    assert "method" in r
```

### `tests/test_config_manager.py`

```python
"""Тесты config_manager: параллельная запись не рвёт файл."""
import json
import threading
import time
from pathlib import Path

from jarvis import config_manager


def test_parallel_writes(tmp_path):
    """20 потоков пишут разные ключи — все должны сохраниться."""
    target = tmp_path / "test.json"
    config_manager.save({}, path=target)

    def writer(i):
        config_manager.update(f"key_{i}", i, path=target)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    data = json.loads(target.read_text(encoding="utf-8"))
    present = [k for k in data if k.startswith("key_")]
    assert len(present) == 20, f"Потерялись ключи: {present}"


def test_atomic_write_valid_json(tmp_path):
    """Если файл есть — он всегда валидный JSON."""
    target = tmp_path / "test.json"
    for i in range(50):
        config_manager.update("counter", i, path=target)
        data = json.loads(target.read_text(encoding="utf-8"))
        assert "counter" in data


def test_load_nonexistent(tmp_path):
    """Несуществующий файл — возвращает {}."""
    assert config_manager.load(path=tmp_path / "nope.json") == {}


def test_load_broken(tmp_path):
    """Битый файл — возвращает {}, не падает."""
    bad = tmp_path / "bad.json"
    bad.write_text("{это не json", encoding="utf-8")
    assert config_manager.load(path=bad) == {}
```

### `tests/test_mood.py`

```python
"""Тесты jarvis.mood — состояние, детекция, decay, влияние."""

import time
from unittest.mock import patch

from jarvis import mood


# =================================================================
# get / set / get_state
# =================================================================

def test_get_default_neutral():
    """Свежий профиль → neutral."""
    # Подменяем profile.get, чтобы не трогать реальный profile.json
    with patch("jarvis.profile.get", return_value=None):
        m = mood.get()
    assert m["state"] == "neutral"
    assert m["reason"] == ""


def test_set_mood_valid():
    """set_mood с валидным состоянием сохраняет."""
    saved = {}

    def fake_get(key, default=None):
        return saved.get(key, default)

    def fake_set(key, value):
        saved[key] = value
        return True

    with patch("jarvis.profile.get", side_effect=fake_get), \
         patch("jarvis.profile.set", side_effect=fake_set):
        ok = mood.set_mood("happy", reason="test")
        assert ok
        assert saved["mood"]["state"] == "happy"
        assert saved["mood"]["reason"] == "test"


def test_set_mood_invalid():
    """Невалидное состояние → False, ничего не сохраняется."""
    with patch("jarvis.profile.set") as mock_set:
        ok = mood.set_mood("ecstatic", reason="test")
        assert not ok
        mock_set.assert_not_called()


def test_set_mood_no_change():
    """Повторная установка того же состояния с тем же reason → no-op."""
    saved = {
        "mood": {"state": "happy", "since": 100.0, "reason": "test"},
    }

    def fake_get(key, default=None):
        return saved.get(key, default)

    with patch("jarvis.profile.get", side_effect=fake_get), \
         patch("jarvis.profile.set") as mock_set:
        ok = mood.set_mood("happy", reason="test")
        assert ok
        mock_set.assert_not_called()


# =================================================================
# Подписки
# =================================================================

def test_subscribe_and_notify():
    """Подписчик вызывается при смене состояния."""
    calls = []

    def cb(old, new):
        calls.append((old, new))

    mood.subscribe(cb)
    try:
        saved = {"mood": {"state": "neutral", "since": 100.0, "reason": ""}}

        def fake_get(key, default=None):
            return saved.get(key, default)

        def fake_set(key, value):
            saved[key] = value
            return True

        with patch("jarvis.profile.get", side_effect=fake_get), \
             patch("jarvis.profile.set", side_effect=fake_set):
            mood.set_mood("happy", reason="test")
    finally:
        mood.unsubscribe(cb)

    assert calls == [("neutral", "happy")]


def test_unsubscribe():
    """После unsubscribe подписчик не вызывается."""
    calls = []

    def cb(old, new):
        calls.append((old, new))

    mood.subscribe(cb)
    mood.unsubscribe(cb)

    saved = {"mood": {"state": "neutral", "since": 100.0, "reason": ""}}

    def fake_get(key, default=None):
        return saved.get(key, default)

    def fake_set(key, value):
        saved[key] = value
        return True

    with patch("jarvis.profile.get", side_effect=fake_get), \
         patch("jarvis.profile.set", side_effect=fake_set):
        mood.set_mood("happy", reason="test")

    assert calls == []


# =================================================================
# Детекция из текста
# =================================================================

def test_detect_praise():
    assert mood.detect("спасибо, ты лучший") == "happy"
    assert mood.detect("молодец!") == "happy"
    assert mood.detect("отлично справился") == "happy"


def test_detect_excited():
    assert mood.detect("ура, получилось!") == "excited"
    assert mood.detect("вау, круто") == "excited"


def test_detect_rude():
    assert mood.detect("ты тупой") == "annoyed"
    assert mood.detect("идиот какой-то") == "annoyed"
    assert mood.detect("дурак") == "annoyed"


def test_detect_tired():
    assert mood.detect("я устал") == "tired"
    assert mood.detect("спать хочу") == "tired"


def test_detect_none():
    assert mood.detect("открой стим") is None
    assert mood.detect("") is None
    assert mood.detect("какая погода") is None


def test_detect_rude_beats_praise():
    """«спасибо, ты тупой» → annoyed, а не happy."""
    assert mood.detect("спасибо, ты тупой") == "annoyed"


# =================================================================
# apply_from_text
# =================================================================

def test_apply_from_text_changes():
    """apply_from_text меняет mood и возвращает True."""
    saved = {"mood": {"state": "neutral", "since": 100.0, "reason": ""}}

    def fake_get(key, default=None):
        return saved.get(key, default)

    def fake_set(key, value):
        saved[key] = value
        return True

    with patch("jarvis.profile.get", side_effect=fake_get), \
         patch("jarvis.profile.set", side_effect=fake_set):
        changed = mood.apply_from_text("спасибо!")

    assert changed
    assert saved["mood"]["state"] == "happy"


def test_apply_from_text_no_change():
    """Без триггеров → False, mood не меняется."""
    with patch("jarvis.profile.set") as mock_set:
        changed = mood.apply_from_text("открой стим")
        assert not changed
        mock_set.assert_not_called()


# =================================================================
# Decay
# =================================================================

def test_decay_old_state():
    """Старое состояние (>5 мин) → neutral."""
    saved = {
        "mood": {"state": "happy", "since": time.time() - 600, "reason": "test"},
    }

    def fake_get(key, default=None):
        return saved.get(key, default)

    def fake_set(key, value):
        saved[key] = value
        return True

    with patch("jarvis.profile.get", side_effect=fake_get), \
         patch("jarvis.profile.set", side_effect=fake_set):
        changed = mood.decay(max_age_sec=300)

    assert changed
    assert saved["mood"]["state"] == "neutral"


def test_decay_fresh_state():
    """Свежее состояние → не трогаем."""
    saved = {
        "mood": {"state": "happy", "since": time.time() - 60, "reason": "test"},
    }

    def fake_get(key, default=None):
        return saved.get(key, default)

    with patch("jarvis.profile.get", side_effect=fake_get), \
         patch("jarvis.profile.set") as mock_set:
        changed = mood.decay(max_age_sec=300)

    assert not changed
    mock_set.assert_not_called()


def test_decay_neutral():
    """neutral не трогаем никогда."""
    saved = {"mood": {"state": "neutral", "since": 0, "reason": ""}}

    def fake_get(key, default=None):
        return saved.get(key, default)

    with patch("jarvis.profile.get", side_effect=fake_get), \
         patch("jarvis.profile.set") as mock_set:
        changed = mood.decay()

    assert not changed
    mock_set.assert_not_called()


# =================================================================
# Влияние на систему
# =================================================================

def test_effective_rate_excited():
    """excited → +10%."""
    with patch("jarvis.mood.get_state", return_value="excited"):
        assert mood.effective_rate(1.0) == 1.1


def test_effective_rate_tired():
    """tired → -10%."""
    with patch("jarvis.mood.get_state", return_value="tired"):
        assert mood.effective_rate(1.0) == 0.9


def test_effective_rate_neutral():
    """neutral → без изменений."""
    with patch("jarvis.mood.get_state", return_value="neutral"):
        assert mood.effective_rate(1.15) == 1.15


def test_color_all_states():
    """Каждое состояние имеет цвет."""
    for state in mood.STATES:
        with patch("jarvis.mood.get_state", return_value=state):
            c = mood.color()
            assert c.startswith("#")
            assert len(c) == 7


# =================================================================
# Prompt block
# =================================================================

def test_build_prompt_block_neutral():
    """neutral → пустая строка (не засоряем промпт)."""
    with patch("jarvis.mood.get_state", return_value="neutral"):
        assert mood.build_prompt_block() == ""


def test_build_prompt_block_annoyed():
    """annoyed → есть блок с подсказкой."""
    with patch("jarvis.mood.get_state", return_value="annoyed"):
        block = mood.build_prompt_block()
        assert "annoyed" in block
        assert "не извиняйся" in block.lower() or "ирони" in block.lower()


# =================================================================
# Описание
# =================================================================

def test_describe_neutral():
    saved = {"mood": {"state": "neutral", "since": 0, "reason": ""}}

    def fake_get(key, default=None):
        return saved.get(key, default)

    with patch("jarvis.profile.get", side_effect=fake_get):
        desc = mood.describe()

    assert "Спокойное" in desc


def test_describe_with_time():
    saved = {
        "mood": {"state": "happy", "since": time.time() - 120, "reason": "test"},
    }

    def fake_get(key, default=None):
        return saved.get(key, default)

    with patch("jarvis.profile.get", side_effect=fake_get):
        desc = mood.describe()

    assert "Хорошее" in desc
    assert "2 минут" in desc


# =================================================================
# Команды
# =================================================================

def test_handle_mood_command_query():
    """«как настроение» → describe()."""
    saved = {"mood": {"state": "neutral", "since": 0, "reason": ""}}

    def fake_get(key, default=None):
        return saved.get(key, default)

    with patch("jarvis.profile.get", side_effect=fake_get):
        reply = mood.handle_mood_command("как настроение")

    assert reply is not None
    assert "Спокойное" in reply or "Настроение" in reply


def test_handle_mood_command_cheer_up():
    """«не грусти» → happy."""
    saved = {"mood": {"state": "neutral", "since": 0, "reason": ""}}

    def fake_get(key, default=None):
        return saved.get(key, default)

    def fake_set(key, value):
        saved[key] = value
        return True

    with patch("jarvis.profile.get", side_effect=fake_get), \
         patch("jarvis.profile.set", side_effect=fake_set):
        reply = mood.handle_mood_command("не грусти")

    assert reply is not None
    assert saved["mood"]["state"] == "happy"


def test_handle_mood_command_calm_down():
    """«успокойся» → neutral."""
    saved = {"mood": {"state": "annoyed", "since": 100.0, "reason": "rude"}}

    def fake_get(key, default=None):
        return saved.get(key, default)

    def fake_set(key, value):
        saved[key] = value
        return True

    with patch("jarvis.profile.get", side_effect=fake_get), \
         patch("jarvis.profile.set", side_effect=fake_set):
        reply = mood.handle_mood_command("успокойся")

    assert reply is not None
    assert saved["mood"]["state"] == "neutral"


def test_handle_mood_command_none():
    """Не наша команда → None."""
    assert mood.handle_mood_command("открой стим") is None
    assert mood.handle_mood_command("какая погода") is None
```

### `tests/test_uia.py`

```python
"""Тесты jarvis.uia — логика обёртки. С моками. ... [7 строк]"""

from unittest.mock import patch, MagicMock

from jarvis import uia


# =================================================================
# list_windows
# =================================================================

def test_list_windows_empty():
    """Пустое дерево → пустой список."""
    fake_root = MagicMock()
    fake_root.GetChildren.return_value = []
    fake_auto = MagicMock()
    fake_auto.GetRootControl.return_value = fake_root

    with patch.object(uia, "_ensure_init", return_value=fake_auto), \
         patch.object(uia, "_uia", fake_auto):
        result = uia.list_windows()

    assert result == []


def test_list_windows_names():
    """Имена окон собираются, пустые — пропускаются."""
    w1 = MagicMock()
    w1.Name = "Chrome"
    w2 = MagicMock()
    w2.Name = ""
    w3 = MagicMock()
    w3.Name = "VS Code"

    fake_root = MagicMock()
    fake_root.GetChildren.return_value = [w1, w2, w3]
    fake_auto = MagicMock()
    fake_auto.GetRootControl.return_value = fake_root

    with patch.object(uia, "_ensure_init", return_value=fake_auto), \
         patch.object(uia, "_uia", fake_auto):
        result = uia.list_windows()

    assert result == ["Chrome", "VS Code"]


# =================================================================
# describe_active_window
# =================================================================

def test_describe_active_window_ok():
    """Заголовок есть → возвращаем фразу."""
    fake_w = MagicMock()
    fake_w.Name = "Chrome"
    with patch.object(uia, "get_active_window", return_value=fake_w):
        result = uia.describe_active_window()
    assert "Chrome" in result


def test_describe_active_window_none():
    """Окна нет → сообщение."""
    with patch.object(uia, "get_active_window", return_value=None):
        result = uia.describe_active_window()
    assert "Не вижу" in result


# =================================================================
# describe_browsers
# =================================================================

def test_describe_browsers_empty():
    with patch.object(uia, "list_browsers", return_value=[]):
        result = uia.describe_browsers()
    assert "не вижу" in result.lower()


def test_describe_browsers_found():
    fake = [("chrome.exe", "Chrome"), ("msedge.exe", "Edge")]
    with patch.object(uia, "list_browsers", return_value=fake):
        result = uia.describe_browsers()
    assert "Chrome" in result
    assert "Edge" in result


# =================================================================
# read_browser_tab_title
# =================================================================

def test_read_browser_tab_title_no_browser():
    """Нет браузера → пустая строка."""
    with patch.object(uia, "_get_browser_window", return_value=None):
        assert uia.read_browser_tab_title() == ""


def test_read_browser_tab_title_strips_suffix():
    """«Страница — Яндекс Браузер» → «Страница»."""
    fake_w = MagicMock()
    fake_w.Name = "YouTube — Яндекс Браузер"
    with patch.object(uia, "_get_browser_window", return_value=fake_w):
        result = uia.read_browser_tab_title()
    assert result == "YouTube"


def test_read_browser_tab_title_no_suffix():
    """Без разделителя — возвращаем как есть."""
    fake_w = MagicMock()
    fake_w.Name = "YouTube"
    with patch.object(uia, "_get_browser_window", return_value=fake_w):
        result = uia.read_browser_tab_title()
    assert result == "YouTube"


# =================================================================
# read_browser_tabs
# =================================================================

def test_read_browser_tabs_no_browser():
    with patch.object(uia, "_get_browser_window", return_value=None):
        assert uia.read_browser_tabs() == []


def test_read_browser_tabs_from_toolbar():
    """Toolbar 'Вкладки' содержит TabItem-детей."""
    fake_tab1 = MagicMock()
    fake_tab1.ControlType = "TabItemControl"
    fake_tab1.Name = "YouTube"
    fake_tab2 = MagicMock()
    fake_tab2.ControlType = "TabItemControl"
    fake_tab2.Name = "GitHub"
    fake_tab3 = MagicMock()
    fake_tab3.ControlType = "ButtonControl"
    fake_tab3.Name = "Новая вкладка"

    fake_toolbar = MagicMock()
    fake_toolbar.Exists.return_value = True
    fake_toolbar.GetChildren.return_value = [fake_tab3, fake_tab1, fake_tab2]

    fake_w = MagicMock()
    fake_w.Name = "YouTube — Chrome"

    fake_auto = MagicMock()
    fake_auto.ToolBarControl.return_value = fake_toolbar
    # Настраиваем ControlType — иначе MagicMock вернёт MagicMock,
    # и сравнение ctrl.ControlType != fake_auto.ControlType.TabItemControl
    # всегда даст True.
    fake_auto.ControlType.TabItemControl = "TabItemControl"

    with patch.object(uia, "_ensure_init", return_value=fake_auto), \
         patch.object(uia, "_uia", fake_auto), \
         patch.object(uia, "_get_browser_window", return_value=fake_w):
        result = uia.read_browser_tabs()

    assert result == ["YouTube", "GitHub"]


def test_read_browser_tabs_fallback():
    """Пусто → fallback на активную вкладку."""
    fake_toolbar = MagicMock()
    fake_toolbar.Exists.return_value = False

    fake_w = MagicMock()
    fake_w.Name = "YouTube — Chrome"

    fake_auto = MagicMock()
    fake_auto.ToolBarControl.return_value = fake_toolbar

    with patch.object(uia, "_ensure_init", return_value=fake_auto), \
         patch.object(uia, "_uia", fake_auto), \
         patch.object(uia, "_get_browser_window", return_value=fake_w):
        result = uia.read_browser_tabs()

    assert result == ["YouTube"]


# =================================================================
# read_browser_url
# =================================================================

def test_read_browser_url_no_browser():
    with patch.object(uia, "_get_browser_window", return_value=None):
        assert uia.read_browser_url() == ""


def test_read_browser_url_from_edit():
    """EditControl с http URL → возвращаем."""
    fake_edit = MagicMock()
    fake_edit.Exists.return_value = True
    value_pattern = MagicMock()
    value_pattern.Value = "https://youtube.com/watch?v=abc"
    fake_edit.GetValuePattern.return_value = value_pattern

    fake_w = MagicMock()
    fake_w.Name = "YouTube — Chrome"

    fake_auto = MagicMock()
    fake_auto.EditControl.return_value = fake_edit

    with patch.object(uia, "_ensure_init", return_value=fake_auto), \
         patch.object(uia, "_uia", fake_auto), \
         patch.object(uia, "_get_browser_window", return_value=fake_w):
        result = uia.read_browser_url()

    assert result == "https://youtube.com/watch?v=abc"


def test_read_browser_url_fallback_from_title():
    """Edit пустой → берём домен из заголовка."""
    fake_edit = MagicMock()
    fake_edit.Exists.return_value = False

    fake_w = MagicMock()
    fake_w.Name = "youtube.com — Chrome"

    fake_auto = MagicMock()
    fake_auto.EditControl.return_value = fake_edit

    with patch.object(uia, "_ensure_init", return_value=fake_auto), \
         patch.object(uia, "_uia", fake_auto), \
         patch.object(uia, "_get_browser_window", return_value=fake_w):
        result = uia.read_browser_url()

    assert result == "https://youtube.com"


# =================================================================
# is_available
# =================================================================

def test_is_available_true():
    fake_w = MagicMock()
    fake_auto = MagicMock()
    with patch.object(uia, "_ensure_init", return_value=fake_auto), \
         patch.object(uia, "_uia", fake_auto), \
         patch.object(uia, "get_active_window", return_value=fake_w):
        assert uia.is_available() is True


def test_is_available_false():
    with patch.object(uia, "_ensure_init", side_effect=ImportError("no uia")):
        assert uia.is_available() is False
```

### `tests/test_weather.py`

```python
"""Тесты weather: структура ответов, describe_*, geocode с моками. ... [3 строк]"""

from unittest.mock import patch

from jarvis import weather


# --- describe_weather ------------------------------------------------------

def test_describe_weather_none():
    assert "Не удалось" in weather.describe_weather(None)


def test_describe_weather_today():
    w = {
        "city": "Москва", "country": "Россия", "day": "сегодня",
        "temp": 5, "feels": 2, "code": 3, "wind": 4,
        "humidity": 70, "temp_min": 1, "temp_max": 8, "precip": 0.2,
    }
    s = weather.describe_weather(w)
    assert "Москва" in s
    assert "5 градусов" in s
    assert "Россия" in s


def test_describe_weather_tomorrow():
    w = {
        "city": "Казань", "country": "Россия", "day": "завтра",
        "temp_min": -2, "temp_max": 3, "code": 71, "precip": 1.5,
    }
    s = weather.describe_weather(w)
    assert "Казань" in s
    assert "завтра" in s


# --- describe_currency -----------------------------------------------------

def test_describe_currency_specific():
    rates = {
        "date": "2026-10-04",
        "valutes": {
            "USD": {"name": "Доллар США", "value": 83.48, "nominal": 1},
            "BYN": {"name": "Белорусский рубль", "value": 27.5, "nominal": 1},
        },
    }
    s = weather.describe_currency(rates, code="BYN")
    assert "Белорусский" in s
    assert "27.50" in s


def test_describe_currency_default():
    rates = {
        "date": "2026-10-04",
        "valutes": {
            "USD": {"name": "Доллар США", "value": 83.48, "nominal": 1},
            "EUR": {"name": "Евро", "value": 94.32, "nominal": 1},
        },
    }
    s = weather.describe_currency(rates)
    assert "Доллар" in s and "Евро" in s


def test_describe_currency_unknown():
    rates = {"date": "2026-10-04", "valutes": {}}
    s = weather.describe_currency(rates, code="XXX")
    assert "не нашёл" in s


# --- geocode с моками ------------------------------------------------------

def test_geocode_ok():
    """geocode возвращает нормализованный dict при успешном ответе."""
    fake = {
        "results": [{
            "name": "Москва",
            "country": "Россия",
            "admin1": "Москва",
            "latitude": 55.75,
            "longitude": 37.62,
        }],
    }
    with patch.object(weather, "_http_get_json", return_value=fake):
        weather._CACHE.clear()
        geo = weather.geocode("Москва")
    assert geo is not None
    assert geo["name"] == "Москва"
    assert geo["country"] == "Россия"
    assert geo["lat"] == 55.75
    assert geo["lon"] == 37.62


def test_geocode_not_found():
    """geocode возвращает None, если результатов нет."""
    with patch.object(weather, "_http_get_json", return_value={"results": []}):
        weather._CACHE.clear()
        assert weather.geocode("НесуществующийГород12345") is None


def test_geocode_http_error():
    """geocode возвращает None, если _http_get_json вернул None (сеть упала)."""
    with patch.object(weather, "_http_get_json", return_value=None):
        weather._CACHE.clear()
        assert weather.geocode("Москва") is None


# --- _get_weather_uncached с моками ----------------------------------------

def test_get_weather_today_ok():
    """get_weather парсит ответ open-meteo и возвращает dict."""
    geo = {"name": "Москва", "country": "Россия", "lat": 55.75, "lon": 37.62}
    api = {
        "current": {
            "temperature_2m": 5.4,
            "apparent_temperature": 2.1,
            "weather_code": 3,
            "wind_speed_10m": 4.2,
            "relative_humidity_2m": 70,
        },
        "daily": {
            "temperature_2m_min": [1.0, -2.0],
            "temperature_2m_max": [8.0, 3.0],
            "weather_code": [3, 71],
            "precipitation_sum": [0.2, 1.5],
        },
    }
    with patch.object(weather, "geocode", return_value=geo), \
         patch.object(weather, "_http_get_json", return_value=api):
        weather._CACHE.clear()
        w = weather.get_weather("Москва", day="today")
    assert w is not None
    assert w["city"] == "Москва"
    assert w["temp"] == 5
    assert w["feels"] == 2
    assert w["code"] == 3
    assert w["wind"] == 4
    assert w["humidity"] == 70
    assert w["temp_min"] == 1
    assert w["temp_max"] == 8


def test_get_weather_tomorrow_ok():
    """get_weather(day='tomorrow') берёт индексы [1] из daily."""
    geo = {"name": "Казань", "country": "Россия", "lat": 55.79, "lon": 49.11}
    api = {
        "current": {
            "temperature_2m": 5.4, "apparent_temperature": 2.1,
            "weather_code": 3, "wind_speed_10m": 4.2, "relative_humidity_2m": 70,
        },
        "daily": {
            "temperature_2m_min": [1.0, -2.0],
            "temperature_2m_max": [8.0, 3.0],
            "weather_code": [3, 71],
            "precipitation_sum": [0.2, 1.5],
        },
    }
    with patch.object(weather, "geocode", return_value=geo), \
         patch.object(weather, "_http_get_json", return_value=api):
        weather._CACHE.clear()
        w = weather.get_weather("Казань", day="tomorrow")
    assert w is not None
    assert w["day"] == "завтра"
    assert w["temp_min"] == -2
    assert w["temp_max"] == 3
    assert w["code"] == 71


def test_get_weather_no_geocode():
    """Если geocode не нашёл город — get_weather возвращает None."""
    with patch.object(weather, "geocode", return_value=None):
        weather._CACHE.clear()
        assert weather.get_weather("НесуществующийГород12345") is None


# --- get_currency_rates с моками -------------------------------------------

def test_get_currency_rates_ok():
    """get_currency_rates парсит ответ ЦБ."""
    api = {
        "Date": "2026-10-04T11:30:00+03:00",
        "Valute": {
            "USD": {"Name": "Доллар США", "Value": 83.48, "Nominal": 1},
            "EUR": {"Name": "Евро", "Value": 94.32, "Nominal": 1},
            "BYN": {"Name": "Белорусский рубль", "Value": 27.5, "Nominal": 1},
        },
    }
    with patch.object(weather, "_http_get_json", return_value=api):
        weather._CACHE.clear()
        r = weather.get_currency_rates()
    assert r is not None
    assert r["date"] == "2026-10-04"
    assert r["valutes"]["USD"]["value"] == 83.48
    assert r["valutes"]["BYN"]["name"] == "Белорусский рубль"


def test_get_currency_rates_http_error():
    """get_currency_rates возвращает None при падении сети."""
    with patch.object(weather, "_http_get_json", return_value=None):
        weather._CACHE.clear()
        assert weather.get_currency_rates() is None


# --- кэш -------------------------------------------------------------------

def test_cache_used():
    """Второй вызов geocode не дёргает _http_get_json — берёт из кэша."""
    fake = {
        "results": [{
            "name": "Москва", "country": "Россия",
            "latitude": 55.75, "longitude": 37.62,
        }],
    }
    weather._CACHE.clear()
    with patch.object(weather, "_http_get_json", return_value=fake) as mock:
        weather.geocode("Москва")
        weather.geocode("Москва")
    assert mock.call_count == 1, "Второй вызов должен брать из кэша"


def test_cache_different_cities():
    """Разные города — разные ключи кэша, _http_get_json вызывается дважды."""
    fake_msk = {
        "results": [{"name": "Москва", "country": "Россия",
                     "latitude": 55.75, "longitude": 37.62}],
    }
    fake_kzn = {
        "results": [{"name": "Казань", "country": "Россия",
                     "latitude": 55.79, "longitude": 49.11}],
    }
    weather._CACHE.clear()
    with patch.object(weather, "_http_get_json") as mock:
        mock.side_effect = [fake_msk, fake_kzn]
        weather.geocode("Москва")
        weather.geocode("Казань")
    assert mock.call_count == 2
```

### `check_syntax.py`

```python
"""Проверяет синтаксис всех .py файлов в проекте."""
import ast
import sys
from pathlib import Path

# Принудительно UTF-8 для stdout/stderr — иначе на CI (Windows, cp1252)
# падает UnicodeEncodeError при печати русских букв.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parent

# Папки, где ищем .py
TARGETS = [
    BASE / "jarvis",
    BASE / "scripts",
    BASE / "tests",   # раньше тесты не проверялись: синтаксис-ошибка
                      # в tests/ проходила этот шаг CI незамеченной
    BASE,             # корень: launcher.py, check_syntax.py, snapshot.py
]

# Исключения
SKIP_DIRS = {"__pycache__", ".venv", "venv", ".git", "models", "voices", "logs"}
SKIP_FILES = set()

files = []
for t in TARGETS:
    if not t.exists():
        continue
    if t == BASE:
        # В корне — только файлы верхнего уровня
        files.extend(f for f in t.glob("*.py") if f.name not in SKIP_FILES)
    else:
        for f in t.rglob("*.py"):
            if any(part in SKIP_DIRS for part in f.parts):
                continue
            if f.name in SKIP_FILES:
                continue
            files.append(f)

files = sorted(set(files))

failed = 0
for f in files:
    try:
        ast.parse(f.read_text(encoding="utf-8"))
        rel = f.relative_to(BASE)
        print(f"OK   {rel}")
    except SyntaxError as e:
        failed += 1
        rel = f.relative_to(BASE) if f.is_relative_to(BASE) else f
        print(f"FAIL {rel}: {e}")

print()
if failed:
    print(f"Ошибок: {failed}")
    sys.exit(1)
else:
    print(f"Все {len(files)} файлов в порядке.")
```

### `launcher.py`

```python
"""Лаунчер Феникса — полный автозапуск. ... [14 строк]"""

import ctypes
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

# ============================================================
# Константы
# ============================================================

# Local\ вместо Global\ — работает без прав администратора
# (Global\ требует SeCreateGlobalPrivilege).
MUTEX_NAME = "Local\\JarvisPhoenixSingleInstance"
_MUTEX_HANDLE = None

PYTHON_INSTALLER_URL = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
PYTHON_INSTALLER_FILE = "python-3.11.9-amd64.exe"

VOSK_MODEL_NAME = "vosk-model-small-ru-0.22"
VOSK_MODEL_URL = f"https://alphacephei.com/vosk/models/{VOSK_MODEL_NAME}.zip"

OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_DOWNLOAD_PAGE = "https://ollama.com/download"

# Где искать Python, если py launcher не работает
PYTHON_SEARCH_PATHS = [
    r"C:\Python312\python.exe",
    r"C:\Python311\python.exe",
    r"C:\Python310\python.exe",
    r"C:\Program Files\Python312\python.exe",
    r"C:\Program Files\Python311\python.exe",
    r"C:\Program Files\Python310\python.exe",
]

# Где искать Ollama
OLLAMA_SEARCH_PATHS = [
    r"C:\Program Files\Ollama\ollama.exe",
    r"C:\Program Files (x86)\Ollama\ollama.exe",
]

# Какие версии Python подходят
REQUIRED_PY_VERSIONS = ("3.12", "3.11", "3.10")

# MessageBox флаги
MB_OK = 0x00
MB_OKCANCEL = 0x01
MB_YESNO = 0x04
MB_ICONERROR = 0x10
MB_ICONWARNING = 0x30
MB_ICONINFORMATION = 0x40
MB_ICONQUESTION = 0x20

IDYES = 6
IDNO = 7
IDOK = 1
IDCANCEL = 2

# Флаги subprocess
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008


# ============================================================
# MessageBox
# ============================================================

def msg_box(text: str, title: str = "Феникс", flags: int = MB_OK) -> int:
    """Показывает Windows MessageBox. Возвращает ID нажатой кнопки."""
    try:
        return ctypes.windll.user32.MessageBoxW(0, text, title, flags)
    except Exception:
        return 0


def info(text: str, title: str = "Феникс") -> None:
    msg_box(text, title, MB_OK | MB_ICONINFORMATION)


def warn(text: str, title: str = "Феникс") -> None:
    msg_box(text, title, MB_OK | MB_ICONWARNING)


def error(text: str, title: str = "Феникс — ошибка") -> None:
    msg_box(text, title, MB_OK | MB_ICONERROR)


def ask_yes_no(text: str, title: str = "Феникс") -> bool:
    return msg_box(text, title, MB_YESNO | MB_ICONQUESTION) == IDYES


# ============================================================
# Логирование
# ============================================================

def _setup_logging(base_dir: Path) -> Path:
    logs_dir = base_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "launcher.log"

    logger = logging.getLogger("launcher")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    fh.setFormatter(logging.Formatter(
        "%(asctime)s launcher %(levelname)s %(message)s"
    ))
    logger.addHandler(fh)

    return log_file


# ============================================================
# Мьютекс
# ============================================================

def already_running(logger) -> bool:
    global _MUTEX_HANDLE

    if _MUTEX_HANDLE is not None:
        return False

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    last_error = kernel32.GetLastError()

    if last_error == 183:
        if handle:
            kernel32.CloseHandle(handle)
        logger.info("Феникс уже запущен")
        return True

    _MUTEX_HANDLE = handle
    return False


# ============================================================
# Поиск папки проекта
# ============================================================

def find_project_dir(logger) -> Path:
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
    else:
        exe_dir = Path(__file__).resolve().parent

    candidates = [exe_dir, exe_dir.parent, Path.cwd()]
    for cand in candidates:
        if (cand / "jarvis" / "__init__.py").exists():
            logger.info("Проект найден: %s", cand)
            return cand

    logger.error("Не найдена папка с jarvis/ (проверены: %s)",
                 ", ".join(str(c) for c in candidates))
    return exe_dir


# ============================================================
# Python: поиск, скачивание installer
# ============================================================

def _check_python_version(python_exe: str, logger) -> str | None:
    """Возвращает версию ('3.11.9') или None, если не подходит."""
    try:
        result = subprocess.run(
            [python_exe, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            return None
        out = result.stdout.strip() or result.stderr.strip()
        if out.startswith("Python "):
            version = out[7:].strip()
            for req in REQUIRED_PY_VERSIONS:
                if version.startswith(req):
                    return version
        return None
    except Exception:
        return None


def find_python(logger) -> str | None:
    """Ищет Python 3.10-3.12. Возвращает путь к python.exe или None."""
    # 1. py launcher
    for ver in REQUIRED_PY_VERSIONS:
        try:
            result = subprocess.run(
                ["py", f"-{ver}", "-c", "import sys; print(sys.executable)"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=CREATE_NO_WINDOW,
            )
            if result.returncode == 0:
                exe = result.stdout.strip()
                if exe and Path(exe).exists():
                    logger.info("Python %s найден через py: %s", ver, exe)
                    return exe
        except Exception:
            pass

    # 2. where python
    for name in ("python.exe", "python"):
        found = shutil.which(name)
        if found:
            version = _check_python_version(found, logger)
            if version:
                logger.info("Python %s найден в PATH: %s", version, found)
                return found

    # 3. Типичные пути
    for path_str in PYTHON_SEARCH_PATHS:
        p = Path(path_str)
        if p.exists():
            version = _check_python_version(str(p), logger)
            if version:
                logger.info("Python %s найден: %s", version, p)
                return str(p)

    # 4. %LOCALAPPDATA%\Programs\Python\PythonXY
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        for ver in ("312", "311", "310"):
            cand = Path(local_appdata) / "Programs" / "Python" / f"Python{ver}" / "python.exe"
            if cand.exists():
                version = _check_python_version(str(cand), logger)
                if version:
                    logger.info("Python %s найден: %s", version, cand)
                    return str(cand)

    logger.info("Python 3.10-3.12 не найден")
    return None


def download_python_installer(logger) -> Path | None:
    """Скачивает официальный installer Python в temp."""
    temp_dir = Path(os.environ.get("TEMP", "."))
    installer = temp_dir / PYTHON_INSTALLER_FILE

    if installer.exists():
        logger.info("Installer уже есть: %s", installer)
        return installer

    info(
        "Сейчас будет скачан установщик Python 3.11 (~25 МБ).\n\n"
        "После скачивания откроется окно установки — "
        "нажми «Install Now» и дождись завершения.\n\n"
        "Нажми ОК, чтобы начать скачивание.",
        "Феникс — установка Python",
    )

    logger.info("Скачиваю installer: %s", PYTHON_INSTALLER_URL)
    try:
        urllib.request.urlretrieve(PYTHON_INSTALLER_URL, installer)
        logger.info("Installer скачан: %s", installer)
        return installer
    except Exception:
        logger.exception("Не удалось скачать installer Python")
        error(
            "Не удалось скачать Python.\n\n"
            "Проверь интернет или скачай вручную:\n"
            "https://www.python.org/downloads/release/python-3119/\n\n"
            "Логи: logs\\launcher.log",
        )
        return None


def run_python_installer(installer: Path, logger) -> bool:
    """Запускает installer Python. Ждёт завершения."""
    logger.info("Запускаю installer: %s", installer)
    try:
        subprocess.run([str(installer)], check=False)
    except Exception:
        logger.exception("Ошибка запуска installer")
        return False

    logger.info("Installer завершён, ищу Python заново")
    time.sleep(2)
    python = find_python(logger)
    return python is not None


# ============================================================
# Venv: создание
# ============================================================

def find_venv_pythonw(project_dir: Path, logger) -> Path | None:
    candidates = [
        project_dir / ".venv311" / "Scripts" / "pythonw.exe",
        project_dir / ".venv" / "Scripts" / "pythonw.exe",
    ]
    for cand in candidates:
        if cand.exists():
            logger.info("venv найден: %s", cand)
            return cand
    return None


def create_venv(project_dir: Path, python_exe: str, logger) -> bool:
    """Создаёт .venv311 через указанный Python."""
    venv_dir = project_dir / ".venv311"

    if venv_dir.exists():
        logger.info("venv уже существует: %s", venv_dir)
        return True

    info(
        "Создаю виртуальное окружение...\n\n"
        "Это займёт несколько секунд.",
        "Феникс — окружение",
    )

    logger.info("Создаю venv: %s", venv_dir)
    try:
        result = subprocess.run(
            [python_exe, "-m", "venv", str(venv_dir)],
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            logger.error("venv не создан: %s", result.stderr)
            error(
                "Не удалось создать виртуальное окружение.\n\n"
                f"{result.stderr[:500]}\n\n"
                "Логи: logs\\launcher.log",
            )
            return False
        logger.info("venv создан: %s", venv_dir)
        return True
    except Exception:
        logger.exception("Ошибка создания venv")
        error("Не удалось создать окружение. Логи: logs\\launcher.log")
        return False


# ============================================================
# Зависимости: установка
# ============================================================

def check_dependencies(project_dir: Path, logger) -> bool:
    """Проверяет, установлены ли ключевые зависимости в venv."""
    python = project_dir / ".venv311" / "Scripts" / "python.exe"
    if not python.exists():
        return False
    try:
        result = subprocess.run(
            [str(python), "-c", "import flet, vosk; print('ok')"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=CREATE_NO_WINDOW,
        )
        return result.returncode == 0
    except Exception:
        return False


def install_dependencies(project_dir: Path, logger) -> bool:
    """Устанавливает зависимости из requirements.txt."""
    python = project_dir / ".venv311" / "Scripts" / "python.exe"
    req = project_dir / "requirements.txt"

    if not req.exists():
        logger.error("requirements.txt не найден: %s", req)
        error("requirements.txt не найден. Феникс установлен неправильно.")
        return False

    info(
        "Устанавливаю зависимости.\n\n"
        "Это займёт 5–10 минут (flet, vosk, piper, faster-whisper).\n\n"
        "Нажми ОК, чтобы начать. После завершения появится ещё одно окно.",
        "Феникс — установка",
    )

    logger.info("pip install -r requirements.txt")
    try:
        result = subprocess.run(
            [str(python), "-m", "pip", "install", "-r", str(req)],
            cwd=str(project_dir),
        )
        if result.returncode != 0:
            logger.error("pip install упал: returncode=%d", result.returncode)
            error(
                "Не удалось установить зависимости.\n\n"
                "Возможные причины:\n"
                "  - Нет интернета\n"
                "  - Нет Visual C++ Redistributable\n\n"
                "Смотри: logs\\launcher.log",
            )
            return False
        logger.info("Зависимости установлены")
        info("Зависимости установлены. OK", "Феникс")
        return True
    except Exception:
        logger.exception("Ошибка pip install")
        error("Ошибка установки зависимостей. Логи: logs\\launcher.log")
        return False


# ============================================================
# Vosk-модель: проверка, скачивание
# ============================================================

def check_vosk_model(project_dir: Path, logger) -> bool:
    """Проверяет Vosk-модель в ASCII-пути (C:\\ProgramData\\Phoenix\\models)."""
    program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    model_dir = Path(program_data) / "Phoenix" / "models" / VOSK_MODEL_NAME
    ok = model_dir.exists() and (model_dir / "am").exists()
    logger.info("Vosk-модель в %s: %s", model_dir, "есть" if ok else "нет")
    return ok


def download_vosk_model(project_dir: Path, logger) -> bool:
    """Скачивает и распаковывает Vosk-модель в ASCII-путь."""
    program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    safe_models = Path(program_data) / "Phoenix" / "models"

    try:
        safe_models.mkdir(parents=True, exist_ok=True)
    except Exception:
        safe_models = Path(r"C:\Phoenix\models")
        safe_models.mkdir(parents=True, exist_ok=True)

    logger.info("Vosk-модель будет в: %s", safe_models)

    zip_path = safe_models / f"{VOSK_MODEL_NAME}.zip"
    target_dir = safe_models / VOSK_MODEL_NAME

    if target_dir.exists() and (target_dir / "am").exists():
        logger.info("Vosk-модель уже есть: %s", target_dir)
        return True

    info(
        "Скачиваю модель Vosk (~45 МБ) в C:\\ProgramData\\Phoenix\\models.\n\n"
        "Это займёт 1–2 минуты.",
        "Феникс — модель Vosk",
    )

    logger.info("Скачиваю Vosk: %s", VOSK_MODEL_URL)
    try:
        urllib.request.urlretrieve(VOSK_MODEL_URL, zip_path)
        logger.info("Vosk скачан: %s", zip_path)
    except Exception:
        logger.exception("Не удалось скачать Vosk")
        error("Не удалось скачать модель Vosk. Проверь интернет. Смотри logs\\launcher.log")
        return False

    info("Распаковываю модель Vosk...", "Феникс")
    logger.info("Распаковываю Vosk")
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.namelist():
                parts = member.split("/", 1)
                if len(parts) < 2 or not parts[1]:
                    continue
                target = target_dir / parts[1]
                # Защита от Zip Slip: путь должен оставаться внутри target_dir.
                try:
                    resolved = target.resolve()
                    base = target_dir.resolve()
                    if base not in resolved.parents and resolved != base:
                        logger.warning("Zip Slip попытка: %r", member)
                        continue
                except Exception:
                    logger.warning("Не удалось проверить путь: %r", member)
                    continue

                if member.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, open(target, "wb") as dst:
                        dst.write(src.read())
        zip_path.unlink(missing_ok=True)
        logger.info("Vosk распакован: %s", target_dir)
        info("Модель Vosk готова. OK", "Феникс")
        return True
    except Exception:
        logger.exception("Ошибка распаковки Vosk")
        error("Не удалось распаковать модель. Логи: logs\\launcher.log")
        return False


# ============================================================
# Ollama: проверка, поиск
# ============================================================

def check_ollama_running(logger) -> bool:
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/version", timeout=2):
            logger.info("Ollama сервер отвечает")
            return True
    except Exception:
        return False


def find_ollama_exe(logger) -> Path | None:
    found = shutil.which("ollama") or shutil.which("ollama.exe")
    if found:
        logger.info("Ollama в PATH: %s", found)
        return Path(found)

    candidates = [Path(p) for p in OLLAMA_SEARCH_PATHS]
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(Path(local_appdata) / "Programs" / "Ollama" / "ollama.exe")

    for cand in candidates:
        if cand.exists():
            logger.info("Ollama найден: %s", cand)
            return cand
    return None


def handle_ollama(logger) -> None:
    """Проверяет Ollama. Если нет — предлагает поставить."""
    if check_ollama_running(logger):
        return

    ollama_exe = find_ollama_exe(logger)
    if ollama_exe:
        logger.info("Ollama найден, запускаю serve")
        try:
            subprocess.Popen(
                [str(ollama_exe), "serve"],
                creationflags=CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        except Exception:
            logger.exception("Не удалось запустить ollama serve")

    logger.warning("Ollama не найдена")
    reply = msg_box(
        "Ollama не найдена.\n\n"
        "Без неё Феникс работает в УРЕЗАННОМ режиме:\n"
        "  ✓ Команды\n"
        "  ✓ Распознавание речи\n"
        "  ✓ Синтез речи\n"
        "  ✗ Свободный диалог с ИИ\n"
        "  ✗ Разбор сложных фраз\n\n"
        "Поставить Ollama?\n"
        "(откроется ollama.com/download)",
        "Феникс — Ollama",
        MB_YESNO | MB_ICONQUESTION,
    )
    if reply == IDYES:
        try:
            os.startfile(OLLAMA_DOWNLOAD_PAGE)
        except Exception:
            logger.exception("Не удалось открыть ollama.com")


# ============================================================
# Запуск Феникса
# ============================================================

def run_jarvis(project_dir: Path, pythonw: Path, logger) -> None:
    logger.info("Запускаю Феникс: %s -m jarvis", pythonw)
    try:
        proc = subprocess.Popen(
            [str(pythonw), "-m", "jarvis"],
            cwd=str(project_dir),
            creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
            close_fds=True,
        )
        logger.info("Феникс запущен, PID=%d", proc.pid)
    except Exception:
        logger.exception("Не удалось запустить Феникс")
        error("Не удалось запустить Феникс. Логи: logs\\launcher.log")


# ============================================================
# Главная функция
# ============================================================

def main() -> None:
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
    else:
        exe_dir = Path(__file__).resolve().parent

    log_file = _setup_logging(exe_dir)
    logger = logging.getLogger("launcher")

    logger.info("=" * 60)
    logger.info("Лаунчер стартует")
    logger.info("exe: %s", sys.executable)
    logger.info("cwd: %s", os.getcwd())
    logger.info("log: %s", log_file)
    logger.info("=" * 60)

    if already_running(logger):
        info("Феникс уже запущен.\n\nПроверь панель задач или трей.")
        return

    project_dir = find_project_dir(logger)
    if not (project_dir / "jarvis" / "__init__.py").exists():
        error(
            "Не найден пакет jarvis/ рядом с Феникс.exe.\n\n"
            "Переустанови Феникс. Логи: logs\\launcher.log",
        )
        return

    python_exe = find_python(logger)
    if python_exe is None:
        logger.info("Python не найден, предлагаю установить")
        reply = msg_box(
            "Python 3.10-3.12 не найден.\n\n"
            "Фениксу нужен Python 3.11.\n\n"
            "Сейчас будет скачан официальный установщик Python "
            "(~25 МБ). После скачивания откроется окно установки — "
            "нажми «Install Now».\n\n"
            "Продолжить?",
            "Феникс — нужен Python",
            MB_OKCANCEL | MB_ICONQUESTION,
        )
        if reply != IDOK:
            logger.info("Пользователь отменил установку Python")
            return

        installer = download_python_installer(logger)
        if installer is None:
            return

        if not run_python_installer(installer, logger):
            error(
                "Python не установлен.\n\n"
                "Установи вручную: https://www.python.org/downloads/\n"
                "Затем запусти Феникс.exe снова.",
            )
            return

        python_exe = find_python(logger)
        if python_exe is None:
            error(
                "Python установлен, но не найден.\n\n"
                "Перезапусти Феникс.exe.",
            )
            return
        logger.info("Python после установки: %s", python_exe)

    pythonw = find_venv_pythonw(project_dir, logger)
    if pythonw is None:
        if not create_venv(project_dir, python_exe, logger):
            return
        pythonw = find_venv_pythonw(project_dir, logger)
        if pythonw is None:
            error("venv создан, но pythonw не найден. Логи: logs\\launcher.log")
            return

    if not check_dependencies(project_dir, logger):
        if not install_dependencies(project_dir, logger):
            return

    if not check_vosk_model(project_dir, logger):
        if not download_vosk_model(project_dir, logger):
            return

    handle_ollama(logger)

    run_jarvis(project_dir, pythonw, logger)


if __name__ == "__main__":
    main()
```

### `snapshot.py`

````python
"""Собирает снимок проекта в один SNAPSHOT.md. ... [30 строк]"""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUTPUT = BASE / "SNAPSHOT.md"

# -----------------------------------------------------------------
# Исключения
# -----------------------------------------------------------------

EXCLUDE_DIRS = {
    ".git", "__pycache__",
    ".venv", ".venv311", "venv", "env", "envs",
    "logs", "models", "dist", "build", ".pytest_cache",
    ".idea", ".vscode", "node_modules",
    ".mypy_cache", ".ruff_cache",
    "voices",
    "profiles",       # личные данные - не в снимок
    "sounds",
}

EXCLUDE_FILES = {
    "config.json",
    "system_caps.json",
    "user_profile.json",
    "dialog.json",
    "timers.json",
    "tasks.json",
    "SNAPSHOT.md",        # сам себя не печатаем
    ".gitignore",
    "config.json.lock",
    "user_profile.json.lock",
    "profile.json.lock",
    "PROJECT.md.orig",
}

EXCLUDE_EXT = {
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".exe", ".bin",
    ".onnx", ".wav", ".mp3", ".zip", ".7z", ".rar",
    ".jpg", ".jpeg", ".png", ".gif", ".ico", ".bmp",
    ".tmp", ".lock", ".log",
}

TEXT_EXT = {
    ".py", ".md", ".txt", ".json", ".bat", ".cmd", ".cfg", ".ini",
    ".yaml", ".yml", ".toml", ".html", ".css", ".js", ".ts",
    ".ps1", ".sh", ".env", ".gitignore", ".iss",
}

MAX_FILE_SIZE = 200 * 1024

# Доки, которые печатаются целиком. Остальные .md в lean-режиме
# заменяются оглавлением: они дублируют PROJECT.md.
DOCS_FULL = {"PROJECT.md"}

# Приоритет для --budget. Что режем первым.
PRIORITY_ORDER = ["pack", "doc", "data", "code"]

# Редакция секретов: ключ с непустым значением.
SECRET_RE = re.compile(
    r'(?i)("[^"\n]*(?:password|passwd|token|api[_-]?key|secret)[^"\n]*"\s*:\s*)"([^"\n]+)"'
)


def redact_secrets(text: str) -> tuple[str, list[str]]:
    """Прячет значения похожие на секреты. Возвращает (текст, что нашлось)."""
    hits: list[str] = []

    def _sub(m: re.Match) -> str:
        value = m.group(2)
        if not value or value in ("***", "null", "sha256:"):
            return m.group(0)
        hits.append(m.group(1)[:60])
        return f'{m.group(1)}"***"'

    return SECRET_RE.sub(_sub, text), hits


def fence_for(content: str) -> str:
    """Длина fence по содержимому: самая длинная серия backticks + 1. ... [3 строк]"""
    longest = max((len(m) for m in re.findall(r"`+", content)), default=0)
    return "`" * max(3, longest + 1)


# -----------------------------------------------------------------
# Сбор файлов
# -----------------------------------------------------------------

def should_skip_dir(path: Path) -> bool:
    name = path.name
    if name in EXCLUDE_DIRS:
        return True
    # .venvXXX / venvXXX / envXXX
    if name.startswith((".venv", "venv", "env")) and len(name) <= 12:
        return True
    return False


def should_skip_file(path: Path) -> bool:
    if path.name in EXCLUDE_FILES:
        return True
    if path.suffix.lower() in EXCLUDE_EXT:
        return True
    try:
        if path.stat().st_size > MAX_FILE_SIZE:
            return True
    except OSError:
        return True
    return False


def collect_files(root: Path) -> list[Path]:
    """Все файлы для снимка, отсортированные по приоритету. ... [4 строк]"""
    found: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        if should_skip_file(path):
            continue
        found.append(path)

    def _rank(p: Path) -> tuple[int, str]:
        rel = p.relative_to(root).as_posix()
        if rel == "PROJECT.md":
            return (0, rel)
        if rel.startswith("jarvis/"):
            return (1, rel)
        if rel.startswith(("scripts/", "tests/")):
            return (2, rel)
        if p.suffix == ".py":
            return (3, rel)
        if p.suffix in (".json", ".bat", ".cmd", ".iss", ".yml"):
            return (4, rel)
        if p.suffix == ".md":
            return (6, rel)
        return (5, rel)

    return sorted(found, key=_rank)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="cp1251")
        except Exception:
            return ""
    except Exception:
        return ""


def count_lines(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def kind_of(path: Path) -> str:
    """Категория для приоритета: code / data / pack / doc."""
    suffix = path.suffix.lower()
    if suffix == ".py":
        return "code"
    if suffix in (".json", ".bat", ".cmd", ".iss", ".yml", ".yaml"):
        return "pack" if path.parent.name == "packs" else "data"
    if suffix == ".md":
        return "doc"
    return "data"



# -----------------------------------------------------------------
# Слой 2: смысл из кода, через ast
# -----------------------------------------------------------------

def _sig(node) -> str:
    """Сигнатура функции через ast.unparse (Python 3.9+)."""
    try:
        args = ast.unparse(node.args)
    except Exception:
        return "(...)"
    args = re.sub(r"\s+", " ", args).strip()
    if len(args) > 110:
        args = args[:107] + "..."
    return f"({args})"


def _list_literal(node) -> str:
    """Распаковывает return [...] в элементы одной строкой. ... [4 строк]"""
    if not isinstance(node, ast.Return) or not isinstance(node.value, ast.List):
        return ""
    items = []
    for el in node.value.elts:
        try:
            items.append(ast.unparse(el))
        except Exception:
            continue
    if not items:
        return ""
    joined = ", ".join(items)
    return joined if len(joined) <= 220 else joined[:217] + "..."


def extract_meaning(path: Path) -> list[str]:
    """Сигнатуры, константы, порядок pipeline, точки входа. ... [3 строк]"""
    src = read_text(path)
    if not src:
        return []
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [f"  !! СИНТАКСИС СЛОМАН: {e.msg} (строка {e.lineno})"]

    out: list[str] = []

    doc = ast.get_docstring(tree)
    if doc:
        out.append(f"  # {doc.strip().splitlines()[0][:110]}")

    has_main = False
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    out.append(f"  {target.id} = ...")
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            if isinstance(target, ast.Name) and target.id.isupper():
                out.append(f"  {target.id}: ...")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_") and node.name != "__init__":
                continue
            kw = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            # Ищем return [...] по всему телу: body[0] почти всегда
            # докстринг, и на нём _list_literal молча ничего не находил.
            literal = ""
            for stmt in node.body:
                literal = _list_literal(stmt)
                if literal:
                    break
            if literal:
                out.append(f"  {kw} {node.name}{_sig(node)} -> [{literal}]")
            else:
                out.append(f"  {kw} {node.name}{_sig(node)}")
        elif isinstance(node, ast.ClassDef):
            bases = ""
            if node.bases:
                try:
                    bases = "(" + ", ".join(ast.unparse(b) for b in node.bases) + ")"
                except Exception:
                    bases = "(...)"
            out.append(f"  class {node.name}{bases}")
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if sub.name.startswith("_") and sub.name != "__init__":
                        continue
                    kw = "async def" if isinstance(sub, ast.AsyncFunctionDef) else "def"
                    out.append(f"    {kw} {sub.name}{_sig(sub)}")
                elif isinstance(sub, ast.AnnAssign):
                    target = sub.target
                    if isinstance(target, ast.Name) and target.id.isupper():
                        out.append(f"    {target.id}: ...")
        elif isinstance(node, ast.If):
            try:
                if ast.unparse(node.test) == '__name__ == "__main__"':
                    has_main = True
            except Exception:
                pass

    if has_main:
        out.append("  >>> ТОЧКА ВХОДА (__main__)")
    if "ft.run(" in src:
        out.append("  >>> GUI: ft.run(...) - Flet в главном потоке")
    return out


def collapse_docstrings(src: str, max_lines: int = 3) -> str:
    """Сворачивает докстринги длиннее max_lines в одну строку. ... [4 строк]"""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src

    spans: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.body:
            continue
        first = node.body[0]
        if not (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            continue
        if first.end_lineno - first.lineno + 1 <= max_lines:
            continue
        doc = first.value.value.strip()
        head = (doc.splitlines()[0] if doc else "").replace('"""', "'''")[:90]
        spans.append((first.lineno, first.end_lineno, head))

    if not spans:
        return src

    lines = src.splitlines()
    # С конца - иначе поедут номера строк
    for start, end, head in sorted(spans, reverse=True):
        indent = re.match(r"\s*", lines[start - 1]).group(0)
        lines[start - 1:end] = [f'{indent}"""{head} ... [{end - start} строк]"""']

    return "\n".join(lines) + ("\n" if src.endswith("\n") else "")



# -----------------------------------------------------------------
# Слои снимка
# -----------------------------------------------------------------

def build_tree(files: list[Path], root: Path) -> str:
    """Дерево проекта. У файлов — сколько строк."""
    tree: dict = {}
    for p in files:
        parts = p.relative_to(root).parts
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = p

    def render(node: dict, indent: str = "") -> list[str]:
        out: list[str] = []
        items = sorted(node.items(), key=lambda x: (x[1] is not None, x[0].lower()))
        for name, sub in items:
            if sub is None:
                out.append(f"{indent}├── {name}")
            elif isinstance(sub, Path):
                out.append(f"{indent}├── {name}  ({count_lines(sub)} стр)")
            else:
                out.append(f"{indent}├── {name}/")
                out.extend(render(sub, indent + "│   "))
        return out

    return "\n".join(render(tree))


def section_code(files: list[Path], root: Path, mode: str,
                 budget_kb: float | None,
                 secrets: list[str]) -> list[str]:
    """Слой 4: полный текст кода и данных."""
    out: list[str] = []
    used = 0.0
    limit = budget_kb * 1024 if budget_kb else None

    for p in files:
        rel = p.relative_to(root).as_posix()
        suffix = p.suffix.lower()
        kind = kind_of(p)

        if suffix not in TEXT_EXT and suffix != "":
            out.append(f"### `{rel}`\n")
            out.append(f"_Нетекстовый файл: {suffix or 'без расширения'}_\n")
            continue

        text = read_text(p)
        if not text:
            continue

        # PROJECT.md уже напечатан слоем 0 — второй раз не нужен
        if p.name == "PROJECT.md":
            continue

        # lean: докстринги сворачиваем. Полный текст .md печатаем только
        # в --full / --include-docs, иначе он дублирует PROJECT.md.
        if kind == "code":
            if mode in ("lean", "full-docs"):
                text = collapse_docstrings(text)
        elif kind == "doc" and p.name not in DOCS_FULL:
            if mode not in ("full", "full-docs"):
                continue

        text, hits = redact_secrets(text)
        secrets.extend(f"{rel}: {h}" for h in hits)

        size = len(text.encode("utf-8"))
        if limit is not None and used + size > limit and out:
            out.append(f"### `{rel}`\n")
            out.append(f"_ОБРЕЗАНО по бюджету {budget_kb:.0f} КБ. "
                       f"Полный файл — в репозитории._\n")
            break
        used += size

        fence = fence_for(text)
        lang = {
            ".py": "python", ".md": "markdown", ".json": "json",
            ".bat": "batch", ".cmd": "batch", ".iss": "ini",
            ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
            ".ps1": "powershell", ".sh": "bash",
        }.get(suffix, "")

        out.append(f"### `{rel}`")
        out.append("")
        out.append(fence + lang)
        out.append(text.rstrip())
        out.append(fence)
        out.append("")

    return out


def section_docs(files: list[Path], root: Path) -> list[str]:
    """Для .md, которых нет в слое 4: только оглавление."""
    out: list[str] = []
    for p in files:
        if p.suffix.lower() != ".md" or p.name in DOCS_FULL:
            continue
        rel = p.relative_to(root).as_posix()
        headings = [ln.strip() for ln in read_text(p).splitlines()
                    if ln.startswith("#")]
        out.append(f"#### `{rel}` — {len(headings)} заголовков, "
                   f"полный текст не включён (дублирует PROJECT.md)")
        out.append("")
        for h in headings[:40]:
            level = len(h) - len(h.lstrip("#"))
            out.append(f"{'  ' * max(0, level - 1)}- {h.lstrip('# ')}")
        out.append("")
    return out



def build_snapshot(mode: str, budget_kb: float | None) -> tuple[str, list[str]]:
    """Собирает весь текст снимка. Возвращает (текст, найденные секреты)."""
    files = collect_files(BASE)
    secrets: list[str] = []

    digest = hashlib.sha256()
    total_bytes = 0
    total_lines = 0
    by_kind: dict[str, list[Path]] = {}
    for p in files:
        digest.update(p.relative_to(BASE).as_posix().encode())
        digest.update(b"\0")
        try:
            digest.update(p.read_bytes())
            total_bytes += p.stat().st_size
        except OSError:
            pass
        total_lines += count_lines(p)
        by_kind.setdefault(kind_of(p), []).append(p)

    code_files = [p for p in files if p.suffix == ".py"]
    L: list[str] = []

    L.append("# SNAPSHOT проекта «Феникс»")
    L.append("")
    L.append(f"`sha256={digest.hexdigest()[:16]}` · режим `{mode}` · "
             f"файлов `{len(files)}` · строк `{total_lines}` · "
             f"источник `{total_bytes / 1024:.0f} КБ`")
    L.append("")
    L.append("> Генерируется `snapshot.py`. Вывод детерминированный: "
             "содержимое меняется только когда меняются файлы.")
    L.append(">")
    L.append("> **Начинай с раздела 0 — PROJECT.md.** Там инварианты, правила "
             "и история ошибок. Дальше карта, смысл из кода, потом сам код.")
    L.append("")
    L.append("---")
    L.append("")

    # --- Слой 0: источник правды ---
    L.append("## 0. PROJECT.md — что это, как устроено, чего нельзя делать")
    L.append("")
    project_md = BASE / "PROJECT.md"
    if project_md.exists():
        text = read_text(project_md)
        text, hits = redact_secrets(text)
        secrets.extend(f"PROJECT.md: {h}" for h in hits)
        fence = fence_for(text)
        L.append(fence)
        L.append(text.rstrip())
        L.append(fence)
    else:
        L.append("_PROJECT.md отсутствует. Это источник правды — "
                 "создайте его, иначе снимок теряет смысловой слой._")
    L.append("")
    L.append("---")
    L.append("")

    # --- Слой 1: карта ---
    L.append("## 1. Карта проекта")
    L.append("")
    L.append("```")
    L.append(BASE.name + "/")
    L.append(build_tree(files, BASE))
    L.append("```")
    L.append("")

    # --- Слой 2: смысл из кода ---
    if mode != "signatures":
        L.append("## 2. Смысл из кода (сигнатуры, константы, порядок)")
        L.append("")
        for p in code_files:
            meaning = extract_meaning(p)
            if not meaning:
                continue
            L.append(f"**`{p.relative_to(BASE).as_posix()}`**")
            L.append("")
            L.append("```")
            L.extend(meaning)
            L.append("```")
            L.append("")

    # --- Слой 3: индекс ---
    L.append("## 3. Индекс кода")
    L.append("")
    L.append("| Файл | Строк | Категория | О чём модуль |")
    L.append("|---|---:|---|---|")
    for p in code_files:
        rel = p.relative_to(BASE).as_posix()
        about = ""
        try:
            doc = ast.get_docstring(ast.parse(read_text(p)))
            about = (doc or "").strip().splitlines()[0] if doc else ""
        except Exception:
            about = ""
        about = about.replace("|", "/")[:70]
        L.append(f"| `{rel}` | {count_lines(p)} | {kind_of(p)} | {about} |")
    L.append("")

    # --- Слой 4: код ---
    L.append("---")
    L.append("")
    L.append("## 4. Код и данные")
    L.append("")
    if mode == "signatures":
        L.append("_Режим `--signatures`: код не печатается. "
                 "Запустите без флага, чтобы получить полный текст._")
        L.append("")
    else:
        L.extend(section_code(files, BASE, mode, budget_kb, secrets))

    extra = section_docs(files, BASE)
    if extra:
        L.append("## 5. Документация (только оглавления)")
        L.append("")
        L.extend(extra)

    stats = ", ".join(f"{k}: {len(v)}" for k, v in sorted(by_kind.items()))
    L.append("---")
    L.append("")
    L.append(f"_Итого по категориям — {stats}. Режим `{mode}`._")
    L.append("")

    return "\n".join(L), secrets



def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Собирает SNAPSHOT.md для Феникса.")
    ap.add_argument("--full", action="store_true",
                    help="полный текст доков и докстрингов (как старая версия)")
    ap.add_argument("--signatures", action="store_true",
                    help="только PROJECT.md + карта + смысл + индекс, без кода")
    ap.add_argument("--include-docs", action="store_true",
                    help="в lean вернуть полный текст .md")
    ap.add_argument("--budget-kb", type=float, default=None,
                    help="ограничить размер, резать с менее важного")
    ap.add_argument("--check", action="store_true",
                    help="сравнить с имеющимся SNAPSHOT.md и не записывать")
    ap.add_argument("--out", default=None, help="путь вместо SNAPSHOT.md")
    return ap.parse_args(argv)


def drift_reason(content: str, path: Path) -> list[str]:
    """Что изменилось относительно файла на диске. Для --check. ... [5 строк]"""
    if not path.exists():
        return ["файла нет — нужно сгенерировать"]
    disk = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if disk == content:
        return []

    def _head(text: str, key: str) -> str:
        m = re.search(rf"{key}\s*`([^`]+)`", text)
        return m.group(1) if m else "?"

    reasons = [
        f"sha256: на диске {_head(disk, 'sha256')} -> сейчас {_head(content, 'sha256')}",
        f"файлов:  на диске {_head(disk, 'файлов')} -> сейчас {_head(content, 'файлов')}",
    ]
    return reasons


def main() -> int:
    args = parse_args()
    out_path = Path(args.out) if args.out else OUTPUT

    if args.signatures:
        mode = "signatures"
    elif args.full:
        mode = "full"
    else:
        mode = "lean"

    if args.include_docs and mode == "lean":
        mode = "full-docs"

    print(f"Снимок проекта: {BASE}")
    print(f"Режим: {mode}")

    content, secrets = build_snapshot(mode, args.budget_kb)

    if secrets:
        print(f"ВНИМАНИЕ: похоже на секреты, отредактировано ({len(secrets)}):")
        for s in secrets[:10]:
            print(f"  - {s}")

    if args.check:
        reasons = drift_reason(content, out_path)
        if not reasons:
            print("CHECK: актуален")
            return 0
        print("CHECK: УСТАРЕЛ — перегенерируйте")
        for r in reasons:
            print(f"  - {r}")
        return 1

    out_path.write_text(content, encoding="utf-8")
    size_kb = out_path.stat().st_size / 1024
    print(f"Готово: {out_path}")
    print(f"Размер: {size_kb:.1f} КБ, строк: {content.count(chr(10)) + 1}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
````

### `test_intents.py`

```python
"""Автотест Феникса без микрофона. ... [17 строк]"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Принудительно UTF-8 для stdout/stderr — иначе на CI (Windows, cp1252)
# падает UnicodeEncodeError при печати русских букв.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)
LOG_FILE = LOGS_DIR / "test_intents.log"

log = logging.getLogger("jarvis.test")
log.setLevel(logging.INFO)

_fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

_fh = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
_fh.setFormatter(_fmt)
log.addHandler(_fh)

_ch = logging.StreamHandler()
_ch.setFormatter(_fmt)
log.addHandler(_ch)


# =================================================================
# Setup / teardown для тестов, которым нужно особое окружение.
# Возвращают (setup, teardown), либо None.
#
# ВАЖНО: работаем с config._data напрямую (в памяти), НЕ через config.set().
# Иначе пароль пользователя уйдёт на диск — если тест упадёт между
# setup и teardown, пароль потеряется.
# =================================================================

def _no_password_setup(handler):
    """Временно выставить danger_password = "" в памяти."""
    handler._saved_password = handler.config._data.get("danger_password", "")
    handler.config._data["danger_password"] = ""


def _no_password_teardown(handler):
    """Вернуть пароль как было — в памяти, без записи на диск."""
    saved = getattr(handler, "_saved_password", "")
    handler.config._data["danger_password"] = saved
    handler._saved_password = ""


def _with_password_setup(handler):
    """Временно выставить danger_password = 'test_password_123' в памяти."""
    handler._saved_password = handler.config._data.get("danger_password", "")
    handler.config._data["danger_password"] = "test_password_123"


# teardown — тот же, что у _no_password_teardown


# (name, cmd, expected, requires_llm, requires_network, hooks)
# hooks: None или (setup_fn, teardown_fn).
TESTS = [
    # === Режимы (без LLM, без сети) ===
    ("mode_set_llm",        "режим ии",                   ["Режим", "ИИ"],          False, False, None),
    ("mode_query",          "какой режим",                ["Сейчас режим"],         False, False, None),
    ("mode_set_combo",      "обычный режим",              ["комбинированный"],      False, False, None),
    ("mode_set_commands",   "режим команды",              ["только команды"],       False, False, None),
    ("mode_restore",        "обычный режим",              ["комбинированный"],      False, False, None),

    # === Голоса (быстрые правила, без LLM) ===
    ("voice_list",          "какой голос",                ["голос"],                False, False, None),
    ("voice_switch_irina",  "смени голос на ирину",       ["Irina", "ирина"],       False, False, None),
    ("voice_switch_ruslan", "смени голос на руслан",      ["Ruslan", "руслан"],     False, False, None),

    # === Паки (быстрые правила, без LLM) ===
    ("packs_list",          "какие паки",                 ["Доступны"],             False, False, None),
    ("packs_unload",        "выгрузи пак игр",            ["выгружен", "уже", "не активен", "загружен"], False, False, None),
    ("packs_load",          "загрузи пак игр",            ["загружен", "уже", "не найден"], False, False, None),

    # === Буфер (без LLM, без сети) ===
    ("clipboard_read",      "что в буфере",               ["буфере", "пуст"],       False, False, None),
    ("clipboard_clear",     "очисти буфер",               ["Буфер"],                False, False, None),

    # === Погода ===
    ("weather_ask_city",    "какая погода",               ["городе"],               False, False, None),
    ("weather_answer_city", "Казань",                     ["Запомнил"],             False, True,  None),
    ("weather_default",     "какая погода",               ["Погода", "Казань"],     False, True,  None),
    ("weather_other_city",  "погода в нижнем новгороде",  ["Погода", "Новгород"],   True,  True,  None),
    ("weather_tomorrow",    "погода в питере на завтра",  ["Погода", "Петербург"],  True,  True,  None),

    # === Курс (требует сеть) ===
    ("currency_usd",        "курс доллара",               ["Доллар"],               False, True,  None),
    ("currency_byn",        "курс белорусского рубля",    ["рубл"],                 False, True,  None),
    ("currency_all",        "курс валют",                 ["ЦБ", "Доллар"],         False, True,  None),

    # === Small talk (без LLM, без сети) ===
    ("small_talk_how",      "как дела",                   [],                       False, False, None),
    ("small_talk_time",     "который час",                ["Сейчас"],               False, False, None),
    ("small_talk_date",     "какое сегодня число",        ["Сегодня"],              False, False, None),
    ("small_talk_who",      "кто ты",                     ["Феникс"],               False, False, None),

    # === Скриншот, сайт (без сети — только открытие URL, не загрузка) ===
    ("screenshot",          "сделай скриншот",            ["Скриншот"],             False, False, None),
    ("open_site",           "открой ютуб",                ["Ютуб", "youtube"],      False, False, None),

    # === Системные (раскладка, громкость, яркость) ===
    # На CI нет звуковой карты/монитора → «Не смог узнать». Локально → значение.
    ("layout_query",        "какая раскладка",            ["раскладк", "Не смог"],  False, False, None),
    ("volume_query",        "какая громкость",            ["Громкость", "Не смог"], False, False, None),
    ("brightness_query",    "какая яркость",              ["Яркость", "Не смог"],   False, False, None),

    # === Диагностика (Н2 + Н3) ===
    ("debug_what_heard",    "что ты слышал",              ["фразы", "слышал", "Пока ничего"], False, False, None),
    ("debug_why_not",       "почему не понял",            ["Фраза", "нечего", "диагност"],    False, False, None),

    # === Отмена (Н1) ===
    ("undo_ne_to",          "не то",                      ["Нечего", "Откатываю", "Вернул", "Переключил", "Действие"], False, False, None),
    ("undo_otmeni",         "отмени",                     ["Нечего", "Откатываю", "Вернул", "Переключил", "Действие"], False, False, None),

    # === Пароль (2.13) ===
    # danger_no_password: setup ставит пароль пустым — команда уходит в profile.delete.
    ("danger_no_password",  "удали профиль тест",
     ["не найден", "активен", "удалён"],
     False, False, (_no_password_setup, _no_password_teardown)),

    # danger_with_password: setup ставит пароль — команда уходит в _ask_password.
    ("danger_with_password", "удали профиль тест",
     ["пароль"],
     False, False, (_with_password_setup, _no_password_teardown)),

    # === Learning (5.3) ===
    ("learn_fact",          "запомни: мой город Казань",  ["Запомнил"],              False, False, None),
    ("learn_fact_query",    "что ты обо мне знаешь",      ["Казань", "Знаю"],        False, False, None),
    ("learn_correction",    "это не то, я сказал логи",   ["Понял", "запомнил", "Что было"], False, False, None),
]


class Result:
    def __init__(self, name, cmd, reply_text, expected, elapsed):
        self.name = name
        self.cmd = cmd
        self.reply_text = reply_text
        self.expected = expected
        self.elapsed = elapsed
        # error инициализируем ДО _check(): иначе тест с исключением
        # не отличить от обычного, а _check() читает self.error.
        self.error = None
        self.passed = self._check()

    def _check(self):
        # Тест с исключением не может быть «пройден», даже если ожиданий нет.
        # Иначе small_talk_how с expected=[] молча съедал TypeError
        # из finalize_stream и харнес рапортовал зелёный.
        if self.error is not None:
            return False
        if not self.reply_text:
            return False
        if not self.expected:
            return True
        text = str(self.reply_text).lower()
        return any(e.lower() in text for e in self.expected)

    def __str__(self):
        mark = "OK  " if self.passed else "FAIL"
        return f"[{mark}] {self.name:24s} ({self.elapsed:5.2f} с) «{self.cmd}»"


def build_handler(use_llm=False, reset_profile=True):
    """Собирает IntentHandler. ... [5 строк]"""
    from jarvis.config import load_config
    from jarvis.apps import build_apps
    from jarvis.intents import IntentHandler

    log.info("Загрузка конфига...")
    config = load_config(BASE_DIR)

    if reset_profile:
        from jarvis import profile
        if profile.forget("default_city"):
            log.info("Профиль: default_city сброшен для чистого прогона")
        else:
            log.info("Профиль: default_city уже отсутствовал")

    brain = None
    if use_llm:
        from jarvis.brain import Brain
        model = config.get("llm_model", "qwen2.5:7b-instruct")
        url = config.get("ollama_url", "http://127.0.0.1:11434")
        log.info("Инициализация LLM: %s", model)
        brain = Brain(model, url)
        if not brain.available:
            log.warning("LLM недоступна — работаем только с правилами")
            brain = None
        else:
            log.info("Ждём прогрева LLM (10 с)...")
            time.sleep(10)

    log.info("Сборка IntentHandler...")
    return IntentHandler(config, build_apps(config), brain)


def reset_handler_state(handler):
    """Сбрасывает stateful-состояние между тестами. ... [7 строк]"""
    handler._pending_password = None
    handler._reset_requested = False


def run_one(handler, speaker, name, cmd, expected, hooks=None):
    log.info("─" * 70)
    log.info("ТЕСТ: %s | команда: %r", name, cmd)

    # Чистое состояние перед каждым тестом
    reset_handler_state(handler)

    setup, teardown = hooks if hooks else (None, None)
    if setup:
        try:
            setup(handler)
        except Exception:
            log.exception("setup не удался для %s", name)

    t0 = time.time()
    try:
        reply = handler.handle(cmd)
        if reply.is_stream:
            reply_text = "".join(reply.stream)
            handler.finalize_stream(reply_text)
        else:
            reply_text = reply.text
    except Exception as e:
        log.exception("Исключение в тесте %s", name)
        r = Result(name, cmd, f"<EXCEPTION: {e}>", expected, time.time() - t0)
        r.error = str(e)
        if teardown:
            try:
                teardown(handler)
            except Exception:
                log.exception("teardown не удался для %s", name)
        return r

    elapsed = time.time() - t0

    if teardown:
        try:
            teardown(handler)
        except Exception:
            log.exception("teardown не удался для %s", name)

    if speaker is not None and reply_text:
        try:
            speaker.speak(reply_text)
        except Exception:
            log.exception("Ошибка озвучки")

    r = Result(name, cmd, reply_text, expected, elapsed)
    log.info("Ответ: %s", str(reply_text)[:200])
    log.info("Результат: %s", "OK" if r.passed else f"FAIL (ожидалось: {expected})")
    return r


def main():
    parser = argparse.ArgumentParser(description="Автотест Феникса")
    parser.add_argument("--llm", action="store_true",
                        help="Использовать LLM (нужна Ollama)")
    parser.add_argument("--voice", action="store_true",
                        help="Озвучивать ответы")
    parser.add_argument("--network", action="store_true",
                        help="Запускать тесты, требующие сеть (погода, курс)")
    parser.add_argument("-k", "--filter",
                        help="Фильтр по имени теста")
    args = parser.parse_args()

    log.info("=" * 70)
    log.info("АВТОТЕСТ ФЕНИКСА")
    log.info("LLM: %s | Сеть: %s | Озвучка: %s",
             "вкл" if args.llm else "выкл",
             "вкл" if args.network else "выкл",
             "вкл" if args.voice else "выкл")
    log.info("Лог: %s", LOG_FILE)
    log.info("=" * 70)

    handler = build_handler(use_llm=args.llm)

    speaker = None
    if args.voice:
        try:
            from jarvis.tts import Speaker
            speaker = Speaker(handler.config)
        except Exception:
            log.exception("Speaker не завёлся — без озвучки")

    tests = TESTS
    if args.filter:
        f = args.filter.lower()
        tests = [t for t in tests if f in t[0].lower()]
        log.info("Фильтр %r: %d тестов", args.filter, len(tests))

    results = []
    skipped = []
    t_start = time.time()
    for entry in tests:
        # entry — 6 полей: (name, cmd, expected, requires_llm, requires_network, hooks)
        name, cmd, expected, requires_llm, requires_network, hooks = entry
        if requires_llm and not args.llm:
            log.info("ПРОПУСК %s (требует --llm)", name)
            skipped.append(f"{name} (--llm)")
            continue
        if requires_network and not args.network:
            log.info("ПРОПУСК %s (требует --network)", name)
            skipped.append(f"{name} (--network)")
            continue
        r = run_one(handler, speaker, name, cmd, expected, hooks)
        results.append(r)

    total = time.time() - t_start
    passed = [r for r in results if r.passed]
    failed = [r for r in results if not r.passed]

    log.info("")
    log.info("=" * 70)
    log.info("ИТОГ: %d / %d пройдено за %.1f с", len(passed), len(results), total)
    if skipped:
        log.info("Пропущено: %d — %s", len(skipped), ", ".join(skipped))
    log.info("=" * 70)

    for r in results:
        log.info(str(r))

    if failed:
        log.info("")
        log.info("ПРОВАЛЫ:")
        for r in failed:
            log.info("  %s", r.name)
            log.info("    команда: %r", r.cmd)
            log.info("    ответ:   %s", str(r.reply_text)[:200])
            log.info("    ждали:   %s", r.expected)
            if r.error:
                log.info("    ошибка:  %s", r.error)

    log.info("")
    log.info("Полный лог: %s", LOG_FILE)
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
```

### `test_uia_dump.py`

```python
"""Дамп дерева UIA активного окна браузера. ... [4 строк]"""

from jarvis import uia
import uiautomation as auto


def dump_tree(ctrl, depth=0, max_depth=8):
    if depth > max_depth:
        return
    try:
        ctype = ctrl.ControlTypeName
        cname = (ctrl.Name or "").strip()
        # Показываем только «интересное»: Edit, Document, Tab, Button.
        if ctype in ("EditControl", "DocumentControl", "TabItemControl",
                     "TabControl", "ButtonControl", "ToolBarControl"):
            name_short = cname[:80] if cname else ""
            print(f"{'  ' * depth}[{ctype}] {name_short!r}")
        for child in ctrl.GetChildren():
            dump_tree(child, depth + 1, max_depth)
    except Exception:
        pass


print("Ищу браузер...")
browser = uia.find_browser_window()
if browser is None:
    print("Браузер не найден.")
    raise SystemExit(1)

print(f"Окно: {browser.Name}")
print()
print("Дерево UIA (только Edit/Document/Tab/Button):")
print("-" * 60)
dump_tree(browser)
print("-" * 60)
```

### `test_uia_manual.py`

```python
"""Ручная проверка UIA в браузере — без хардкода конкретного браузера."""

import time
from jarvis import uia

print("=" * 60)
print("UIA — ручная проверка")
print("=" * 60)

# 1. Список всех видимых окон.
print()
print("[1] Видимые окна системы:")
windows = uia.list_windows()
for i, w in enumerate(windows[:20], 1):
    print(f"    {i:2}. {w}")

# 2. Запущенные браузеры.
print()
print("[2] Запущенные браузеры:")
browsers = uia.list_browsers()
for exe, human in browsers:
    print(f"    - {human} ({exe})")

# 3. Найти окно браузера.
print()
print("[3] Ищу окно браузера...")
browser = uia.find_browser_window()
if browser is None:
    print("    НЕ найдено.")
else:
    print(f"    нашёл: {browser.Name}")

    # 4. Активировать и ждать.
    print()
    print("[4] Активирую + жду 1.0 сек...")
    try:
        browser.SetActive()
        browser.SetFocus()
        time.sleep(1.0)  # ← было 0.5, увеличили
        print("    ок")
    except Exception as e:
        print(f"    ошибка: {e}")

    # 5. Данные.
    print()
    print("[5] Читаю данные:")
    print("    URL:  ", uia.read_browser_url() or "(пусто)")
    print("    TAB:  ", uia.read_browser_tab_title() or "(пусто)")
    print("    TABS: ", uia.read_browser_tabs() or "(пусто)")

print()
print("=" * 60)
```

### `.github/workflows/test.yml`

```yaml
# ============================================================
# GitHub Actions: автоматическая проверка при каждом push.
#
# Что делает:
#   1. Поднимает виртуалку с Windows.
#   2. Ставит Python 3.11.
#   3. Ставит лёгкие зависимости (requirements-ci.txt).
#   4. Проверяет синтаксис (check_syntax.py).
#   5. Гоняет pytest (tests/).
#   6. Гоняет test_intents.py (без LLM, без сети, без озвучки).
#
# Где смотреть результат:
#   На GitHub → вкладка "Actions" → последний запуск.
#
# Файл лежит в: .github/workflows/test.yml
# ============================================================

name: tests

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

jobs:
  test:
    runs-on: windows-latest
    timeout-minutes: 15

    # PYTHONUTF8=1 — включает UTF-8 mode интерпретатора.
    # Страховка от UnicodeEncodeError в cp1252-консоли GitHub Actions.
    # В коде тоже есть reconfigure — здесь глобально на весь job.
    env:
      PYTHONUTF8: "1"
      PYTHONIOENCODING: "utf-8"

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install dependencies
        run: pip install -r requirements-ci.txt

      - name: Check syntax
        run: python check_syntax.py

      - name: Unit tests (pytest)
        run: python -m pytest tests/ -q

      - name: Intent tests (без LLM, без сети, без озвучки)
        run: python test_intents.py
```

### `check_all.bat`

```batch
@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title Проверка Феникса

echo ============================================================
echo   Проверка проекта Феникс
echo ============================================================
echo.

cd /d "%~dp0"
call .venv311\Scripts\activate.bat

set FAILED=0

REM =====================================================================
REM 1. Синтаксис
REM =====================================================================
echo [1/3] Проверка синтаксиса...
echo.
python check_syntax.py
if errorlevel 1 (
    echo.
    echo   [!!] Синтаксис сломан
    set FAILED=1
) else (
    echo.
    echo   [OK] Синтаксис в порядке
)
echo.
echo ------------------------------------------------------------
echo.

REM =====================================================================
REM 2. pytest
REM =====================================================================
echo [2/3] Юнит-тесты (pytest)...
echo.
python -m pytest tests/ -q
if errorlevel 1 (
    echo.
    echo   [!!] Тесты упали
    set FAILED=1
) else (
    echo.
    echo   [OK] Тесты прошли
)
echo.
echo ------------------------------------------------------------
echo.

REM =====================================================================
REM 3. test_intents
REM =====================================================================
echo [3/3] Интент-тесты (test_intents.py)...
echo   Это может занять до 30 секунд.
echo.
python test_intents.py
if errorlevel 1 (
    echo.
    echo   [!!] Интент-тесты упали — смотри logs\test_intents.log
    set FAILED=1
) else (
    echo.
    echo   [OK] Интент-тесты прошли
)
echo.

REM =====================================================================
REM Итог
REM =====================================================================
echo ============================================================
if "!FAILED!"=="1" (
    echo   ЕСТЬ ОШИБКИ
    echo ============================================================
    echo.
    echo   Что смотреть:
    echo     1. Выше — какой шаг упал
    echo     2. logs\errors.log
    echo     3. logs\test_intents.log
    echo.
) else (
    echo   ВСЁ РАБОТАЕТ
    echo ============================================================
    echo.
)

pause
```

### `check_syntax.bat`

```batch
@echo off
rem №98: cd /d "%~dp0" вместо хардкода C:\jarvis.
rem Теперь скрипт работает, даже если проект перемещён.
cd /d "%~dp0"
call .venv311\Scripts\activate.bat
python check_syntax.py
pause
```

### `cmds/open_terminal.bat`

```batch
@echo off
cd /d C:\jarvis
cmd
```

### `cmds/show_ip.bat`

```batch
@echo off
ipconfig
pause
```

### `config.example.json`

```json
{
  "wake_words": [
    "феникс",
    "финикс",
    "феникса",
    "fenix",
    "phoenix",
    "джарвис",
    "jarvis"
  ],
  "observer_enabled": true,
  "tts_backend": "auto",
  "xtts_ref": "voices/jarvis.wav",
  "tts_voice": "ruslan",
  "tts_voice_quality": "medium",
  "voice_rate": 1.15,
  "voice": "Pavel",
  "music_app": "яндекс музыка",
  "music_wait_sec": 6,
  "dialog_window_sec": 20,
  "sample_rate": 16000,
  "input_device": null,
  "mic_check_sec": 20,
  "mic_watchdog_enabled": true,
  "command_window_sec": 8,
  "mode": "combo",
  "barge_enabled": true,
  "active_packs": [],
  "timers_file": "timers.json",
  "tasks_file": "tasks.json",
  "memory_file": "dialog.json",
  "memory_max": 100,
  "llm_context_messages": 20,
  "weather_cache_ttl_sec": 600,
  "danger_password": "",
  "gui_enabled": true,
  "gui_theme": "Системная",
  "gui_x": null,
  "gui_y": null,
  "tray_enabled": true,
  "launch_mode": "gui",
  "use_whisper": true,
  "whisper_model": "deepdml/faster-whisper-large-v3-turbo-ct2",
  "whisper_device": "auto",
  "use_llm": true,
  "llm_model": "qwen2.5:7b-instruct",
  "ollama_url": "http://127.0.0.1:11434",
  "prompt_level": "auto",
  "llm_temperature": 0.7,
  "llm_timeout": 45.0,
  "app_paths": {},
  "custom_commands": [],

  "celebration_enabled": false,
  "celebration_triggers": [],
  "celebration_short_text": "Поздравляю! С днём рождения!",
  "celebration_long_text": "Поздравляю с днём рождения! Здоровья, счастья и удачи!",
  "celebration_sound_1_plays": 2,
  "celebration_sound_2_plays": 3,
  "celebration_duration_1": 6.0,
  "celebration_duration_2": 10.0
}
```

### `create_shortcut.bat`

```batch
@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title Ярлык Феникса

echo ============================================================
echo   Создание ярлыка Феникса на рабочем столе
echo ============================================================
echo.

cd /d "%~dp0"

REM Целевой файл — Феникс.exe в корне проекта
set "TARGET=%~dp0Феникс.exe"

if not exist "%TARGET%" (
    echo   ОШИБКА: Феникс.exe не найден в корне проекта.
    echo.
    echo   Сначала собери его: python scripts\build_exe.py
    echo.
    pause
    exit /b 1
)

set "ICON=%TARGET%"

echo   Цель:    %TARGET%
echo   Иконка:  %ICON%
echo.

powershell -NoProfile -Command ^
    "$ws = New-Object -ComObject WScript.Shell;" ^
    "$sc = $ws.CreateShortcut([System.IO.Path]::Combine([Environment]::GetFolderPath('Desktop'), 'Феникс.lnk'));" ^
    "$sc.TargetPath = '%TARGET%';" ^
    "$sc.IconLocation = '%ICON%';" ^
    "$sc.Description = 'Феникс — голосовой ассистент';" ^
    "$sc.WorkingDirectory = '%~dp0';" ^
    "$sc.Save()"

if errorlevel 1 (
    echo.
    echo   ОШИБКА: не удалось создать ярлык.
    pause
    exit /b 1
)

echo ============================================================
echo   Ярлык создан на рабочем столе: Феникс.lnk
echo ============================================================
echo.
pause
```

### `install.bat`

```batch
@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title Установка Феникса

echo ============================================================
echo   Феникс — установка
echo ============================================================
echo.

cd /d "%~dp0"

REM =====================================================================
REM 1. Проверка Python 3.10-3.12
REM =====================================================================
echo [1/11] Проверка Python — нужен 3.10-3.12...

where py >nul 2>nul
if errorlevel 1 (
    echo.
    echo   Python Launcher py.exe не найден.
    echo.
    echo   Установи Python 3.11.9:
    echo     https://www.python.org/downloads/release/python-3119/
    echo   При установке отметь:
    echo     - Add python.exe to PATH
    echo     - Install launcher for all users
    echo.
    pause
    exit /b 1
)

py -3.11 --version >nul 2>nul
if errorlevel 1 (
    echo.
    echo   Python 3.11 не найден.
    echo.
    echo   Установи Python 3.11.9:
    echo     https://www.python.org/downloads/release/python-3119/
    echo.
    echo   ВАЖНО: Python 3.13/3.14 НЕ подходит.
    echo   Vosk 0.3.45 падает с access violation в libvosk.dll.
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('py -3.11 --version 2^>^&1') do set PYVER=%%v
echo   Найден Python %PYVER% через py -3.11
echo.

REM =====================================================================
REM 2. Создание .venv311
REM =====================================================================
echo [2/11] Создание виртуального окружения .venv311...

if exist ".venv311\Scripts\python.exe" (
    echo   .venv311 уже существует, использую его.
) else (
    echo   Создаю .venv311...
    py -3.11 -m venv .venv311
    if errorlevel 1 (
        echo   ОШИБКА: не удалось создать .venv311.
        pause
        exit /b 1
    )
    echo   .venv311 создан.
)
echo.

REM =====================================================================
REM 3. Активация venv
REM =====================================================================
echo [3/11] Активация .venv311...
call .venv311\Scripts\activate.bat
if errorlevel 1 (
    echo   ОШИБКА: не удалось активировать .venv311.
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set VENVVER=%%v
echo   Активен Python %VENVVER% из .venv311
echo.

REM =====================================================================
REM 4. Обновление pip
REM =====================================================================
echo [4/11] Обновление pip...
python -m pip install --upgrade pip
if errorlevel 1 (
    echo   ОШИБКА: не удалось обновить pip.
    pause
    exit /b 1
)
echo   pip обновлён.
echo.

REM =====================================================================
REM 5. Python-зависимости из requirements.txt
REM =====================================================================
echo [5/11] Установка зависимостей из requirements.txt...
echo   Это может занять 5-15 минут.
echo.
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo   ОШИБКА: не удалось установить зависимости.
    echo   Проверь requirements.txt или скинь лог автору.
    pause
    exit /b 1
)
echo.
echo   Зависимости установлены.
echo.

REM =====================================================================
REM 6. eSpeak NG
REM =====================================================================
echo [6/11] Проверка eSpeak NG — нужен для Piper TTS...
where espeak-ng >nul 2>nul
if errorlevel 1 (
    if exist "C:\Program Files\eSpeak NG\espeak-ng.exe" (
        echo   eSpeak NG найден в C:\Program Files\eSpeak NG
    ) else (
        echo.
        echo   eSpeak NG не найден. Без него Piper не заведётся.
        echo.
        set /p INSTALL_ESPEAK="Установить eSpeak NG сейчас? y/n: "
        if /i "!INSTALL_ESPEAK!"=="y" (
            echo   Устанавливаю через winget...
            winget install --id eSpeak-NG.eSpeak-NG -e --accept-source-agreements --accept-package-agreements
            if errorlevel 1 (
                echo.
                echo   Не удалось установить автоматически.
                echo   Скачай вручную: https://github.com/espeak-ng/espeak-ng/releases
                start https://github.com/espeak-ng/espeak-ng/releases
                pause
            ) else (
                echo   eSpeak NG установлен.
            )
        ) else (
            echo   Пропускаю. Поставишь позже.
        )
    )
) else (
    echo   eSpeak NG найден.
)
echo.

REM =====================================================================
REM 7. Ollama
REM =====================================================================
echo [7/11] Проверка Ollama — для LLM-диалога...
where ollama >nul 2>nul
if errorlevel 1 (
    echo.
    echo   Ollama не установлена.
    echo   Без неё Феникс работает только на правилах.
    echo.
    set /p INSTALL_OLLAMA="Установить Ollama сейчас? y/n: "
    if /i "!INSTALL_OLLAMA!"=="y" (
        echo   Устанавливаю через winget...
        winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
        if errorlevel 1 (
            echo   Не удалось. Скачай вручную: https://ollama.com/download
            pause
        )
    ) else (
        echo   Пропускаю. Поставишь позже: winget install Ollama.Ollama
    )
) else (
    echo   Ollama найдена.
)
echo.

REM =====================================================================
REM 8. Выбор модели LLM
REM =====================================================================
where ollama >nul 2>nul
if errorlevel 1 (
    echo [8/11] Ollama не установлена — пропускаю выбор модели.
    echo.
    goto skip_model
)

echo [8/11] Выбор модели для LLM.
echo.
echo   ============================================================
echo    Слабые ПК, встроенная графика, 4-8 ГБ RAM, без GPU
echo   ============================================================
echo     1) qwen2.5:0.5b    ~0.5 ГБ RAM   Очень слабо, только тест
echo     2) qwen2.5:1.5b    ~1.5 ГБ RAM   Базовое, для теста
echo     3) qwen2.5:3b      ~3 ГБ RAM     Заметно лучше
echo.
echo   ============================================================
echo    Ноутбуки с дискретной GPU, 8-16 ГБ VRAM
echo   ============================================================
echo     4) qwen2.5:7b      ~5-6 ГБ VRAM  Отличное, рекомендуется
echo     5) qwen2.5:14b     ~10 ГБ VRAM   Максимум для 12 ГБ
echo.
echo   ============================================================
echo    Мощные ПК и серверы, 16+ ГБ VRAM
echo   ============================================================
echo     6) qwen2.5:32b     ~20 ГБ VRAM   Профессиональное
echo     7) qwen2.5:72b     ~40 ГБ VRAM   Только для топовых GPU
echo.
echo   ============================================================
echo    Альтернативные семейства, для русского тоже ок
echo   ============================================================
echo     8) gemma2:2b       ~1.5 ГБ RAM   Быстрая, для слабых ПК
echo     9) gemma2:9b       ~6 ГБ VRAM    Хорошо держит русский
echo    10) llama3.1:8b     ~5 ГБ VRAM    Популярная, многоязычная
echo    11) mistral:7b      ~5 ГБ VRAM    Быстрая, живая
echo.
echo   ============================================================
echo    12) Пропустить — модель уже скачана или не нужна
echo   ============================================================
echo.
echo   Если не знаешь свою видеокарту:
echo     Win+R -> dxdiag -> Enter -> вкладка "Экран"
echo     Смотри "Видеопамять VRAM".
echo.

set /p LLM_CHOICE="Выбери модель 1-12, по умолчанию 4: "
if "!LLM_CHOICE!"=="" set LLM_CHOICE=4

if "!LLM_CHOICE!"=="1"  set LLM_MODEL=qwen2.5:0.5b
if "!LLM_CHOICE!"=="2"  set LLM_MODEL=qwen2.5:1.5b-instruct
if "!LLM_CHOICE!"=="3"  set LLM_MODEL=qwen2.5:3b-instruct
if "!LLM_CHOICE!"=="4"  set LLM_MODEL=qwen2.5:7b-instruct
if "!LLM_CHOICE!"=="5"  set LLM_MODEL=qwen2.5:14b-instruct
if "!LLM_CHOICE!"=="6"  set LLM_MODEL=qwen2.5:32b-instruct
if "!LLM_CHOICE!"=="7"  set LLM_MODEL=qwen2.5:72b-instruct
if "!LLM_CHOICE!"=="8"  set LLM_MODEL=gemma2:2b
if "!LLM_CHOICE!"=="9"  set LLM_MODEL=gemma2:9b
if "!LLM_CHOICE!"=="10" set LLM_MODEL=llama3.1:8b
if "!LLM_CHOICE!"=="11" set LLM_MODEL=mistral:7b
if "!LLM_CHOICE!"=="12" goto skip_model

if not defined LLM_MODEL (
    echo   Некорректный выбор. Ставлю по умолчанию qwen2.5:7b-instruct.
    set LLM_MODEL=qwen2.5:7b-instruct
)

echo.
echo   Проверяю, скачана ли !LLM_MODEL!...
set ALREADY=
for /f "tokens=*" %%m in ('ollama list 2^>nul ^| findstr /C:"!LLM_MODEL!"') do set ALREADY=1
if defined ALREADY (
    echo   Модель уже скачана. Пропускаю.
) else (
    echo   Скачиваю !LLM_MODEL! ... это займёт несколько минут.
    ollama pull !LLM_MODEL!
    if errorlevel 1 (
        echo   Не удалось скачать модель. Попробуй позже: ollama pull !LLM_MODEL!
    ) else (
        echo   Модель !LLM_MODEL! скачана.
    )
)

echo   Обновляю config.json — устанавливаю llm_model = !LLM_MODEL! ...
python scripts\set_llm_model.py "!LLM_MODEL!"
if errorlevel 1 (
    echo   ВНИМАНИЕ: не удалось обновить config.json
)
echo.

goto after_model

:skip_model
echo   Пропускаю скачивание модели.
echo.

:after_model

REM =====================================================================
REM 9. Конфиг, папки
REM =====================================================================
echo [9/11] Настройка конфига и папок...

if not exist "config.json" (
    if exist "config.example.json" (
        copy config.example.json config.json >nul
        echo   Создан config.json из config.example.json
    ) else (
        echo   ВНИМАНИЕ: config.example.json не найден.
    )
) else (
    echo   config.json уже существует, оставляю как есть.
)

if not exist "logs" mkdir logs
if not exist "models" mkdir models
echo   Папки logs/ и models/ готовы.
echo.

REM =====================================================================
REM 10. Проверка возможностей системы
REM =====================================================================
echo [10/11] Проверка возможностей системы.
echo.
python scripts\check_caps.py
echo.

REM =====================================================================
REM 11. Проверка работоспособности
REM =====================================================================
echo [11/11] Проверка работоспособности Феникса.
echo.
echo   Сейчас прогонятся:
echo     - Проверка синтаксиса check_syntax.py
echo     - Юнит-тесты pytest tests/
echo     - Интент-тесты test_intents.py
echo.

set /p RUN_CHECKS="Запустить проверку сейчас? y/n: "
if /i "%RUN_CHECKS%"=="n" goto skip_checks

set CHECK_FAILED=0

REM --- Проверка синтаксиса ---
echo.
echo   --- Проверка синтаксиса ---
python check_syntax.py
if errorlevel 1 (
    echo   ОШИБКА: синтаксис сломан
    set CHECK_FAILED=1
) else (
    echo   OK: синтаксис в порядке
)

REM --- pytest ---
echo.
echo   --- Юнит-тесты pytest ---
python -m pytest tests/ -q
if errorlevel 1 (
    echo   ОШИБКА: тесты упали
    set CHECK_FAILED=1
) else (
    echo   OK: тесты прошли
)

REM --- test_intents ---
echo.
echo   --- Интент-тесты test_intents.py ---
echo   Это может занять до 30 секунд.
python test_intents.py
if errorlevel 1 (
    echo   ОШИБКА: интент-тесты упали — смотри logs\test_intents.log
    set CHECK_FAILED=1
) else (
    echo   OK: интент-тесты прошли
)

echo.
if "!CHECK_FAILED!"=="1" (
    echo ============================================================
    echo   ЕСТЬ ОШИБКИ — смотри выше
    echo ============================================================
    echo.
    echo   Что делать:
    echo     1. Проверь logs\errors.log
    echo     2. Проверь logs\test_intents.log
    echo     3. Скинь эти логи автору
    echo.
) else (
    echo ============================================================
    echo   ВСЁ РАБОТАЕТ
    echo ============================================================
    echo.
)
goto checks_done

:skip_checks
echo   Пропускаю проверку. Запустишь позже вручную:
echo     check_syntax.bat
echo     python -m pytest tests/ -q
echo     python test_intents.py
echo.

:checks_done

REM =====================================================================
REM Финальный экран
REM =====================================================================
echo ============================================================
echo   Установка завершена!
echo ============================================================
echo.
echo   Что дальше:
echo.
echo   1. Проверь микрофон:
echo        .venv311\Scripts\activate.bat
echo        python scripts\mics.py
echo.
echo   2. Запусти Феникса:
echo        start_fenix.bat        — без консоли
echo        start_fenix_debug.bat  — с логами в консоли
echo.
echo   3. Говори "Феникс ..." — и он ответит.
echo.

set /p RUN_MICS="Запустить проверку микрофона сейчас? y/n: "
if /i "%RUN_MICS%"=="y" (
    python scripts\mics.py
)

echo.
pause
```

### `installer.iss`

```ini
; Inno Setup скрипт для Феникса.
;
; Собирает установщик Феникс_Setup.exe:
;   - Копирует всю папку проекта в Program Files\Феникс
;   - Создаёт ярлык в меню Пуск
;   - Создаёт ярлык на рабочем столе (опционально)
;   - Добавляет в автозапуск (опционально)
;
; Сборка:
;   1. Установи Inno Setup: https://jrsoftware.org/isdl.php
;   2. Открой installer.iss в Inno Setup Compiler
;   3. Нажми Build → Build
;
; Результат: dist\Феникс_Setup.exe

#define MyAppName "Феникс"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Phoenix Project"
#define MyAppURL "https://github.com/BobLoTiK/jarvis-fenix"
#define MyAppExeName "Феникс.exe"

[Setup]
AppId={{8E4B3F2A-1A2B-4C5D-9E8F-7A6B5C4D3E2F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={commonappdata}\Phoenix
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=README.md
OutputDir=dist
OutputBaseFilename=Феникс_Setup
SetupIconFile=jarvis\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
WizardImageFile=installer_banner.bmp
WizardSmallImageFile=installer_small.bmp
WizardImageStretch=yes
WizardImageBackColor=$00160E0A
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"; Flags: checkedonce
Name: "autostart"; Description: "Запускать Феникс при старте Windows"; GroupDescription: "Автозапуск:"; Flags: unchecked

[Files]
; Главный exe
Source: "Феникс.exe"; DestDir: "{app}"; Flags: ignoreversion
; Пакет jarvis
Source: "jarvis\*"; DestDir: "{app}\jarvis"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__,*.pyc"
; Паки
Source: "packs\*"; DestDir: "{app}\packs"; Flags: ignoreversion recursesubdirs createallsubdirs
; Скрипты
Source: "scripts\*"; DestDir: "{app}\scripts"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__,*.pyc"
; Конфиг-пример
Source: "config.example.json"; DestDir: "{app}"; Flags: ignoreversion
; Зависимости
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
; Документация
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "ARCHITECTURE.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Ярлык в меню Пуск
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\Удалить {#MyAppName}"; Filename: "{uninstallexe}"
; Ярлык на рабочем столе (если выбран)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Запустить после установки
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Registry]
; Автозапуск (если выбран)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: autostart
```

### `packs/apps.json`

```json
[
  {"phrases": ["открой дискорд", "открой дс"], "action": "open_app:discord", "reply": "Открываю Discord."},
  {"phrases": ["открой телеграм", "открой тг", "открой телегу"], "action": "open_app:telegram", "reply": "Открываю Telegram."},
  {"phrases": ["открой обс", "открой обс студио"], "action": "open_app:obs", "reply": "Открываю OBS Studio."},
  {"phrases": ["открой вс код", "открой вскод", "открой код"], "action": "open_app:code", "reply": "Открываю VS Code."},
  {"phrases": ["открой спотифай", "открой споти"], "action": "open_app:spotify", "reply": "Открываю Spotify."},
  {"phrases": ["открой яндекс музыку"], "action": "open_app:яндекс музыка", "reply": "Открываю Яндекс Музыку."},
  {"phrases": ["открой эпик геймс", "открой эпик"], "action": "open_app:epic", "reply": "Открываю Epic Games."},
  {"phrases": ["открой фотошоп"], "action": "open_app:photoshop", "reply": "Открываю Photoshop."},
  {"phrases": ["открой браузер"], "action": "browser", "reply": "Открываю браузер."},
  {"phrases": ["открой проводник", "открой мой компьютер"], "action": "explorer.exe", "reply": "Открываю проводник."},
  {"phrases": ["открой калькулятор", "открой калк"], "action": "calc.exe", "reply": "Открываю калькулятор."},
  {"phrases": ["открой блокнот"], "action": "notepad.exe", "reply": "Открываю блокнот."},
  {"phrases": ["открой диспетчер задач", "открой таск менеджер"], "action": "taskmgr.exe", "reply": "Открываю диспетчер задач."},
  {"phrases": ["открой настройки", "открой параметры"], "action": "ms-settings:", "reply": "Открываю настройки."},
  {"phrases": ["открой панель управления"], "action": "control.exe", "reply": "Открываю панель управления."},
  {"phrases": ["открой терминал", "открой консоль"], "action": "cmd.exe", "reply": "Открываю терминал."},
  {"phrases": ["открой павершелл", "открой powershell"], "action": "powershell.exe", "reply": "Открываю PowerShell."},
  {"phrases": ["открой часы", "открой будильник"], "action": "ms-clock:", "reply": "Открываю часы."},
  {"phrases": ["открой камеру"], "action": "microsoft.windows.camera:", "reply": "Открываю камеру."}
]
```

### `packs/games.json`

```json
[
  {"phrases": ["запусти доту", "врубай доту"], "action": "steam://rungameid/570", "reply": "Запускаю Доту."},
  {"phrases": ["запусти кс", "врубай кс", "запусти кс2"], "action": "steam://rungameid/730", "reply": "Запускаю CS2."},
  {"phrases": ["запусти сабнатику", "врубай сабнатику"], "action": "steam://rungameid/264710", "reply": "Запускаю Subnautica."},
  {"phrases": ["запусти тарков", "запусти побег из таркова"], "action": "steam://rungameid/270880", "reply": "Запускаю Тарков."},
  {"phrases": ["запусти пабг", "запусти пубг"], "action": "steam://rungameid/578080", "reply": "Запускаю PUBG."},
  {"phrases": ["запусти апекс", "врубай апекс"], "action": "steam://rungameid/1172470", "reply": "Запускаю Apex Legends."},
  {"phrases": ["запусти раст", "врубай раст"], "action": "steam://rungameid/252490", "reply": "Запускаю Rust."},
  {"phrases": ["запусти гта", "запусти гта 5"], "action": "steam://rungameid/271590", "reply": "Запускаю GTA V."},
  {"phrases": ["запусти рдр", "запусти ред дед"], "action": "steam://rungameid/1174180", "reply": "Запускаю Red Dead Redemption 2."},
  {"phrases": ["запусти дум", "врубай дум"], "action": "steam://rungameid/782330", "reply": "Запускаю DOOM Eternal."},
  {"phrases": ["запусти витчер", "запусти ведьмака"], "action": "steam://rungameid/292030", "reply": "Запускаю Ведьмака 3."},
  {"phrases": ["запусти скайрим"], "action": "steam://rungameid/489830", "reply": "Запускаю Skyrim."},
  {"phrases": ["запусти фоллаут 4"], "action": "steam://rungameid/377160", "reply": "Запускаю Fallout 4."},
  {"phrases": ["запусти террарию"], "action": "steam://rungameid/105600", "reply": "Запускаю Terraria."},
  {"phrases": ["запусти стардев"], "action": "steam://rungameid/413150", "reply": "Запускаю Stardew Valley."},
  {"phrases": ["открой стим"], "action": "steam://open/main", "reply": "Открываю Steam."},
  {"phrases": ["открой библиотеку стим"], "action": "steam://open/games", "reply": "Открываю библиотеку Steam."},
  {"phrases": ["открой магазин стим"], "action": "steam://store", "reply": "Открываю магазин Steam."},
  {"phrases": ["открой друзей стим"], "action": "steam://open/friends", "reply": "Открываю друзей."},
  {"phrases": ["открой загрузки стим"], "action": "steam://open/downloads", "reply": "Открываю загрузки Steam."}
]
```

### `packs/sites.json`

```json
[
  {"phrases": ["открой ютуб", "открой youtube"], "action": "https://www.youtube.com", "reply": "Открываю YouTube."},
  {"phrases": ["открой твич", "открой twitch"], "action": "https://www.twitch.tv", "reply": "Открываю Twitch."},
  {"phrases": ["открой гитхаб", "открой github"], "action": "https://github.com", "reply": "Открываю GitHub."},
  {"phrases": ["открой вк", "открой вконтакте"], "action": "https://vk.com", "reply": "Открываю ВКонтакте."},
  {"phrases": ["открой телегу веб", "открой веб телеграм"], "action": "https://web.telegram.org", "reply": "Открываю Telegram Web."},
  {"phrases": ["открой кинопоиск"], "action": "https://www.kinopoisk.ru", "reply": "Открываю Кинопоиск."},
  {"phrases": ["открой хабр", "открой habr"], "action": "https://habr.com", "reply": "Открываю Хабр."},
  {"phrases": ["открой википедию"], "action": "https://ru.wikipedia.org", "reply": "Открываю Википедию."},
  {"phrases": ["открой почту", "открой gmail"], "action": "https://mail.google.com", "reply": "Открываю почту."},
  {"phrases": ["открой яндекс"], "action": "https://ya.ru", "reply": "Открываю Яндекс."},
  {"phrases": ["открой гугл"], "action": "https://www.google.com", "reply": "Открываю Google."},
  {"phrases": ["открой авито"], "action": "https://www.avito.ru", "reply": "Открываю Авито."},
  {"phrases": ["открой озон", "открой ozon"], "action": "https://www.ozon.ru", "reply": "Открываю Ozon."},
  {"phrases": ["открой вайлдберриз", "открой вб"], "action": "https://www.wildberries.ru", "reply": "Открываю Wildberries."},
  {"phrases": ["открой дзен"], "action": "https://dzen.ru", "reply": "Открываю Дзен."},
  {"phrases": ["открой пикабу"], "action": "https://pikabu.ru", "reply": "Открываю Пикабу."},
  {"phrases": ["открой реддит"], "action": "https://www.reddit.com", "reply": "Открываю Reddit."},
  {"phrases": ["открой тикток"], "action": "https://www.tiktok.com", "reply": "Открываю TikTok."},
  {"phrases": ["открой инстаграм"], "action": "https://www.instagram.com", "reply": "Открываю Instagram."},
  {"phrases": ["открой стим комьюнити"], "action": "https://steamcommunity.com", "reply": "Открываю Steam Community."}
]
```

### `packs/system.json`

```json
[
  {"phrases": ["заблокируй компьютер", "заблокируй пк", "залочь пк"], "action": "rundll32.exe user32.dll,LockWorkStation", "reply": "Блокирую компьютер."},
  {"phrases": ["спящий режим", "усни", "сон пк"], "action": "rundll32.exe powrprof.dll,SetSuspendState 0,1,0", "reply": "Ухожу в спящий режим."},
  {"phrases": ["перезагрузи компьютер", "перезагрузка"], "action": "shutdown /r /t 10", "reply": "Перезагружаю через 10 секунд."},
  {"phrases": ["выключи компьютер", "отключи пк"], "action": "shutdown /s /t 10", "reply": "Выключаю через 10 секунд."},
  {"phrases": ["отмени выключение", "отмена выключения"], "action": "shutdown /a", "reply": "Отменяю выключение."},
  {"phrases": ["открой диспетчер устройств"], "action": "devmgmt.msc", "reply": "Открываю диспетчер устройств."},
  {"phrases": ["открой редактор реестра"], "action": "regedit.exe", "reply": "Открываю редактор реестра."},
  {"phrases": ["открой управление дисками"], "action": "diskmgmt.msc", "reply": "Открываю управление дисками."},
  {"phrases": ["покажи ip", "какой у меня ip"], "action": "cmd /k ipconfig", "reply": "Показываю IP."},
  {"phrases": ["покажи процессы", "список процессов"], "action": "cmd /k tasklist", "reply": "Показываю процессы."},
  {"phrases": ["покажи версию винды"], "action": "cmd /k winver", "reply": "Показываю версию Windows."},
  {"phrases": ["открой монитор ресурсов"], "action": "resmon.exe", "reply": "Открываю монитор ресурсов."},
  {"phrases": ["открой службы"], "action": "services.msc", "reply": "Открываю службы."},
  {"phrases": ["открой планировщик задач"], "action": "taskschd.msc", "reply": "Открываю планировщик."},
  {"phrases": ["открой программы и компоненты"], "action": "appwiz.cpl", "reply": "Открываю список программ."}
]
```

### `packs/work.json`

```json
[
  {"phrases": ["открой рабочий стол"], "action": "shell:Desktop", "reply": "Открываю рабочий стол."},
  {"phrases": ["открой загрузки"], "action": "shell:Downloads", "reply": "Открываю загрузки."},
  {"phrases": ["открой документы"], "action": "shell:Personal", "reply": "Открываю документы."},
  {"phrases": ["открой изображения", "открой картинки"], "action": "shell:My Pictures", "reply": "Открываю изображения."},
  {"phrases": ["открой музыку"], "action": "shell:My Music", "reply": "Открываю музыку."},
  {"phrases": ["открой видео"], "action": "shell:My Video", "reply": "Открываю видео."},
  {"phrases": ["открой корзину"], "action": "shell:RecycleBinFolder", "reply": "Открываю корзину."},
  {"phrases": ["открой сеть"], "action": "shell:NetworkPlacesFolder", "reply": "Открываю сеть."},
  {"phrases": ["открой системный диск"], "action": "shell:MyComputerFolder", "reply": "Открываю Этот компьютер."}
]
```

### `start_fenix.bat`

```batch
@echo off
rem cd /d "%~dp0" — работает из любой папки, куда пользователь распаковал проект.
rem Раньше был хардкод "cd /d C:\jarvis" — у пользователей с другим путём не работал.
cd /d "%~dp0"
start "" pythonw -m jarvis
exit
```

### `start_fenix_debug.bat`

```batch
@echo off
title Феникс
cd /d "%~dp0"
echo ============================================
echo  Феникс запускается...
echo  Чтобы выключить — нажми Ctrl+C
echo ============================================
echo.
python -m jarvis
echo.
echo ============================================
echo  Феникс остановлен.
echo  Нажми любую клавишу, чтобы закрыть окно.
echo ============================================
pause >nul
```

### `LICENSE`

```
MIT License

Copyright (c) 2026 BobLoTiK

Portions of this software are derived from the project "jarvis"
by jsays12 (https://github.com/jsays12/jarvis),
used with attribution. Original copyright (c) jsays12.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### `jarvis-fenix.code-workspace`

_Нетекстовый файл: .code-workspace_

### `requirements-ci.txt`

```
# Зависимости для CI (GitHub Actions) и минимального прогона тестов.
#
# Здесь НЕТ:
#   - piper-tts, faster-whisper, sounddevice, vosk, winrt-* — на сервере нет звука
#   - pycaw, screen-brightness-control — тяжёлые, Windows-специфичные
#   - pyautogui, pygetwindow, keyboard, mouse — GUI
#
# Здесь ЕСТЬ только то, что реально импортируется IntentHandler
# и тестами (tests/, test_intents.py).

# --- Утилиты ---
filelock>=3.13
psutil>=5.9
pyperclip>=1.8
Pillow>=10

# --- Тесты ---
pytest>=8.0
pytest-asyncio>=0.23
```

### `requirements-dev.txt`

```
# Зависимости для разработки (не нужны в проде).

# --- Сборка .exe ---
pyinstaller>=6.0

# --- Покрытие тестов ---
pytest-cov>=5.0

# --- Линтеры ---
ruff>=0.4
```

### `requirements.txt`

```
# === Ядро STT ===
vosk>=0.3.45
faster-whisper>=1.2.1
ctranslate2>=4.8.2
sounddevice>=0.5
numpy>=1.26

# === TTS ===
piper-tts>=1.8.0
pyttsx3>=2.99

# === WinRT (для медиа, TTS, уведомлений) ===
winrt-runtime>=3.2
winrt-Windows.Foundation>=3.2
winrt-Windows.Foundation.Collections>=3.2
winrt-Windows.Media.SpeechSynthesis>=3.2
winrt-Windows.Media.Control>=3.2
winrt-Windows.Storage.Streams>=3.2

# === Утилиты ===
filelock>=3.13
psutil>=5.9
pyperclip>=1.8
Pillow>=10
huggingface_hub>=0.20

# === Трей ===
pystray>=0.19

# === Автоматизация Windows ===
pyautogui>=0.9.54
uiautomation>=2.0.29
pygetwindow>=0.0.9
keyboard>=0.13.5
mouse>=0.7.1

# === Громкость / яркость ===
pycaw>=20240210
comtypes>=1.4
screen-brightness-control>=0.22

# === GUI ===
flet>=1.0.3
flet-desktop>=1.0.3

# === Тесты ===
pytest>=8.0
pytest-asyncio>=0.23

# === Опционально: мягкое удаление профиля ===
send2trash>=1.8
```

## 5. Документация (только оглавления)

#### `.github/workflows/README.md` — 3 заголовков, полный текст не включён (дублирует PROJECT.md)

- Workflows
  - test.yml
  - Как добавить новый workflow

#### `ARCHITECTURE.md` — 45 заголовков, полный текст не включён (дублирует PROJECT.md)

- 🏗 Архитектура «Феникс»
  - 📑 Содержание
  - 🗂 Два корня путей
    - Fallback для `PROGRAM_DIR`
    - В `USER_DIR` также живут
  - 🗺 Карта модулей
  - 🔄 Поток обработки фразы
  - 🎓 Онбординг (первый запуск)
  - 👁 Observer (фоновое извлечение фактов)
  - 🎭 Персона
  - 💗 Mood
  - 🖥 UIA
  - ⚡ Реестр быстрых обработчиков
  - 👤 Универсальный профиль (`set_profile` / `get_profile`)
  - 🖼 GUI (Flet 1.0.3)
    - Режим запуска
    - Трей (отключён)
    - Темы GUI
    - Подписки GUI
    - Вкладка «Микрофон»
    - Салют (праздничный)
    - Иконка окна
  - 👥 Мультипрофиль
  - ⚙️ Поток конфига
  - 🌤 Погода и курс валют
  - 📂 Открытие файлов в редакторе
  - 📦 Пак-команды с аргументами
  - 🚀 Лаунчер (`Феникс.exe`)
  - 🧩 Ключевые объекты
  - 💾 Файлы данных
  - 🌐 Внешние зависимости
  - 🧪 Тесты
  - 🏗 Инфраструктура
    - `.venv311`
    - Git
    - `commit.bat`
  - 📦 Сборка и установка
    - `scripts/make_icon.py`
    - `scripts/make_installer_images.py`
    - `scripts/build_exe.py`

#### `CHANGELOG.md` — 38 заголовков, полный текст не включён (дублирует PROJECT.md)

- Changelog
  - 📑 Содержание
  - 🚧 [Unreleased] — 0.4.0
    - 📅 Сессия 10.10.2026
      - ✨ Добавлено
        - 🧹 Технический долг (ТД)
        - 🎭 Mood — эмоциональное состояние ассистента
        - 🖥 UIA — управление окнами Windows
        - 🎉 Праздничные триггеры — в config
      - 🐛 Исправлено
  - 📅 Сессия 10.10.2026
      - ✨ Добавлено
        - 📋 PROJECT.md — источник правды
        - 🧰 snapshot.py — переписан
      - 🔧 Исправлено (аудит 10.10.2026)
    - 📅 Сессия 09.10.2026
      - ✨ Добавлено
        - 🎭 Персона — `jarvis/persona.py`
        - 🎓 Онбординг через LLM-диалог
        - 👁 Observer — `jarvis/observer.py`
        - 🎨 Красивый установщик — Inno UI
        - 🛡 Защита от BOM и кракозябр
      - 🔧 Исправлено
    - 📅 Сессия 08.10.2026
      - ✨ Добавлено
        - 🎉 Поздравление с ДР — `jarvis/celebrations.py`
        - 🔍 Аудит Kimi — 25 багов
    - 📅 Сессия 07.10.2026
      - 🔧 Исправлено
      - ✨ Добавлено
  - 🌙 [0.3.0] — 2026-10-06 (вечерняя)
    - ✨ Добавлено
    - 🔧 Исправлено
    - 🔄 Изменено
  - 🌆 [0.2.2] — 2026-10-05
    - ✨ Добавлено
    - 🔧 Исправлено
  - 📦 [0.2.1] и раньше

#### `CI.md` — 13 заголовков, полный текст не включён (дублирует PROJECT.md)

- CI — что это и как с ним жить
  - 🎯 Что такое CI
  - 📁 Где лежит
  - 🔍 Что делает
  - 🚀 Как смотреть результат
  - 🔧 Если упало
  - 📦 requirements-ci.txt
  - ➕ Как добавить шаг
  - 🎨 Бейдж в README
  - 📋 Что проверять **локально** перед пушем
  - 🆕 Пути в CI
  - 🎯 Автоматизация релизов (в планах)
  - 📌 Полезное

#### `CONTRIBUTING.md` — 32 заголовков, полный текст не включён (дублирует PROJECT.md)

- Как контрибьютить в Феникс
  - 🎯 Главное правило
  - 📁 Структура
  - 📝 Правила кода
  - 🔒 Правила безопасности
  - 🚀 Рабочий процесс
    - 1. Правка
    - 2. Проверка синтаксиса
    - 3. Тесты
    - 4. Обновление SNAPSHOT
    - 5. Коммит
  - 🎨 Стиль
    - Комментарии
- Per-call stop-token: каждый вызов создаёт свой Event.
- Иначе старый поток не завершится, и будет 2-3 голоса одновременно.
- создаём токен
    - Имена
    - Логи
  - 🧪 Тесты
    - Что писать
    - Чего не делать
  - ⚠️ Частые ошибки
  - 📦 Как добавить новый интент
    - 1. Быстрое правило (без LLM)
    - 2. Через LLM
  - 📦 Как добавить новый пак
  - 📦 Как добавить свою фразу
  - 📦 Как добавить новый TTS-голос
  - 🚨 Если что-то сломалось
  - 📋 Чек-лист перед коммитом
  - 🤝 Как задавать вопросы
  - 🎯 Философия

#### `PLAN.md` — 73 заголовков, полный текст не включён (дублирует PROJECT.md)

- 📋 План развития «Феникс»
  - 🎯 ФИЛОСОФИЯ ПРОЕКТА
  - 📊 СВОДКА
  - ✅ СЕССИЯ 09.10.2026 — Inno UI + Персона + Observer + Онбординг
    - Inno UI (1)
    - Персона (З2–З4, З6)
    - Онбординг через LLM-диалог (З1, З5, З7)
    - Observer
    - Фиксы
  - ✅ СЕССИЯ 08.10.2026 — Поздравление + Аудит Kimi
    - Поздравление с ДР (1)
    - Аудит Kimi — 25 багов
  - ✅ СЕССИЯ 07.10.2026 — Релиз v1.0.0
    - Релиз и инфраструктура (4)
    - Unicode / пути (2)
    - Автолаунчер + установщик (2)
    - UI/UX (3 из 4)
    - Мелкие фиксы (3)
    - `text_utils.py` (1)
    - Критичный баг Vosk (1)
  - ✅ ПРЕДЫДУЩИЕ СЕССИИ
    - СЕССИЯ 06.10.2026 (вечерняя)
  - 🚧 ФАЗА 1 — НАШИ ФИЧИ (+ AIRI-концепции внутри)
    - 🆕 UI/UX (1)
    - 🆕 Красивый установщик (Inno UI) ✅
    - 🆕 Знакомство + Персона + Observer ✅
    - 🆕 Mood (3) ⭐ AIRI-концепция ✅
    - 🆕 UIA — элементы окон (6) ✅
    - 🆕 Silero TTS (3)
    - 🆕 VAD (Silero) — замена Wake-слова (2) ⭐ AIRI-концепция
    - 🆕 Многошаговые сценарии (6)
    - 🆕 Мои команды и сценарии (12)
    - 🆕 Фичи (бесплатные) (13)
    - 🆕 Управление приложениями (6)
    - 🆕 Persistent + Vector memory (RAG) (3) ⭐ AIRI-концепция сразу
    - 🆕 MCP + плагины — ЗАГОТОВКИ (2)
    - 🆕 Telegram + веб (2)
    - 🆕 Визуализация + Спрайт (4) ⭐ AIRI-концепция сразу
    - 🆕 Сборка в `.exe` (PyInstaller) (2)
    - 🆕 CI/релизы (1)

#### `PROMPT.md` — 27 заголовков, полный текст не включён (дублирует PROJECT.md)

- 🤖 ПРОМПТ для LLM — «Феникс»
  - 🎯 Контекст
  - 🎭 Как со мной работать
  - 🚨 Ошибки, которые я уже делал (не повторяй)
  - 🗂 Пути (главное правило)
  - 🏗 Архитектура (кратко)
    - Модули
    - Поток обработки
    - Mood
    - UIA
  - 📋 Режимы работы
    - 🏠 Local
    - 🌐 Hybrid
    - ☁️ Cloud — 🚧 в планах
    - 💎 Premium — ⏸
  - 📊 ТЕКУЩИЙ СТАТУС
    - ✅ Закрыто
    - 🚧 Осталось
  - 🎯 ПОРЯДОК РАБОТЫ
  - 🎯 КЛЮЧЕВЫЕ ПРАВИЛА
    - Код
    - GUI
    - Безопасность
    - Окружение
    - Git
  - 🛠 Как чинить баги
  - 📎 БЫСТРЫЕ ССЫЛКИ

#### `README.md` — 55 заголовков, полный текст не включён (дублирует PROJECT.md)

- 🦅 Феникс
  - 📑 Содержание
  - 🆕 Что добавлено в форке
    - 🧱 Этап 0 — рефакторинг
    - 🗣 Этап 1 — команды
    - 💬 Этап 2 — живой диалог
    - 📨 Этап 3 — Reply + CI
    - 🖥 Этап 4 — системные команды
    - 👥 Этап 5 — мультипрофиль
    - 🎨 Этап 6 — Flet GUI
    - 🔤 Этап 7 — реестр + Unicode-пути
    - 📦 Этап 8 — автолаунчер и установщик
    - 🎉 Этап 9 — поздравление с ДР
    - 🔍 Этап 10 — аудит Kimi (25 багов)
    - 🎭 Этап 11 — Персона, Онбординг, Observer
    - ✨ Этап 12 — красивый установщик (Inno UI)
    - 🧹 Этап 13 — Техдолг
    - 💗 Этап 14 — Mood
    - 🖥 Этап 15 — UIA
    - 🎉 Этап 16 — Праздничные триггеры в config
  - 💻 Требования
  - 📥 Установка
    - 🤖 Автоматическая
    - 🛠 Ручная (для разработки)
  - 🚀 Первый запуск
  - 🎓 Знакомство (первый диалог)
  - 🎭 Персона и стиль общения
  - 💗 Mood (эмоции в моменте)
  - 👁 Observer (фоновое обучение)
  - 🖥 UIA (управление окнами)
  - ⚠️ Возможные проблемы
  - 🖼 GUI (Flet)
  - ⚙️ Режимы работы
  - 🧠 Настройка LLM (Ollama)
  - 📦 Паки команд
  - 👥 Мультипрофиль
  - 💭 Память диалога
  - ↩️ Отмена действий
  - 🔒 Пароль на опасные
  - 🎙 Голоса

---

_Итого по категориям — code: 98, data: 16, doc: 9, pack: 5. Режим `lean`._
