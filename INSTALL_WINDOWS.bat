@echo off
title iNeuron-NetSync - installer
REM Double-click this file to install iNeuron-NetSync on Windows.
REM No administrator password is needed. See HOW_TO_INSTALL.md for the full guide.
echo.
echo  iNeuron-NetSync - installer
echo  ====================================
echo  This window will show the progress. Leave it open until it says
echo  INSTALLATION COMPLETE (or STOPPED). This can take from 30 minutes to a few hours.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install\install_windows.ps1"
echo.
pause
