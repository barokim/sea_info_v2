"""여러 화면이 같이 쓰는 API 모양 (pydantic, 편성훈).

화면(Streamlit)이 받는 JSON 모양은 시안 때 예시 데이터와 같게 맞췄어요.
그래서 화면 코드는 거의 그대로 쓸 수 있어요.
"""
from __future__ import annotations

from datetime import date as Date
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class SafetyOut(BaseModel):
    level: Literal["safe", "caution", "danger"]
    reason: str


class InfoOut(BaseModel):
    habitat: str = ""
    food: str = ""
    fun_fact: str = ""


class SpeciesOut(BaseModel):
    id: str
    name: str
    emoji: str = "🌊"
    tone: str = "aqua"
    confidence: Literal["high", "medium", "low"] = "high"
    safety: SafetyOut
    protected: bool = False
    summary: str = ""
    info: InfoOut
    candidates: list[str] = []


class AnalysisResult(SpeciesOut):
    photo_id: str = ""
    source: Literal["gemini", "example"] = "example"


class IdentifyOut(BaseModel):
    result: AnalysisResult
    left: int
    limit: int


class UsageOut(BaseModel):
    left: int
    limit: int
    used: int


class UserPublic(BaseModel):
    id: str
    nickname: str
    character: str = "🐢"
    aquarium_public: bool = False


class UserMe(UserPublic):
    email: str
    role: Literal["user", "admin"] = "user"
    provider: str = "local"
    region: str = "jeju"
    grade: str = ""
    points: int = 0
    created: str = ""


class SessionOut(BaseModel):
    token: str
    user: UserMe


class BoardOut(BaseModel):
    id: str
    name: str
    type: str
    layout: str
    status: str
    order: int
    system: bool
    desc: str = ""
    manager: str = ""
    period: str = ""
    page_size: int = 20
    sort: str = "latest"
    search_fields: list[str] = []
    pin_notice: bool = True
    perm: dict[str, str] = {}
    rules: dict[str, Any] = {}
    fields: list[dict[str, Any]] = []


class PostOut(BaseModel):
    id: str
    board: str
    user: str
    author: Optional[UserPublic] = None
    title: str
    body: str = ""
    species: Optional[str] = None
    place: str = ""
    place_level: str = "none"
    extra: dict[str, Any] = {}
    photo_url: str = ""
    likes: int = 0
    comments: int = 0
    report_count: int = 0
    pinned: bool = False
    hidden: bool = False
    created: str = ""  # '2시간 전'
    created_at: str = ""  # ISO


class CommentOut(BaseModel):
    id: str
    post: str
    user: str
    author: Optional[UserPublic] = None
    body: str
    created: str


class NewsOut(BaseModel):
    id: str
    title: str
    summary: str = ""
    source: str = ""
    url: str = ""
    date: str = ""
    ai: bool = True
    public: bool = True
    views: int = 0


class TideOut(BaseModel):
    id: str
    name: str
    high: list[str]
    low: list[str]
    wave: str
    updated: str
    source: str = "예시 데이터"


class ObservationOut(BaseModel):
    id: str
    user: str
    species: str
    date: str
    place: str = ""
    memo: str = ""
    post_id: Optional[str] = None
    photo_url: str = ""


class AquariumCard(BaseModel):
    species: SpeciesOut
    records: list[ObservationOut]
    count: int
    last: str
    shared: bool


class SettingsPublic(BaseModel):
    limit_member: int
    limit_guest: int
    max_mb: int
    formats: list[str]
    report_hide: int
    default_region: str


class SaveIn(BaseModel):
    """U-04 수족관에 담기 (+ 선택 공유)."""
    result: AnalysisResult
    date: Date
    place: str = Field("", max_length=60)
    memo: str = Field("", max_length=200)
    share: bool = False
    title: str = Field("", max_length=50)
    place_level: Literal["none", "region"] = "none"
    consent: bool = False

    @model_validator(mode="after")
    def _share_needs(self):
        if self.share and not self.title.strip():
            raise ValueError("공유하려면 제목을 적어 주세요.")
        if self.share and not self.consent:
            raise ValueError("공유하려면 사진 활용 동의가 필요해요.")
        return self


class SaveOut(BaseModel):
    new_species: bool
    total_species: int
    count: int
    post_id: Optional[str] = None


class DraftIn(BaseModel):
    result: AnalysisResult


class DraftOut(BaseModel):
    id: str


class OkOut(BaseModel):
    ok: bool = True
    message: str = ""


class HealthOut(BaseModel):
    ok: bool
    app_env: str
    db: bool
    redis: bool
    modes: dict[str, str]
