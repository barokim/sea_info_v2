#!/usr/bin/env bash
# Sea-Info Agent 끄기 (Mac · Linux). Redis 데이터와 data/sea_info.db 는 그대로 남아요.
cd "$(dirname "$0")"
if [ -f .run/api.pid ]; then kill "$(cat .run/api.pid)" 2>/dev/null && echo "✓ API 서버를 껐어요."; rm -f .run/api.pid; fi
if [ -f .run/web.pid ]; then kill "$(cat .run/web.pid)" 2>/dev/null && echo "✓ 화면(Streamlit)을 껐어요."; rm -f .run/web.pid; fi
if [ -f .run/redis_local ]; then redis-cli shutdown nosave >/dev/null 2>&1; rm -f .run/redis_local; echo "✓ Redis를 껐어요."
elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then docker compose stop redis >/dev/null 2>&1 && echo "✓ Redis(Docker)를 멈췄어요."; fi
echo "모두 껐어요."
