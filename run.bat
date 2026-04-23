@echo off
cd /d "%~dp0"
py -3 main.py
if %errorlevel% neq 0 (
    echo.
    echo Error running app. Run install.bat first if you haven't already.
    pause
)
