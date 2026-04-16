@echo off
REM -----------------------------------------------------------------
REM  Birkin -- One-click launcher for Windows
REM
REM  Double-click this file to:
REM    1. Verify Python 3.11+ is installed
REM    2. Create a virtual environment (if needed)
REM    3. Install dependencies
REM    4. Launch Birkin
REM -----------------------------------------------------------------
setlocal enabledelayedexpansion

REM  Resolve script directory
cd /d "%~dp0"

set "VENV_DIR=.venv"
set "MIN_MAJOR=3"
set "MIN_MINOR=11"

REM -- Find Python ---------------------------------------------------
REM Try py launcher first (most reliable on Windows), then python, python3
set "PYTHON="
where py >nul 2>&1 && ( set "PYTHON=py" & goto :check_version )
where python >nul 2>&1 && ( set "PYTHON=python" & goto :check_version )
where python3 >nul 2>&1 && ( set "PYTHON=python3" & goto :check_version )

echo.
echo [birkin] ERROR: Python %MIN_MAJOR%.%MIN_MINOR%+ is required but was not found.
echo [birkin] Download it from https://www.python.org/downloads/
echo [birkin] Make sure to check "Add Python to PATH" during installation.
echo.
pause
exit /b 1

:check_version
for /f "tokens=*" %%V in ('%PYTHON% --version 2^>^&1') do set "PYVER=%%V"
echo [birkin] Found %PYVER%

REM Verify minimum version using a simple Python check
%PYTHON% -c "import sys; exit(0 if sys.version_info >= (3, 11) else 1)" 2>nul
if errorlevel 1 (
    echo [birkin] ERROR: Python %MIN_MAJOR%.%MIN_MINOR%+ is required. Found %PYVER%.
    pause
    exit /b 1
)
echo [birkin] Using %PYVER%

REM -- Virtual environment -------------------------------------------
if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo [birkin] Creating virtual environment in %VENV_DIR% ...
    %PYTHON% -m venv %VENV_DIR%
    if errorlevel 1 (
        echo [birkin] ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [birkin] Virtual environment created.
)

REM Activate
call "%VENV_DIR%\Scripts\activate.bat"

REM -- Dependencies --------------------------------------------------
if not exist "%VENV_DIR%\.deps_installed" (
    echo [birkin] Installing dependencies (first run, this may take a minute) ...
    pip install --upgrade pip --quiet
    pip install -e ".[all]" --quiet 2>nul || pip install -e "." --quiet
    if errorlevel 1 (
        echo [birkin] ERROR: Failed to install dependencies.
        pause
        exit /b 1
    )
    echo. > "%VENV_DIR%\.deps_installed"
    echo [birkin] Dependencies installed.
) else (
    echo [birkin] Dependencies already installed.
)

REM -- Auth token ----------------------------------------------------
REM Ensure BIRKIN_AUTH_TOKEN exists in .env
set "HAS_AUTH_TOKEN=0"
if exist ".env" (
    findstr /C:"BIRKIN_AUTH_TOKEN" ".env" >nul 2>&1 && set "HAS_AUTH_TOKEN=1"
)
if "!HAS_AUTH_TOKEN!"=="0" (
    echo [birkin] Generating auth token ...
    for /f "tokens=*" %%T in ('"%VENV_DIR%\Scripts\python.exe" -c "import secrets; print(secrets.token_urlsafe(32))"') do set "NEW_TOKEN=%%T"
    echo BIRKIN_AUTH_TOKEN=!NEW_TOKEN!>> ".env"
    echo [birkin] Auth token written to .env
    echo.
    echo   BIRKIN_AUTH_TOKEN=!NEW_TOKEN!
    echo.
    echo   Save this token -- you will need it to access the web UI.
    echo.
)

REM -- Launch --------------------------------------------------------
set "HOST=127.0.0.1"
set "PORT=8321"
set "URL=http://%HOST%:%PORT%"

echo.
echo =======================================
echo   Birkin WebUI starting ...
echo   %URL%
echo =======================================
echo.

REM Launch via Python module (more reliable than relying on Scripts/birkin.exe)
"%VENV_DIR%\Scripts\python.exe" -m birkin.cli.main serve --host %HOST% --port %PORT%

REM Keep window open if birkin exits
pause
