"""Sea-Info Agent API 서버 (편성훈).

실행:  uvicorn backend.main:app --reload --port 8000
문서:  http://localhost:8000/docs  (모든 API를 눌러서 시험해 볼 수 있어요)

backend/routers/ 폴더의 파일마다 router 가 하나씩 있고, 여기서 자동으로 모두 연결해요.
담당자는 자기 라우터 파일만 고치면 돼요.
"""
from __future__ import annotations

import importlib
import logging
import pathlib
import pkgutil
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import routers
from backend.config import get_settings
from backend.db import init_db

log = logging.getLogger("sea_info")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    s = get_settings()
    print(f"[Sea-Info Agent API] 환경={s.app_env} · 로그인={'Supabase' if s.supabase_on else '로컬'} · "
          f"메일={'Google SMTP' if s.smtp_on else '개발 모드(터미널 출력)'} · AI={'Gemini' if s.gemini_on else '예시'} · "
          f"Jira={'연결' if s.jira_on else '미연결'}", flush=True)
    yield


app = FastAPI(title="Sea-Info Agent API", version="1.0.0", lifespan=lifespan,
              description="Streamlit 화면이 부르는 API예요. 데이터는 SQLite, 빠른 값은 Redis, 로그인은 Supabase(또는 로컬 대체)를 써요.")

for mod in pkgutil.iter_modules(routers.__path__):
    try:
        module = importlib.import_module(f"backend.routers.{mod.name}")
    except Exception as e:  # 한 사람 파일에 오류가 있어도 나머지 API는 켜지게 (터미널에 크게 알려요)
        print(f"\n[라우터 불러오기 실패] backend/routers/{mod.name}.py → {type(e).__name__}: {e}\n", flush=True)
        continue
    if hasattr(module, "router"):
        app.include_router(module.router)

_up = pathlib.Path(get_settings().upload_dir)
_up.mkdir(parents=True, exist_ok=True)
app.mount("/files", StaticFiles(directory=_up), name="files")


@app.exception_handler(Exception)
async def unexpected(request: Request, exc: Exception):
    log.exception("처리하지 못한 오류: %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "서버에 문제가 생겼어요. 잠시 뒤 다시 시도해 주세요."})
