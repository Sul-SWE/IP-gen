@echo off
rem Double-click this file to start the IP Generator website on Windows.
rem Keep this window open while you use the website. Close it to stop the website.
cd /d "%~dp0backend"

where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Install Python 3.11 or newer from python.org
  echo and tick "Add Python to PATH" on the first screen of the installer.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo First run: installing the Python packages. This takes 1-2 minutes...
  python -m venv .venv || (pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || (echo Package install failed. Check the internet connection. & pause & exit /b 1)
)

start "" cmd /c "timeout /t 6 >nul & start http://localhost:8000"
".venv\Scripts\python.exe" run.py
pause
