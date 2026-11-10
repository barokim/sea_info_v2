"""커뮤니티 · 게시판 빌더 데이터 도우미 (차유진 담당). 이제 FastAPI 서버를 불러요.

검사(게시판 상태 · 권한 · 금칙어 · 연속 글쓰기 간격 · 사용자 정의 항목)는 모두 서버가 해요.
서버가 칸별 안내를 주면 Problem.errors = {칸: 안내} 로 받아서 화면이 그 칸 아래에 보여줘요.

    try:
        pid = cd.create_post("dive", title, body, extra)
    except cd.Problem as e:
        errs = cd.write_errors(e)      # {"title": ..., "depth": ..., "_wait": ...}
"""
from __future__ import annotations

from datetime import date

import httpx
import streamlit as st

from backend.schemas import community as rules
from services import api, auth, db
from services.api import ApiError

PERM_LEVELS = rules.PERM_LEVELS
STATUSES = rules.STATUSES
BOARD_TYPES = rules.BOARD_TYPES
LAYOUTS = rules.LAYOUTS
SORTS = rules.SORTS
SEARCH_FIELDS = rules.SEARCH_FIELDS
PERM_NAMES = rules.PERM_NAMES
REPORT_REASONS = rules.REPORT_REASONS
SYSTEM_BOARDS = rules.SYSTEM_BOARDS
LOG_SCREEN = "게시판 관리"

BOARD_DEFAULTS = {
    "page_size": 20,
    "sort": "latest",
    "search": ["제목", "생물 이름"],
    "pin_notice": True,
    "rules": {"comment": True, "like": True, "report": True, "interval": 30},
    "manager": "운영자 바다",
    "period": None,
}


# ---------- 서버 부르기 (칸별 안내까지 받아요) ----------
class Problem(ApiError):
    """ApiError + 서버가 준 칸별 안내(errors)와 자세한 값(detail)."""

    def __init__(self, status: int, message: str, code: str = "", detail=None):
        super().__init__(status, message, code)
        self.detail = detail if isinstance(detail, dict) else {}
        self.errors: dict[str, str] = dict(self.detail.get("errors") or {})


def _call(method: str, path: str, **kw):
    """services/api.request 와 같아요. 다만 실패하면 칸별 안내가 담긴 Problem 을 던져요."""
    try:
        r = api._client.request(method, path, headers=api._headers(), **kw)
    except httpx.TimeoutException:
        raise ApiError(0, "서버 응답이 너무 늦어요. 잠시 뒤 다시 시도해 주세요.")
    except httpx.HTTPError:
        raise ApiError(0, f"서버(FastAPI)에 연결하지 못했어요. 설치 가이드대로 백엔드를 켰는지 확인해 주세요. ({api.BASE})")
    if r.status_code == 401 and st.session_state.get("token"):
        auth.clear_session()  # 로그인이 만료됐어요
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = r.text
        msg, code = api._message(detail, r.status_code)
        raise Problem(r.status_code, msg, code, detail)
    return r.json() if r.content else None


def _changed(out=None):
    db.clear_cache()
    return out


# ---------- 권한 · 게시판 설정 ----------
def can(user: dict | None, level: str) -> bool:
    if level == "모두":
        return True
    if level == "회원":
        return user is not None
    return bool(user and user.get("role") == "admin")


def is_admin(user: dict | None) -> bool:
    return bool(user and user.get("role") == "admin")


def opt(b: dict, name: str):
    """게시판 설정 값 (화면이 쓰는 이름으로). 서버의 rules.comments 는 화면에서 rules['comment'] 예요."""
    if name == "rules":
        r = {**rules.DEFAULT_RULES, **(b.get("rules") or {})}
        return {"comment": bool(r["comments"]), "like": bool(r["likes"]), "report": bool(r["reports"]),
                "interval": int(r.get("interval") or 0)}
    if name == "search":
        return list(b.get("search_fields") or BOARD_DEFAULTS["search"])
    if name == "period":
        p = b.get("period") or ""
        parts = [x.strip() for x in p.split("~")] if p else []
        return parts if len(parts) == 2 else None
    return b.get(name, BOARD_DEFAULTS.get(name))


def visible_boards(user: dict | None) -> list[dict]:
    """고객 화면 탭: 운영 중 + 목록 보기 권한이 있는 것, 정한 순서대로."""
    return [b for b in db.boards() if can(user, b["perm"]["list"])]


def writable_boards(user: dict | None) -> list[dict]:
    """글쓰기 화면에서 고를 수 있는 게시판. 관찰 이야기는 생물 알아보기에서만 올라가요."""
    return [b for b in db.boards() if b["id"] != "obs" and can(user, b["perm"]["write"])
            and (b["perm"]["write"] != "모두" or user)]


# ---------- 게시글 ----------
def list_posts(b: dict, q: str = "", sort: str = "latest") -> list[dict]:
    """게시판 설정(검색 항목 · 공지 고정 · 목록 권한)은 서버가 따라요."""
    return api.get("/posts", params={"board": b["id"], "q": (q or "").strip(), "sort": sort})


def get_post(pid: str) -> tuple[dict | None, dict | None]:
    """(글, 막힘). 읽기 권한이 없으면 글 대신 {"board", "level", "message"} 를 돌려줘요."""
    try:
        return _call("GET", f"/posts/{pid}"), None
    except Problem as e:
        if e.status == 404:
            return None, None
        if e.status == 403 and e.detail.get("board"):
            return None, {"board": e.detail["board"], "level": e.detail.get("level", "회원"), "message": e.message}
        raise


def upload_photo(file) -> str:
    """올린 사진(st.file_uploader 값)을 서버에 맡기고 사진 번호를 받아요."""
    out = _call("POST", "/posts/photos", files={"file": (file.name, file.getvalue(), file.type or "image/jpeg")})
    return out["id"]


def create_post(board_id: str, title: str, body: str, extra: dict, photo_id: str | None = None,
                consent: bool = False) -> str:
    out = _call("POST", "/posts", json={"board": board_id, "title": title, "body": body, "extra": extra,
                                        "photo_id": photo_id, "photo_consent": consent})
    return _changed(out["id"])


def update_post(pid: str, title: str, body: str, extra: dict, photo_id: str | None = None,
                consent: bool = False) -> dict:
    """‘사용 안 함’ 항목 값은 서버가 그대로 남겨요."""
    out = _call("PATCH", f"/posts/{pid}", json={"title": title, "body": body, "extra": extra,
                                                 "photo_id": photo_id, "photo_consent": consent})
    return _changed(out)


def delete_post(pid: str) -> str:
    """관찰 이야기 글이면 수족관 기록은 남기고 ‘나만 보기’로 (서버가 해요)."""
    return _changed(_call("DELETE", f"/posts/{pid}"))["message"]


def write_errors(e: Problem) -> dict:
    """서버 안내 → 글쓰기 화면의 칸 key ({"title", "body", "photo", <항목 key>, "_wait", "_other"})."""
    if e.status == 429:
        return {"_wait": e.message}
    if not e.errors:
        return {"_other": e.message}
    out = {}
    for k, v in e.errors.items():
        k = k.removeprefix("extra.")
        if k in ("board", "species", "place", "_"):
            out.setdefault("_other", v)
        else:
            out[k] = v
    return out


# ---------- 댓글 · 공감 · 신고 ----------
def comments_for(p: dict) -> list[dict]:
    return db.comments(p["id"])


def add_comment(pid: str, body: str) -> dict:
    return _changed(_call("POST", f"/posts/{pid}/comments", json={"body": body}))


def delete_comment(comment_id: str) -> None:
    _changed(_call("DELETE", f"/comments/{comment_id}"))


def toggle_like(pid: str) -> dict:
    """{"liked", "likes"}"""
    return _changed(_call("POST", f"/posts/{pid}/like"))


def is_liked(pid: str) -> bool:
    if not auth.current_user():
        return False
    try:
        return bool(_call("GET", f"/posts/{pid}/like")["liked"])
    except ApiError:
        return False


def reported(pid: str, uid: str | None = None) -> bool:
    if not auth.current_user():
        return False
    try:
        return bool(_call("GET", f"/posts/{pid}/report")["reported"])
    except ApiError:
        return False


def report(pid: str, reason: str, detail: str = "") -> str:
    """신고를 남겨요. 쌓인 신고가 운영 설정 횟수 이상이면 서버가 글을 숨겨요. 안내 문구를 돌려줘요."""
    return _changed(_call("POST", f"/posts/{pid}/report", json={"reason": reason, "detail": detail or ""}))["message"]


# ---------- 게시판 관리 (A-02) ----------
BOARD_ERR_KEYS = {"id": "slug", "search_fields": "search", "rules.interval": "interval", "pin_notice": "pin"}


def board_errors(e: Problem) -> dict:
    """서버 안내 → 게시판 양식 칸 key. 칸이 없는 안내는 "_other"."""
    if not e.errors:
        return {"_other": e.message}
    out = {}
    for k, v in e.errors.items():
        k = BOARD_ERR_KEYS.get(k, k)
        if k.startswith("perm."):
            k = "perm"
        out.setdefault(k, v)
    return out


def board_payload(v: dict, is_new: bool) -> dict:
    """양식 값 → 서버에 보낼 모양."""
    period = [d.isoformat() for d in (v.get("period") or ()) if isinstance(d, date)]
    data = {
        "name": (v.get("name") or "").strip(), "desc": (v.get("desc") or "").strip(), "type": v.get("type"),
        "manager": (v.get("manager") or "").strip(), "period": period or None, "status": v.get("status") or "준비 중",
        "layout": v.get("layout"), "page_size": int(v.get("page_size") or 20), "sort": v.get("sort"),
        "search_fields": list(v.get("search") or []), "pin_notice": bool(v.get("pin")),
        "rules": {"comments": bool(v.get("r_comment")), "likes": bool(v.get("r_like")),
                  "reports": bool(v.get("r_report")), "interval": int(v.get("interval") or 0)},
        "perm": {k: v.get(f"perm_{k}") or rules.DEFAULT_PERM[k] for k in PERM_NAMES},
    }
    if is_new:
        data["id"] = (v.get("slug") or "").strip()
    return data


def create_board(data: dict) -> dict:
    return _changed(_call("POST", "/admin/boards", json=data))


def update_board(bid: str, data: dict) -> dict:
    return _changed(_call("PATCH", f"/admin/boards/{bid}", json=data))


def save_order(ids: list[str], status: dict[str, str]) -> list[dict]:
    return _changed(_call("PUT", "/admin/boards/order", json={"ids": ids, "status": status}))


def delete_board(bid: str) -> str:
    return _changed(_call("DELETE", f"/admin/boards/{bid}"))["message"]


def add_field(bid: str, field: dict, order: int) -> dict:
    return _changed(_call("POST", f"/admin/boards/{bid}/fields", json={**field, "order": order}))


def update_field(bid: str, key: str, changes: dict) -> dict:
    """{"board", "impact"} — impact: 유형 · 선택지를 바꿔 이미 쓴 글에 생길 일."""
    return _changed(_call("PATCH", f"/admin/boards/{bid}/fields/{key}", json=changes))


def delete_field(bid: str, key: str) -> None:
    _changed(_call("DELETE", f"/admin/boards/{bid}/fields/{key}"))


def stats() -> dict:
    """{게시판: {"posts": 글 수, "fields": {항목 key: 쓴 글 수}}} (관리자만)."""
    return db._cached("board_stats", lambda: api.get("/admin/boards/stats"), ttl=10)


def count_posts(board_id: str) -> int:
    return int((stats().get(board_id) or {}).get("posts", 0))


def field_used(board_id: str, key: str) -> int:
    """이 항목에 값이 들어 있는 글 수."""
    return int(((stats().get(board_id) or {}).get("fields") or {}).get(key, 0))


def logs() -> list[dict]:
    """게시판 관리 변경 기록 (최근 순): when · who · target · action · before · after."""
    return db._cached("board_logs", lambda: api.get("/admin/boards/logs"), ttl=10)
