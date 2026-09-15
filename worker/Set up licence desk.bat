@echo off
REM Double-click this. It is the whole job.
REM
REM The Desktop shortcut "Set up licence desk" points here. It checks the
REM Cloudflare password, asks for a new one ONLY if the saved one has stopped
REM working, and then puts the licence desk up by itself.
REM
REM The pause at the end is deliberate: double-clicked, the window would shut
REM before anything could be read.
title Construction Paper - licence desk setup
cd /d "%~dp0"
python "%~dp0setup_licence_desk.py"
echo.
echo Press any key to close this window.
pause >nul
