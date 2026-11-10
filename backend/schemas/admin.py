"""관리자 운영 API 모양 (pydantic, 이종민): 대시보드 · 게시물 · 신고 · 회원 · 운영 설정 · 조치 기록."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from backend.schemas.common import PostOut

ACTION_REASONS = ["스팸·광고", "욕설·비방", "개인정보 노출", "주제와 맞지 않음", "기타"]
FORMATS = ["jpg", "jpeg", "png", "heic", "webp"]


# ---------- 조치 기록 ----------
class LogOut(BaseModel):
    id: int
    when: str  # 'MM-DD HH:MM'
    at: str  # ISO
    screen: str
    who: str
    what: str
    target: str = ""
    before: str = ""
    after: str = ""
    why: str = ""


# ---------- 신고 (글마다 묶음) ----------
class ReasonCount(BaseModel):
    reason: str
    count: int


class ReportGroupOut(BaseModel):
    post: str  # 글 id
    title: str
    board: str = ""
    author: str = ""  # 쓴 사람 닉네임
    body: str = ""  # 미리보기
    species: Optional[str] = None  # 사진 자리 이모지용
    created: str = ""  # 글을 쓴 때 ('2시간 전')
    hidden: bool = False
    deleted: bool = False
    reason: str  # 가장 많은 사유
    reasons: list[ReasonCount] = []
    count: int  # 이 묶음의 신고 수
    date: str  # 가장 최근 신고 날짜 YYYY-MM-DD
    status: str  # 대기 | 숨김 | 문제없음 | 삭제


class ResolveIn(BaseModel):
    action: Literal["hide", "dismiss"]
    reason: str = Field("", max_length=200)


# ---------- 대시보드 ----------
class DayCount(BaseModel):
    date: str  # YYYY-MM-DD
    value: int


class Metric(BaseModel):
    today: int
    yesterday: int
    trend: list[DayCount]  # 최근 7일 (마지막이 오늘)


class InquiryTodo(BaseModel):
    id: str
    type: str
    title: str
    status: str
    date: str
    who: str  # 닉네임 또는 '비회원 (ab**@x.com)'


class DashboardOut(BaseModel):
    date: str
    signups: Metric
    identifies: Metric  # 지난 날짜는 대시보드를 열 때마다 기록해 둔 값이에요 (Redis 하루 횟수는 자정에 사라져서)
    new_posts: Metric
    pending_reports: Metric  # today = 지금 대기 중인 글 수, trend = 날마다 새로 들어온 신고 수
    pending_inquiries: Metric
    reports: list[ReportGroupOut]
    inquiries: list[InquiryTodo]
    logs: list[LogOut]
    report_hide: int


# ---------- 게시물 ----------
class AdminPostOut(PostOut):
    author_nickname: str = ""
    board_name: str = ""
    pending_reports: int = 0
    deleted: bool = False


class AdminPostList(BaseModel):
    items: list[AdminPostOut]
    total: int  # 필터와 상관없이 지워지지 않은 전체 글
    hidden: int
    reported: int  # 대기 중인 신고가 있는 글


class ActionIn(BaseModel):
    reason: str = Field("", max_length=200)


# ---------- 회원 ----------
class SuspendInfo(BaseModel):
    until: str  # '2026-11-15까지' | '영구'
    reason: str
    memo: str = ""


class MemberOut(BaseModel):
    id: str
    nickname: str
    character: str
    email: str
    joined: str  # YYYY-MM-DD
    posts: int
    reports: int  # 내 글들이 받은 신고 수
    role: str  # '관리자' | '회원'
    role_key: Literal["user", "admin"] = "user"
    status: str  # '이용 중' | '이용 정지 · 2026-11-15까지'
    suspended: Optional[SuspendInfo] = None
    public: bool = False
    recent: list[str] = []
    provider: str = "local"


class SuspendIn(BaseModel):
    days: Optional[int] = Field(None, description="정지 일수. 비우면 영구 정지")
    reason: str
    memo: str = Field("", max_length=200)

    @field_validator("days")
    @classmethod
    def _days(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not 1 <= v <= 365:
            raise ValueError("정지 기간은 1일에서 365일 사이로 정해 주세요. 영구 정지는 기간을 비워 주세요.")
        return v

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("정지 사유를 골라 주세요.")
        return v[:50]


# ---------- 운영 설정 ----------
class SettingsFull(BaseModel):
    limit_member: int
    limit_guest: int
    max_mb: int
    formats: list[str]
    report_hide: int
    banned: list[str]
    default_region: str
    extra: dict[str, Any] = {}  # 다른 화면이 쓰는 설정 (그대로 둬요)


class SettingsIn(BaseModel):
    limit_member: int
    limit_guest: int
    max_mb: int
    formats: list[str]
    report_hide: int
    banned: list[str]
    default_region: str

    @field_validator("limit_member")
    @classmethod
    def _member(cls, v: int) -> int:
        if not 1 <= v <= 200:
            raise ValueError("회원 하루 횟수는 1~200회로 정해 주세요.")
        return v

    @field_validator("limit_guest")
    @classmethod
    def _guest(cls, v: int) -> int:
        if not 0 <= v <= 50:
            raise ValueError("비회원 하루 횟수는 0~50회로 정해 주세요.")
        return v

    @field_validator("max_mb")
    @classmethod
    def _mb(cls, v: int) -> int:
        if not 1 <= v <= 30:
            raise ValueError("사진 최대 크기는 1~30MB로 정해 주세요.")
        return v

    @field_validator("report_hide")
    @classmethod
    def _report(cls, v: int) -> int:
        if not 1 <= v <= 50:
            raise ValueError("신고 자동 숨김 기준은 1~50회로 정해 주세요.")
        return v

    @field_validator("formats")
    @classmethod
    def _formats(cls, v: list[str]) -> list[str]:
        out = []
        for f in v:
            f = f.strip().lower().lstrip(".")
            if f not in FORMATS:
                raise ValueError(f"‘{f}’ 형식은 고를 수 없어요. {', '.join(x.upper() for x in FORMATS)} 중에서 골라 주세요.")
            if f not in out:
                out.append(f)
        return out

    @field_validator("banned")
    @classmethod
    def _banned(cls, v: list[str]) -> list[str]:
        out = []
        for w in v:
            w = (w or "").strip()
            if not w:
                continue
            if len(w) > 20:
                raise ValueError(f"금칙어는 20자까지예요. ‘{w[:20]}…’를 줄여 주세요.")
            if w not in out:
                out.append(w)
        if len(out) > 300:
            raise ValueError("금칙어는 300개까지 둘 수 있어요.")
        return out


class SettingsSaveOut(BaseModel):
    settings: SettingsFull
    changed: int
    message: str = ""
