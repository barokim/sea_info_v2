#!/usr/bin/env bash
# 모든 화면을 비회원 · 회원 · 관리자로 열어 보고 오류를 찾아요. 마지막 줄이 '문제 0건'이면 통과.
# (먼저 ./start.sh 로 API 서버가 켜져 있어야 해요)
cd "$(dirname "$0")"
source .venv/bin/activate 2>/dev/null || true
API_PORT=${API_PORT:-8000} BACKEND_URL="http://localhost:${API_PORT:-8000}" python tools/smoke_test.py "$@"
