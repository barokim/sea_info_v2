"""바다 소식 · 소식 관리 · 수집 API 모양 (pydantic, 이정민 담당).

공개 소식 한 건은 schemas/common.py 의 NewsOut 을 그대로 써요 (홈 화면도 같은 모양을 써요).
"""
from __future__ import annotations

from datetime import date as Date
from typing import Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.core.timefmt import today
from backend.schemas.common import NewsOut


def check_url(v: str, what: str = "원문 주소") -> str:
    v = (v or "").strip()
    u = urlparse(v)
    if u.scheme not in ("http", "https") or not u.netloc or " " in v:
        raise ValueError(f"{what}가 맞지 않아요. http:// 또는 https://로 시작하는 주소를 적어 주세요.")
    if len(v) > 500:
        raise ValueError(f"{what}가 너무 길어요. 500자 안의 주소를 적어 주세요.")
    return v


def _text(v: Optional[str], empty: str, limit: int, long_: str) -> str:
    v = (v or "").strip()
    if not v:
        raise ValueError(empty)
    if len(v) > limit:
        raise ValueError(long_)
    return v


def _title(v):
    return _text(v, "제목이 비어 있어요. 제목을 적어 주세요.", 60, "제목이 너무 길어요. 60자 안으로 적어 주세요.")


def _summary(v):
    return _text(v, "요약이 비어 있어요. 두세 문장으로 적어 주세요.", 400, "요약이 너무 길어요. 400자 안으로 줄여 주세요.")


def _source(v):
    return _text(v, "출처가 비어 있어요. 소식을 낸 기관 · 매체 이름을 적어 주세요.", 40,
                 "출처 이름이 너무 길어요. 40자 안으로 적어 주세요.")


class NewsViewOut(BaseModel):
    views: int
    counted: bool = Field(description="이번에 조회수가 올랐는지 (같은 사람은 24시간에 한 번)")


class LastRunOut(BaseModel):
    """바다 소식 화면 위의 ‘○○에 새로 모았어요’ 표시용."""
    date: str
    ok: int
    fail: int


class AdminNewsOut(NewsOut):
    body: str = ""
    edited: bool = False  # 운영자가 고친 적이 있는지 (관리 기록으로 알아봐요)
    created_at: str = ""


class NewsCreateIn(BaseModel):
    """관리자 직접 등록. use_ai면 내용(body)을 AI가 두세 문장으로 요약하고 ‘AI 요약’이 붙어요."""
    title: str
    source: str
    url: str
    date: Optional[Date] = None
    summary: str = ""
    body: str = Field("", max_length=20000)
    use_ai: bool = False

    @field_validator("title")
    @classmethod
    def _t(cls, v):
        return _title(v)

    @field_validator("source")
    @classmethod
    def _src(cls, v):
        return _source(v)

    @field_validator("url")
    @classmethod
    def _u(cls, v):
        return check_url(v)

    @model_validator(mode="after")
    def _need_text(self):
        self.summary, self.body = self.summary.strip(), self.body.strip()
        if not (self.summary or self.body):
            raise ValueError("내용이 비어 있어요. 요약이나 원문 내용을 적어 주세요.")
        if self.summary:
            self.summary = _summary(self.summary)
        if self.date and self.date > today():
            raise ValueError("앞으로 올 날짜는 고를 수 없어요. 오늘이나 지난 날짜를 골라 주세요.")
        return self


class NewsPatch(BaseModel):
    """고칠 칸만 보내요. public=False면 바다 소식에서 숨겨요."""
    title: Optional[str] = None
    summary: Optional[str] = None
    source: Optional[str] = None
    url: Optional[str] = None
    public: Optional[bool] = None

    @field_validator("title")
    @classmethod
    def _t(cls, v):
        return None if v is None else _title(v)

    @field_validator("summary")
    @classmethod
    def _s(cls, v):
        return None if v is None else _summary(v)

    @field_validator("source")
    @classmethod
    def _src(cls, v):
        return None if v is None else _source(v)

    @field_validator("url")
    @classmethod
    def _u(cls, v):
        return None if v is None else check_url(v)


class SourceIn(BaseModel):
    id: Optional[int] = None
    name: str
    url: str
    checked: Optional[Date] = Field(None, description="이용 조건 확인일. 비어 있으면 수집하지 않아요")
    active: bool = False

    @field_validator("name")
    @classmethod
    def _n(cls, v):
        return _text(v, "이름이 빈 출처가 있어요. 이름을 적어 주세요.", 40, "출처 이름이 너무 길어요. 40자 안으로 적어 주세요.")

    @field_validator("url")
    @classmethod
    def _u(cls, v):
        return check_url(v, "출처 주소")

    @field_validator("checked", mode="before")
    @classmethod
    def _c(cls, v):
        return v or None

    @model_validator(mode="after")
    def _not_future(self):
        if self.checked and self.checked > today():
            raise ValueError("이용 조건 확인일은 오늘이나 지난 날짜여야 해요.")
        return self


class SourceOut(BaseModel):
    id: int
    name: str
    url: str
    checked: str = ""
    active: bool = False


class FailedSource(BaseModel):
    name: str
    reason: str


class RunOut(BaseModel):
    id: int
    date: str  # '2026-11-08 06:00' (한국 시간)
    ok: int
    fail: int
    failed: list[str] = []  # 실패한 출처 이름 (예시 데이터와 같은 모양)
    reasons: dict[str, str] = {}  # 출처 이름 → 실패 이유


class CollectIn(BaseModel):
    source_names: Optional[list[str]] = Field(None, description="비우면 사용 중인 출처 모두. 이름을 주면 그 출처만 다시 모아요")


class CollectOut(BaseModel):
    ok: int
    fail: int
    failed: list[FailedSource]
    added: list[str] = []  # 새로 넣은 소식 제목
    run: RunOut
