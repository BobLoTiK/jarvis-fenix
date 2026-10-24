@echo off
setlocal
cd /d "%~dp0"
echo AEC diagnostic mode: LOCAL MICROPHONE RECORDING.
echo Close any running Fenix instance before continuing.
echo Supports Piper and Silero through the common PCM output.
echo Requires the existing AEC setting; it is not enabled automatically.
echo SAPI direct playback has no PCM reference: metadata only, no full AEC trace.
echo For SAPI, close normally to save the metadata-only ZIP.
echo Records the selected PCM voice, microphone and AEC output. No upload.
echo In this diagnostic run AEC also processes Silero; normal launches are unchanged.
echo Stops 2 seconds after the first barge-in, or after 90 seconds of the session.
echo Maximum audio data: 32 MiB. The application keeps running after recording stops.
echo Normal start_fenix.bat does not enable this mode.
echo.
choice /C YN /N /M "Start Fenix with local recording? [Y/N] "
if errorlevel 2 exit /b 0
if not exist ".venv311\Scripts\python.exe" (
    echo ERROR: .venv311\Scripts\python.exe not found. Use the existing Python 3.11 installation.
    pause
    exit /b 1
)
set "FENIX_AEC_DIAGNOSTICS=1"
"%~dp0.venv311\Scripts\python.exe" -m jarvis
set "RESULT=%errorlevel%"
echo.
echo Recording is not enabled for normal launches.
echo Look for the AEC diagnostic SAVED line with the ZIP path.
echo Default folder: %%APPDATA%%\Phoenix\logs\aec_diagnostics
pause
exit /b %RESULT%
