@echo off
setlocal
cd /d "%~dp0"
set "BUILD_PY=build\nuitka-env\Scripts\python.exe"
if not exist "%BUILD_PY%" (
    py -3.11 -m venv "build\nuitka-env"
    if errorlevel 1 exit /b 1
)
"%BUILD_PY%" -m pip install --disable-pip-version-check -r requirements-nuitka.txt
if errorlevel 1 exit /b 1
"%BUILD_PY%" scripts\build_nuitka.py %*
exit /b %errorlevel%