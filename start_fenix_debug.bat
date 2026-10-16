@echo off
setlocal
chcp 65001 >nul
title Феникс — диагностика
cd /d "%~dp0"
if not exist ".venv311\Scripts\python.exe" (
    echo Нет .venv311. Сначала запусти install.bat или Феникс.exe.
    pause
    exit /b 1
)
"%~dp0.venv311\Scripts\python.exe" -m jarvis
set "RESULT=%errorlevel%"
echo.
echo Феникс завершился с кодом %RESULT%.
pause
exit /b %RESULT%
