@echo off
REM Launch the stages 2-3 GUI (Windows).  Double-click this file, or run it from cmd.
REM Opens a local web page in your browser. Nothing is uploaded; it runs on this PC.
setlocal
set "HERE=%~dp0"

REM Skip Streamlit's one-time "enter your email" prompt (blocks startup on a fresh PC).
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
  if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
  > "%USERPROFILE%\.streamlit\credentials.toml" echo [general]
  >> "%USERPROFILE%\.streamlit\credentials.toml" echo email = ""
)
set STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

where conda >nul 2>&1
if %ERRORLEVEL%==0 (
  conda env list | findstr /R /C:"\\gui$" >nul 2>&1
  if %ERRORLEVEL%==0 (
    conda run --no-capture-output -n gui python -m streamlit run "%HERE%app.py"
    goto :eof
  )
)

python -c "import streamlit" >nul 2>&1
if %ERRORLEVEL%==0 (
  python -m streamlit run "%HERE%app.py"
  goto :eof
)

echo Streamlit is not installed. Create the GUI env once with:
echo   conda env create -f "%HERE%..\envs\gui.yml"
echo or install it into any env with:  pip install streamlit pandas openpyxl
exit /b 1
