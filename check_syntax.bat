@echo off
cd /d C:\jarvis
call .venv311\Scripts\activate.bat
python check_syntax.py
pause