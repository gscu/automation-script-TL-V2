@echo off
REM ============================================================
REM  Builds "Bandwidth Report Manager.exe" and zips it for sending.
REM  Run this ONCE on a Windows PC that has Python 3 installed.
REM  Output:  Bandwidth Report Manager.zip   (hand this to users)
REM ============================================================
setlocal
cd /d "%~dp0"
title Build Bandwidth Report Manager .exe

echo.
echo   Building Bandwidth Report Manager...
echo   ====================================
echo.

REM --- find Python ------------------------------------------------
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
    echo   [X] Python 3 was not found. Install it from
    echo       https://www.python.org/downloads/  ^(tick "Add Python to PATH"^),
    echo       then run this again.
    pause & exit /b 1
)
echo   [1/5] Python: %PY%

REM --- install build + app dependencies ---------------------------
echo   [2/5] Installing build tools and dependencies...
%PY% -m pip install --upgrade pip pyinstaller >nul
%PY% -m pip install -r requirements.txt
if errorlevel 1 ( echo   [X] Dependency install failed. & pause & exit /b 1 )

REM --- build the windowed exe -------------------------------------
echo   [3/5] Compiling the .exe (this takes a few minutes)...
%PY% -m PyInstaller --noconfirm bandwidth_manager.spec
if errorlevel 1 ( echo   [X] Build failed. See messages above. & pause & exit /b 1 )

set "OUT=dist\Bandwidth Report Manager"

REM --- place runtime files next to the exe ------------------------
REM The report scripts stay as loose .py files: the manager patches
REM credentials into them and runs them with the machine's Python.
echo   [4/5] Adding report scripts and templates...
if exist "Morning BW Reports.py"    copy /y "Morning BW Reports.py"    "%OUT%\" >nul
if exist "Afternoon BW Reports.py"  copy /y "Afternoon BW Reports.py"  "%OUT%\" >nul
if exist "Setup_script.py"          copy /y "Setup_script.py"          "%OUT%\" >nul
if exist "credential_store.py"      copy /y "credential_store.py"      "%OUT%\" >nul
if exist "Task Morning BW Reports.bat"   copy /y "Task Morning BW Reports.bat"   "%OUT%\" >nul
if exist "Task Afternoon BW Reports.bat" copy /y "Task Afternoon BW Reports.bat" "%OUT%\" >nul
if exist "requirements.txt"         copy /y "requirements.txt"         "%OUT%\" >nul
if exist "setup.bat"                copy /y "setup.bat"                "%OUT%\" >nul
if exist "EASY_SETUP.md"            copy /y "EASY_SETUP.md"            "%OUT%\" >nul
if exist "README.md"                copy /y "README.md"                "%OUT%\" >nul
if exist "USER_GUIDE.md"            copy /y "USER_GUIDE.md"            "%OUT%\" >nul
if exist "Launch Bandwidth Report Manager.vbs" copy /y "Launch Bandwidth Report Manager.vbs" "%OUT%\" >nul
if exist "bw.ico"                   copy /y "bw.ico"                   "%OUT%\" >nul
for %%F in ("*.oft") do copy /y "%%F" "%OUT%\" >nul

REM --- zip it for distribution ------------------------------------
echo   [5/5] Zipping for distribution...
if exist "Bandwidth Report Manager.zip" del /q "Bandwidth Report Manager.zip"
powershell -NoProfile -Command ^
  "Compress-Archive -Path '%OUT%\*' -DestinationPath 'Bandwidth Report Manager.zip' -Force"

echo.
echo   Done!
echo   ------
echo   App folder : %OUT%\Bandwidth Report Manager.exe
echo   Sendable    : %~dp0Bandwidth Report Manager.zip
echo.
echo   NOTE: target machines still need Python + the report dependencies
echo   for the actual report scripts. Have users run setup.bat once
echo   after unzipping (it installs those and the browser engine).
echo.
pause
endlocal
