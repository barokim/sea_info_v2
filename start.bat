@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if "%API_PORT%"=="" set API_PORT=8000
if "%WEB_PORT%"=="" set WEB_PORT=8501

echo.
echo [1/6] Python 확인
set PY=python
where py >nul 2>nul && set PY=py -3
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" || (echo   Python 3.10 이상을 설치해 주세요: https://www.python.org/downloads/ ^(설치할 때 Add python.exe to PATH 체크^) & pause & exit /b 1)

echo [2/6] 가상환경 (.venv)
if not exist .venv %PY% -m venv .venv
call .venv\Scripts\activate.bat

echo [3/6] 필요한 프로그램 설치
python tools\runtools.py need-install
if errorlevel 1 (
  echo   처음이거나 목록이 바뀌어서 설치해요. 몇 분 걸려요...
  python -m pip install -q --upgrade pip
  python -m pip install -q -r requirements.txt || (echo   설치에 실패했어요. 인터넷 연결을 확인해 주세요. & pause & exit /b 1)
  python tools\runtools.py mark-installed
)

echo [4/6] 환경변수 파일 (.env)
if not exist .env (copy .env.example .env >nul & echo   .env 를 새로 만들었어요. 키를 넣으면 실제 서비스로 바뀌어요.)
if not exist logs mkdir logs
if not exist data mkdir data

echo [5/6] Redis (Docker)
python tools\runtools.py redis-ping
if errorlevel 1 (
  docker compose up -d redis || (echo   Docker Desktop을 설치하고 실행한 뒤 다시 해 주세요. & pause & exit /b 1)
)
python tools\runtools.py wait-redis 30 || (pause & exit /b 1)

echo [6/6] API 서버 - 화면
start "Sea-Info API" /min cmd /c "python -m uvicorn backend.main:app --host 127.0.0.1 --port %API_PORT% > logs\api.log 2>&1"
python tools\runtools.py wait-api 60 || (pause & exit /b 1)
set BACKEND_URL=http://localhost:%API_PORT%
echo.
echo   화면 주소: http://localhost:%WEB_PORT%   (끄려면 이 창에서 Ctrl+C, 모두 끄려면 stop.bat)
python -m streamlit run app.py --server.port %WEB_PORT%
