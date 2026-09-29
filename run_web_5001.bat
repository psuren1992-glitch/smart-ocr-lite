@echo off
cd /d "%~dp0"
set PORT=5001
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" webapp.py
) else (
  python webapp.py
)
pause
