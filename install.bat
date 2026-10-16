@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
title Установка Феникса

echo ============================================================
echo   Феникс — установка
echo ============================================================
echo.

cd /d "%~dp0"
setlocal EnableDelayedExpansion

REM =====================================================================
REM 1. Проверка Python 3.11
REM =====================================================================
echo [1/11] Проверка Python — нужен 3.11...

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
python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3,11) else 1)"
if errorlevel 1 (
    echo   ОШИБКА: .venv311 не использует Python 3.11. Сохрани старую папку под другим именем и повтори установку.
    pause
    exit /b 1
)
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
REM 6. Piper package
REM =====================================================================
echo [6/11] Проверка пакета Piper...
python -c "from importlib.metadata import version; print('Piper:', version('piper-tts'))"
if errorlevel 1 (
    echo   Пакет Piper не установлен. Проверь предыдущий шаг pip.
    pause
    exit /b 1
)
echo   Голосовые модели не загружаются этим шагом.
echo   Внешний espeak-ng.exe автоматически не устанавливается.
echo.

REM =====================================================================
REM 7. Ollama
REM =====================================================================
echo [7/11] Проверка Ollama — для LLM-диалога...
where ollama >nul 2>nul
if errorlevel 1 (
    echo.
    echo   Ollama не установлена.
    echo   Без неё остаются быстрые локальные команды; LLM-диалога не будет.
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
echo     4) qwen2.5:7b      Размер и скорость зависят от квантования и контекста
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

set /p LLM_CHOICE="Выбери модель 1-12, по умолчанию 12 - пропустить: "
if "!LLM_CHOICE!"=="" set LLM_CHOICE=12

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
    echo   Некорректный выбор. Конфиг и модели не меняю.
    goto skip_model
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
        echo   Не удалось скачать модель. Конфиг не меняю.
        echo   Попробуй позже: ollama pull !LLM_MODEL!
        goto after_model
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

python scripts\init_user_data.py --record-dependencies
if errorlevel 1 (
    echo   ОШИБКА: не удалось подготовить данные или проверить окружение.
    pause
    exit /b 1
)
echo   Пользовательские данные хранятся в APPDATA, модели - в ASCII-пути.
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
if not exist "tests\conftest.py" (
    echo [11/11] Тестов нет в runtime-поставке. Для разработки используй исходный проект.
    goto checks_done
)
echo [11/11] Проверка работоспособности Феникса.
echo.
echo   Полный прогон: синтаксис, pytest, интенты и стресс-тесты.
set /p RUN_CHECKS="Запустить проверку сейчас? y/n: "
if /i "%RUN_CHECKS%"=="n" goto skip_checks
python -m pip install -r requirements-dev.txt
if errorlevel 1 goto checks_failed
python check_all.py
if errorlevel 1 goto checks_failed
echo   Проверки прошли.
goto checks_done

:checks_failed
echo   Проверки не завершились успешно. Смотри вывод выше и logs\check_all.
goto checks_done

:skip_checks
echo   Позже: check_all.bat

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