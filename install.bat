@echo off
setlocal

echo ============================================
echo  PSA Card Tracker - Installation
echo ============================================
echo.

:: Check Python is available
py -3 --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python 3 not found.
    echo.
    echo Please install Python 3.10 or later from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

echo Python found:
py -3 --version
echo.

:: Upgrade pip first to avoid stale pip issues
echo Upgrading pip...
py -3 -m pip install --upgrade pip --quiet
echo.

:: Install each package individually so failures are visible
echo Installing packages...
echo.

set FAILED=0

call :install PyQt6
call :install requests
call :install "beautifulsoup4"
call :install lxml
call :install "curl-cffi"
call :install setuptools

echo.
if %FAILED% neq 0 (
    echo ============================================
    echo  ERROR: One or more packages failed.
    echo  Check the messages above for details.
    echo ============================================
) else (
    echo ============================================
    echo  Installation complete!
    echo  Run "run.bat" to launch the app.
    echo ============================================
)

echo.
pause
exit /b %FAILED%

:: --- helper function ---
:install
echo Installing %~1...
py -3 -m pip install %~1 --quiet
if %errorlevel% neq 0 (
    echo   FAILED: %~1
    set FAILED=1
) else (
    echo   OK: %~1
)
goto :eof
