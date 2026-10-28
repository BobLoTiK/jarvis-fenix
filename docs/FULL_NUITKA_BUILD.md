# Полное приложение Nuitka и установщик без внешнего Python

## Актуальный единый архив

Используйте только `jarvis_nuitka_all_in_one.zip`: полный патч, исправление metadata
и последнее исправление внутренних тестов Torch уже объединены. Старые ZIP поверх
него не применять. Это исходники сборочной цепочки, не готовый установщик.

Перед повторной компиляцией на уже подготовленном компьютере выполните в PowerShell:

```powershell
cd C:\jarvis
.\build\nuitka-app-env\Scripts\python.exe -c "from pathlib import Path; from scripts.build_nuitka_app import validate_torch_runtime; validate_torch_runtime(Path('build/nuitka-app')); print('TORCH PREFLIGHT OK')"
```

При отказе сначала прочитайте `build/nuitka-app/torch-builder-preflight.log`.
Прежняя проверка ошибочно требовала одинаковую серию версий. TorchAudio 2.11
поддерживает PyTorch 2.11 и новее, включая 2.14.1. Теперь проверяются требования
установленного пакета torchaudio, импорты и CPU TorchScript. Переустановка по
одним номерам не нужна. Источник: https://docs.pytorch.org/audio/master/installation.html
Скрипт не меняет версии автоматически. Пока эта проверка не пройдёт,
долгую компиляцию запускать не нужно. Если build-окружение ещё не создано,
его создаёт BAT, который тоже выполняет эту проверку перед компиляцией.

После успеха используйте `--low-memory --jobs 1`. Память важнее параллелизма
после обнаруженного `cc1.exe: out of memory`. Кэш и build не удалять.
Исключён только `torch.testing._internal`, не рабочий Torch или TorchScript JIT.
Это не гарантия отсутствия других тяжёлых модулей.

Предупреждения об отсутствующих VC++ runtime DLL пока не исправлены;
переносимость на чистом Windows не подтверждена. Настоящая Windows-компиляция
и Sandbox в Linux-среде не выполнялись.

## Отличие от прежней сборки

`build_nuitka.bat` оставлен как старый bootstrap-вариант: он компилирует только
`launcher.py`. **Для автономной поставки его не использовать.**

Новый путь: `build_nuitka_full.bat` → `phoenix_app.py` + пакет `jarvis` + runtime
и нативные зависимости → `dist/nuitka-app` → Inno Setup →
`dist/Феникс_Nuitka_Setup.exe`.

На машине пользователя **не нужны Python, pip, исходники проекта или .venv311**.
Python DLL и расширения входят в standalone-папку. Nuitka не превращает все
сторонние библиотеки в независимые от Python C-библиотеки: встроенный runtime
остаётся частью приложения. Само приложение компилируется, не запускается
через `pythonw.exe -m jarvis`.

## Что включено и что остаётся отдельным

- Flet Python API **и готовый Windows Flet-клиент** с Flutter DLL/данными.
  В `flet-desktop==1.0.3` wheel нет самого EXE: builder вызывает
  `ensure_client_cached()` и копирует только клиент соответствующей версии.
  На целевом ПК не требуется клиент из `~/.flet` или загрузка через pip.
- Vosk, Piper, SAPI/pyttsx3, Whisper/CTranslate2, ONNX Runtime, Torch/Torchaudio,
  WinRT Media Control, автоматизация Windows, словари русской морфологии,
  сертификаты CA, графика, звуковые ресурсы и публичные command packs.
- Torch JIT явно **не отключён**: он нужен Silero/TorchScript.
- Голосовые и ASR-модели, личные профили/конфиги/история, старый venv и кэши
  разработчика **не копируются**. Vosk скачивается с согласия при первом запуске;
  голос Piper и Whisper могут загружаться при использовании. Поэтому отсутствие
  внешнего Python не означает полностью офлайн-поставку всех моделей.
- Ollama остаётся отдельным необязательным сервисом. Без него локальные команды
  могут работать, но ответы LLM недоступны. Ollama/LLM-модели установщик не ставит.
- CUDA-драйвер не поставляется. Состав Torch/CTranslate2 определяется пакетами
  build-окружения; отсутствие GPU проверяется отдельно, CPU должен оставаться
  доступным. Возможности микрофона/мониторов зависят от оборудования Windows.

## Требования только к компьютеру сборки

- Windows 10/11 x64, официальный CPython 3.11 x64 с Tcl/Tk.
- Optional AEC-плагин из requirements-aec.txt в этот базовый профиль не включён.
- Inno Setup 6 (`ISCC.exe` в PATH или стандартной папке; можно задать `INNO_SETUP`).
- MSVC Build Tools C++ или MinGW64; Nuitka может предложить загрузку compiler tools.
- Интернет для build-пакетов/Flet. Место на диске с запасом: Torch и standalone
  могут занимать много гигабайт. Время сборки существенно больше, чем у launcher.
- Windows Sandbox — отдельная функция поддерживаемых редакций Windows Pro /
  Enterprise / Education и поддерживаемой конфигурации виртуализации. Если она
  недоступна, использовать чистую Windows VM. Скрипт не включает функции ОС сам.

Python нужен **сборщику**, не пользователю. BAT создаёт отдельное окружение
`build/nuitka-app-env`, не меняя рабочую `.venv311`.

## Команды CMD

Сначала недеструктивный preflight (без установки пакетов и компиляции):

```bat
cd /d C:\jarvis
build_nuitka_full.bat --check
```

Полная сборка + запрос запуска Windows Sandbox:

```bat
cd /d C:\jarvis
build_nuitka_full.bat --jobs 5 --sandbox
```

`--jobs 1` нужен только при нехватке памяти: на Ryzen 5 5600 / 32 ГБ разница
между `--jobs 1` и `--jobs 5` — часы против примерно часа.

Для диагностики консоли или конкретного компилятора:

```bat
build_nuitka_full.bat --console --compiler msvc --low-memory --jobs 1 --sandbox
```

Без Sandbox:

```bat
build_nuitka_full.bat --low-memory --jobs 1
```

Вариант только standalone, без Inno:

```bat
build_nuitka_full.bat --no-setup --console --low-memory --jobs 1
```

Параметры: `--jobs 2` по умолчанию, `--version 2.1.2`. Для первого опыта лучше
оставить два compiler job, а не пытаться занять всю память Torch-компиляцией;
на 32 ГБ и Ryzen 5 5600 `--jobs 5` укладывает компиляцию примерно в час.
`requirements-nuitka-app.txt` использует runtime requirements проекта, Nuitka 4.3.1
и согласованную пару Flet/Flet-desktop 1.0.3. Точные версии всех установленных
build-зависимостей записываются в `build-info.json`; это журнал окружения,
не заявление, что непроверенные будущие версии зависимостей поддерживаются.

## Что делает builder

1. Проверяет Windows/Python x64, runtime-зависимости, Tk, ресурсы и Inno.
2. Подготавливает Flet-клиент на build-машине.
3. Компилирует **phoenix_app.py**, включая пакет `jarvis` и динамические импорты.
4. Проверяет XML-отчёт Nuitka: основные модули приложения действительно compiled.
5. Проверяет Python DLL и нативные библиотеки; запрещает внешний `python.exe`,
   `pythonw.exe`, venv, пользовательские данные и сырые исходники `jarvis` в payload.
6. Публикует отдельную папку `dist/nuitka-app`, добавляет клиент и ресурсы,
   `build-info.json` и SHA-256 manifest.
7. Запускает `Феникс.exe --self-test <report.json>` на временной копии сборки,
   чтобы динамические COM/сторонние кэши не попали в установщик.
   Это ранняя проверка; она **не заменяет чистую машину**.
8. Собирает `Феникс_Nuitka_Setup.exe`. Только после успеха готовит Sandbox.

Дистрибутив по умолчанию устанавливается в Program Files/Phoenix с правами
администратора; данные остаются в AppData/Phoenix и ProgramData/Phoenix.
Используется прежний AppId для обновления ярлыков, но каталог установки для новой
схемы не наследуется от старого bootstrap. Старые кэши/venv не удаляются автоматически.
Не запускайте старый и новый Феникс одновременно: mutex общий.
COM-обёртки генерируются в AppData/Phoenix/comtypes-cache, не в Program Files.
При заблокированной прежней сборке публикация останавливается без удаления
её файлов; при ошибке замены предыдущая папка возвращается.

## Проверка в Windows Sandbox

Сценарий создаёт случайную папку `build/sandbox-nuitka/<id>`:

- `input` — копия установщика, SHA-256 и проверочный PS1, в Sandbox **read-only**;
- `results` — единственная writable-папка, доступная гостю на хосте;
- `Phoenix_Nuitka_Test.wsb` — настройки изоляции.

Рабочий проект, домашняя папка, профили, токены и модели хоста не расшариваются.
Сеть, vGPU, микрофон, камера, буфер обмена и принтеры отключены.
В PowerShell используется process-only ExecutionPolicy Bypass для данного теста;
постоянные настройки безопасности хоста не меняются.

В госте автоматически проверяются:

1. Отсутствие внешнего Python и совпадение SHA-256 установщика.
2. Тихая установка в чистый ASCII-каталог, без postinstall-запуска ассистента.
3. Manifest установленного payload и отсутствие python.exe/venv.
4. Импорты встроенных DLL/модулей, русские словари и TorchScript CPU.
5. Отдельный Flet GUI-smoke: встроенный клиент открывает страницу и закрывается
   с `await`. Этот режим не загружает Vosk, не открывает микрофон и не общается с LLM.
6. Удаление приложения и сохранение тестового пользовательского файла.

Каждый процесс имеет timeout. Ошибка, ненулевой ExitCode, отсутствие отчёта или
`ok != true` считаются отказом, а не успехом. В конце в `results/summary.json`
появляется `ok: true` или `ok: false` и перечень **непроверенных** функций.
Просто открывшееся окно Sandbox не означает, что проверки прошли.
Не закрывайте Sandbox до завершения отчёта; при отказе сохраните все results.

Чтобы повторить тест **без повторной компиляции**:

```bat
py -3.11 scripts\prepare_nuitka_sandbox.py --open
```

Для нормального ручного Windows-прогона дополнительно нужны сеть/модели, настоящий
микрофон, вывод звука и при необходимости Ollama. Проверить Piper/Silero/SAPI,
проба → stop → новая проба, переключение при загрузке, voice-команды, трей/выход.
Offline Sandbox не подтверждает эти функции или GPU inference.

## Silero без внешнего Python

После установки используйте ярлык «Подготовить Silero» в меню Пуск при закрытом
Фениксе либо:

```bat
"C:\Program Files\Phoenix\Феникс.exe" --prepare-silero
```

Приложение явно спрашивает разрешение доверять и выполнять код
`snakers4/silero-models`, после согласия подготавливает модель встроенным runtime.
Автоматическое скрытое доверие не добавляется.

## Артефакты и границы проверки

- `build/nuitka-app/compilation-report.xml` — отчёт реального компилятора.
- `build/nuitka-app/build-command.json` — точная команда.
- `build/nuitka-app/native-probe.json` — проверка на builder, не Sandbox.
- `dist/nuitka-app` — полная runtime-папка (передавать целиком, не один EXE).
- `dist/Феникс_Nuitka_Setup.exe` — установщик новой схемы.
- `build/sandbox-nuitka/<id>/results` — результаты чистой Windows-проверки.

## Исправления по результатам реальной Windows-сборки

- Пакет `flet` включается целиком (`--include-package=flet`). Раньше
  `flet.controls.material.icons` импортировался динамически и отсутствовал в
  сборке; self-test падал на `ModuleNotFoundError` уже после успешной линковки.
- `validate_report()` принимает отчёт Nuitka с объявлением `encoding='utf8'`:
  expat такой псевдоним не понимает и падал на первом не-ASCII символе
  (кириллица в имени `Феникс.exe`), хотя компиляция была успешной.
- Флаг `--skip-compile` повторно использует готовый `phoenix_app.dist`
  и отчёт: после падения в пост-обработке не нужно ждать полную
  перекомпиляцию. Требует существующих dist и `compilation-report.xml`.
- `--jobs 5` вместо `--jobs 1`: 4197 C-файлов собираются примерно в 8 раз
  быстрее при свободной памяти (проверено: ~14 ГБ остаётся). `--low-memory`
  оставлен включённым.
- `torch.testing._internal` больше не исключается. `torch/utils/checkpoint.py`
  импортирует `torch.testing._internal.logging_tensor` безусловно, поэтому
  `import torch` в сборке падал с `ImportError ... actively excluded`.
  Цепочка `logging_tensor` лёгкая (без pytest и common_utils), рост сборки
  незначителен.
- Добавлены данные `--include-package-data=winrt`: winrt 4 читает таблицу
  проекций `_table.pywinrt` рядом с модулем, без неё self-test падал на
  `winrt.windows.media.control`.
- Известное расхождение: в окружении сборки установлен winrt 4.0.3
  (`requirements.txt` не ограничивает версию сверху: `winrt-runtime>=3.2`),
  а в рабочем `.venv311` — 3.2.1. Артефакт собран с winrt 4.0.3; поведение
  Media Control на winrt 4 отдельно не проверялось.
- Полная сборка на Ryzen 5 5600 / 32 ГБ: скан графа ≈25 мин, C-компиляция
  ≈60 мин при `--jobs 5`, линковка и публикация ≈10 мин, Inno Setup — отдельно.
- Прямой запуск `scripts/build_nuitka_app.py` нужно делать интерпретатором
  окружения сборки, а не рабочей `.venv311`:
  `.\build\nuitka-app-env\Scripts\python.exe scripts\build_nuitka_app.py --jobs 5`.
  В `.venv311` нет Nuitka, и builder падает на `No package metadata was found
  for Nuitka` — сообщение легко принять за сломанный пакет, хотя он стоит в env.
  `.bat` подставляет нужный интерпретатор сам.
- `verify_nuitka_sandbox.ps1` должен оставаться чистым ASCII: Windows
  PowerShell 5.1 читает `.ps1` без BOM как ANSI, поэтому кириллическое имя
  `Феникс.exe` превращалось в кракозябры, и первый реальный прогон упал с
  «Application executable was not installed» уже после успешной установки.
  Теперь имя EXE ищется в каталоге установки, а `tests/test_nuitka_full.py`
  содержит страж на ASCII-совместимость.

В Linux-среде разработки можно проверить генерацию команд, изоляцию, manifest,
контракты probe/отказов и portable tests. Реальная Windows-компиляция, исполнение
установщика и Sandbox там невозможны. Текущий статус на Windows (28.10.2026):
**сборка и `--self-test` подтверждены, Sandbox-приёмка не завершена** — первый
прогон упал на дефекте harness (сама установка в песочнице прошла), harness
исправлен, повторный прогон требует перезагрузки хоста, потому что осиротевшая
VM держит единственный экземпляр Windows Sandbox.

Официальные источники:

- https://nuitka.net/user-documentation/tutorial-setup-and-build.html
- https://nuitka.net/user-documentation/nuitka-package-config.html
- https://github.com/Nuitka/Nuitka/blob/4.3.1/nuitka/plugins/standard/standard.nuitka-package.config.yml
