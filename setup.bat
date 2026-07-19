@echo off
REM ============================================================
REM  Bandwidth Report Manager - one-time setup
REM   1. Installs the Python packages the app needs
REM   2. Installs the browser engine used to reach the eHealth portal
REM   3. Adds a "Bandwidth Report Manager" shortcut to your Desktop
REM   4. Walks you through configuration (folder, login, schedule)
REM  Safe to run more than once.
REM ============================================================
setlocal
cd /d "%~dp0"
title Bandwidth Report Manager - Setup

echo.
echo   Setting up Bandwidth Report Manager...
echo   --------------------------------------
echo.

REM --- find Python -------------------------------------------------
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
    echo   [X] Python was not found.
    echo       Install Python 3 from https://www.python.org/downloads/
    echo       and tick "Add Python to PATH", then run this again.
    echo.
    pause
    exit /b 1
)
echo   [1/4] Using Python: %PY%

REM --- install Python packages ------------------------------------
echo   [2/4] Installing required packages...
%PY% -m pip install --upgrade pip >nul 2>nul
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
    echo   [X] Package install failed. Check your internet connection.
    pause
    exit /b 1
)

REM --- install the browser engine (for the eHealth portal path) ---
echo   [3/4] Installing the browser engine (one-time, ~150MB)...
%PY% -m playwright install chromium
if errorlevel 1 (
    echo   [!] Browser engine install had a problem. The manager still opens;
    echo       the report scripts just won't run until this succeeds.
)

REM --- desktop shortcut -------------------------------------------
echo   [4/4] Adding a Desktop shortcut...
powershell -NoProfile -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Bandwidth Report Manager.lnk');" ^
  "$s.TargetPath='%SystemRoot%\System32\wscript.exe';" ^
  "$s.Arguments='\"%~dp0Launch Bandwidth Report Manager.vbs\"';" ^
  "$s.WorkingDirectory='%~dp0';" ^
  "$s.IconLocation='%SystemRoot%\System32\shell32.dll,165';" ^
  "$s.Save()" >nul 2>nul

REM --- guided configuration ---------------------------------------
echo.
echo   Almost there - a few questions to finish up
echo   (reports folder, eHealth login, and optional daily scheduling).
echo.
%PY% "Setup_script.py" --skip-install

echo.
echo   Done!  Open the app from the "Bandwidth Report Manager" icon on
echo   your Desktop, or double-click "Launch Bandwidth Report Manager.vbs"
echo   in this folder. You can change any setting later in the app under
echo   the Options button.
echo.
pause
endlocal
