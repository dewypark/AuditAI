@echo off
cd /d "%~dp0"
py -m pip install -r requirements.txt
if errorlevel 1 (
  echo Dependency installation failed. Check Python and network.
  pause
  exit /b 1
)
echo Open http://127.0.0.1:5000 in your browser.
py app.py
pause
