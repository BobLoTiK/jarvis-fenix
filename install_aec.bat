@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist ".venv311\Scripts\python.exe" (
  echo Сначала подготовь Феникс: окружение .venv311 не найдено.
  pause
  exit /b 1
)
echo Будет установлен необязательный пакет AEC из PyPI в .venv311.
echo Драйверы, модели и настройки не меняются. Для отмены закрой окно.
pause
".venv311\Scripts\python.exe" -m pip install --only-binary=:all: -r requirements-aec.txt
if errorlevel 1 (
  echo Установка не завершена. Сохрани текст ошибки. Феникс работает и без AEC.
  pause
  exit /b 1
)
".venv311\Scripts\python.exe" -c "from pywebrtc_audio import AudioProcessor; p=AudioProcessor(sample_rate=16000, echo_cancellation=True); print('AEC native initialization: OK')"
if errorlevel 1 (
  echo Нативный AEC не загрузился. Не включай эксперимент; сохрани ошибку.
  pause
  exit /b 1
)
echo Готово. В Голосе и звуке выбери Piper, включи эксперимент AEC и перезапусти Феникс.
echo Автоматического изменения твоих настроек не было.
pause
