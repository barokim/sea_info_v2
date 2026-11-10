"""FastAPI 서버를 부르는 창구 (편성훈). 화면 파일은 이걸 직접 쓰지 않고 services/*.py 함수를 써요.

    from services import api
    posts = api.get("/posts", params={"board": "obs"})
    api.post("/posts/p1/comments", json={"body": "멋져요!"})

서버 주소는 환경변수 BACKEND_URL (기본 http://localhost:8000).
실패하면 ApiError(상태 코드, 사용자에게 보여줄 한국어 문구)를 던져요 → 화면에서 st.error(e.message).
"""
from __future__ import annotations

import os
import uuid
from typing import Any

import httpx
import streamlit as st

BASE = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")
_client = httpx.Client(base_url=BASE, timeout=45)


class ApiError(Exception):
    def __init__(self, status: int, message: str, code: str = ""):
        super().__init__(message)
        self.status, self.message, self.code = status, message, code


def _headers() -> dict:
    h = {"X-Guest-Id": st.session_state.setdefault("_guest_id", uuid.uuid4().hex)}
    ip = getattr(st.context, "ip_address", None)
    if ip:
        h["X-Client-Ip"] = str(ip)
    if token := st.session_state.get("token"):
        h["Authorization"] = f"Bearer {token}"
    return h


def _message(detail: Any, status: int) -> tuple[str, str]:
    if isinstance(detail, str):
        return detail, ""
    if isinstance(detail, dict):
        return detail.get("message", "요청을 처리하지 못했어요."), detail.get("code", "")
    if isinstance(detail, list):  # pydantic 입력 검사 오류
        msgs = [str(d.get("msg", "")).removeprefix("Value error, ") for d in detail if isinstance(d, dict)]
        return " ".join(m for m in msgs if m) or "입력한 내용을 한 번 더 확인해 주세요.", "validation"
    return f"요청을 처리하지 못했어요. ({status})", ""


def request(method: str, path: str, **kw) -> Any:
    try:
        r = _client.request(method, path, headers=_headers(), **kw)
    except httpx.TimeoutException:
        raise ApiError(0, "서버 응답이 너무 늦어요. 잠시 뒤 다시 시도해 주세요.")
    except httpx.HTTPError:
        raise ApiError(0, f"서버(FastAPI)에 연결하지 못했어요. 설치 가이드대로 백엔드를 켰는지 확인해 주세요. ({BASE})")
    if r.status_code == 401 and st.session_state.get("token"):
        st.session_state.pop("token", None)  # 로그인이 만료됐어요
        st.session_state.pop("user", None)
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = r.text
        msg, code = _message(detail, r.status_code)
        raise ApiError(r.status_code, msg, code)
    return r.json() if r.content else None


def get(path: str, **kw) -> Any:
    return request("GET", path, **kw)


def post(path: str, **kw) -> Any:
    return request("POST", path, **kw)


def put(path: str, **kw) -> Any:
    return request("PUT", path, **kw)


def patch(path: str, **kw) -> Any:
    return request("PATCH", path, **kw)


def delete(path: str, **kw) -> Any:
    return request("DELETE", path, **kw)


def file_url(path: str) -> str:
    """API가 준 '/files/xxx.jpg' 를 브라우저에서 열 수 있는 주소로."""
    return f"{BASE}{path}" if path else ""
