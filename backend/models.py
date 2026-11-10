"""SQLite 테이블 (SQLModel = SQLAlchemy + pydantic).

앱 데이터는 모두 여기 있어요. Supabase에는 가입 · 로그인 · 메일 인증 · 권한만 맡겨요.
Redis에는 하루 분석 횟수, 랭킹, 조회수, 1회용 인증 링크 값 · 문의 조회 코드, 로그인 세션, 임시 보관처럼 '빨리 바뀌고 사라져도 되는 값'만 둬요.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from backend.core.timefmt import now


class User(SQLModel, table=True):
    id: str = Field(primary_key=True)  # Supabase 모드에서는 Supabase 사용자 id
    email: str = Field(index=True, unique=True)
    nickname: str
    character: str = "🐢"
    role: str = "user"  # user | admin
    provider: str = "local"  # local | supabase
    password_hash: Optional[str] = None  # 로컬 대체 모드에서만 사용
    email_verified: bool = False
    aquarium_public: bool = False
    region: str = "jeju"
    grade: str = "새내기 탐험가"
    points: int = 0
    suspended_until: Optional[datetime] = None
    suspend_reason: str = ""
    created_at: datetime = Field(default_factory=now)


class Species(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str = Field(index=True)
    emoji: str = "🌊"
    tone: str = "aqua"
    confidence: str = "high"
    safety_level: str = "caution"  # safe | caution | danger
    safety_reason: str = ""
    protected: bool = False
    summary: str = ""
    habitat: str = ""
    food: str = ""
    fun_fact: str = ""
    candidates: list = Field(default_factory=list, sa_column=Column(JSON))
    source: str = "seed"  # seed | gemini


class Observation(SQLModel, table=True):
    id: str = Field(primary_key=True)
    user_id: str = Field(index=True, foreign_key="user.id")
    species_id: str = Field(index=True, foreign_key="species.id")
    date: str  # YYYY-MM-DD
    place: str = ""
    memo: str = ""
    post_id: Optional[str] = Field(default=None, index=True)
    photo_path: str = ""
    created_at: datetime = Field(default_factory=now)


class Board(SQLModel, table=True):
    id: str = Field(primary_key=True)  # 고유 주소 (영문)
    name: str = Field(unique=True)
    type: str = "일반형"  # 일반형 | 사진형 | 질문형
    layout: str = "list"  # card | list
    status: str = "준비 중"  # 준비 중 | 운영 중 | 일시 중지 | 보관
    order: int = 99
    system: bool = False  # 관찰 이야기 · 공지사항 (지울 수 없음)
    desc: str = ""
    manager: str = ""
    period: str = ""
    page_size: int = 20
    sort: str = "latest"
    search_fields: list = Field(default_factory=lambda: ["제목", "생물 이름"], sa_column=Column(JSON))
    pin_notice: bool = True
    perm: dict = Field(default_factory=dict, sa_column=Column(JSON))  # list/read/write/comment/photo → 모두/회원/관리자
    rules: dict = Field(default_factory=dict, sa_column=Column(JSON))  # comments/likes/reports(bool), interval(초)
    fields: list = Field(default_factory=list, sa_column=Column(JSON))  # 사용자 정의 항목 정의 목록


class Post(SQLModel, table=True):
    id: str = Field(primary_key=True)
    board_id: str = Field(index=True, foreign_key="board.id")
    user_id: str = Field(index=True, foreign_key="user.id")
    title: str
    body: str = ""
    species_id: Optional[str] = None
    place: str = ""
    place_level: str = "none"  # none | region
    extra: dict = Field(default_factory=dict, sa_column=Column(JSON))  # 사용자 정의 항목 값
    photo_path: str = ""
    likes: int = 0
    comments: int = 0
    report_count: int = 0
    pinned: bool = False
    hidden: bool = False
    deleted: bool = False
    created_at: datetime = Field(default_factory=now)


class Comment(SQLModel, table=True):
    id: str = Field(primary_key=True)
    post_id: str = Field(index=True, foreign_key="post.id")
    user_id: str = Field(foreign_key="user.id")
    body: str
    deleted: bool = False
    created_at: datetime = Field(default_factory=now)


class Like(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("post_id", "user_id"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    post_id: str = Field(index=True, foreign_key="post.id")
    user_id: str = Field(foreign_key="user.id")


class Report(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("post_id", "user_id"),)  # 같은 사람이 같은 글은 한 번만
    id: Optional[int] = Field(default=None, primary_key=True)
    post_id: str = Field(index=True, foreign_key="post.id")
    user_id: str = Field(foreign_key="user.id")
    reason: str
    status: str = "대기"  # 대기 | 숨김 | 문제없음
    created_at: datetime = Field(default_factory=now)


class QuizQuestion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    q: str
    options: list = Field(default_factory=list, sa_column=Column(JSON))
    answer: int = 0
    explain: str = ""
    active: bool = True


class ScoreLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    game: str = Field(index=True)  # quiz | puzzle
    user_id: Optional[str] = None
    nickname: str
    score: int
    created_at: datetime = Field(default_factory=now)


class News(SQLModel, table=True):
    id: str = Field(primary_key=True)
    title: str
    summary: str = ""
    body: str = ""
    source: str = ""
    url: str = ""
    date: str = ""  # YYYY-MM-DD
    ai: bool = True
    public: bool = True
    created_at: datetime = Field(default_factory=now)


class NewsSource(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    url: str
    checked: str = ""  # 이용 조건 확인일
    active: bool = True


class NewsRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    date: str
    ok: int = 0
    fail: int = 0
    failed: list = Field(default_factory=list, sa_column=Column(JSON))


class Inquiry(SQLModel, table=True):
    id: str = Field(primary_key=True)  # 접수번호 R-1108-K3F9
    type: str
    title: str
    body: str
    status: str = "접수"  # 접수 | 처리 중 | 완료
    user_id: Optional[str] = None
    email: str = ""
    answer: str = ""
    photo_path: str = ""
    jira_key: str = ""
    jira_status: str = "off"  # off(미연결) | created | failed | done
    jira_error: str = ""
    mail_sent: bool = False
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class Setting(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)
    data: dict = Field(default_factory=dict, sa_column=Column(JSON))


class AdminLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    screen: str
    actor: str
    action: str
    target: str = ""
    before: str = ""
    after: str = ""
    reason: str = ""
    created_at: datetime = Field(default_factory=now)


def species_dict(s: Species) -> dict[str, Any]:
    """화면이 쓰는 생물 모양 (예시 데이터와 같은 모양)."""
    return {"id": s.id, "name": s.name, "emoji": s.emoji, "tone": s.tone, "confidence": s.confidence,
            "safety": {"level": s.safety_level, "reason": s.safety_reason}, "protected": s.protected,
            "summary": s.summary, "info": {"habitat": s.habitat, "food": s.food, "fun_fact": s.fun_fact},
            "candidates": list(s.candidates or [])}
