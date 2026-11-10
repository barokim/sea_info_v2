"""생물 알아보기 창구 (편성훈). 실제 분석은 FastAPI 서버(backend/core/gemini.py)가 해요.

Gemini 키는 서버의 .env(GEMINI_API_KEY)에만 있어요. 화면 쪽에는 키가 없어요.
"""
from __future__ import annotations

import streamlit as st

from services import api, auth
from services.api import ApiError


class NotSeaCreature(Exception):
    """사진에서 바다 생물을 찾지 못했어요."""


def analyze(example: str | None = None, image_bytes: bytes | None = None, filename: str = "photo.jpg") -> dict:
    """예시 이름(소라게 · 불가사리 · 해파리) 또는 사진으로 알아봐요. 결과 dict를 돌려줘요."""
    if example or not image_bytes:
        out = api.post("/identify", data={"example": example or "소라게"})
    else:
        try:
            out = api.post("/identify", files={"file": (filename, image_bytes, "application/octet-stream")})
        except ApiError as e:
            if e.code == "not_sea_creature":
                raise NotSeaCreature(e.message) from e
            raise
    st.session_state["_usage"] = (out["left"], out["limit"])
    return out["result"]


def real_ai_on() -> bool:
    try:
        return auth.health()["modes"]["ai"] == "gemini"
    except (ApiError, KeyError):
        return False
