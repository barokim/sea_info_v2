"""로그인 제공자 (이종민). 환경변수에 따라 Supabase 또는 로컬(SQLite)로 가입 · 로그인 · 메일 인증을 해요.

- Supabase 모드 (SUPABASE_URL · SUPABASE_ANON_KEY 있음): 가입 · 로그인 · 메일 인증 · 비밀번호 재설정 메일 · 권한만 Supabase.
  인증 메일은 Supabase가 보내요 (Supabase에 Gmail SMTP를 연결). 메일 속 링크가 우리 /verify 화면을 열고,
  링크에 든 인증값(token_hash)을 Supabase에 확인해서 인증을 끝내요 → sb_verify_link.
  로그인에 성공하면 SQLite의 User 행을 Supabase 사용자 id로 만들거나 고쳐요. 앱 데이터는 계속 SQLite에 있어요.
- 로컬 모드 (키 없음): User.password_hash · email_verified 로 대신하고, 인증 링크는 우리가 만들어 Gmail로 보내요
  (Redis에 1회용 인증값 저장 · 메일 미연결 개발 모드면 링크를 화면과 터미널에 보여줘요).

로그인 세션은 두 모드 모두 Redis 세션 토큰이에요 (backend/core/security.py).
"""
from __future__ import annotations

import logging
import random
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, select

from backend.config import get_settings
from backend.core import redis_store
from backend.core.security import is_admin_email
from backend.db import new_id
from backend.models import User

log = logging.getLogger("sea_info.auth")

WITHDRAWN_ID = "u_withdrawn"  # 탈퇴한 회원의 글 · 댓글을 옮겨 두는 자리 (로그인할 수 없는 계정)
WITHDRAWN_NICK = "탈퇴한 회원"


# ---------- 공통 도우미 ----------
def fail(status: int, code: str, message: str) -> HTTPException:
    """화면이 code로 다음 할 일을 고를 수 있게 {code, message} 모양으로 돌려줘요."""
    return HTTPException(status, {"code": code, "message": message})


def dev_code_allowed() -> bool:
    """메일을 보내지 않는 로컬 개발 모드에서만 화면에 인증 링크 · 코드를 보여줘요."""
    s = get_settings()
    return (not s.smtp_on) and s.is_local


def mask_email(email: str) -> str:
    if "@" not in (email or ""):
        return email or ""
    name, host = email.split("@", 1)
    return f"{name[:2]}{'*' * max(len(name) - 2, 2)}@{host}"


def send_mail(fn, *args) -> dict:
    """메일 보내기 실패를 한국어 안내로 바꿔요 (Gmail 앱 비밀번호가 틀렸을 때 등)."""
    try:
        return fn(*args)
    except Exception as e:  # smtplib 오류 등
        log.exception("메일 보내기 실패")
        print(f"[메일 오류] {type(e).__name__}: {e}", flush=True)
        raise fail(502, "mail_failed", "메일을 보내지 못했어요. 잠시 뒤 다시 시도해 주세요.")


def end_sessions(user_id: str, keep: str = "") -> int:
    """이 회원의 로그인 세션을 모두 끝내요 (탈퇴 · 비밀번호 변경). keep 토큰은 남겨요."""
    n = 0
    try:
        for key in redis_store.r().scan_iter("session:*", count=500):
            if key != f"session:{keep}" and redis_store.r().get(key) == user_id:
                redis_store.r().delete(key)
                n += 1
    except Exception as e:
        print(f"[세션 정리 실패] {e}", flush=True)
    return n


def default_nickname(session: Session) -> str:
    taken = {u.nickname for u in session.exec(select(User)).all()}
    for _ in range(50):
        nick = f"바다친구{random.randint(1000, 9999)}"
        if nick not in taken:
            return nick
    return f"바다친구{new_id('', 6)}"


def withdrawn_user(session: Session) -> User:
    """탈퇴한 회원 자리 (없으면 만들어요). 비밀번호가 없어서 로그인할 수 없어요."""
    u = session.get(User, WITHDRAWN_ID)
    if not u:
        u = User(id=WITHDRAWN_ID, email="withdrawn@sea-info.invalid", nickname=WITHDRAWN_NICK, character="🌊",
                 role="user", provider="system", password_hash=None, email_verified=False)
        session.add(u)
        session.flush()
    return u


# ---------- Supabase ----------
def _client():
    """요청마다 새 클라이언트를 만들어요 (다른 사람의 로그인 상태가 섞이지 않게)."""
    from supabase import create_client
    from supabase.lib.client_options import SyncClientOptions

    s = get_settings()
    return create_client(s.supabase_url, s.supabase_anon_key,
                         options=SyncClientOptions(auto_refresh_token=False, persist_session=False,
                                                   flow_type="implicit"))


_SB_MESSAGES: dict[str, tuple[int, str, str]] = {
    # Supabase 오류 코드: (상태, 화면용 code, 한국어 문구)
    "invalid_credentials": (401, "invalid_credentials",
                            "이메일이나 비밀번호가 맞지 않아요. 다시 입력하거나 아래 ‘비밀번호 찾기’를 눌러 주세요."),
    "email_not_confirmed": (403, "email_not_verified",
                            "메일 인증을 아직 마치지 않았어요. 메일함의 인증 링크를 누른 뒤 다시 로그인해 주세요."),
    "user_already_exists": (409, "email_exists", "이미 가입한 메일이에요. 로그인하거나 비밀번호를 찾아 주세요."),
    "email_exists": (409, "email_exists", "이미 가입한 메일이에요. 로그인하거나 비밀번호를 찾아 주세요."),
    "weak_password": (400, "weak_password", "비밀번호가 너무 쉬워요. 영문과 숫자를 섞어 8자 이상으로 만들어 주세요."),
    "same_password": (400, "same_password", "지금 쓰는 비밀번호와 달라야 해요. 새 비밀번호를 정해 주세요."),
    "over_email_send_rate_limit": (429, "rate_limited", "메일을 너무 자주 요청했어요. 1분쯤 뒤에 다시 시도해 주세요."),
    "over_request_rate_limit": (429, "rate_limited", "요청이 너무 많아요. 1분쯤 뒤에 다시 시도해 주세요."),
    "email_address_invalid": (400, "email_invalid", "이메일 주소를 한 번 더 확인해 주세요. 예) you@example.com"),
    "email_address_not_authorized": (400, "email_invalid", "이 메일 주소로는 메일을 보낼 수 없어요. 다른 메일로 시도해 주세요."),
    "validation_failed": (400, "validation", "입력한 내용을 한 번 더 확인해 주세요."),
    "signup_disabled": (403, "signup_disabled", "지금은 새로 가입할 수 없어요. 잠시 뒤 다시 시도해 주세요."),
    "email_provider_disabled": (403, "signup_disabled", "지금은 이메일로 가입 · 로그인할 수 없어요. 운영자에게 알려 주세요."),
    "user_banned": (403, "suspended", "이용이 정지된 계정이에요. 궁금한 점은 제보·건의로 알려 주세요."),
    "otp_expired": (400, "link_expired",
                    "이미 사용했거나 시간이 지난 링크예요. 인증을 마쳤다면 로그인해 주세요. 아니라면 메일을 다시 받아 주세요."),
    "flow_state_expired": (400, "link_expired", "시간이 지난 링크예요. 메일을 다시 받아 주세요."),
    "session_expired": (400, "expired", "시간이 지났어요. 처음부터 다시 해 주세요."),
    "user_not_found": (404, "not_found", "가입한 계정을 찾지 못했어요. 이메일을 다시 확인해 주세요."),
}
_SB_TEXT = [  # 오류 코드가 없는 옛 서버를 위해 영어 문구로도 찾아요
    ("invalid login credentials", "invalid_credentials"),
    ("email not confirmed", "email_not_confirmed"),
    ("already registered", "user_already_exists"),
    ("already been registered", "user_already_exists"),
    ("rate limit", "over_email_send_rate_limit"),
    ("password should be", "weak_password"),
    ("token has expired", "otp_expired"),
    ("invalid or has expired", "otp_expired"),
    ("is invalid", "email_address_invalid"),
]


def supabase_error(e: Exception) -> HTTPException:
    """Supabase 오류 → 한국어 HTTPException."""
    from supabase_auth.errors import AuthApiError, AuthRetryableError, AuthWeakPasswordError

    if isinstance(e, AuthWeakPasswordError):
        code = "weak_password"
    elif isinstance(e, AuthRetryableError):
        return fail(502, "auth_unavailable", "로그인 서버(Supabase)에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요.")
    else:
        code = getattr(e, "code", None) or ""
        if code not in _SB_MESSAGES:
            text = str(getattr(e, "message", e)).lower()
            code = next((c for t, c in _SB_TEXT if t in text), code)
    if code in _SB_MESSAGES:
        status, ui_code, msg = _SB_MESSAGES[code]
        return fail(status, ui_code, msg)
    print(f"[Supabase 오류] {type(e).__name__}: {getattr(e, 'code', '')} {e}", flush=True)
    if isinstance(e, AuthApiError) and getattr(e, "status", 500) >= 500:
        return fail(502, "auth_unavailable", "로그인 서버(Supabase)에 문제가 생겼어요. 잠시 뒤 다시 시도해 주세요.")
    return fail(400, "auth_failed", "로그인 서버가 요청을 처리하지 못했어요. 잠시 뒤 다시 시도해 주세요.")


def _call(fn, *args):
    from supabase_auth.errors import AuthError

    try:
        return fn(*args)
    except AuthError as e:
        raise supabase_error(e)
    except HTTPException:
        raise
    except Exception as e:  # 연결 실패 · 주소 오타 등
        print(f"[Supabase 연결 오류] {type(e).__name__}: {e}", flush=True)
        raise fail(502, "auth_unavailable", "로그인 서버(Supabase)에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요.")


def site(path: str = "") -> str:
    return get_settings().public_site_url.rstrip("/") + path


def sb_signup(email: str, password: str, meta: dict[str, Any]) -> None:
    c = _client()
    res = _call(c.auth.sign_up, {"email": email, "password": password,
                                 "options": {"data": meta, "email_redirect_to": site("/verify")}})
    user = getattr(res, "user", None)
    # 메일 인증을 켠 Supabase는 이미 가입한 메일에도 오류 대신 identities가 빈 사용자를 돌려줘요
    if user is not None and getattr(user, "identities", None) == []:
        raise fail(409, "email_exists", "이미 가입한 메일이에요. 로그인하거나 비밀번호를 찾아 주세요.")


def sb_resend(email: str) -> None:
    c = _client()
    _call(c.auth.resend, {"type": "signup", "email": email, "options": {"email_redirect_to": site("/verify")}})


def sb_login(email: str, password: str):
    """성공하면 Supabase 사용자(User)를 돌려줘요. 세션 토큰은 쓰지 않고 Redis 세션을 따로 만들어요."""
    c = _client()
    res = _call(c.auth.sign_in_with_password, {"email": email, "password": password})
    if not res or not res.user:
        raise fail(401, "invalid_credentials", _SB_MESSAGES["invalid_credentials"][2])
    if not res.user.email_confirmed_at and not res.user.confirmed_at:
        raise fail(403, "email_not_verified", _SB_MESSAGES["email_not_confirmed"][2])
    return res.user


def sb_reset(email: str) -> None:
    c = _client()
    _call(c.auth.reset_password_for_email, email, {"redirect_to": site("/verify")})


def sb_verify_link(token_hash: str, otp_type: str):
    """메일 속 링크의 인증값 확인 (Supabase 메일 템플릿이 /verify?token_hash=...&type=... 로 보내요).

    otp_type: 가입 인증 'email'(옛 이름 'signup') · 비밀번호 재설정 'recovery'.
    돌려주는 값: AuthResponse (user · session). 재설정이면 session으로 새 비밀번호를 저장해요.
    """
    c = _client()
    res = _call(c.auth.verify_otp, {"token_hash": token_hash, "type": otp_type})
    if not res or not res.user:
        raise fail(400, "link_expired", _SB_MESSAGES["otp_expired"][2])
    return res


def sb_set_password(access_token: str, refresh_token: str, new_password: str) -> None:
    """재설정 링크로 받은 Supabase 세션으로 새 비밀번호를 저장해요."""
    c = _client()
    _call(c.auth.set_session, access_token, refresh_token)
    _call(c.auth.update_user, {"password": new_password})


def sync_supabase_user(session: Session, sb_user) -> User:
    """Supabase 사용자 → SQLite User 행 (없으면 만들고, 권한 · 인증 상태는 매번 맞춰요). commit은 부른 쪽에서."""
    email = (sb_user.email or "").lower()
    meta = dict(getattr(sb_user, "user_metadata", None) or {})
    app_meta = dict(getattr(sb_user, "app_metadata", None) or {})
    role = "admin" if is_admin_email(email) or app_meta.get("role") == "admin" else "user"
    u = session.get(User, sb_user.id)
    if not u and email:  # 같은 메일의 예전 행이 있으면 그 행을 이어서 써요 (Supabase가 메일을 확인했어요)
        u = session.exec(select(User).where(User.email == email)).first()
    if not u:
        nick = str(meta.get("nickname") or "").strip()[:10]
        if len(nick) < 2 or session.exec(select(User).where(User.nickname == nick)).first():
            nick = default_nickname(session)
        char = meta.get("character") if meta.get("character") else "🐢"
        u = User(id=sb_user.id, email=email, nickname=nick, character=char, provider="supabase", role=role,
                 email_verified=True)
        session.add(u)
    else:
        u.email = email or u.email
        u.provider = "supabase"
        u.email_verified = True
        u.role = role
    return u
