@echo off
REM End-user wrapper (Windows). Usage: run.bat "C:\path\to\recording"
REM The folder must contain a suite2p\ subfolder and a config.json.
REM You can also drag-and-drop the recording folder onto this file.

set IMAGE=ghcr.io/samuelchu030609-commits/calcium-network-pipeline:latest

if "%~1"=="" (
  echo Usage: run.bat "C:\path\to\recording"
  echo   (the folder that contains suite2p\ and config.json^)
  pause
  exit /b 1
)

set FOLDER=%~f1
echo Running pipeline on: %FOLDER%
docker run --rm -v "%FOLDER%:/data" %IMAGE% /data
echo Done. Look for *_metrics.xlsx inside %FOLDER%\suite2p\plane0\
pause
