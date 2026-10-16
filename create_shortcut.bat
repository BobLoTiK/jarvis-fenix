@echo off
setlocal DisableDelayedExpansion
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
set "PHOENIX_SHORTCUT_CWD=%~dp0"

echo   Цель:    %TARGET%
echo   Иконка:  %ICON%
echo.

powershell -NoProfile -Command ^
    "$ws = New-Object -ComObject WScript.Shell;" ^
    "$sc = $ws.CreateShortcut([System.IO.Path]::Combine([Environment]::GetFolderPath('Desktop'), 'Феникс.lnk'));" ^
    "$sc.TargetPath = $env:TARGET;" ^
    "$sc.IconLocation = $env:ICON;" ^
    "$sc.Description = 'Феникс — голосовой ассистент';" ^
    "$sc.WorkingDirectory = $env:PHOENIX_SHORTCUT_CWD;" ^
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