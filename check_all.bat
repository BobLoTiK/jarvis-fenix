@echo off
rem check_all.bat — единая проверка Феникса.
rem
rem Вся логика в check_all.py: 4 шага (синтаксис -> pytest -> интент-тесты
rem -> стресс-тест). В конце — либо одна строка «ВСЁ ОТЛИЧНО», либо разбор
rem того, что именно упало. Полные логи шагов: logs\check_all\*.log
rem
rem Запускает:  check_all.bat    (или doskey-алиас checkall)

setlocal
chcp 65001 >nul
title Проверка Феникса
cd /d "%~dp0"

rem Активируем локальное окружение, если оно есть рядом с проектом.
if exist ".venv311\Scripts\activate.bat" call ".venv311\Scripts\activate.bat"

python check_all.py
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" echo   (код возврата: %RC%)
pause
exit /b %RC%
