"""로그인 · 가입 · 메일 링크 인증 · 내 정보 API 모양 (pydantic, 이종민).

화면에 보여줄 입력 오류는 한국어로 나가게 직접 검사해요 (ValueError 문구가 그대로 화면에 떠요).
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, field_validator

from backend.schemas.common import CommentOut, UserMe

EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

# 가입할 때 · 내 정보에서 고르는 바다 캐릭터 (🐋는 운영자 계정이 쓰고 있어서 함께 허용해요)
CHARACTERS = {"🐢": "거북", "🐬": "돌고래", "🦭": "물범", "🐠": "열대어", "🐳": "고래",
              "🐚": "조개", "🦀": "게", "⭐": "불가사리", "🪼": "해파리", "🦑": "오징어"}
ALLOWED_CHARACTERS = set(CHARACTERS) | {"🐋"}


def clean_email(v: str) -> str:
    v = (v or "").strip().lower()
    if not EMAIL_RE.fullmatch(v) or len(v) > 254:
        raise ValueError("이메일 주소를 한 번 더 확인해 주세요. 예) you@example.com")
    return v


def check_password(v: str) -> str:
    if len(v or "") < 8 or not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
        raise ValueError("비밀번호는 영문과 숫자를 섞어 8자 이상으로 만들어 주세요.")
    if len(v) > 72:
        raise ValueError("비밀번호는 72자보다 짧게 만들어 주세요.")
    return v


def check_nickname(v: str) -> str:
    v = (v or "").strip()
    if not 2 <= len(v) <= 10:
        raise ValueError("닉네임은 2~10자로 정해 주세요.")
    return v


def check_character(v: str) -> str:
    if v not in ALLOWED_CHARACTERS:
        raise ValueError("목록에 있는 바다 캐릭터 중에서 골라 주세요.")
    return v


TOKEN_RE = re.compile(r"[A-Za-z0-9_\-.]{8,300}")


def check_token(v: str) -> str:
    v = (v or "").strip()
    if not TOKEN_RE.fullmatch(v):
        raise ValueError("링크 주소가 잘렸어요. 메일 속 링크를 다시 눌러 주세요.")
    return v


class _EmailIn(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return clean_email(v)


# ---------- 가입 · 메일 인증 ----------
class SignupIn(_EmailIn):
    password: str
    nickname: Optional[str] = None  # 화면은 ③단계에서 PATCH /auth/me 로 정해요. 미리 주면 같이 저장해요
    character: Optional[str] = None
    agree: bool = False  # 필수 약관 세 개(이용약관 · 개인정보 · 만 14세 이상)에 모두 동의했는지
    marketing: bool = False

    @field_validator("password")
    @classmethod
    def _pw(cls, v: str) -> str:
        return check_password(v)

    @field_validator("nickname")
    @classmethod
    def _nick(cls, v: Optional[str]) -> Optional[str]:
        return check_nickname(v) if v else None

    @field_validator("character")
    @classmethod
    def _char(cls, v: Optional[str]) -> Optional[str]:
        return check_character(v) if v else None

    @field_validator("agree")
    @classmethod
    def _agree(cls, v: bool) -> bool:
        if not v:
            raise ValueError("필수 약관 세 개에 모두 동의해 주세요.")
        return v


class VerifySentOut(BaseModel):
    """메일을 보냈어요. 메일 속 링크를 누르면 /verify 화면에서 인증이 끝나요."""
    status: Literal["verify_email", "sent"] = "verify_email"
    via: Literal["link"] = "link"
    email: str
    message: str = ""
    expires_in: int = 0  # 초
    dev_link: Optional[str] = None  # 로컬 + 메일 미연결일 때만: 메일 대신 화면에 링크를 보여줘요


class VerifyLinkIn(BaseModel):
    """메일 속 링크 주소의 ?token_hash=...&type=... 값을 그대로 보내요."""
    token_hash: str
    type: Literal["email", "signup", "recovery"] = "email"

    @field_validator("token_hash")
    @classmethod
    def _token(cls, v: str) -> str:
        return check_token(v)


class VerifyLinkOut(BaseModel):
    """kind=signup 이면 바로 로그인(token · user), kind=recovery 면 reset_id 로 새 비밀번호를 정해요."""
    kind: Literal["signup", "recovery"]
    message: str = ""
    token: Optional[str] = None
    user: Optional[UserMe] = None
    reset_id: Optional[str] = None
    email_masked: Optional[str] = None


class ResendIn(_EmailIn):
    pass


# ---------- 로그인 (비밀번호만) ----------
class LoginIn(_EmailIn):
    password: str

    @field_validator("password")
    @classmethod
    def _pw(cls, v: str) -> str:
        if not v:
            raise ValueError("비밀번호를 입력해 주세요.")
        return v


class LoginOut(BaseModel):
    """로그인 성공: token · user (SessionOut 과 같은 모양)."""
    status: Literal["ok"] = "ok"
    token: str
    user: UserMe


# ---------- 비밀번호 ----------
class ResetIn(_EmailIn):
    pass


class ResetConfirmIn(BaseModel):
    """재설정 링크를 눌러 받은 reset_id + 새 비밀번호."""
    reset_id: str
    new_password: str

    @field_validator("reset_id")
    @classmethod
    def _rid(cls, v: str) -> str:
        return check_token(v)

    @field_validator("new_password")
    @classmethod
    def _pw(cls, v: str) -> str:
        return check_password(v)


class PasswordChangeIn(BaseModel):
    current: str
    new: str

    @field_validator("current")
    @classmethod
    def _now(cls, v: str) -> str:
        if not v:
            raise ValueError("지금 쓰는 비밀번호를 먼저 입력해 주세요.")
        return v

    @field_validator("new")
    @classmethod
    def _pw(cls, v: str) -> str:
        if len(v or "") < 8 or not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
            raise ValueError("새 비밀번호는 영문과 숫자를 섞어 8자 이상으로 만들어 주세요.")
        return check_password(v)


# ---------- 내 정보 ----------
class ProfileIn(BaseModel):
    nickname: Optional[str] = None
    character: Optional[str] = None
    aquarium_public: Optional[bool] = None
    region: Optional[str] = None

    @field_validator("nickname")
    @classmethod
    def _nick(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else check_nickname(v)

    @field_validator("character")
    @classmethod
    def _char(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else check_character(v)

    @field_validator("region")
    @classmethod
    def _region(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not re.fullmatch(r"[a-z0-9_-]{1,20}", v):
            raise ValueError("물때 지역을 목록에서 골라 주세요.")
        return v


class WithdrawIn(BaseModel):
    reason: str = ""

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        return (v or "").strip()[:100]


class MyCommentOut(CommentOut):
    """내 댓글 + 어느 글에 남겼는지."""
    post_title: str = ""
    post_hidden: bool = False
