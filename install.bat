@echo off
echo Installing PSA Card Tracker dependencies...
py -3 -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo Installation failed. Make sure Python 3 is installed.
    pause
    exit /b 1
)
echo.
echo Installation complete! Run "run.bat" to start the app.
pause
