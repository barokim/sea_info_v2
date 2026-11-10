"""로그인 · 내 정보 · 관리자 화면이 같이 쓰는 데이터 도우미 (이종민 담당).

이제 FastAPI 서버(/admin/* · /me/*)를 불러요. 바꾸는 함수는 실패하면 ApiError(한국어 문구)를 던져요.
관리자 조치 기록(누가 · 언제 · 무엇을 · 왜)은 서버가 같은 저장 안에서 남겨요.
    admin_data.hide_post("p9", "스팸·광고")       # 숨기기 (+ 기록)
    admin_data.pending_reports()                   # 대기 중인 신고 (글마다 묶음)
    admin_data.member_rows()                       # 회원 표
"""
from __future__ import annotations

import html
from datetime import date, timedelta

import streamlit as st

from components import ui
from services import api, auth, db
from services.api import ApiError

__all__ = ["ApiError"]

# 가입할 때 · 내 정보에서 고르는 바다 캐릭터 (서버 backend/schemas/auth.py 와 같아요)
CHARACTERS = {"🐢": "거북", "🐬": "돌고래", "🦭": "물범", "🐠": "열대어", "🐳": "고래",
              "🐚": "조개", "🦀": "게", "⭐": "불가사리", "🪼": "해파리", "🦑": "오징어"}

ACTION_REASONS = ["스팸·광고", "욕설·비방", "개인정보 노출", "주제와 맞지 않음", "기타"]
SUSPEND_DAYS = {"3일": 3, "7일": 7, "30일": 30, "영구": None}
POST_STATUS = {"전체": "all", "공개 중": "public", "숨김": "hidden", "신고 있음": "reported"}
MEMBER_STATUS = {"전체": "all", "이용 중": "active", "이용 정지": "suspended", "신고 받은 회원": "reported"}


def _changed() -> None:
    db.clear_cache()


# ---------- 대시보드 ----------
def dashboard() -> dict:
    return api.get("/admin/dashboard")


# ---------- 조치 기록 ----------
def logs(screens: tuple[str, ...] | None = None, limit: int = 100) -> list[dict]:
    params = {"limit": limit}
    if screens:
        params["screen"] = ",".join(screens)
    return api.get("/admin/logs", params=params)


def log_rows(screens: tuple[str, ...] | str | None = None, limit: int = 100, rows: list[dict] | None = None) -> list[dict]:
    """표에 넣기 좋은 모양."""
    if isinstance(screens, str):
        screens = (screens,)
    out = []
    for r in rows if rows is not None else logs(screens, limit):
        out.append({"언제": r.get("when", ""), "누가": r.get("who", ""), "무엇을": r.get("what", ""),
                    "대상": r.get("target", ""), "왜": r.get("why", "") or "-"})
    return out


def settings_logs(limit: int = 100) -> list[dict]:
    return [{"언제": r["when"], "누가": r["who"], "항목": r["target"], "바꾸기 전": r["before"], "바꾼 후": r["after"]}
            for r in logs(("운영 설정",), limit)]


# ---------- 게시물 · 신고 ----------
def admin_posts(q: str = "", board: str = "all", status: str = "전체") -> dict:
    """{items: [...], total, hidden, reported}. status는 화면 글자(전체 · 공개 중 · 숨김 · 신고 있음)."""
    return api.get("/admin/posts", params={"q": q, "board": "" if board == "all" else board,
                                           "status": POST_STATUS.get(status, "all")})


def hide_post(post_id: str, reason: str) -> str:
    out = api.post(f"/admin/posts/{post_id}/hide", json={"reason": reason})
    _changed()
    return out.get("message", "")


def restore_post(post_id: str, reason: str) -> str:
    out = api.post(f"/admin/posts/{post_id}/restore", json={"reason": reason})
    _changed()
    return out.get("message", "")


def delete_post(post_id: str, reason: str) -> str:
    out = api.delete(f"/admin/posts/{post_id}", json={"reason": reason})
    _changed()
    return out.get("message", "")


def reports(status: str | None = None) -> list[dict]:
    """신고 묶음 [{post, title, board, author, body, hidden, deleted, reason, reasons, count, date, status}]"""
    return api.get("/admin/reports", params={"status": status} if status else None)


def report_status(r: dict) -> str:
    return r.get("status", "대기")


def pending_reports() -> list[dict]:
    return reports("대기")


def resolve_report(post_id: str, action: str, reason: str = "") -> str:
    """action: 'hide'(숨기기) | 'dismiss'(문제없음)"""
    out = api.post(f"/admin/reports/{post_id}/resolve", json={"action": action, "reason": reason})
    _changed()
    return out.get("message", "")


def post_look(p: dict | None) -> tuple[str, str]:
    """글을 보여줄 사진 자리 (이모지, 톤)."""
    sp = db.species(p.get("species") or "") if p else None
    return (sp["emoji"], sp.get("tone", "aqua")) if sp else ("🌊", "aqua")


def board_name(board_id: str) -> str:
    b = db.board(board_id)
    return b["name"] if b else board_id


# ---------- 내 활동 ----------
def my_posts(user_id: str | None = None) -> list[dict]:
    return auth.my_posts()


def my_comments(user_id: str | None = None) -> list[tuple[dict, dict]]:
    """[(글, 댓글), ...] 최근 것부터. 글은 {id, title, hidden}만 있어요."""
    return [({"id": c["post"], "title": c.get("post_title", ""), "hidden": c.get("post_hidden", False)}, c)
            for c in auth.my_comments()]


# ---------- 회원 ----------
def mask_email(email: str) -> str:
    if "@" not in (email or ""):
        return email or "-"
    name, host = email.split("@", 1)
    return f"{name[:2]}{'*' * max(len(name) - 2, 2)}@{host}"


def member_rows(q: str = "", status: str = "전체") -> list[dict]:
    """[{id, nickname, character, email, joined, posts, reports, role, status, suspended, public, recent}]"""
    return api.get("/admin/members", params={"q": q, "status": MEMBER_STATUS.get(status, "all")})


def member(user_id: str) -> dict | None:
    try:
        return api.get(f"/admin/members/{user_id}")
    except ApiError as e:
        if e.status == 404:
            return None
        raise


def suspend(user_id: str, period: str, reason: str, memo: str = "") -> dict:
    out = api.post(f"/admin/members/{user_id}/suspend",
                   json={"days": SUSPEND_DAYS.get(period, 7), "reason": reason, "memo": memo})
    _changed()
    return out


def unsuspend(user_id: str) -> dict:
    out = api.post(f"/admin/members/{user_id}/unsuspend", json={"reason": "관리자가 해제"})
    _changed()
    return out


def suspend_until(period: str) -> str:
    days = SUSPEND_DAYS.get(period)
    return f"{date.today() + timedelta(days=days):%Y-%m-%d}까지" if days else "영구"


# ---------- 운영 설정 ----------
def settings_full() -> dict:
    return api.get("/admin/settings")


def save_settings(values: dict) -> dict:
    """{settings, changed, message}. 잘못된 값이면 ApiError (e.code: limit · formats · region · validation)."""
    out = api.put("/admin/settings", json=values)
    _changed()
    return out


# ---------- 화면 조각 (Streamlit 글 상자 아래 여백 보정) ----------
# Streamlit 1.67의 글 상자(stMarkdownContainer)는 아래 여백이 -1rem이라,
# 문단(p) 여백이 없는 ui.item_row · ui.muted가 테두리 상자 맨 아래에 오면 테두리에 붙어요.
# 같은 모양에 1rem 받침만 더해서 써요. (공통 CSS가 고쳐지면 ui.item_row · ui.muted로 바꿔도 돼요)
_PAD = '<div style="height:1rem"></div>'


def item_row(emoji: str, title: str, sub: str = "", tone: str = "aqua", size: int = 56) -> None:
    sub_html = f'<span class="sia-muted">{html.escape(sub)}</span>' if sub else ""
    st.markdown(f'<div class="sia-item">{ui.photo_html(emoji, tone, size, width=size)}'
                f'<div><b>{html.escape(title)}</b><br>{sub_html}</div></div>{_PAD}', unsafe_allow_html=True)


def muted(text: str) -> None:
    st.markdown(f'<p class="sia-muted">{html.escape(text)}</p>{_PAD}', unsafe_allow_html=True)


def text_row(title: str, sub: str = "") -> None:
    """사진 없이 제목 + 보조 글 한 줄 (item_row와 같은 글자 모양)."""
    sub_html = f'<br><span class="sia-muted">{html.escape(sub)}</span>' if sub else ""
    st.markdown(f'<div class="sia-item"><div><b>{html.escape(title)}</b>{sub_html}</div></div>{_PAD}',
                unsafe_allow_html=True)
