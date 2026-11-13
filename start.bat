@echo off
rem Double-click this file to start the IP Generator on Windows.
cd /d "%~dp0backend"

where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Install Python 3.11 or newer from python.org and tick "Add Python to PATH".
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo First run: preparing Python packages. This takes 1-2 minutes...
  python -m venv .venv || (pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || (echo Package install failed. Check the internet connection. & pause & exit /b 1)
)

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo.
  echo A settings file was created: backend\.env
  echo Fill in DATABASE_URL and ADMIN_PASSWORD in Notepad, save, close Notepad,
  echo then double-click start.bat again.
  notepad ".env"
  pause
  exit /b 0
)

start "" "http://localhost:8000"
".venv\Scripts\python.exe" run.py
pause
