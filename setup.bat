@echo off
REM nullaOS one-click setup + run for Windows 11
REM
REM Double-click this file in File Explorer, OR open PowerShell in the
REM nullaOS folder and run: .\setup.bat
REM
REM What it does:
REM   1. Checks that Python and pip are installed
REM   2. Installs Python dependencies (PySide6, python-vlc, pygame-ce)
REM   3. Checks that VLC Media Player is installed
REM   4. Optionally generates SMPTE test-pattern videos via ffmpeg
REM   5. Launches nullaOS
REM
REM After the first run, you can just use:  python scripts\app.py

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo === nullaOS setup ===
echo.

REM ---- 1. Check Python ----
echo [1/5] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo   ERROR: Python not found in PATH.
    echo   Install from https://python.org/ and check "Add Python to PATH" during install.
    pause
    exit /b 1
)
for /f "delims=" %%v in ('python --version') do set PYVER=%%v
echo   OK: %PYVER%
echo.

REM ---- 2. Install Python deps ----
echo [2/5] Installing Python dependencies...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo   ERROR: pip install failed. See output above.
    pause
    exit /b 1
)
echo   OK: PySide6, python-vlc, pygame-ce installed
echo.

REM ---- 3. Check VLC ----
echo [3/5] Checking VLC Media Player...
if exist "C:\Program Files\VideoLAN\VLC\libvlc.dll" (
    echo   OK: VLC found at C:\Program Files\VideoLAN\VLC\
) else if exist "C:\Program Files (x86)\VideoLAN\VLC\libvlc.dll" (
    echo   OK: VLC found at C:\Program Files ^(x86^)\VideoLAN\VLC\
) else (
    echo   WARNING: VLC not found at default install locations.
    echo   Install VLC from https://www.videolan.org/ before running the app.
    echo   If you've already installed VLC elsewhere, edit vlc_player.py.
)
echo.

REM ---- 4. Generate test patterns (optional) ----
echo [4/5] Checking for test content...
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo   ffmpeg not found in PATH — skipping test-pattern generation.
    echo   To use SMPTE test bars as placeholder content, install ffmpeg
    echo   from https://ffmpeg.org/download.html and run:
    echo     python scripts\test_pattern.py
) else (
    echo   ffmpeg found. Generate SMPTE test-pattern videos? ^(Y/N^)
    set /p GEN=      >
    if /I "!GEN!"=="Y" (
        python scripts\test_pattern.py
    ) else (
        echo   Skipped — drop your own MP4s in assets\mock\ instead.
    )
)
echo.

REM ---- 5. Launch ----
echo [5/5] Launching nullaOS...
echo.
echo   Controls:
echo     Arrows / D-pad  - navigate
echo     Enter / A       - select
echo     Backspace / B   - back
echo     Space / Start   - pause/resume
echo     G               - TV guide
echo     V               - Browser mode
echo     I               - info popup
echo     Q               - quit
echo.
pause
python scripts\app.py
