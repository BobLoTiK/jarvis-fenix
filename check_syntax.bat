@echo off
rem №98: cd /d "%~dp0" вместо хардкода C:\jarvis.
rem Теперь скрипт работает, даже если проект перемещён.
cd /d "%~dp0"
call .venv311\Scripts\activate.bat
python check_syntax.py
pause