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