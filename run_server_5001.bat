@echo off
cd /d "%~dp0"
set PORT=5001
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" serve.py --backup-dir "D:\BlanksBackups"
) else (
  python serve.py --backup-dir "D:\BlanksBackups"
)
pause
