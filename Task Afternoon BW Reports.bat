@echo off
REM Runs the afternoon report. Setup_script.py regenerates this file with
REM the exact Python path chosen during setup; this default version just
REM uses whatever Python is on PATH.
cd /d "%~dp0"
set "PY=python"
where py >nul 2>nul && set "PY=py"
%PY% "Afternoon BW Reports.py"
