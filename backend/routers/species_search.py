"""공식 해양생물 이름 검색. 기존 DB의 생물/관찰/수족관 자료를 변경하지 않는다."""
from __future__ import annotations

import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import quote, unquote

import httpx
from fastapi import APIRouter, HTTPException, Path, Query

from backend.config import get_settings
from backend.core import redis_store
from backend.core.timefmt import now
from backend.schemas.species_search import (Provider, SourceSearch, SpeciesDetailOut,
                                           SpeciesRecord, SpeciesSearchOut)

# [BARO-SCOPE-EXTENSION] 별도 검색·공식 API 연결을 위해 사용자가 추가 승인한 신규 파일.
# [BARO-CHANGE-036] 공식 문서의 고정 HTTPS 주소만 사용하고 키·외부 오류 원문을 응답에 노출하지 않는다.
# MBRIS: https://www.data.go.kr/data/15094770/openapi.do
# WoRMS: https://www.marinespecies.org/rest/
router = APIRouter(tags=["생물 이름 검색"])
MBRIS_URL = "https://apis.data.go.kr/B553482/mbrisdataview3/taxonlist3"
WORMS_URL = "https://www.marinespecies.org/rest"
PAGE_SIZE = 10
TIMEOUT = httpx.Timeout(8, connect=3)


class _MbrisLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not (isinstance(record.args, tuple) and any(MBRIS_URL in str(arg) for arg in record.args))


logging.getLogger("httpx").addFilter(_MbrisLogFilter())


class ProviderError(Exception):
    def __init__(self, message: str, status: str = "error"):
        self.message, self.status = message, status


# [BARO-CHANGE-037] 외부 개요·생태의 HTML을 일반 텍스트로 바꾸고 XML 선언형 엔티티를 거부한다.
class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        elif tag in ("br", "p", "div", "li"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        elif tag in ("p", "div", "li"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _text(value) -> str:
    parser = _PlainText()
    parser.feed(str(value or "")[:30000])
    return "\n".join(s.strip() for s in "".join(parser.parts).splitlines() if s.strip())[:20000]


def _mbris(params: dict) -> tuple[list[dict], int]:
    key = get_settings().mbris_api_key.strip()
    if not key:
        raise ProviderError("국립해양생물자원관 연결이 설정되지 않았어요.", "not_configured")
    try:
        response = httpx.get(MBRIS_URL, params={**params, "serviceKey": unquote(key)},
                             timeout=TIMEOUT, follow_redirects=False)
        if response.status_code != 200 or len(response.content) > 2_000_000:
            raise ValueError("invalid response")
        if re.search(br"<!\s*(?:DOCTYPE|ENTITY)", response.content, re.I):
            raise ValueError("unsafe XML")
        root = ET.fromstring(response.content)
        if root.findtext("./header/ResultCode") != "00":
            raise ValueError("provider result")
        total = int(root.findtext("./body/totalCount", "-1"))
        rows = [{child.tag: child.text or "" for child in item} for item in root.findall("./body/items/item")]
        offset = (int(params.get("pageNo", 1)) - 1) * int(params.get("numOfRows", PAGE_SIZE))
        if total < len(rows) or (offset < total and not rows):
            raise ValueError("missing items")
        return rows, total
    except Exception:
        raise ProviderError("국립해양생물자원관 자료를 불러오지 못했어요. 잠시 뒤 다시 검색해 주세요.") from None


def _worms(path: str, params: dict | None = None):
    try:
        response = httpx.get(WORMS_URL + path, params=params, timeout=TIMEOUT, follow_redirects=False)
        if response.status_code == 204:
            return None
        if response.status_code != 200 or len(response.content) > 2_000_000:
            raise ValueError("provider response")
        data = response.json()
        if not isinstance(data, (dict, list)):
            raise ValueError("provider data")
        return data
    except Exception:
        raise ProviderError("WoRMS 자료를 불러오지 못했어요. 잠시 뒤 다시 검색해 주세요.") from None


def _mbris_record(row: dict, full: bool = False) -> SpeciesRecord:
    rid = _text(row.get("SpcTxnId"))
    scientific = _text(row.get("SpcScitfNm"))
    if not re.fullmatch(r"[0-9]{1,20}", rid) or not scientific:
        raise ValueError("invalid MBRIS identity")
    ranks = {"계": "Kingdom", "문": "PhylumDivision", "강": "Class", "목": "Order", "과": "Family"}
    sections = {"개요": "ABST", "형태": "FORM", "생태": "ECOL", "국내 분포": "NADI",
                "해외 분포": "INDI", "서식지": "HABI", "이용 및 활용": "UTLZ"}
    return SpeciesRecord(provider="mbris", id=rid, name=_text(row.get("CommKorNm")), scientific_name=scientific,
                         short_name=_text(row.get("SpcScitfNmShort")), accepted_name=_text(row.get("CorrSpcScitfNm")),
                         taxon_status=_text(row.get("CorrNmTyp")),
                         classification={label: _text(row.get(field)) for label, field in ranks.items() if row.get(field)},
                         sections={label: _text(row.get(field)) for label, field in sections.items()
                                   if full and row.get(field) and _text(row[field])},
                         source_url="https://www.data.go.kr/data/15094770/openapi.do",
                         citation="국립해양생물자원관 해양생물종정보 서비스")


def _worms_record(row: dict) -> SpeciesRecord:
    rid = str(row.get("AphiaID", ""))
    scientific = _text(row.get("scientificname"))
    if not re.fullmatch(r"[0-9]{1,10}", rid) or not scientific:
        raise ValueError("invalid WoRMS identity")
    ranks = {"계": "kingdom", "문": "phylum", "강": "class", "목": "order", "과": "family", "속": "genus"}
    return SpeciesRecord(provider="worms", id=rid, scientific_name=scientific, short_name=scientific,
                         accepted_name=_text(row.get("valid_name")), accepted_id=str(row.get("valid_AphiaID") or ""),
                         taxon_status=_text(row.get("status")), rank=_text(row.get("rank")),
                         marine=bool(row["isMarine"]) if row.get("isMarine") in (0, 1) else None,
                         classification={label: _text(row.get(field)) for label, field in ranks.items() if row.get(field)},
                         source_url=f"https://www.marinespecies.org/aphia.php?p=taxdetails&id={rid}",
                         citation=_text(row.get("citation")) or "WoRMS Editorial Board, World Register of Marine Species")


# [BARO-CHANGE-038] 검색은 출처별로 병렬 조회하고 한쪽 실패를 정상적인 빈 결과로 위장하지 않는다.
def _search_source(provider: str, query: str, page: int) -> SourceSearch:
    korean = bool(re.search(r"[가-힣]", query))
    try:
        if provider == "mbris":
            rows, total = _mbris({"CommKorNm" if korean else "SpcScitfNm": query,
                                  "pageNo": page, "numOfRows": PAGE_SIZE})
            items = [_mbris_record(row) for row in rows]
            more = page * PAGE_SIZE < total
        else:
            method = "AphiaRecordsByVernacular" if korean else "AphiaRecordsByName"
            params = {"like": "true", "offset": (page - 1) * PAGE_SIZE + 1}
            if not korean:
                params["marine_only"] = "true"
            rows = _worms(f"/{method}/{quote(query, safe='')}", params) or []
            if not isinstance(rows, list):
                raise ValueError("invalid search list")
            items = [_worms_record(row) for row in rows[:PAGE_SIZE]]
            total, more = None, len(rows) > PAGE_SIZE
        return SourceSearch(provider=provider, status="ok" if items else "empty", items=items, total=total, has_more=more)
    except ProviderError as exc:
        return SourceSearch(provider=provider, status=exc.status, message=exc.message)
    except Exception:
        return SourceSearch(provider=provider, status="error", message="검색 자료의 형식을 확인하지 못했어요. 잠시 뒤 다시 시도해 주세요.")


# [BARO-CHANGE-039] 학명과 계가 일치한 후보만 연결하며, 동명이종·잘린 결과는 확정하지 않는다.
def _same_taxon(left: SpeciesRecord, right: SpeciesRecord) -> bool:
    normalize = lambda value: " ".join(value.split()).casefold()
    a, b = normalize(left.short_name), normalize(right.short_name)
    ka, kb = left.classification.get("계", ""), right.classification.get("계", "")
    return bool(a and a == b and (not ka or not kb or normalize(ka) == normalize(kb)))


def _detail(provider: str, rid: str) -> SpeciesDetailOut:
    if provider == "mbris":
        rows, total = _mbris({"SpcTxnId": rid, "numOfRows": 2, "pageNo": 1})
        if not rows and total == 0:
            raise HTTPException(404, "해당 생물 정보를 찾지 못했어요. 검색 결과에서 다시 골라 주세요.")
        if len(rows) != 1 or str(rows[0].get("SpcTxnId")) != rid:
            raise ProviderError("종 식별자가 일치하는 자료를 확인하지 못했어요.")
        primary = _mbris_record(rows[0], full=True)
    else:
        if int(rid) > 2_147_483_647:
            raise HTTPException(422, "WoRMS 종 식별자를 확인해 주세요.")
        row = _worms(f"/AphiaRecordByAphiaID/{rid}")
        if row is None:
            raise HTTPException(404, "해당 생물 정보를 찾지 못했어요. 검색 결과에서 다시 골라 주세요.")
        primary = _worms_record(row)
        if primary.id != rid:
            raise ProviderError("종 식별자가 일치하는 자료를 확인하지 못했어요.")
    linked, status = [], "unmatched"
    message = "정확히 일치하는 다른 출처의 종 정보를 찾지 못했어요."
    try:
        if not primary.short_name or primary.taxon_status in ("deleted", "quarantined"):
            candidates, truncated = [], False
        elif provider == "mbris":
            rows = _worms(f"/AphiaRecordsByName/{quote(primary.short_name, safe='')}",
                           {"like": "false", "marine_only": "false"}) or []
            if not isinstance(rows, list):
                raise ValueError("invalid linked list")
            candidates = [_worms_record(row) for row in rows]
            truncated = len(rows) >= 50
        else:
            rows, total = _mbris({"SpcScitfNm": primary.short_name, "pageNo": 1, "numOfRows": 20})
            candidates = [_mbris_record(row, full=True) for row in rows]
            truncated = total > len(rows)
        linked = [row for row in candidates if _same_taxon(primary, row) and row.taxon_status not in ("deleted", "quarantined")]
        linked = list({row.id: row for row in linked}.values())
        if len(linked) == 1 and not truncated:
            status, message = "matched", "학명과 제공된 계 정보를 대조해 다른 출처의 종 정보를 연결했어요."
        elif linked or truncated:
            status, message = "ambiguous", "후보가 여러 개이거나 일부 결과만 확인되어 동일 종으로 확정하지 않았어요."
        linked = linked[:5]
    except ProviderError as exc:
        status = "not_configured" if exc.status == "not_configured" else "unavailable"
        message = exc.message + " 선택한 출처의 정보는 아래에서 볼 수 있어요."
    except Exception:
        status, message = "unavailable", "다른 출처와의 연결을 확인하지 못했어요. 선택한 출처의 정보만 표시해요."
    return SpeciesDetailOut(record=primary, linked_records=linked, link_status=status,
                            link_message=message, fetched_at=now().isoformat(timespec="seconds"))


# [BARO-CHANGE-040] 공개 조회만 짧게 캐시하고 캐시 장애·손상은 공급자 재조회로 복구한다.
# 키에는 검색어 대신 해시를 사용하고 오류·미설정 결과는 저장하지 않는다.
def _cached(key: str, model, fetch, accept):
    try:
        cached = redis_store.cache_get(key)
        if cached is not None:
            result = model.model_validate(cached)
            if accept(result):
                return result
    except Exception:
        pass
    result = fetch()
    healthy = (all(source.status in ("ok", "empty") for source in result.sources)
               if isinstance(result, SpeciesSearchOut) else result.link_status not in ("unavailable", "not_configured"))
    if healthy:
        try:
            redis_store.cache_set(key, result.model_dump(), ttl=3600)
        except Exception:
            pass
    return result


@router.get("/species-search", response_model=SpeciesSearchOut, summary="국명·학명으로 공식 해양생물 검색")
def search(q: str = Query(..., min_length=1, max_length=100), page: int = Query(1, ge=1, le=100)):
    query = " ".join(q.split())
    if not query:
        raise HTTPException(422, "검색할 생물 이름을 적어 주세요.")

    def fetch():
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_search_source, provider, query, page) for provider in ("mbris", "worms")]
            sources = [future.result() for future in futures]
        return SpeciesSearchOut(query=query, page=page, sources=sources, fetched_at=now().isoformat(timespec="seconds"))

    digest = hashlib.sha256(query.encode("utf-8")).hexdigest()
    return _cached(f"species-search:v1:{digest}:{page}", SpeciesSearchOut, fetch,
                   lambda result: result.query == query and result.page == page)


@router.get("/species-search/{provider}/{record_id}", response_model=SpeciesDetailOut, summary="종 식별자로 상세·출처 간 학명 연결")
def detail(provider: Provider, record_id: str = Path(..., pattern=r"^[0-9]{1,20}$")):
    try:
        return _cached(f"species-detail:v1:{provider}:{record_id}", SpeciesDetailOut,
                       lambda: _detail(provider, record_id),
                       lambda result: result.record.provider == provider and result.record.id == record_id)
    except HTTPException:
        raise
    except ProviderError as exc:
        raise HTTPException(503, exc.message) from None
    except Exception:
        raise HTTPException(503, "생물 상세 정보를 확인하지 못했어요. 잠시 뒤 다시 시도해 주세요.") from None
