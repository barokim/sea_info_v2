"""로그인 상태 · 가입 · 메일 링크 인증 · 내 정보 (편성훈 뼈대 · 이종민 담당).

로그인하면 서버가 준 토큰을 st.session_state["token"]에, 내 정보를 ["user"]에 둬요.
current_user()가 돌려주는 모양: None 또는 {"id", "nickname", "character", "email", "role", ...}

실패하면 ApiError(상태, 한국어 문구, code)를 던져요 → 화면에서 st.error(e.message).
e.code 로 다음 할 일을 골라요: email_exists · email_not_verified · link_expired · expired · too_soon …

    auth.login("me@example.com", "pw")            # 성공하면 로그인 끝 (코드 입력 없음)
    auth.verify_link(token_hash, "email")         # 메일 속 링크를 누르면 /verify 화면이 불러요 → 인증 + 로그인
"""
from __future__ import annotations

import time

import streamlit as st

from services import api
from services.api import ApiError

__all__ = ["ApiError"]


def current_user() -> dict | None:
    return st.session_state.get("user")


COOKIE = "sea_token"  # 새로 고침해도 로그인이 이어지게 브라우저에 두는 로그인 토큰


def set_session(token: str, user: dict, keep: bool | None = None) -> None:
    st.session_state["token"] = token
    st.session_state["user"] = user
    st.session_state.pop("_api_cache", None)  # 다른 사람으로 보던 값이 남지 않게
    # '로그인 상태 유지'를 체크했으면 7일, 아니면 브라우저를 닫을 때까지. 어느 쪽이든 새로 고침으로는 풀리지 않아요.
    # 체크 여부는 로그인 버튼을 누를 때 _keep_login에 옮겨 둬요 (체크박스가 없는 화면, 예를 들어 가입 ②단계의 ‘인증을 마쳤어요’에서 로그인하면 값이 지워져 있어서 기본값 '유지 안 함'이에요).
    if keep is None:
        keep = bool(st.session_state.pop("_keep_login", False))
    st.session_state["_cookie_op"] = ("set", token, keep)


def clear_session() -> None:
    st.session_state.pop("token", None)
    st.session_state.pop("user", None)
    st.session_state.pop("_api_cache", None)
    st.session_state["_cookie_op"] = ("clear", "", False)


def restore_from_cookie() -> None:
    """새 탭 · 새로 고침이면 브라우저 쿠키의 토큰으로 로그인을 되살려요 (app.py가 처음에 불러요)."""
    if st.session_state.get("_cookie_checked"):
        return
    st.session_state["_cookie_checked"] = True
    if st.session_state.get("token"):
        return
    token = (st.context.cookies or {}).get(COOKIE)
    if not token:
        return
    st.session_state["token"] = token
    try:
        st.session_state["user"] = api.get("/auth/me")
    except ApiError:  # 만료됐거나 로그아웃한 토큰
        clear_session()


def flush_cookie() -> None:
    """미뤄 둔 쿠키 쓰기 · 지우기를 브라우저에 반영해요 (app.py가 매번 불러요)."""
    op = st.session_state.pop("_cookie_op", None)
    if not op:
        return
    kind, token, keep = op
    if kind == "set":
        value = f"{COOKIE}={token}; path=/; SameSite=Lax" + ("; max-age=604800" if keep else "")
    else:
        value = f"{COOKIE}=; path=/; max-age=0; SameSite=Lax"
    script = ("<script>try{window.parent.document.cookie=%r;}catch(e){document.cookie=%r;}</script>"
              % (value, value))
    with st.container(key="sia_cookie"):
        st.iframe(script, height=1)


def refresh_me() -> dict | None:
    """서버에서 내 정보를 다시 받아요 (닉네임을 바꾼 뒤 등)."""
    if not st.session_state.get("token"):
        return None
    try:
        st.session_state["user"] = api.get("/auth/me")
    except ApiError:
        clear_session()
    return current_user()


def health() -> dict:
    """서버 상태와 연동 모드. 30초 동안 기억해요."""
    cached = st.session_state.get("_health")
    if cached and time.time() - cached[0] < 30:
        return cached[1]
    data = api.get("/health")
    st.session_state["_health"] = (time.time(), data)
    return data


def dev_mode() -> bool:
    try:
        return health().get("app_env", "local") != "production"
    except ApiError:
        return False


def supabase_mode() -> bool:
    """가입 · 로그인을 Supabase가 맡는지 (아니면 로컬 대체 모드: 메일 코드로 인증)."""
    try:
        return health().get("modes", {}).get("auth") == "supabase"
    except ApiError:
        return False


def login_as(kind: str) -> None:
    """시험용 로그인 (로컬에서만). kind: 'guest' | 'member' | 'admin'"""
    if kind in ("member", "admin"):
        out = api.post("/auth/dev-login", json={"kind": kind})
        set_session(out["token"], out["user"], keep=True)
    else:
        logout()


def logout() -> None:
    if st.session_state.get("token"):
        try:
            api.post("/auth/logout")
        except ApiError:
            pass
    clear_session()


# ---------- 가입 · 메일 링크 인증 ----------
def signup(email: str, password: str, agree: bool, marketing: bool = False,
           nickname: str | None = None, character: str | None = None) -> dict:
    """{status: 'verify_email', via: 'link', email, message, expires_in, dev_link?}"""
    return api.post("/auth/signup", json={"email": email, "password": password, "agree": agree,
                                          "marketing": marketing, "nickname": nickname, "character": character})


def resend_verify(email: str) -> dict:
    return api.post("/auth/resend", json={"email": email})


def verify_link(token_hash: str, kind: str = "email") -> dict:
    """메일 속 링크 확인. kind='email' 이면 인증 + 바로 로그인, 'recovery' 면 {reset_id} 를 돌려줘요."""
    out = api.post("/auth/verify-link", json={"token_hash": token_hash, "type": kind})
    if out.get("token") and out.get("user"):
        set_session(out["token"], out["user"])
    return out


# ---------- 로그인 ----------
def login(email: str, password: str) -> dict:
    """성공하면 {status: 'ok', token, user} 이고 로그인이 끝나요."""
    out = api.post("/auth/login", json={"email": email, "password": password})
    set_session(out["token"], out["user"])
    return out


def login_with_email(email: str, password: str) -> tuple[bool, str]:
    """예전 화면용: (로그인 끝?, 안내 문구)."""
    try:
        login(email, password)
    except ApiError as e:
        return False, e.message
    return True, ""


# ---------- 비밀번호 ----------
def reset_password(email: str) -> dict:
    """{via: 'link', message, dev_link?} 메일 속 링크를 누르면 /verify 화면에서 새 비밀번호를 정해요."""
    return api.post("/auth/password/reset", json={"email": email})


def reset_confirm(reset_id: str, new_password: str) -> dict:
    return api.post("/auth/password/reset/confirm", json={"reset_id": reset_id, "new_password": new_password})


def change_password(current: str, new: str) -> dict:
    return api.post("/auth/password/change", json={"current": current, "new": new})


# ---------- 내 정보 ----------
def update_profile(**fields) -> dict:
    """nickname · character · aquarium_public · region 중 바꿀 것만. 성공하면 내 정보도 새로 고쳐요."""
    out = api.patch("/auth/me", json={k: v for k, v in fields.items() if v is not None})
    st.session_state["user"] = out
    st.session_state.pop("_api_cache", None)
    return out


def withdraw(reason: str = "") -> dict:
    out = api.delete("/auth/me", json={"reason": reason})
    clear_session()
    return out


def my_posts() -> list[dict]:
    return api.get("/me/posts")


def my_comments() -> list[dict]:
    """[{id, post, body, created, post_title, post_hidden}, ...] 최근 것부터."""
    return api.get("/me/comments")
