@echo off
rem cd /d "%~dp0" — работает из любой папки, куда пользователь распаковал проект.
rem Раньше был хардкод "cd /d C:\jarvis" — у пользователей с другим путём не работал.
cd /d "%~dp0"
start "" pythonw -m jarvis
exit