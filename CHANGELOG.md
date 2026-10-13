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
  - [Сессия 13.10.2026](#сессия-13102026)
  - [Сессия 12.10.2026](#сессия-12102026)
  - [Сессия 10.10.2026](#сессия-10102026)
  - [Сессия 09.10.2026](#сессия-09102026)
  - [Сессия 08.10.2026](#сессия-08102026)
  - [Сессия 07.10.2026](#сессия-07102026)
- [0.3.0 — 2026-10-06](#-030--2026-10-06-вечерняя)
- [0.2.2 — 2026-10-05](#-022--2026-10-05)
- [0.2.1 и раньше](#-021-и-раньше)

---

## 🚧 [Unreleased] — 0.4.0

### 📅 Сессия 13.10.2026

#### 🐞 «Закрой вкладку ютуб» — почему вкладка не закрывалась

Три независимые причины, все три — в `jarvis/uia.py`:

- **Русское название против латинского заголовка.** Вкладка называется
  «(2) YouTube», а просят «ютуб» — `"ютуб" in "(2) youtube"` не срабатывало.
  Теперь `title_matches()` сравнивает варианты написания: алиасы сайтов
  (`_SITE_ALIASES`: ютуб → youtube) и транслитерацию («хабр» → habr),
  причём **пословно** — иначе «вк» прилипало к «vkhoda» («без входа») и
  закрывалась чужая вкладка.
- **`uia.ControlTypeName` не существует** (см. PROMPT.md #43): у модуля
  `uiautomation` есть только `ControlTypes`, `ControlTypeNames` и числа
  `ControlType`. Обращение бросало `AttributeError`, он глотался
  `except Exception` внутри обходов дерева — и не находилось **ни одной**
  вкладки. Тип контрола теперь сравнивается строкой у самого контрола
  (`ctrl.ControlTypeName`, хелперы `_is_control_type` / `_is_tab_item` /
  `_is_button` / `_is_menu_item`) — в `jarvis/uia.py` заменены все восемь
  сломанных сравнений.
- **`Invoke()` отдаёт True, ничего не сделав** — и ответ «закрыл» был
  враньём. Теперь `close_browser_tab()` пробует **три** способа и после
  каждого сверяет список вкладок (`_tabs_shrank`): 1) кнопка закрытия
  внутри вкладки; 2) средний клик по вкладке (обычный жест «закрыть
  вкладку»); 3) выбрать вкладку и нажать Ctrl+W. `True` — только если
  вкладка действительно исчезла, иначе честное `False`. Имя вкладки
  читается **до** действий: у закрытой вкладки UIA-элемент мёртв, и
  обращение к `Name` бросает COMError — на этом падал ответ (живой случай,
  теперь под тестом `test_close_browser_tab_survives_vanished_element`).
- **`fast/uia.py`** — Ctrl+W остаётся запасным ходом, но только когда
  список вкладок не читается (`_tabs_unreadable()`). Если список виден,
  вкладку закрывает сам `close_browser_tab`, а второе нажатие закрыло бы
  соседнюю: «ютуб» часто открыт не в одном экземпляре.
- **Тесты:** `tests/test_uia.py` — 39 тестов, `tests/test_uia_fast.py` —
  10; всего в `tests/` — **300** (`check_all.bat` гоняет 300 вместо 277).
  Заглушки в тестах раньше повторяли **сломанный** API (`ControlType` и
  `ControlTypeName` у модуля) и потому молчали о мине — теперь как у
  настоящего `uiautomation` (строка у контрола). Тест
  `test_no_module_level_control_type_name` читает исходник `jarvis/uia.py`
  и не даёт вернуть `uia.ControlTypeName` обратно.
- **`tests/manual/uia_close_probe.py`** — ручной прогон на живом браузере:
  какие вкладки видит UIA, есть ли внутри них кнопка закрытия, и с флагом
  `--close` — реальное закрытие. Dry-run по умолчанию ничего не нажимает.

#### 🧪 Тесты — одна папка, стресс-тест на 100 ситуаций, единый прогон

- **Все проверки собраны в `tests/`.** `test_intents.py` → `tests/test_intents.py`,
  а ручные скрипты (`test_vad_live.py`, `test_vad_debug.py`, `test_uia_dump.py`,
  `test_uia_manual.py`) → `tests/manual/` **без** префикса `test_`: это не тесты,
  а ручные прогоны, и pytest их больше не подхватывает (раньше `test_vad_live.py`
  открывал микрофон и подвешивал `pytest` из корня).
- **`tests/conftest.py`** — `collect_ignore` для `tests/test_intents.py`:
  это скрипт-раннер на своём харнесе, а не pytest-тест (имя сохранено
  историческое — оно упоминается в документации).
- **`tests/stress_intents.py`** — новый стресс-тест: ровно **100 ситуаций**
  (интенты, граничные формы записи, мусор, эмодзи, инъекции в промпт,
  строка на 5000 символов, повторные вызовы) + инварианты «не падает,
  отвечает непустым текстом, укладывается в 5 секунд». В конце —
  «ИТОГ: N / 100» и блок «ПРОВАЛЫ» с причиной по каждой ситуации.
  Тест восстанавливает настройки (режим, память, стиль персоны) и удаляет
  тестовый факт из профиля — следов не остаётся. Лог: `logs/stress_intents.log`.
- **`check_all.bat` (+ `check_all.py`)** — один прогон четырёх шагов
  (синтаксис → pytest → интент-тесты → стресс) с компактным итогом:
  либо «ВСЁ ОТЛИЧНО», либо разбор того, что именно упало, с путями
  к полным логам в `logs/check_all/`. Раньше `check_all.bat` был линейкой
  `if errorlevel` и валил в консоль вывод всех тестов.
- **`tests/README.md`** — карта тестов: что где, как запускать, правила
  для новых тестов (pytest — `test_*.py`, ручное — `manual/` без префикса).
- **`tests/test_intents.py`** — логирование теперь настраивается лениво
  (`setup_logging()`), чтобы импорт харнеса из стресс-теста не обрезал
  `logs/test_intents.log`.

##### 🕐 Время — добавлены естественные формулировки

- **«сколько сейчас времени», «какой сейчас час», «сколько время»,
  «текущее время», «сколько на часах»** — раньше не распознавались
  и уходили в LLM. Нашёл стресс-тест (`tests/stress_intents.py`),
  фикс — `jarvis/intents/fast/small_talk.py`.

#### 🐛 Исправлено

##### 🖥 UIA без библиотеки — понятный отказ вместо «LLM недоступна»

Показал CI: шаг `Stress test` дал **95/100** — все пять провалов были UIA.
Причина: в `requirements-ci.txt` нет `uiautomation`, обработчик падал,
стадия `fast` глотала исключение, и на «какие вкладки открыты» человек
получал «LLM недоступна. Скажите «режим команды»» — понять, что случилось,
было нельзя.

- **`jarvis/uia.py`** — новый `UIAUnavailable(ImportError)` (именно
  наследник, чтобы старый код и тесты продолжали ловить `ImportError`)
  и `is_supported()` — «есть ли библиотека», без обращения к COM.
- **`jarvis/intents/fast/uia.py`** — `uia_fast()` ловит `UIAUnavailable`
  и отвечает «UI Automation недоступна: не установлена библиотека
  uiautomation. Установите её: pip install uiautomation». Ветки, которым
  UIA не нужна («нажми enter», «закрой вкладку эту» — Ctrl+W), работают и
  без библиотеки — поэтому проверяем не вход, а сам вызов UIA. Из логов
  ушли трассировки «Обработчик uia упал».
- **`tests/stress_intents.py`** — ожидания пяти ситуаций `uia_*` зависят
  от окружения (спрашиваем `jarvis.uia.is_supported()`): библиотека есть —
  читаем окна, нет (CI-раннер) — ждём понятный отказ. Набор остаётся ровно
  **100** ситуаций, и в CI теперь тоже 100/100. Плюс у `uia_*` свой потолок
  отзывчивости — 15 секунд вместо 5: они читают реальный рабочий стол,
  и на загруженной машине пяти секунд не хватает (`uia_tabs` один раз
  поймал ложный ПРОВАЛ, пока параллельно молотил `snapshot.py`).
- **`_require_uia()`** — проверка библиотеки ПЕРЕД каждым действием, которое
  требует UIA. На CI нет ни библиотеки, ни запущенного браузера: поиск окна
  отдавал `None` раньше, чем дело доходило до UIA, и команда отвечала «Не
  вижу открытых вкладок. Возможно, активное окно — не браузер» вместо
  честного отказа — стресс-тест ловил это как ПРОВАЛ. Теперь причина отказа
  всегда та, что есть на самом деле.
- **`tests/test_uia.py`** (+4 теста) и **`tests/test_uia_fast.py`** (новый,
  5 тестов) — ветка «библиотеки нет» теперь под тестами, а не только на
  CI: `check_all.bat` гоняет 277 pytest вместо 268. Сценарии новые: браузер
  не запущен (как на раннере) и «нажми enter» без библиотеки — он работает,
  потому что это клавиша, а не UIA.

##### 📦 Установщик (Inno Setup) — доведён до рабочего состояния

- **`installer.iss` не клал `system_caps.json`**, хотя файл читают
  `jarvis/actions.py` (громкость/яркость) и `jarvis/gui.py`. Теперь он в
  поставке — с флагом `skipifsourcedoesntexist` (файл генерируется
  `scripts/check_caps.py`, в git его нет).
- **`LicenseFile=README.md`** — установщик показывал 39 КБ README вместо
  лицензии. Исправлено на `LICENSE` (сам файл тоже добавлен в поставку).
- **`Excludes: "__pycache__,*.pyc"` не исключал папки.** В Inno Setup
  `Excludes` матчится по концу пути, поэтому маска `__pycache__` не
  срабатывала. Теперь `__pycache__\*,*.pyc,*.pyo` — мусор из установщика
  выпал (~1.7 МБ, 113 файлов, 0 `.pyc`).
- Добавлен `CHANGELOG.md` в поставку.
- Добавлен `AppMutex=Local\JarvisPhoenixSingleInstance` — тот же мьютекс,
  что в `launcher.py`: обновление поверх запущенного Феникса корректно
  попросит закрыть приложение.
- Добавлены пустые `models\` и `runtime\` (ASCII-пути из `paths.py`).
- **Пустые `__pycache__` всё равно создавались.** Флаг `createallsubdirs`
  создаёт все подпапки источника, даже если все файлы в них исключены.
  Убран → в установке **0** `__pycache__` (проверено на живой установке).
- **Комментарий в шапке скрипта врал:** там было «Program Files\Феникс», а
  сборка ставится в `C:\ProgramData\Phoenix` (ASCII-путь — требование Vosk/Kaldi).

#### ✨ Добавлено

##### 🛠 `scripts/build_setup.py` — вся сборка одной командой

- Шаги: иконка → баннеры → `system_caps.json` → `Феникс.exe` → `ISCC.exe`.
- `ISCC.exe` ищется в `PATH`, затем в стандартных папках Inno Setup 6.
- Флаг `--run` — сразу запустить собранный установщик.
- Раньше: 4–5 ручных команд + компиляция в GUI Inno Setup.

#### 📦 Сборка

- `Феникс.exe` пересобран: в exe от 06.10 не было `launcher.py` от 08.10.
- `dist\Феникс_Setup.exe` пересобран (Inno Setup 6.7.3, 9.65 МБ).
- Проверено **живой установкой** (`/VERYSILENT /DIR=C:\phoenix-test`): exit 0,
  85/85 `.py` на месте, `packs\`, `scripts\`, `models\`, `runtime\` созданы,
  0 `__pycache__`/`.pyc`, импорт пакета из установки работает, тихая
  деинсталляция удаляет всё подчистую.

#### 🚀 CI — авторелиз по тегу (`release.yml`)

- Новый workflow `.github/workflows/release.yml`: пуш тега `v*` собирает на
  windows-latest `Феникс.exe` + `Феникс_Setup.exe` и создаёт GitHub Release
  (`gh release create --generate-notes`) с двумя вложениями. Любой запуск
  кладёт файлы в артефакты; ручной (Actions → build-release → Run workflow)
  собирает без релиза.
- **Версия из тега.** `v1.0.2` → `build_setup.py --version 1.0.2` →
  `ISCC /DMyAppVersion=1.0.2` → `ProductVersion` установщика. Проверено
  локально: с флагом — `1.0.2`, без флага — дефолт `1.0.0`.
- `installer.iss` — `MyAppVersion` обёрнут в `#ifndef`, дефолт остаётся
  `1.0.0` (= `jarvis.__version__`).
- `scripts/build_setup.py` — флаг `--version X` / `--version=X`; шаг
  `system_caps.json` мягко пропускается, если нет `pycaw` /
  `screen-brightness-control` (на CI-раннере их нет).
- В CI ставятся только `PyInstaller` + `Pillow`: `Феникс.exe` — это
  `launcher.py` на чистой stdlib, зависимости проекта он ставит сам при первом
  запуске (экономия ~2 ГБ и минут на раннере).
- Inno Setup 6 — `choco install innosetup --no-progress -y`; `ISCC.exe`
  появляется в `PATH` (плюс запасной поиск в стандартных папках).
- 8 тестов: `tests/test_build_setup.py` (парсинг версии, `caps_available`,
  контракт «дефолт `installer.iss` = `jarvis.__version__`»).

#### 📝 Документация

- `CI.md` — раздел про релизы: локальная сборка уже автоматизирована
  (`scripts/build_setup.py`), в CI осталось обернуть её в workflow.
- `PLAN.md` — новый раздел «Инсталлятор + сборка (13.10.2026)», статусы
  (1.12 VAD ✅, CI 🚧, инсталлятор ✅), счётчики в сводке.
- `PROJECT.md` — стек сборки, контракт проверки (260 тестов, 32/32 интентов),
  раздел «что дальше» сведён с порядком работ из `PLAN.md`.
- `SNAPSHOT.md` перегенерирован; `check_syntax.py` — 123 файла OK.
- `CI.md` — раздел «Авторелиз — release.yml»: шаги, версия из тега, как выпустить
  релиз (`git tag` + `git push origin`), таблица «если упало».
- `README.md` — бейдж `build-release`, `--version` в примерах сборки, абзац об
  авторелизе, строка «Авторелиз» в таблице технологий.
- `.github/workflows/README.md` — описание `release.yml`; `PLAN.md` — №121 ✅,
  новая сводка «CI-релизы (13.10.2026)», счётчики (~195 / ~83 / ~112).

### 📅 Сессия 12.10.2026

#### 🐛 Исправлено

##### 🔊 VAD (Silero) — починен и сделан адаптивным

- **`jarvis/vad.py` переписан.** Была серия багов, из-за которых VAD
  либо резал тихую речь, либо отключался на обычном микрофоне:
  - **Абсолютный порог RMS 80 резал тихую речь** ещё до калибровки —
    тихий микрофон вообще не мог «договориться»: калибровка и auto-off
    стояли за этим `return False` и были недостижимы. Порог убран,
    решение теперь по нормализованной вероятности Silero.
  - **`_quiet_baseline = 300` отключал VAD почти на любом микрофоне**
    (фон тихой комнаты ~10–100 < 300). Заменено на порог «мёртвого»
    микрофона `_DEAD_MIC_RMS = 1.0` (реальная цифровая тишина).
  - **Адаптивный порог работал наоборот** относительно своего описания.
    Теперь порог зависит от SNR: явно выше фона → ниже, у уровня
    фона → выше (границы 0.30–0.80).
  - **Фон обучается на лету:** калибровка (усреднение N=30) → EMA
    (вниз быстрее, вверх медленнее), всплески речи не задирают фон.
  - **Нормализация** (пик → 3000, gain ≤ ×20) делает Silero почти
    независимым от уровня микрофона: речь ~0.9, шум ~0.1. Без неё
    низкоуровневый шум даёт prob ~0.32 (риск ложных срабатываний).
  - **Крупнейшая причина «резания» речи — неверная подача в ONNX.**
    Silero v5 ожидает `context(64) + chunk(512)` и переносимый `state`
    (как в официальной обёртке `OnnxWrapper`). Прежний код подавал
    только 512 сэмплов — вероятность «проседала» на непрерывной речи.
    На реальной записи JFK recall тихой речи вырос (~0.6 → ~0.9),
    precision остался 1.0.
- **`_find_model()`** ищет модель через `paths.program_dir()`
  (`PROGRAM_DIR/vad/silero_vad.onnx`); захардкоженный
  `C:\ProgramData\Phoenix` оставлен лишь как fallback.
- **Потокобезопасность:** ONNX-state защищён `threading.Lock` —
  `is_speech` (аудио-callback) и `reset()` (flush из основного потока)
  больше не гоняют состояние наперегонки.
- **`tests/test_vad.py`** переписан под новое поведение; 3 падавших
  теста (auto-off на тихом микрофоне, warning, debug-лог) починены.
- **`jarvis/config.py`:** `vad_debug` по умолчанию `False` (был `True` —
  спамил лог на каждый чанк).
- **`config.example.json`:** убраны дубли ключей `prosody_*`, добавлен
  `vad_debug`.

##### ⏱ VAD тормозил ответ — Vosk не видел тишину

- **Корень «долгого ответа» при включённом VAD.** `KaldiRecognizer.
  AcceptWaveform()` завершает фразу по **тишине**. VAD вырезал тишину
  целиком (в Vosk уходили только «речевые» блоки), поэтому Vosk не видел
  паузу и **не отдавал финальный текст** — Феникс отвечал поздно или не
  отвечал вовсе.
- **Замер на реальной речи** (SAPI «Феникс, включи музыку» + комнатный
  шум RMS 40, поток 8 с, блоки 500 мс): VAD OFF — Vosk отдал фразу на
  **5.0 с**; VAD ON — **за весь поток финальной фразы не было** (в Vosk
  ушло 5 из 15 блоков, текст висел только в `PartialResult`).
- **`jarvis/vad.py` → `SpeechHangover`** — «хвост» тишины после речи:
  после последнего речевого блока в Vosk уходит ещё N блоков тишины
  (по умолчанию 1500 мс = 3 × 500 мс), длинная тишина по-прежнему не
  гоняется. Класс без зависимостей (numpy/onnxruntime/sounddevice) —
  тестируется в CI.
- **`jarvis/stt.py`** — `_callback` использует `SpeechHangover`; `flush()`
  сбрасывает и хвост. Исправлен неверный комментарий: `is_speech`
  зовётся из **аудио-callback** (PortAudio-поток), не из listener-потока.
- **`jarvis/config.py` / `config.example.json`** — новый ключ
  `vad_hangover_ms` (`1500`).
- **CPU тут не виноват:** `VAD.is_speech()` на блоке 8000 сэмплов =
  **2.2 мс** (15 чанков × 512 × ONNX, `intra_op_num_threads=1`).
- **`tests/test_speech_gate.py`** — 12 тестов `SpeechHangover`.
- **`scripts/vadbench.py`** — воспроизводимый бенчмарк: синтезирует
  русскую речь (SAPI) + комнатный шум и печатает, на какой секунде Vosk
  отдаёт фразу при `VAD OFF` / `VAD ON h=0` / `VAD ON h=N`.

##### 🖥 GUI — что не доходило до ядра

- **Настройки VAD из GUI не применялись на лету.** Порог, адаптивность и
  «хвост» (`vad_threshold` / `vad_adaptive` / `vad_hangover_ms`) читаются
  ТОЛЬКО при создании VAD, поэтому ползунок писал config.json, а детекция
  работала со старыми значениями до перезапуска. Теперь
  `Listener.reload_vad()` пересоздаёт VAD, а подписчик конфига его зовёт.
- **Смена микрофона требовала перезапуска.** `Listener.set_input_device()`
  помечает смену, `phrases()` сам закрывает и открывает `RawInputStream`
  на новом устройстве (в своём потоке — так безопасно для PortAudio), а
  Vosk-контекст сбрасывается, чтобы фразы не склеились.
- **Список голосов в GUI тянул модель с HF Hub.** `_get_voice_options()`
  падал в `factory._try_create(name, "")`, который создавал НАСТОЯЩИЙ
  движок: Piper — 2.96 с (модель с HF + ONNX), Silero — torch.hub.
  Теперь служебный `voice=""` возвращает лёгкую заглушку с голосами класса
  (`_EngineProbe`): **2.96 с → 0.13 с** и без сети вообще.
- **Позиция окна не запоминалась:** `gui_x` / `gui_y` только читались при
  старте, сохранять их было некому. Теперь пишутся по
  `WindowEventType.MOVED` (одно событие на перетаскивание, не на пиксель).
- **Статус «Слушаю» зависал** после команды из текстового поля — теперь
  возвращается в «Спит».
- **Кнопки, которых не хватало:** «хвост» VAD (`vad_hangover_ms`),
  barge-in, «ждать wake-слово». Все три применяются сразу, без перезапуска.
- **Подписчик конфига вынесен из `main()`** в `make_config_listener()` —
  раньше эту проводку можно было проверить только руками.
- **Тесты на проводку:** `tests/test_gui_wiring.py` (34 теста: каждый
  обработчик → нужный ключ config) и `tests/test_main_wiring.py`
  (ключ config → нужный метод компонента), `tests/test_stt.py` (живое
  применение VAD и смена микрофона).

##### ⚡ Запуск: ~7.3 с → ~1.3 с до появления окна

- **Whisper грузился до показа окна** (large-v3-turbo — 4.05 с на GPU).
  `WhisperTranscriber(..., lazy=True)` + `preload_async()`: модель грузится
  фоном, первый `transcribe()` дожидается загрузки.
- **TTS-движок тоже блокировал старт** (`PiperVoice.load` — 2.3 с).
  `Speaker(config, lazy=True)`: движок грузится фоном, первый `say()` ждёт
  готовности (`_ensure_engine`), `switch_backend` из GUI сериализован с
  фоновой загрузкой одним локом.
- **Приветствие озвучивалось в главном потоке** — окно появлялось только
  после фразы. Теперь приветствие в отдельном потоке.
- **Piper больше не ходит в сеть за закэшированной моделью:**
  `try_to_load_from_cache` вместо `hf_hub_download` (0.00 с против
  0.16–0.36 с на файл; «ruslan/high», которого нет, больше не ищется).
- **`scripts/startup_probe.py`** — замер по этапам: видно, что блокирует
  старт, а что грузится фоном.
- **`pytest.ini`** — `testpaths = tests`. Раньше `pytest` из корня
  подхватывал ручные скрипты (`test_vad_live.py` открывал микрофон).

Замер (этот ПК, `tts_backend=piper`, `use_whisper=true`):

| этап | было | стало |
| --- | --- | --- |
| Whisper (блокировал окно) | 4.05 с | 0 (3.8 с фоном) |
| Speaker / TTS (блокировал окно) | ~3.0 с | 0 (1.6 с фоном) |
| список голосов в GUI | 2.96 с | 0.13 с |
| **до появления окна** | **~7.3 с** | **~1.3 с** |

#### 🆕 Добавлено и исправлено (продолжение сессии)

##### 🧰 Модель VAD качается сама

- **Найдено при аудите:** `silero_vad.onnx` не лежит в репозитории
  (`*.onnx` в `.gitignore`) и его не ставит установщик. На чистой
  установке VAD молча выключался, юзер узнавал об этом только из лога.
- **`jarvis/vad.py`:** `download_model()` / `ensure_model_async()` качают
  модель (2.3 МБ, официальный репозиторий Silero) **в фоне**: пишем в
  `.part` и только потом переименовываем — оборванное скачивание не
  оставит битый файл, который потом «нашёлся» бы поиском. Модель меньше
  `MODEL_MIN_BYTES` не принимается.
- **VAD включается на лету:** фоновый поток по готовности зовёт
  `_on_model_ready()` → сессия ONNX поднимается без перезапуска Феникса.
  Пока модель качается, VAD ничего не режет (иначе потеряли бы речь).
- **`vad_auto_download`** (default `true`) + чекбокс во вкладке «Аудио»:
  на машине без сети скачивание можно запретить; переключение применяется
  на лету (ключ пересоздаёт VAD).
- Живой замер на этом ПК: скачивание 2272 КБ — **0.85 с**, дальше
  «VAD: модель докачана — включаю на лету» → «VAD: Silero ONNX загружен»,
  файл совпал с официальным по SHA256.

##### ⏱ Блок аудио 500 мс → 128 мс (минус ~500 мс к ответу)

- **Было `self._block_size = 8000`** (500 мс): VAD не мог отреагировать
  быстрее 500 мс, а датчик «хвоста» тишины округлялся до 500 мс.
- **Стало 2048 сэмплов (128 мс)** при 16 кГц — кратно 512, Silero считает
  ровно 4 чанка без остатка на полу (раньше из 8000 сэмплов 320 молча не
  доходили до модели). Константа `stt.DEFAULT_BLOCK_MS` — единая точка.
- Barge-in считает мс от реального блока (`_block_ms`), а не `block / 16`.
- `scripts/vadbench.py` больше не хардкодит 8000: размер блока берётся из
  `jarvis.stt` — иначе бенчмарк мерил не то, что происходит в бою.

| режим (замер `scripts/vadbench.py`) | блок 500 мс | блок 128 мс |
| --- | --- | --- |
| VAD OFF (эталон) | 5.0 с | 5.0 с |
| VAD ON, хвост 1500 мс | **5.5 с** | **5.0 с** |

##### 🖥 Трей снова работает (и в нём есть «Выход»)

- **Причина отключения была в порядке запуска, а не в pystray:** иконка
  поднималась после `ft.run`, когда главный поток уже занят Flet'ом.
  Теперь `jarvis/tray.py::start_tray()` поднимает иконку **до** `ft.run`
  в daemon-потоке. Ошибки pystray/PIL не роняют Феникса: нет иконки —
  нет трея, в логе предупреждение. Живьём: иконка в трее через 0.3 с
  после старта Flet, зависаний нет.
- **`prevent_close` выставляется заранее** (`gui.set_tray_active()`):
  в обработчике CLOSE флаг уже опаздывает, окно успевает закрыться.
  Живьём: WM_CLOSE → окно скрыто (`IsWindowVisible=False`), Феникс жив,
  «Открыть окно» возвращает окно. Без трея крестик закрывает как раньше.
- **«Выход» стал настоящим выходом:** `jarvis.shutdown()` ставил только
  `stop_event`, а окно Flet продолжало жить — процесс не завершался, и
  помогал лишь диспетчер задач. `FenixGUI.quit()` снимает `prevent_close`
  и закрывает окно.
- **Новые контролы во вкладке «Настройки»** (ключи были в config, но
  правились только файлом): чекбокс «Иконка в трее» (применяется на
  лету — иконка поднимается/снимается) и список «Режим запуска»
  (`gui` / `tray`).
- `tests/test_tray.py`: пункты меню дёргают ядро и GUI (message loop не
  запускается, иконка в трей не ставится), `start_tray()` не падает без
  pystray.

##### 🔍 Whisper `beam_size`: замерили и оставили как есть

- Whisper расшифровывает каждую команду (проверка wake-слова). Замер на
  этом ПК (GPU, large-v3-turbo, 4 с речи): `beam_size=1` — 0.162 с,
  `2` — 0.184 с, `5` — 0.207 с. Разница ~20 мс, а greedy-декодинг хуже
  по качеству — менять не стали.

##### 🧪 Тесты больше не лезут в сеть и не портят рабочую модель

- `VAD()` без модели уходит качать её в фоне, и тесты этим пользовались:
  фоновое скачивание писало `.part` в `PROGRAM_DIR/vad` и **перезаписало
  рабочую модель** во время прогона. В `tests/test_vad.py` авто-скачивание
  отключено autouse-фикстурой.
- Два теста на «синтетический голос» проверяли абсолютный порог 0.5 и
  падали на официальной модели: она даёт на синтетических гармониках
  prob ≈ 0.41 (шум — ≈ 0.02). Теперь проверяется сам конвейер (порог 0.3
  задаётся явно) плюс инвариант «голос речевее шума/тишины», не зависящий
  от версии модели.
- Итог: **253 теста**, `python -m pytest` — зелёный, без сети и без
  обращения к живому микрофону.

### 📅 Сессия 10.10.2026

#### ✨ Добавлено

##### 🧹 Технический долг (ТД)

- **`intents.py` → пакет `jarvis/intents/`** — распил на ~40 файлов:
  `handler.py`, `context.py`, `verbs.py`, `password.py`, `sites.py`,
  `execute.py`, `stages/` (11 стадий), `fast/` (17 обработчиков).
- **`snapshot.py`** — `system_caps.json` в `EXCLUDE_FILES`.
- **`.gitignore`** — `*.bak*`, `jarvis/intents_old.py`, `system_caps.json`.
- **`jarvis/profile.py`** — warning про `send2trash`
  (не удалять навсегда, если модуля нет).
- **`jarvis/main.py`** — `finalize_stream(full_text)` без лишнего `cmd`.
- **`jarvis/intents/fast/profile.py`** — парсинг «мой город Казань» →
  `("город", "Казань")`, а не `("мой город казань", "да")`.

##### 🎭 Mood — эмоциональное состояние ассистента

- **`jarvis/mood.py`** — состояния `neutral/happy/excited/annoyed/bored/tired`.
- Хранится в `profile.json` → `mood` (`state`, `since`, `reason`).
- Детекция из текста: похвала → `happy`, грубость → `annoyed`,
  радость → `excited`, усталость → `tired`.
- **Приоритет:** `rude` > `tired` > `excited` > `praise`.
- **Decay** — возврат к `neutral` через 5 мин.
- Подписки: `mood.subscribe(cb)`.
- **Влияние на TTS** — `mood.effective_rate()`: `excited` +10%, `tired` -10%.
- **Влияние на GUI** — `mood.color()` для статус-сферы.
- **Влияние на LLM** — `mood.build_prompt_block()` в system prompt.
- **Команды**: «как настроение», «не грусти», «успокойся».
- **`tests/test_mood.py`** — 29 тестов.

##### 🖥 UIA — управление окнами Windows

- **`jarvis/uia.py`** — обёртка над `uiautomation`:
  - `find_browser_window()` — находит любой браузер (Chrome, Edge,
    Яндекс, Opera, Brave, Firefox и др.) **по PID процесса**,
    а не по имени окна.
  - `list_windows()` — все видимые окна (для отладки).
  - `list_browsers()` — запущенные браузеры.
  - `read_browser_tab_title()` — заголовок активной вкладки.
  - `read_browser_tabs()` — список всех вкладок (18+ на Яндексе).
  - `read_browser_url()` — URL адресной строки (с fallback на заголовок).
  - `close_browser_tab(name)` / `switch_browser_tab(name)`.
  - `read_active_text()` — текст активного окна.
  - `click_button(name)` — нажать кнопку по имени.
  - `click_menu_item(path)` — клик по меню («Файл > Сохранить»).
  - `describe_active_window()` / `describe_browsers()` — для отладки.
- **`jarvis/intents/fast/uia.py`** — 10 голосовых команд без LLM.
- **`jarvis/brain.py`** — 9 UIA-actions в `ACTIONS` + промпты
  (SMALL/MEDIUM/LARGE).
- **`jarvis/intents/execute.py`** — 9 UIA-обработчиков + dispatch.
- **`tests/test_uia.py`** — 17 тестов с моками.

**Примеры:**

- «Прочитай окно» → текст активного окна.
- «Какой сайт открыт» → URL (если браузер отдаёт) или заголовок.
- «Какая вкладка» → заголовок.
- «Какие вкладки» → список.
- «Закрой вкладку ютуб» → ищет и закрывает.
- «Переключись на вкладку хабр» → активирует.
- «Нажми OK» → ищет кнопку.
- «Что открыто» → активное окно.

##### 🎉 Праздничные триггеры — в config

- **`jarvis/celebrations.py`** — триггеры и текст из `config.json`.
- По умолчанию `celebration_enabled: false` — **не срабатывает
  без настройки**.
- Ключи: `celebration_enabled`, `celebration_triggers`,
  `celebration_short_text`, `celebration_long_text`,
  `celebration_sound_1_plays`, `celebration_sound_2_plays`,
  `celebration_duration_1`, `celebration_duration_2`.
- **`config.example.json`** — блок `celebration_*` в конце.

#### 🐛 Исправлено

- **`tests/test_uia.py`** — `uia.ControlTypeName` → строки
  (`"TabItemControl"`, `"ButtonControl"`).
- **`jarvis/intents/__init__.py`** — `IntentHandler` из `handler.py`.
- **`jarvis/intents/stages/password.py`** — «удали профиль X»
  обрабатывается **до** `fast`-реестра (иначе `tasks_fast` перехватывает).
- **`jarvis/intents/fast/__init__.py`** — `screenshot` добавлен в реестр
  (был в pipeline напрямую, при распиле забыли перенести).

---

## 📅 Сессия 10.10.2026

#### ✨ Добавлено

##### 📋 PROJECT.md — источник правды

- **`PROJECT.md`** (~200 строк) — курируемый файл, заменяющий дубли в
  `README` / `ARCHITECTURE` / `PROMPT` / `CONTRIBUTING` / `PLAN`.
- `snapshot.py` печатает его **первым разделом**, а остальные `.md`
  в lean-режиме не печатает вовсе (только оглавления).

##### 🧰 snapshot.py — переписан

- Слои: `0 PROJECT.md` → `1 карта` → `2 смысл из кода` → `3 индекс` → `4 код`.
- **Смысл из кода** через `ast`: сигнатуры, `UPPER_CASE`-константы,
  фактический порядок `build_pipeline()` и `build_registry()`, точки входа.
- **fence по содержимому**: раньше файл с внутренними ``` заворачивался в
  ```` ```markdown ````, внешний fence закрывался раньше времени, и половина
  дампа рендерилась как код.
- **Детерминированный вывод**: `sha256` в шапке вместо timestamp. Файл
  больше не «грязный» в git, когда ничего не менялось.
- **Guard на секреты**: `password|token|api_key|secret` с непустым
  значением редактируется в `***`.
- Режимы: lean (по умолчанию), `--full`, `--signatures` (~40 КБ),
  `--include-docs`, `--budget-kb N`, `--check`, `--out`.
- `EXCLUDE_FILES` почищен от мусора (`ft.Control`, `None`, `python`, `str`).

#### 🐛 Погода — падежи городов

- **`weather.normalize_city()`** — словарь 70+ русских городов
  в родительном/дательном/предложном/винительном падежах.
- **`_strip_city_noise()`** — отсекает «на завтра», «сегодня»
  из захваченного regex города.
- **Гибрид:** словарь → LLM (если не нашлось) → `default_city`.
- `test_intents.py --llm --network` — **39/39** (было 37/39).

**Примеры:**

| Фраза | До | После |
|---|---|---|
| «погода в нижнем новгороде» | отвечал про Казань (default_city) | «Нижний Новгород: 10°C, преимущественно ясно» |
| «погода в питере на завтра» | отвечал про Казань | «Санкт-Петербург завтра: от 6 до 9, лёгкая морось» |

#### 🔧 Исправлено (аудит 10.10.2026)

| Что | Где |
|---|---|
| `finalize_stream(cmd, text)` — арность не сходилась, `--llm` падал с `TypeError` | `test_intents.py` |
| Тест с `expected=[]` проходил при исключении — дыра в харнесе | `test_intents.py` `Result._check` |
| `_on_profile_switch` не существовал → GUI не был подписан на профиль | `gui.py` |
| Пересборка UI теряла вкладку «Персона»: `_tabs` из 3 вместо 4 | `gui.py` `_rebuild_ui_for_theme` |
| `_tabs[idx]` → `KeyError`, вкладка молча не переключалась | `gui.py` `_on_nav_change` |
| Мёртвый код + вызов отсутствующей `first_run.after_first_command()` | `main.py` |
| `packs/work.json` — хардкод `C:\jarvis`, неверные пути, перебивал `paths.py` | `packs/work.json` |
| `normalize()` съедал точки: домены открывались как `gismeteoru.ru` | `actions.guess_site`, `execute._do_open_site`, `actions.normalize_url` |
| `say()` звался из таймеров/watchdog/celebrations без лока → резал речь | `main.py` `_say_lock` |
| Профиль читался с диска на каждый `get()`, включая `mood.effective_rate()` на каждом предложении | `profile.py` кэш в памяти |
| `Path.home()` вопреки правилу проекта | `paths.user_home()` + 4 файла |
| Две карты папок с разным поведением, мёртвый `_USER_FOLDERS` | `actions.py`, `files.py` |
| `llm_timeout` захардкожен 20 с — на 14b молча падал в «не понял» | `config.py`, `brain.py` |
| `verify_password` — не constant-time | `hmac.compare_digest` |
| `ACTIONS` ↔ `_DISPATCH` рассинхрон: мёртвые `debug_*`, недостижимые `clipboard_*` | `brain.py` |
| `num2words` — мёртвая зависимость | оба `requirements` |
| `check_syntax.py` не проверял `tests/` | `check_syntax.py` |
| Дрейф `command_window_sec` (9 vs 8) | `config.example.json` |
| `PLAN.md` врал «Mood ❌ 0%, UIA ❌ 0%»; `ARCHITECTURE.md` перечислял несуществующие модули | доки |

---

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
- `intents._looks_like_command()` — эвристика
  «это команда или свободный текст».
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

- **Ошибка №39** — BOM в `intents.py`
  (`invalid non-printable character U+FEFF`). **Фикс:** UTF-8 без BOM.
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
- `gui.py` → `PALETTES`, `_detect_system_theme`,
  `_rebuild_ui_for_theme`, `_mic_level_loop`.
- `profile.py` → `_current_lock`, `_listeners`, `subscribe()`,
  `_on_profile_switch`.

---

## 🌆 [0.2.2] — 2026-10-05

### ✨ Добавлено

- **Этап 0:** `config_manager`, `Config` в памяти, barge-in, CJK-фильтр,
  few-shot промпт.
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