@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
call .venv\Scripts\activate.bat
if "%API_PORT%"=="" set API_PORT=8000
set BACKEND_URL=http://localhost:%API_PORT%
python tools\smoke_test.py %*
pause
