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
set "PYTHON="
for %%P in (python py python3) do (
    where %%P >nul 2>&1 && (
        for /f "tokens=*" %%V in ('%%P -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2^>nul') do (
            for /f "tokens=1,2 delims=." %%A in ("%%V") do (
                if %%A GEQ %MIN_MAJOR% if %%B GEQ %MIN_MINOR% (
                    set "PYTHON=%%P"
                    goto :found_python
                )
            )
        )
    )
)

echo.
echo [birkin] ERROR: Python %MIN_MAJOR%.%MIN_MINOR%+ is required but was not found.
echo [birkin] Download it from https://www.python.org/downloads/
echo [birkin] Make sure to check "Add Python to PATH" during installation.
echo.
pause
exit /b 1

:found_python
for /f "tokens=*" %%V in ('%PYTHON% --version 2^>^&1') do set "PYVER=%%V"
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

REM Auto-open browser after 2 seconds
start /b cmd /c "timeout /t 2 /nobreak >nul & start %URL%"

birkin serve --host %HOST% --port %PORT%

REM Keep window open if birkin exits
pause
