#!/usr/bin/env bash
# Sea-Info Agent 한 번에 실행 (Mac · Linux)
#   ./start.sh            → 설치(처음 한 번) → Redis → API 서버 → 화면, 브라우저가 열려요
#   API_PORT=8001 WEB_PORT=8502 ./start.sh   → 포트를 바꿔서 실행
# 끄기: 이 창에서 Ctrl+C 후 ./stop.sh
set -e
cd "$(dirname "$0")"
API_PORT=${API_PORT:-8000}
WEB_PORT=${WEB_PORT:-8501}
export API_PORT
say() { printf "\n▶ %s\n" "$1"; }

say "[1/6] Python 확인"
PY=$(command -v python3 || command -v python || true)
if [ -z "$PY" ] || ! "$PY" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"; then
  echo "  ✕ Python 3.10 이상이 필요해요. https://www.python.org/downloads/ 에서 설치해 주세요."; exit 1
fi
"$PY" --version

say "[2/6] 가상환경 (.venv)"
[ -d .venv ] || "$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

say "[3/6] 필요한 프로그램 설치"
if ! python tools/runtools.py need-install; then
  echo "  처음이거나 목록이 바뀌어서 설치해요. 몇 분 걸려요…"
  python -m pip install -q --upgrade pip
  python -m pip install -q -r requirements.txt
  python tools/runtools.py mark-installed
fi
echo "  ✓ 설치 완료"

say "[4/6] 환경변수 파일 (.env)"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "  .env 를 새로 만들었어요. 키를 넣으면 실제 서비스로 바뀌어요 (지금은 로컬 대체 모드)."
else
  echo "  ✓ .env 있음"
fi
mkdir -p logs .run data

say "[5/6] Redis"
if ! python tools/runtools.py redis-ping; then
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    docker compose up -d redis
  elif command -v redis-server >/dev/null 2>&1; then
    echo "  Docker가 없어서 이 컴퓨터의 redis-server로 켜요."
    redis-server --daemonize yes --appendonly yes --dir "$PWD/data" && touch .run/redis_local
  else
    echo "  ✕ Redis를 켤 수 없어요. Docker Desktop을 설치하고 실행한 뒤 다시 해 주세요."; exit 1
  fi
fi
python tools/runtools.py wait-redis 30

say "[6/6] API 서버 → 화면"
if [ -f .run/api.pid ] && kill -0 "$(cat .run/api.pid)" 2>/dev/null; then
  echo "  API 서버가 이미 켜져 있어요."
else
  nohup python -m uvicorn backend.main:app --host 127.0.0.1 --port "$API_PORT" > logs/api.log 2>&1 &
  echo $! > .run/api.pid
fi
python tools/runtools.py wait-api 60

export BACKEND_URL="http://localhost:$API_PORT"
echo
echo "  화면 주소: http://localhost:$WEB_PORT   (끄려면 Ctrl+C, 모두 끄려면 ./stop.sh)"
echo $$ > .run/web.pid   # stop.sh 가 이 화면만 끌 수 있게 기억해요
# shellcheck disable=SC2086
exec python -m streamlit run app.py --server.port "$WEB_PORT" ${STREAMLIT_ARGS:-}
