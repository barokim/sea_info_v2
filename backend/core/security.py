"""로그인 확인 (편성훈). FastAPI 함수에 이렇게 붙여 써요.

    def my_api(user: User = Depends(require_user)): ...     # 회원만
    def admin_api(user: User = Depends(require_admin)): ... # 관리자만
    def any_api(user: User | None = Depends(optional_user)): ...

로그인하면 서버가 '세션 토큰'을 주고(Redis에 7일 보관), Streamlit은 요청마다
Authorization: Bearer <토큰> 머리글로 보내요. Supabase 모드든 로컬 모드든 같은 방식이에요.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import Depends, Header, HTTPException, Request
from sqlmodel import Session

from backend.config import get_settings
from backend.core import redis_store
from backend.core.timefmt import as_kst, now
from backend.db import get_session
from backend.models import User

ITER = 200_000


def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), ITER).hex()
    return f"pbkdf2${ITER}${salt}${h}"


def verify_password(pw: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        _, it, salt, h = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(it)).hex()
        return hmac.compare_digest(calc, h)
    except ValueError:
        return False


def is_admin_email(email: str) -> bool:
    return email.lower() in get_settings().admin_email_set


def _token(authorization: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def optional_user(authorization: str | None = Header(default=None),
                  session: Session = Depends(get_session)) -> User | None:
    uid = redis_store.session_user(_token(authorization))
    return session.get(User, uid) if uid else None


def require_user(user: User | None = Depends(optional_user)) -> User:
    if not user:
        raise HTTPException(401, "로그인이 필요해요.")
    if user.suspended_until and as_kst(user.suspended_until) > now():
        raise HTTPException(403, f"이용이 정지된 계정이에요. ({user.suspended_until:%Y.%m.%d}까지 · {user.suspend_reason})")
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "관리자만 할 수 있어요.")
    return user


def viewer_key(request: Request, user: User | None) -> str:
    """횟수 · 조회수를 셀 때 쓰는 이름. 회원은 계정, 비회원은 브라우저 식별값 + IP."""
    if user:
        return f"user:{user.id}"
    gid = request.headers.get("x-guest-id", "")[:40]
    ip = request.headers.get("x-client-ip") or (request.client.host if request.client else "")
    return f"guest:{gid}:{ip}"


def user_private(u: User) -> dict:
    return {"id": u.id, "email": u.email, "nickname": u.nickname, "character": u.character, "role": u.role,
            "provider": u.provider, "aquarium_public": u.aquarium_public, "region": u.region,
            "grade": u.grade, "points": u.points, "created": u.created_at.strftime("%Y-%m-%d")}
