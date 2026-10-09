@echo off
REM One-time setup: creates a private Python environment in .venv and installs the packages.
REM storm_report.bat runs this automatically the first time, so you rarely need to run it yourself.
cd /d "%~dp0"

set "PYLAUNCH="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul && set "PYLAUNCH=py -3"
if not defined PYLAUNCH python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul && set "PYLAUNCH=python"
if not defined PYLAUNCH (
    echo Python 3.10 or newer is required but was not found.
    echo Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^), then run this again.
    pause
    exit /b 1
)

echo Creating the Python environment in .venv ...
%PYLAUNCH% -m venv .venv || (echo Could not create the environment. & pause & exit /b 1)
echo Installing packages (about a minute) ...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt || (echo Package install failed. & pause & exit /b 1)
echo Setup complete.
