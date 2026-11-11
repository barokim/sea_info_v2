"""공식 생물 이름 검색·상세 조회 응답 계약. 기존 내부 Species 모델과 구분한다."""
from typing import Literal

from pydantic import BaseModel, Field

# [BARO-SCOPE-EXTENSION] 별도 검색 기능을 위해 사용자가 추가 승인한 신규 파일.
# [BARO-CHANGE-034] 출처별 식별자와 정상·빈 결과·미설정·오류를 분리하여 잘못된 종 병합을 막는다.
Provider = Literal["mbris", "worms"]


class SpeciesRecord(BaseModel):
    provider: Provider
    id: str
    name: str = ""
    scientific_name: str
    short_name: str = ""
    accepted_name: str = ""
    accepted_id: str = ""
    taxon_status: str = ""
    rank: str = ""
    marine: bool | None = None
    classification: dict[str, str] = Field(default_factory=dict)
    sections: dict[str, str] = Field(default_factory=dict)
    source_url: str
    citation: str = ""


class SourceSearch(BaseModel):
    provider: Provider
    status: Literal["ok", "empty", "not_configured", "error"]
    message: str = ""
    total: int | None = None
    has_more: bool = False
    items: list[SpeciesRecord] = Field(default_factory=list)


class SpeciesSearchOut(BaseModel):
    query: str
    page: int
    sources: list[SourceSearch]
    fetched_at: str


class SpeciesDetailOut(BaseModel):
    record: SpeciesRecord
    linked_records: list[SpeciesRecord] = Field(default_factory=list)
    link_status: Literal["matched", "ambiguous", "unmatched", "unavailable", "not_configured"]
    link_message: str
    fetched_at: str
