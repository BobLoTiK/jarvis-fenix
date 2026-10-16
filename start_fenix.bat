@echo off
setlocal
cd /d "%~dp0"
if exist ".venv311\Scripts\pythonw.exe" (
    start "" "%~dp0.venv311\Scripts\pythonw.exe" "%~dp0launcher.py"
    exit /b 0
)
if exist "Феникс.exe" (
    start "" "%~dp0Феникс.exe"
    exit /b 0
)
py -3.11 launcher.py
exit /b %errorlevel%
