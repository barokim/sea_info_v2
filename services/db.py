"""데이터 창구 (편성훈). 이제 예시 JSON 대신 FastAPI 서버를 불러요.

함수 이름과 돌려주는 모양은 시안 때와 같아요. 그래서 화면 코드는 거의 그대로예요.
- 여러 화면이 같이 쓰는 조회 함수는 여기 있어요.
- 각 담당 기능의 쓰기 · 관리 함수는 담당자 모듈에 있어요
  (services/community_data.py · aquarium_data.py · news_data.py · admin_data.py · auth.py).
API 목록은 docs/API_목록.md 또는 서버를 켜고 http://localhost:8000/docs 에서 볼 수 있어요.
"""
from __future__ import annotations

import time

import streamlit as st

from services import api
from services.api import ApiError

__all__ = ["ApiError"]


def _cached(key: str, fn, ttl: int = 30):
    """같은 화면을 다시 그릴 때 같은 요청을 반복하지 않게 잠깐 기억해요 (세션별)."""
    box = st.session_state.setdefault("_api_cache", {})
    hit = box.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    box[key] = (time.time(), val)
    return val


def clear_cache() -> None:
    """데이터를 바꾼 뒤 부르면 다음 화면에서 새 값을 받아요."""
    st.session_state.pop("_api_cache", None)


def table(name: str):
    raise RuntimeError(f"db.table('{name}')은 더 이상 쓰지 않아요. FastAPI 함수(services/*.py)를 써 주세요.")


# ---------- 생물 ----------
def all_species() -> list[dict]:
    return _cached("species", lambda: api.get("/species"), ttl=60)


def species(species_id: str) -> dict | None:
    if not species_id:
        return None
    hit = next((s for s in all_species() if s["id"] == species_id), None)
    if hit:
        return hit
    try:  # AI가 새로 알려준 생물
        clear_cache()
        return api.get(f"/species/{species_id}")
    except ApiError:
        return None


# ---------- 회원 ----------
def user(user_id: str) -> dict:
    return _cached(f"user:{user_id}", lambda: api.get(f"/users/{user_id}"), ttl=60)


# ---------- 게시판 · 게시글 (조회) ----------
def boards(active_only: bool = True) -> list[dict]:
    return _cached(f"boards:{active_only}", lambda: api.get("/boards", params={"all": not active_only}), ttl=10)


def board(board_id: str) -> dict | None:
    return next((b for b in boards(active_only=False) if b["id"] == board_id), None)


def posts(board_id: str | None = None, q: str = "", sort: str = "latest") -> list[dict]:
    params = {"q": q, "sort": sort}
    if board_id:
        params["board"] = board_id
    return api.get("/posts", params=params)


def post(post_id: str) -> dict | None:
    try:
        return api.get(f"/posts/{post_id}")
    except ApiError as e:
        if e.status == 404:
            return None
        raise


def recent_posts(n: int = 6) -> list[dict]:
    return api.get("/posts/recent", params={"n": n})


def comments(post_id: str) -> list[dict]:
    return api.get(f"/posts/{post_id}/comments")


# ---------- 게시판 · 게시글 (쓰기: API는 차유진 담당, 아래는 얇은 창구) ----------
def add_comment(post_id: str, user_id: str, body: str) -> dict:
    return api.post(f"/posts/{post_id}/comments", json={"body": body})


def toggle_like(post_id: str, user_id: str) -> bool:
    return api.post(f"/posts/{post_id}/like")["liked"]


def is_liked(post_id: str, user_id: str) -> bool:
    try:
        return api.get(f"/posts/{post_id}/like")["liked"]
    except ApiError:
        return False


def add_post(board_id: str, user_id: str, title: str, body: str, extra: dict | None = None,
             species_id: str | None = None, place: str = "", place_level: str = "none") -> str:
    out = api.post("/posts", json={"board": board_id, "title": title, "body": body, "extra": extra or {},
                                   "species": species_id, "place": place, "place_level": place_level})
    return out["id"]


def report_post(post_id: str, reason: str) -> None:
    api.post(f"/posts/{post_id}/report", json={"reason": reason})


def reports() -> list[dict]:
    return api.get("/admin/reports")


# ---------- 수족관 ----------
def observations(user_id: str | None = None) -> list[dict]:
    return api.get("/me/observations")


def aquarium(user_id: str | None = None) -> list[dict]:
    return api.get("/me/aquarium")


def add_observation(user_id: str, result: dict, when: str, place: str, memo: str, share: bool,
                    title: str = "", place_level: str = "none") -> dict:
    """담기(+선택 공유)를 서버에서 한 번에 처리해요. 둘 중 하나라도 실패하면 아무것도 남지 않아요."""
    out = api.post("/identify/save", json={"result": result, "date": when, "place": place, "memo": memo,
                                           "share": share, "title": title, "place_level": place_level,
                                           "consent": share})
    clear_cache()
    return out


# ---------- 물때 ----------
def regions() -> dict:
    return _cached("regions", lambda: api.get("/tide/regions"), ttl=300)


def tide(region_id: str) -> dict:
    return api.get(f"/tide/{region_id}")


# ---------- 설정 · 횟수 ----------
def settings() -> dict:
    return _cached("settings", lambda: api.get("/settings/public"), ttl=30)


def remaining(user: dict | None = None) -> tuple[int, int]:
    """(남은 횟수, 하루 횟수)"""
    u = api.get("/usage")
    return u["left"], u["limit"]


def use_one() -> None:
    """횟수는 이제 서버(Redis)가 결과를 준 경우에만 세요. 남겨 둔 빈 함수예요."""


# ---------- 바다 소식 (조회) ----------
def news(public_only: bool = True) -> list[dict]:
    return api.get("/news")


def latest_news(n: int = 3) -> list[dict]:
    return api.get("/news/latest", params={"n": n})


def top_news(n: int = 5) -> list[dict]:
    return api.get("/news/top", params={"n": n})


# ---------- 제보 · 건의 (API는 김바로 담당) ----------
def inquiries(user_id: str | None = None) -> list[dict]:
    return api.get("/me/inquiries")
