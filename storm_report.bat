@echo off
REM Double-click: lists the storms in the latest WeatherNext 3 run, asks which one,
REM then builds that storm's report and opens it in your browser.
REM Keep this window open while viewing - it powers the report's Refresh button.
title WeatherNext storm viewer (keep open for Refresh)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo First run: setting things up...
    call setup.bat || exit /b 1
    echo.
)
".venv\Scripts\python.exe" scripts\serve.py
