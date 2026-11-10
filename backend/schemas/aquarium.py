"""나의 수족관 · 다른 사람 수족관 · 물때 지역 API 모양 (pydantic, 김바로 담당).

화면이 받는 JSON 모양은 시안 때 예시 데이터와 같게 맞췄어요.
  - 내 수족관 카드: schemas/common.py 의 AquariumCard · ObservationOut (편성훈)
  - 다른 사람 수족관 카드: 아래 SharedCard (기록 한 줄 = 공유한 글 하나)
"""
from __future__ import annotations

from datetime import date as Date
from typing import Literal, Optional

from pydantic import BaseModel, field_validator, model_validator

from backend.core.timefmt import today
from backend.schemas.common import ObservationOut, SpeciesOut, UserPublic


def _clean(v: Optional[str], limit: int, what: str) -> Optional[str]:
    if v is None:
        return None
    v = v.strip()
    if len(v) > limit:
        raise ValueError(f"{what}은(는) {limit}자 안으로 적어 주세요.")
    return v


# ---------- 내 관찰 기록 고치기 · 공유 ----------
class ObservationPatch(BaseModel):
    """고칠 칸만 보내요. 보내지 않은 칸은 그대로예요. species_id를 바꾸면 그 생물 카드로 옮겨져요."""
    date: Optional[Date] = None
    place: Optional[str] = None
    memo: Optional[str] = None
    species_id: Optional[str] = None

    @field_validator("date")
    @classmethod
    def _date(cls, v):
        if v is not None and v > today():
            raise ValueError("만난 날은 오늘보다 늦을 수 없어요. 날짜를 다시 골라 주세요.")
        return v

    @field_validator("place")
    @classmethod
    def _place(cls, v):
        return _clean(v, 60, "만난 곳")

    @field_validator("memo")
    @classmethod
    def _memo(cls, v):
        return _clean(v, 200, "메모")

    @field_validator("species_id")
    @classmethod
    def _species(cls, v):
        if v is not None and not v.strip():
            raise ValueError("생물 이름을 골라 주세요.")
        return v.strip() if v else v


class ShareIn(BaseModel):
    """내 기록을 ‘관찰 이야기’에 공유하기."""
    title: str
    place_level: Literal["none", "region"] = "none"
    consent: bool = False

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("공유하려면 제목을 적어 주세요.")
        if len(v) > 50:
            raise ValueError("제목은 50자 안으로 적어 주세요.")
        return v

    @model_validator(mode="after")
    def _consent(self):
        if not self.consent:
            raise ValueError("공유하려면 사진 활용 동의가 필요해요.")
        return self


class ShareOut(BaseModel):
    post_id: str
    observation: ObservationOut


class PublicIn(BaseModel):
    public: bool


class PublicOut(BaseModel):
    public: bool
    message: str


# ---------- 다른 사람 수족관 (U-11) ----------
class SharedRecord(BaseModel):
    """공유한 기록 한 줄 (관찰 이야기 글 하나). 위치는 올린 사람이 ‘지역까지만’ 공개한 경우만 담아요."""
    title: str
    memo: str = ""
    date: str  # YYYY-MM-DD (정렬용)
    when: str  # '11월 3일'
    place: str = ""
    likes: int = 0
    post_id: Optional[str] = None


class SharedCard(BaseModel):
    species: SpeciesOut
    records: list[SharedRecord]
    count: int
    last: str  # '11월 3일'
    shared: bool = True


class AquariumOwner(UserPublic):
    grade: str = ""


class PublicAquariumOut(BaseModel):
    owner: AquariumOwner
    cards: list[SharedCard]
    species_count: int
    record_count: int


class PublicAquariumItem(BaseModel):
    """구경할 수 있는 수족관 목록 한 줄."""
    owner: AquariumOwner
    species_count: int
    record_count: int


# ---------- 물때 지역 기억 (C-02) ----------
class RegionIn(BaseModel):
    region: str


class RegionOut(BaseModel):
    region: str
    name: str
