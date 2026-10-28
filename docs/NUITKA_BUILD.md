# Сборка лаунчера через Nuitka

> Это прежний bootstrap-вариант. Полная сборка приложения **без внешнего Python**:
> `build_nuitka_full.bat`; см. [FULL_NUITKA_BUILD](FULL_NUITKA_BUILD.md).

## Что именно компилируется

Компилируется `launcher.py` и его bootstrap-зависимости, включая окно Tk.
Это **не полностью автономный Феникс**: сам ассистент по-прежнему работает
из `.venv311`, а код и ресурсы приложения должны оставаться рядом с EXE.
Flet, Torch, Whisper, голоса и модели не встраиваются в лаунчер.

PyInstaller-путь и `scripts/build_setup.py` не заменены. Эта сборка —
отдельный вариант для проверки Nuitka, без автоматической сборки Inno Setup.

## Требования на компьютере сборки

- Windows 10/11 x64.
- Официальный Python 3.11 x64 с установленным Tcl/Tk.
- Интернет для установки Nuitka и при необходимости инструментов компилятора.
- MSVC Build Tools с C++ либо MinGW64, который Nuitka может загрузить сам.
- Для первого прогона лучше ASCII-путь к проекту, например `C:\jarvis`.

`requirements-nuitka.txt` фиксирует Nuitka 4.3.1. BAT создаёт отдельное
окружение `build\nuitka-env`; рабочее `.venv311` не изменяется.
Не устанавливай туда тяжёлые runtime-зависимости из `requirements.txt`.

## Сначала standalone

Из корня исходного проекта:

```bat
build_nuitka.bat --console
```

По умолчанию выбрана папочная сборка `standalone`. Готовая поставка:

```text
dist\nuitka-standalone\Феникс.exe
```

Запускай EXE из этой папки. При передаче сохраняй **всю папку**
`dist\nuitka-standalone`, а не только EXE: в ней DLL/Tcl/Tk и публичный
payload приложения. Личные конфиги, профили, кэши моделей и старое окружение
компьютера сборщика не включаются.

Для принудительного выбора компилятора:

```bat
build_nuitka.bat --compiler msvc --console
build_nuitka.bat --compiler mingw64 --console
```

BAT разрешает Nuitka загружать необходимые compiler/cache tools.
По умолчанию используются два процесса компилятора; число меняется
параметром `--jobs`.

## Потом onefile

Только после проверки папочной сборки:

```bat
build_nuitka.bat --mode onefile
```

Результат:

```text
dist\nuitka-onefile\Феникс.exe
```

Это onefile **лаунчера**, не всего ассистента. Соседние исходники, ресурсы
и `requirements.txt` всё ещё обязательны: передавай всю итоговую папку.
Во время первого запуска лаунчер может устанавливать Python/зависимости
с согласия пользователя, загружать Vosk и предлагать настройку Ollama.

## Повторный запуск из дерева проекта

Лаунчер проверяет папку EXE, её родительские каталоги и текущую папку.
Сначала выбирается каталог с пакетом `jarvis/` и рабочим окружением
`.venv311` (Python 3.11, `python.exe` и `pythonw.exe`). Поэтому сборка
`C:\jarvis\dist\nuitka-standalone\Феникс.exe` использует готовое
`C:\jarvis\.venv311`, а не создаёт второе окружение внутри `dist`.
Если готового окружения нет, сохраняется обычная подготовка рядом с EXE.
При нескольких готовых окружениях приоритет у расположенного рядом с EXE.

После обновления `launcher.py` нужно заново выполнить `build_nuitka.bat --console`:
изменение исходника не меняет уже скомпилированный EXE.

## Диагностика

- Консоль: `--console`.
- Подробный отчёт Nuitka:
  `build\nuitka-standalone\compilation-report.xml` либо
  `build\nuitka-onefile\compilation-report.xml`.
- Журнал лаунчера: `logs\launcher.log` рядом с реальным EXE.
- Проверка команды/ресурсов без компиляции, Windows и Tk:

```text
python scripts/build_nuitka.py --check
```

При повторной успешной сборке папка `dist\nuitka-<mode>` заменяется.
Пользовательские данные не следует хранить в этих build-owned папках.

Для Nuitka исправлено определение расположения EXE: используется
`__compiled__.containing_dir`, а не временная папка распаковки onefile.
Существующий режим PyInstaller и запуск исходного `launcher.py` сохранены.

## Что проверено и что ещё нужно проверить

В этой подготовке выполнены проверка команды, модульные тесты и реальная
компиляция `launcher.py` в Linux-extension через Nuitka 4.3.1 / GCC 11
на Python 3.13. Скомпилированный модуль загружен; проверены поиск папки
и вычисление fingerprint зависимостей без запуска интерфейса.
Это не Windows EXE и не проверка Tk/UI.
Сборку Windows standalone/onefile и фактический запуск Windows нужно
выполнить на Windows. `--check` не подменяет такой прогон.

Официальная документация:

- [Setup/build и рекомендуемый порядок standalone → onefile](https://nuitka.net/user-documentation/tutorial-setup-and-build.html).
- [Расположение файлов и особенности onefile](https://nuitka.net/user-documentation/common-issue-solutions.html).