@echo off
setlocal
cd /d "%~dp0"
rem Preflight must not create an environment or download packages.
for %%A in (%*) do if /I "%%~A"=="--check" goto check
set "BUILD_PY=build\nuitka-app-env\Scripts\python.exe"
if not exist "%BUILD_PY%" (
    py -3.11 -m venv "build\nuitka-app-env"
    if errorlevel 1 exit /b 1
)
"%BUILD_PY%" -m pip install --disable-pip-version-check -r requirements-nuitka-app.txt
if errorlevel 1 exit /b 1
"%BUILD_PY%" scripts\build_nuitka_app.py %*
exit /b %errorlevel%
:check
py -3.11 scripts\build_nuitka_app.py %*
exit /b %errorlevel%
