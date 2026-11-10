"""로그인 API (이종민 담당).

편성훈이 먼저 만든 것: 시험용 로그인(로컬 전용) · 내 정보 · 로그아웃.
이종민: 가입 · 메일 링크 인증 · 비밀번호 로그인 · 비밀번호 찾기(링크)/바꾸기 · 프로필 수정 · 탈퇴 · 내 활동.

메일 인증은 '메일 속 링크를 누르면 끝'이에요. 코드를 입력하지 않아요.
  1) 가입 → 인증 메일 (링크: {PUBLIC_SITE_URL}/verify?token_hash=...&type=email)
  2) 링크를 누르면 화면(views/verify.py)이 POST /auth/verify-link 로 인증값을 보내요 → 인증 끝 + 바로 로그인
  비밀번호 찾기도 같아요 (type=recovery → 새 비밀번호 정하기 → POST /auth/password/reset/confirm).

로그인 제공자는 환경변수로 골라요 (backend/auth_provider.py).
  Supabase 모드: Supabase가 인증 메일을 보내고(Supabase에 Gmail SMTP 연결), 링크의 인증값을 Supabase에 확인해요.
  로컬 모드:     우리가 1회용 인증값을 Redis에 두고 Gmail로 링크를 보내요 (메일 미연결이면 개발 모드에서 dev_link로 화면에 보여줘요).
로그인은 이메일 + 비밀번호만이에요. 두 모드 모두 로그인 뒤에는 Redis 세션 토큰을 써요.
"""
from __future__ import annotations

import secrets
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from backend import auth_provider as ap
from backend.config import get_settings
from backend.core import mail, redis_store
from backend.core.convert import post_out
from backend.core.security import (_token, hash_password, is_admin_email, require_user, user_private,
                                   verify_password)
from backend.core.timefmt import ago, as_kst, now
from backend.db import get_session, new_id
from backend.models import (Comment, Inquiry, Like, Observation, Post, Report, ScoreLog, Setting, User)
from backend.schemas.auth import (LoginIn, LoginOut, MyCommentOut, PasswordChangeIn, ProfileIn, ResendIn,
                                  ResetConfirmIn, ResetIn, SignupIn, VerifyLinkIn, VerifyLinkOut, VerifySentOut,
                                  WithdrawIn)
from backend.schemas.common import OkOut, PostOut, SessionOut, UserMe

router = APIRouter()
auth = APIRouter(prefix="/auth", tags=["로그인"])
me_router = APIRouter(prefix="/me", tags=["내 정보"])

SIGNUP_LINK_TTL = 86400  # 가입 인증 링크 24시간 (로컬 모드. Supabase는 대시보드 설정을 따라요)
RESET_LINK_TTL = 3600  # 비밀번호 재설정 링크 1시간
RESET_FORM_TTL = 900  # 링크를 누른 뒤 새 비밀번호를 정할 수 있는 시간 15분
MAIL_GAP = 30  # 같은 메일로 다시 보내려면 30초 기다려요
MAX_LOGIN_FAILS = 10  # 10분 동안 비밀번호를 10번 틀리면 잠깐 막아요


def _me(u: User) -> UserMe:
    return UserMe(**user_private(u))


def _dev(link: str | None) -> str | None:
    """메일을 보내지 않는 로컬 개발 모드에서만 링크를 화면에 같이 줘요."""
    return link if link and ap.dev_code_allowed() else None


LINK_EXPIRED = "이미 사용했거나 시간이 지난 링크예요. 인증을 마쳤다면 로그인해 주세요. 아니라면 메일을 다시 받아 주세요."


# ---------- 로컬 모드의 1회용 링크 (Supabase 모드에서는 Supabase가 만들어요) ----------
def _link_make(kind: str, email: str, ttl: int) -> str:
    """kind: 'email'(가입 인증) | 'recovery'(비밀번호 재설정). 메일에 넣을 링크 주소를 돌려줘요."""
    token = secrets.token_urlsafe(24)
    redis_store.r().setex(f"link:{kind}:{token}", ttl, email)
    return ap.site(f"/verify?token_hash={token}&type={kind}")


def _link_take(kind: str, token: str) -> str | None:
    """링크의 인증값 → 메일 주소. 한 번 쓰면 지워요."""
    return redis_store.r().getdel(f"link:{kind}:{token}")


def _gap(kind: str, key: str) -> None:
    if not redis_store.gap_ok(f"mail:{kind}:{key}", MAIL_GAP):
        raise ap.fail(429, "too_soon", f"조금 전에 메일을 보냈어요. {MAIL_GAP}초쯤 뒤에 다시 눌러 주세요.")


def _commit(session: Session, what: str = "저장") -> None:
    try:
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"[{what} 오류] {type(e).__name__}: {e}", flush=True)
        raise HTTPException(500, f"{what}하지 못했어요. 입력한 내용은 그대로 있어요. 잠시 뒤 다시 시도해 주세요.")


def _suspended_msg(u: User) -> str | None:
    if u.suspended_until and as_kst(u.suspended_until) > now():
        until = "영구" if as_kst(u.suspended_until).year >= 9000 else f"{as_kst(u.suspended_until):%Y.%m.%d}까지"
        return f"이용이 정지된 계정이에요. ({until} · {u.suspend_reason or '운영 정책 위반'}) 궁금한 점은 제보·건의로 알려 주세요."
    return None


def _banned_words(session: Session) -> list[str]:
    row = session.get(Setting, 1)
    return [w for w in (row.data or {}).get("banned", []) if w] if row else []


# =====================================================================
# 시험용 로그인 · 내 정보 · 로그아웃 (편성훈)
# =====================================================================
class DevLoginIn(BaseModel):
    kind: Literal["member", "admin"]


@auth.post("/dev-login", response_model=SessionOut, summary="시험용 로그인 (APP_ENV=local 에서만)")
def dev_login(body: DevLoginIn, session: Session = Depends(get_session)):
    if not get_settings().is_local:
        raise HTTPException(404, "없는 기능이에요.")
    u = session.get(User, "u_admin" if body.kind == "admin" else "u_me")
    if not u:
        raise HTTPException(404, "시험용 계정이 없어요. data/sea_info.db를 지우고 서버를 다시 켜 주세요.")
    return SessionOut(token=redis_store.session_create(u.id), user=_me(u))


@auth.get("/me", response_model=UserMe, summary="내 정보")
def me(user: User = Depends(require_user)):
    return _me(user)


@auth.post("/logout", response_model=OkOut, summary="로그아웃")
def logout(authorization: str | None = Header(default=None)):
    redis_store.session_delete(_token(authorization))
    return OkOut(message="로그아웃했어요.")


# =====================================================================
# 가입 · 메일 인증
# =====================================================================
def _send_signup_link(email: str) -> str:
    url = _link_make("email", email, SIGNUP_LINK_TTL)
    ap.send_mail(mail.link_mail, email, url, "signup")
    return url


@auth.post("/signup", response_model=VerifySentOut, summary="가입 ① 이메일 · 비밀번호 · 약관 → 인증 링크 메일")
def signup(body: SignupIn, session: Session = Depends(get_session)):
    s = get_settings()
    sent = "인증 메일을 보냈어요. 메일 속 [메일 인증하기] 링크를 눌러 주세요."
    if s.supabase_on:
        meta = {k: v for k, v in {"nickname": body.nickname, "character": body.character,
                                  "marketing": body.marketing}.items() if v is not None}
        _gap("signup", body.email)
        ap.sb_signup(body.email, body.password, meta)
        return VerifySentOut(email=body.email, expires_in=SIGNUP_LINK_TTL, message=sent)
    u = session.exec(select(User).where(User.email == body.email)).first()
    if u and (u.email_verified or u.provider != "local"):
        raise ap.fail(409, "email_exists", "이미 가입한 메일이에요. 로그인하거나 비밀번호를 찾아 주세요.")
    if body.nickname and session.exec(select(User).where(User.nickname == body.nickname,
                                                         User.email != body.email)).first():
        raise ap.fail(409, "nickname_taken", "이미 쓰는 닉네임이에요. 다른 이름으로 정해 주세요.")
    _gap("signup", body.email)
    if not u:  # 인증 전 계정을 먼저 만들어 둬요 (인증을 마쳐야 로그인할 수 있어요)
        u = User(id=new_id("u_", 8), email=body.email, nickname=body.nickname or ap.default_nickname(session),
                 character=body.character or "🐢", role="admin" if is_admin_email(body.email) else "user",
                 provider="local", email_verified=False)
        session.add(u)
    elif body.nickname:
        u.nickname = body.nickname
    if body.character:
        u.character = body.character
    u.password_hash = hash_password(body.password)  # 인증 전에 다시 가입하면 새 비밀번호로 바꿔요
    _commit(session, "가입 정보를 저장")
    url = _send_signup_link(body.email)
    return VerifySentOut(email=body.email, expires_in=SIGNUP_LINK_TTL, dev_link=_dev(url), message=sent)


@auth.post("/verify-link", response_model=VerifyLinkOut,
           summary="가입 ② 메일 속 링크 확인 (가입 인증 → 바로 로그인 · 비밀번호 재설정 → reset_id)")
def verify_link(body: VerifyLinkIn, session: Session = Depends(get_session)):
    recovery = body.type == "recovery"
    if get_settings().supabase_on:
        res = ap.sb_verify_link(body.token_hash, body.type)
        u = ap.sync_supabase_user(session, res.user)
        _commit(session, "메일 인증을 저장")
        session.refresh(u)
        if recovery:
            if not res.session:
                raise ap.fail(400, "link_expired", LINK_EXPIRED)
            rid = redis_store.temp_put({"user_id": u.id, "email": u.email, "access": res.session.access_token,
                                        "refresh": res.session.refresh_token}, ttl=RESET_FORM_TTL, prefix="resetform")
    else:
        email = _link_take("recovery" if recovery else "email", body.token_hash)
        if not email:
            raise ap.fail(400, "link_expired", LINK_EXPIRED)
        u = session.exec(select(User).where(User.email == email, User.provider == "local")).first()
        if not u:
            raise ap.fail(404, "not_found", "가입 정보를 찾지 못했어요. 처음부터 다시 가입해 주세요.")
        u.email_verified = True  # 메일 속 링크를 눌렀으니 본인 메일이 맞아요
        _commit(session, "메일 인증을 저장")
        session.refresh(u)
        if recovery:
            rid = redis_store.temp_put({"user_id": u.id, "email": u.email}, ttl=RESET_FORM_TTL, prefix="resetform")
    if recovery:
        return VerifyLinkOut(kind="recovery", reset_id=rid, email_masked=ap.mask_email(u.email),
                             message=f"새 비밀번호를 정해 주세요. {RESET_FORM_TTL // 60}분 안에 저장해 주세요.")
    if msg := _suspended_msg(u):
        raise ap.fail(403, "suspended", msg)
    # 링크로 본인 메일임을 확인했으니 바로 로그인해요 (③ 닉네임 · 캐릭터 단계로)
    return VerifyLinkOut(kind="signup", message="메일 인증을 마쳤어요.", token=redis_store.session_create(u.id),
                         user=_me(u))


@auth.post("/resend", response_model=VerifySentOut, summary="가입 인증 메일 다시 보내기")
def resend(body: ResendIn, session: Session = Depends(get_session)):
    again = "인증 메일을 다시 보냈어요. 새 메일의 링크를 눌러 주세요. 먼저 받은 링크도 시간 안에는 쓸 수 있어요."
    if get_settings().supabase_on:
        _gap("signup", body.email)
        ap.sb_resend(body.email)
        return VerifySentOut(email=body.email, expires_in=SIGNUP_LINK_TTL, message=again)
    u = session.exec(select(User).where(User.email == body.email)).first()
    if not u:
        raise ap.fail(404, "not_found", "가입 정보를 찾지 못했어요. 처음부터 다시 가입해 주세요.")
    if u.email_verified:
        raise ap.fail(409, "already_verified", "이미 인증을 마친 메일이에요. 로그인해 주세요.")
    _gap("signup", body.email)
    url = _send_signup_link(body.email)
    return VerifySentOut(email=body.email, expires_in=SIGNUP_LINK_TTL, dev_link=_dev(url), message=again)


# =====================================================================
# 로그인 (이메일 + 비밀번호)
# =====================================================================
def _fails_key(email: str) -> str:
    return f"loginfail:{email}"


def _check_fails(email: str) -> None:
    if int(redis_store.r().get(_fails_key(email)) or 0) >= MAX_LOGIN_FAILS:
        raise ap.fail(429, "too_many_fails",
                      "비밀번호를 여러 번 틀려서 잠시 막았어요. 10분 뒤에 다시 시도하거나 ‘비밀번호 찾기’를 눌러 주세요.")


def _add_fail(email: str) -> None:
    k = _fails_key(email)
    redis_store.r().incr(k)
    redis_store.r().expire(k, 600)


@auth.post("/login", response_model=LoginOut, summary="이메일 · 비밀번호 로그인 (메일 인증을 마친 계정)")
def login(body: LoginIn, session: Session = Depends(get_session)):
    s = get_settings()
    _check_fails(body.email)
    if s.supabase_on:
        try:
            sb_user = ap.sb_login(body.email, body.password)
        except HTTPException as e:
            if e.status_code == 401:
                _add_fail(body.email)
            raise
        u = ap.sync_supabase_user(session, sb_user)
        _commit(session, "로그인 정보를 저장")
        session.refresh(u)
    else:
        u = session.exec(select(User).where(User.email == body.email)).first()
        if not u or not verify_password(body.password, u.password_hash):
            _add_fail(body.email)
            raise ap.fail(401, "invalid_credentials",
                          "이메일이나 비밀번호가 맞지 않아요. 다시 입력하거나 아래 ‘비밀번호 찾기’를 눌러 주세요.")
        if not u.email_verified:
            raise ap.fail(403, "email_not_verified",
                          "메일 인증을 아직 마치지 않았어요. 메일함의 [메일 인증하기] 링크를 눌러 주세요. "
                          "메일이 없으면 ‘인증 메일 다시 받기’를 눌러 주세요.")
        if is_admin_email(u.email) and u.role != "admin":
            u.role = "admin"
            _commit(session, "권한을 저장")
    redis_store.r().delete(_fails_key(body.email))
    if msg := _suspended_msg(u):
        raise ap.fail(403, "suspended", msg)
    return LoginOut(token=redis_store.session_create(u.id), user=_me(u))


# =====================================================================
# 비밀번호 찾기 (메일 링크) · 바꾸기
# =====================================================================
@auth.post("/password/reset", response_model=VerifySentOut, summary="비밀번호 찾기 → 재설정 링크 메일")
def password_reset(body: ResetIn, session: Session = Depends(get_session)):
    sent = "가입한 메일이라면 재설정 메일이 도착해요. 메일 속 링크를 눌러 새 비밀번호를 정해 주세요."
    _gap("reset", body.email)
    if get_settings().supabase_on:
        ap.sb_reset(body.email)
        return VerifySentOut(status="sent", email=body.email, expires_in=RESET_LINK_TTL, message=sent)
    u = session.exec(select(User).where(User.email == body.email, User.provider == "local")).first()
    url = None
    if u:  # 가입하지 않은 메일이어도 같은 답을 줘요 (누가 가입했는지 알 수 없게)
        url = _link_make("recovery", body.email, RESET_LINK_TTL)
        ap.send_mail(mail.link_mail, body.email, url, "reset")
    return VerifySentOut(status="sent", email=body.email, expires_in=RESET_LINK_TTL, dev_link=_dev(url), message=sent)


@auth.post("/password/reset/confirm", response_model=OkOut, summary="재설정 링크를 누른 뒤 새 비밀번호 저장")
def password_reset_confirm(body: ResetConfirmIn, session: Session = Depends(get_session)):
    data = redis_store.temp_get(body.reset_id, prefix="resetform")
    if not data:
        raise ap.fail(400, "expired", "시간이 지났어요. ‘비밀번호 찾기’를 처음부터 다시 해 주세요.")
    if get_settings().supabase_on:
        ap.sb_set_password(data["access"], data["refresh"], body.new_password)
    else:
        u = session.get(User, data["user_id"])
        if not u:
            raise ap.fail(404, "not_found", "가입한 계정을 찾지 못했어요. 이메일을 다시 확인해 주세요.")
        u.password_hash = hash_password(body.new_password)
        _commit(session, "새 비밀번호를 저장")
    redis_store.r().delete(f"resetform:{body.reset_id}")  # 한 번 쓰면 버려요
    ap.end_sessions(data["user_id"])  # 다른 곳에 로그인돼 있던 것도 끝내요
    redis_store.r().delete(_fails_key(data["email"]))
    return OkOut(message="비밀번호를 새로 정했어요. 새 비밀번호로 로그인해 주세요.")


@auth.post("/password/change", response_model=OkOut, summary="비밀번호 바꾸기 (로그인한 상태 · 로컬 모드)")
def password_change(body: PasswordChangeIn, authorization: str | None = Header(default=None),
                    user: User = Depends(require_user), session: Session = Depends(get_session)):
    if user.provider == "supabase" or get_settings().supabase_on:
        raise ap.fail(400, "use_reset_link",
                      "이 계정은 비밀번호를 메일로 바꿔요. 로그아웃한 뒤 ‘비밀번호 찾기’를 누르면 재설정 링크를 보내 드려요.")
    if not verify_password(body.current, user.password_hash):
        raise ap.fail(400, "wrong_password", "지금 비밀번호가 맞지 않아요. 다시 입력해 주세요.")
    if body.current == body.new:
        raise ap.fail(400, "same_password", "지금 쓰는 비밀번호와 달라야 해요. 새 비밀번호를 정해 주세요.")
    user.password_hash = hash_password(body.new)
    _commit(session, "새 비밀번호를 저장")
    ap.end_sessions(user.id, keep=_token(authorization))  # 이 기기는 그대로, 다른 기기는 로그아웃
    return OkOut(message="비밀번호를 바꿨어요. 다음 로그인부터 새 비밀번호를 써 주세요.")


# =====================================================================
# 프로필 · 탈퇴
# =====================================================================
@auth.patch("/me", response_model=UserMe, summary="프로필 바꾸기 (닉네임 · 캐릭터 · 수족관 공개 · 지역)")
def update_me(body: ProfileIn, user: User = Depends(require_user), session: Session = Depends(get_session)):
    if body.nickname is not None and body.nickname != user.nickname:
        if any(w in body.nickname for w in _banned_words(session)):
            raise ap.fail(400, "banned_word", "쓸 수 없는 말이 들어 있어요. 다른 이름으로 정해 주세요.")
        if user.role != "admin" and any(w in body.nickname for w in ("운영자", "관리자", ap.WITHDRAWN_NICK)):
            raise ap.fail(400, "reserved", "운영자처럼 보이거나 쓸 수 없는 이름이에요. 다른 이름으로 정해 주세요.")
        if session.exec(select(User).where(User.nickname == body.nickname, User.id != user.id)).first():
            raise ap.fail(409, "nickname_taken", "이미 쓰는 닉네임이에요. 다른 이름으로 정해 주세요.")
        user.nickname = body.nickname
    if body.character is not None:
        user.character = body.character
    if body.aquarium_public is not None:
        user.aquarium_public = body.aquarium_public
    if body.region is not None:
        try:
            from backend.routers.tide import _all as tide_regions

            known = set(tide_regions())
        except Exception:
            known = {body.region}
        if body.region not in known:
            raise ap.fail(400, "region", "물때 지역을 목록에서 골라 주세요.")
        user.region = body.region
    session.add(user)
    _commit(session, "프로필을 저장")
    session.refresh(user)
    return _me(user)


@auth.delete("/me", response_model=OkOut, summary="회원 탈퇴 (수족관 기록은 지우고, 글 · 댓글은 ‘탈퇴한 회원’으로 남겨요)")
def withdraw(body: WithdrawIn | None = None, user: User = Depends(require_user),
             session: Session = Depends(get_session)):
    if user.role == "admin":
        raise ap.fail(403, "admin", "관리자 계정은 바로 탈퇴할 수 없어요. 다른 관리자에게 권한을 넘긴 뒤 제보·건의로 알려 주세요.")
    uid = user.id
    try:
        ghost = ap.withdrawn_user(session)
        for o in session.exec(select(Observation).where(Observation.user_id == uid)).all():
            session.delete(o)
        for lk in session.exec(select(Like).where(Like.user_id == uid)).all():
            p = session.get(Post, lk.post_id)
            if p:
                p.likes = max((p.likes or 0) - 1, 0)
            session.delete(lk)
        ghost_reports = {r.post_id for r in session.exec(select(Report).where(Report.user_id == ghost.id)).all()}
        for rp in session.exec(select(Report).where(Report.user_id == uid)).all():
            if rp.post_id in ghost_reports:  # 같은 글을 신고한 다른 탈퇴 회원이 있으면 기록만 합쳐요
                session.delete(rp)
            else:
                rp.user_id = ghost.id
                ghost_reports.add(rp.post_id)
        for p in session.exec(select(Post).where(Post.user_id == uid)).all():
            p.user_id = ghost.id
        for c in session.exec(select(Comment).where(Comment.user_id == uid)).all():
            c.user_id = ghost.id
        for q in session.exec(select(Inquiry).where(Inquiry.user_id == uid)).all():
            q.user_id = None
            q.email = ""
        for sc in session.exec(select(ScoreLog).where(ScoreLog.user_id == uid)).all():
            sc.user_id = None
            sc.nickname = ap.WITHDRAWN_NICK
        session.flush()
        session.delete(user)
        session.commit()  # 한 번에 저장해요. 하나라도 실패하면 아무것도 바뀌지 않아요
    except Exception as e:
        session.rollback()
        print(f"[탈퇴 오류] {type(e).__name__}: {e}", flush=True)
        raise HTTPException(500, "탈퇴하지 못했어요. 아무것도 지워지지 않았어요. 잠시 뒤 다시 시도해 주세요.")
    ap.end_sessions(uid)
    if body and body.reason:
        print(f"[탈퇴] 이유: {body.reason}", flush=True)
    return OkOut(message="탈퇴했어요. 그동안 함께해 줘서 고마워요.")


# =====================================================================
# 내 활동 (/me/posts · /me/comments)
# =====================================================================
@me_router.get("/posts", response_model=list[PostOut], summary="내가 쓴 글 (운영자가 숨긴 글 포함)")
def my_posts(user: User = Depends(require_user), session: Session = Depends(get_session)):
    rows = session.exec(select(Post).where(Post.user_id == user.id, Post.deleted == False)).all()  # noqa: E712
    return [post_out(p, session) for p in sorted(rows, key=lambda p: as_kst(p.created_at), reverse=True)]


@me_router.get("/comments", response_model=list[MyCommentOut], summary="내가 남긴 댓글 (어느 글인지 함께)")
def my_comments(user: User = Depends(require_user), session: Session = Depends(get_session)):
    rows = session.exec(select(Comment).where(Comment.user_id == user.id, Comment.deleted == False)).all()  # noqa: E712
    out = []
    for c in sorted(rows, key=lambda c: as_kst(c.created_at), reverse=True):
        p = session.get(Post, c.post_id)
        if not p or p.deleted:
            continue
        out.append(MyCommentOut(id=c.id, post=c.post_id, user=c.user_id, body=c.body, created=ago(c.created_at),
                                post_title=p.title, post_hidden=p.hidden))
    return out


router.include_router(auth)
router.include_router(me_router)
