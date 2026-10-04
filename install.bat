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
REM 1. Проверка Python
REM =====================================================================
echo [1/9] Проверка Python...
where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo   Python не найден в PATH.
    echo   Скачай Python 3.10+ отсюда: https://www.python.org/downloads/
    echo   При установке отметь "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo   Найден Python %PYVER%
echo.

REM =====================================================================
REM 2. pip
REM =====================================================================
echo [2/9] Проверка pip...
python -m pip --version >nul 2>nul
if errorlevel 1 (
    echo   pip не найден, ставлю ensurepip...
    python -m ensurepip --default-pip
    python -m pip install --upgrade pip
)
echo   pip готов
echo.

REM =====================================================================
REM 3. Python-зависимости
REM =====================================================================
echo [3/9] Установка Python-зависимостей...
echo   Это может занять несколько минут.
echo.
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo   Ошибка при установке зависимостей.
    pause
    exit /b 1
)
echo   Зависимости установлены.
echo.

REM =====================================================================
REM 4. Дополнительные пакеты
REM =====================================================================
echo [4/9] Установка дополнительных пакетов...
python -m pip install pyautogui pygetwindow keyboard mouse pyperclip psutil pycaw screen-brightness-control 2>nul
echo   Готово.
echo.

REM =====================================================================
REM 5. eSpeak NG
REM =====================================================================
echo [5/9] Проверка eSpeak NG (нужен для Piper TTS)...
where espeak-ng >nul 2>nul
if errorlevel 1 (
    if exist "C:\Program Files\eSpeak NG\espeak-ng.exe" (
        echo   eSpeak NG найден в C:\Program Files\eSpeak NG
    ) else (
        echo.
        echo   eSpeak NG не найден. Без него Piper не заведётся.
        echo.
        set /p INSTALL_ESPEAK="Установить eSpeak NG сейчас (через winget)? (y/n): "
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
            echo   Пропускаю. Поставишь позже — иначе Piper не будет работать.
        )
    )
) else (
    echo   eSpeak NG найден.
)
echo.

REM =====================================================================
REM 6. Ollama
REM =====================================================================
echo [6/9] Проверка Ollama (для LLM-фолбэка)...
where ollama >nul 2>nul
if errorlevel 1 (
    echo.
    echo   Ollama не установлена.
    echo   Без неё Феникс работает только на правилах — без свободного диалога.
    echo.
    set /p INSTALL_OLLAMA="Установить Ollama сейчас (через winget)? (y/n): "
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
REM 7. Выбор модели LLM
REM =====================================================================
where ollama >nul 2>nul
if errorlevel 1 (
    echo [7/9] Ollama не установлена — пропускаю выбор модели.
    echo.
    goto skip_model
)

echo [7/9] Выбор модели для LLM.
echo.
echo   ============================================================
echo    Слабые ПК, встроенная графика, 4-8 ГБ RAM (без GPU)
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
echo    Мощные ПК / серверы, 16+ ГБ VRAM
echo   ============================================================
echo     6) qwen2.5:32b     ~20 ГБ VRAM   Профессиональное
echo     7) qwen2.5:72b     ~40 ГБ VRAM   Только для топовых GPU
echo.
echo   ============================================================
echo    Альтернативные семейства (для русского тоже ок)
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
echo     Смотри "Видеопамять (VRAM)".
echo.

set /p LLM_CHOICE="Выбери модель (1-12, по умолчанию 4): "
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

echo.
echo   Обновляю config.json — устанавливаю llm_model = !LLM_MODEL! ...
python -c "import json, pathlib; p = pathlib.Path('config.json'); d = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}; d['llm_model'] = '!LLM_MODEL!'; p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8'); print('OK')"
echo.

goto after_model

:skip_model
echo   Пропускаю скачивание модели.
echo.

:after_model

REM =====================================================================
REM 8. Конфиг, папки, микрофон
REM =====================================================================
echo [8/9] Настройка конфига и папок...

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
REM 9. Проверка работоспособности
REM =====================================================================
echo [9/9] Проверка работоспособности Феникса.
echo.
echo   Сейчас прогонятся:
echo     - Проверка синтаксиса (check_syntax.py)
echo     - Юнит-тесты (pytest tests/)
echo     - Интент-тесты (test_intents.py)
echo.

set /p RUN_CHECKS="Запустить проверку сейчас? (y/n): "
if /i "%RUN_CHECKS%"=="n" goto skip_checks

set CHECK_FAILED=0

REM --- 9.1. Синтаксис ---
echo.
echo   --- Проверка синтаксиса ---
python check_syntax.py
if errorlevel 1 (
    echo   [!!] Ошибки синтаксиса
    set CHECK_FAILED=1
) else (
    echo   [OK] Синтаксис в порядке
)

REM --- 9.2. pytest ---
echo.
echo   --- Юнит-тесты (pytest) ---
python -m pytest tests/ -q
if errorlevel 1 (
    echo   [!!] Тесты упали
    set CHECK_FAILED=1
) else (
    echo   [OK] Тесты прошли
)

REM --- 9.3. test_intents ---
echo.
echo   --- Интент-тесты (test_intents.py) ---
echo   (это может занять до 30 секунд)
python test_intents.py
if errorlevel 1 (
    echo   [!!] Интент-тесты упали — смотри logs\test_intents.log
    set CHECK_FAILED=1
) else (
    echo   [OK] Интент-тесты прошли
)

echo.
if "!CHECK_FAILED!"=="1" (
    echo ============================================================
    echo   ⚠  ЕСТЬ ОШИБКИ — смотри выше
    echo ============================================================
    echo.
    echo   Что делать:
    echo     1. Проверь logs\errors.log
    echo     2. Проверь logs\test_intents.log
    echo     3. Скинь эти логи автору
    echo.
) else (
    echo ============================================================
    echo   ✅  ВСЁ РАБОТАЕТ
    echo ============================================================
    echo.
)
goto checks_done

:skip_checks
echo   Пропускаю проверку. Запустишь позже вручную:
echo     python check_syntax.py
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
echo   1. Проверь микрофон (если ещё не):
echo        python scripts\mics.py
echo.
echo   2. Запусти Феникса:
echo        start_fenix.bat         (без консоли)
echo        start_fenix_debug.bat   (с логами в консоли)
echo.
echo   3. Говори "Феникс ..." — и он ответит.
echo.

set /p RUN_MICS="Запустить проверку микрофона сейчас? (y/n): "
if /i "%RUN_MICS%"=="y" (
    python scripts\mics.py
)

echo.
pause