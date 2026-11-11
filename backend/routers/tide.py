"""물때 API: 공식 고·저조 예보 또는 명시적인 예시 자료를 제공한다."""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from urllib.parse import unquote

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from backend.config import get_settings
from backend.core import redis_store
from backend.core.security import require_user
from backend.core.timefmt import now
from backend.db import MOCK, get_session
from backend.models import User
from backend.schemas.aquarium import RegionIn, RegionOut
from backend.schemas.common import TideOut

router = APIRouter(tags=["물때"])
CACHE_TTL = 3600
OBSERVATION_CACHE_TTL = 60

# [BARO-CHANGE-005] 공식 포털의 2026-11-06 활용 가이드 코드표를 사용한다.
# https://www.data.go.kr/data/15156018/openapi.do
# 지역별 대표 예보지점이며 기존 해변과 동일 위치 또는 최근접 지점이라는 의미는 아니다.
API_URL = "https://apis.data.go.kr/1192136/tideFcstHghLw/GetTideFcstHghLwApiService"
REGIONS = {
    "jeju": ("제주 · 협재", "DT_0004", "제주"),
    "busan": ("부산 · 해운대", "DT_0005", "부산"),
    "taean": ("태안 · 만리포", "SO_0699", "천리포항"),
    "gangneung": ("강릉 · 경포", "SO_0733", "강릉항"),
    "incheon": ("인천 · 을왕리", "DT_0001", "인천"),
    "tongyeong": ("통영 · 한산도", "DT_0014", "통영"),
}
SOURCE = "해양수산부 국립해양조사원 조석예보(고, 저조)"

# [BARO-CHANGE-046] 공식 dtRecent 관측 코드가 실제 응답한 네 곳만 연결한다.
# 태안·강릉의 기존 SO 예보 코드는 dtRecent에서 관측소로 인정되지 않아 오연결을 피한다.
OBSERVATION_API_URL = "https://apis.data.go.kr/1192136/dtRecent/GetDTRecentApiService"
OBSERVATION_STATIONS = {
    "jeju": ("DT_0004", "제주"),
    "busan": ("DT_0005", "부산"),
    "incheon": ("DT_0001", "인천"),
    "tongyeong": ("DT_0014", "통영"),
}
OBSERVATION_SOURCE = "해양수산부 국립해양조사원 조위관측소 최신 관측데이터"


# [BARO-CHANGE-030] HTTPX의 INFO 접근 로그에도 인증키가 있는 공식 요청 URL을 남기지 않는다.
class _TideRequestLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return (not any(url in str(arg) for arg in record.args for url in (API_URL, OBSERVATION_API_URL))
                if isinstance(record.args, tuple) else True)


logging.getLogger("httpx").addFilter(_TideRequestLogFilter())


# [BARO-CHANGE-006] 지역 목록은 미조회 상태로 제공해 공급자 장애와 지역 선택을 분리한다.
# 기존 dict[str, TideOut] 구조는 유지하며 실제 시각은 지역별 API에서 조회한다.
def _catalog(region_id: str) -> TideOut:
    name, code, station = REGIONS[region_id]
    official = bool(get_settings().tide_api_key.strip())
    return TideOut(id=region_id, name=name, high=[], low=[], wave="미제공", updated="",
                   source=SOURCE if official else "예시 데이터", available=False,
                   data_kind="forecast" if official else "example", station_id=code if official else "",
                   station_name=station if official else "")


# [BARO-CHANGE-007] 공식 응답의 극치구분 1·3(고조), 2·4(저조)를 날짜 검증 후 변환한다.
# 제공되지 않는 파고·예보 발표시각은 생성하지 않으며 공식 API 오류를 mock으로 대체하지 않는다.
def _fetch(region_id: str) -> dict:
    meta = _catalog(region_id)
    key = get_settings().tide_api_key.strip()
    if not key:
        data = json.loads((MOCK / "tide.json").read_text(encoding="utf-8"))[region_id]
        return {**data, "id": region_id, "source": "예시 데이터", "data_kind": "example", "available": True}
    day = now().date()
    try:
        # 키는 공식 HTTPS 호스트에만 전송한다. redirect·예외 원문·요청 URL은 노출하지 않는다.
        response = httpx.get(API_URL, params={"serviceKey": unquote(key), "obsCode": meta.station_id,
                             "reqDate": day.strftime("%Y%m%d"), "type": "json", "pageNo": 1, "numOfRows": 10},
                             timeout=10, follow_redirects=False)
        if response.status_code != 200:
            raise ValueError("upstream status")
        payload = response.json()
        root = payload.get("response", payload)
        if str(root["header"]["resultCode"]) != "00":
            raise ValueError("upstream result")
        items = root["body"]["items"]
        rows = items.get("item", []) if isinstance(items, dict) else items
        rows = [rows] if isinstance(rows, dict) else rows
        if not isinstance(rows, list) or not rows:
            raise ValueError("no forecast")
        high, low = [], []
        for row in rows:
            stamp = datetime.fromisoformat(row["predcDt"])
            if stamp.date() != day or row["obsvtrNm"] != meta.station_name:
                raise ValueError("forecast target mismatch")
            kind = str(row["extrSe"])
            if kind not in ("1", "2", "3", "4"):
                raise ValueError("unknown extremum")
            (high if kind in ("1", "3") else low).append(stamp.strftime("%H:%M"))
        return {**meta.model_dump(), "high": sorted(set(high)), "low": sorted(set(low)),
                "available": True, "target_date": day.isoformat(), "updated": now().isoformat(timespec="seconds")}
    except Exception:
        raise HTTPException(503, "공식 물때 예보를 확인하지 못했어요. API 권한·제공 상태를 확인한 뒤 다시 시도해 주세요.") from None


# [BARO-CHANGE-047] 최신 관측 API에서 검증된 조위(cm)·수온(°C)·관측시각만 별도로 읽는다.
def _fetch_observation(region_id: str) -> dict:
    station = OBSERVATION_STATIONS.get(region_id)
    if not station:
        return {"observation_status": "unavailable",
                "observation_message": "선택 지역에 연결할 수 있는 조위관측소 자료가 아직 없어요."}
    key = get_settings().observation_api_key.strip()
    if not key:
        return {"observation_status": "not_configured",
                "observation_message": "조위관측 API 키가 설정되지 않았어요."}
    station_id, expected_name = station
    day = now().date()
    try:
        response = httpx.get(OBSERVATION_API_URL,
                             params={"serviceKey": unquote(key), "obsCode": station_id,
                                     "reqDate": day.strftime("%Y%m%d"), "type": "json",
                                     "pageNo": 1, "numOfRows": 1, "min": 1},
                             timeout=10, follow_redirects=False)
        if response.status_code != 200:
            raise ValueError("upstream status")
        payload = response.json()
        root = payload.get("response", payload)
        header = root["header"]
        if str(header["resultCode"]) != "00":
            raise ValueError("upstream result")
        body = root["body"]
        items = body.get("items", {})
        rows = items.get("item", []) if isinstance(items, dict) else items
        rows = [rows] if isinstance(rows, dict) else rows
        if not isinstance(rows, list) or not rows:
            return {"observation_status": "empty",
                    "observation_message": "오늘 날짜의 조위관측 자료가 아직 없어요.",
                    "observation_station_id": station_id, "observation_station_name": expected_name,
                    "observation_source": OBSERVATION_SOURCE}
        row = rows[0]
        if row.get("obsvtrNm") != expected_name:
            raise ValueError("station mismatch")
        observed_at = datetime.fromisoformat(str(row["obsrvnDt"]))
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=now().tzinfo)
        if observed_at.date() != day or observed_at > now():
            raise ValueError("observation date mismatch")
        level = float(row["bscTdlvHgt"])
        temperature_value = row.get("wtem")
        temperature = float(temperature_value) if temperature_value not in (None, "") else None
        if not math.isfinite(level) or (temperature is not None and not math.isfinite(temperature)):
            raise ValueError("invalid observation value")
        stale = (now() - observed_at).total_seconds() > 2 * 60 * 60
        return {"observation_status": "stale" if stale else "ok",
                "observation_message": "관측 시각이 2시간 이상 지난 자료예요." if stale else "",
                "observation_level_cm": level, "observation_water_temp_c": temperature,
                "observation_time": observed_at.isoformat(timespec="minutes"),
                "observation_station_id": station_id, "observation_station_name": expected_name,
                "observation_source": OBSERVATION_SOURCE}
    except Exception:
        # [BARO-CHANGE-048] 관측 실패가 정상적인 예보를 가리거나 외부 오류 원문을 노출하지 않게 한다.
        return {"observation_status": "error",
                "observation_message": "현재 관측자료를 가져오지 못했어요. API 권한·제공 상태를 확인해 주세요.",
                "observation_station_id": station_id, "observation_station_name": expected_name,
                "observation_source": OBSERVATION_SOURCE}


# [BARO-CHANGE-051] 1분 관측 캐시도 지역·관측소·날짜·수치가 맞는지 확인한 뒤 화면에 전달한다.
def _validate_observation(data: dict, region_id: str) -> dict:
    station_id, station_name = OBSERVATION_STATIONS[region_id]
    if (not isinstance(data, dict) or data.get("observation_station_id") != station_id
            or data.get("observation_station_name") != station_name
            or data.get("observation_source") != OBSERVATION_SOURCE):
        raise ValueError("observation target mismatch")
    status = data.get("observation_status")
    if status == "empty":
        return {"observation_status": status, "observation_message": str(data.get("observation_message", "")),
                "observation_station_id": station_id, "observation_station_name": station_name,
                "observation_source": OBSERVATION_SOURCE}
    if status not in ("ok", "stale"):
        raise ValueError("observation cache status")
    observed_at = datetime.fromisoformat(str(data.get("observation_time", "")))
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=now().tzinfo)
    if observed_at.date() != now().date() or observed_at > now():
        raise ValueError("observation cache time")
    level = float(data["observation_level_cm"])
    raw_temperature = data.get("observation_water_temp_c")
    temperature = float(raw_temperature) if raw_temperature is not None else None
    if not math.isfinite(level) or (temperature is not None and not math.isfinite(temperature)):
        raise ValueError("observation cache value")
    stale = (now() - observed_at).total_seconds() > 2 * 60 * 60
    return {"observation_status": "stale" if stale else "ok",
            "observation_message": "관측 시각이 2시간 이상 지난 자료예요." if stale else "",
            "observation_level_cm": level, "observation_water_temp_c": temperature,
            "observation_time": observed_at.isoformat(timespec="minutes"),
            "observation_station_id": station_id, "observation_station_name": station_name,
            "observation_source": OBSERVATION_SOURCE}


# [BARO-CHANGE-049] 예보 캐시와 분리해 관측값은 1분만 캐시하며 장애 시 예보는 계속 표시한다.
def _attach_observation(result: TideOut, region_id: str) -> TideOut:
    station = OBSERVATION_STATIONS.get(region_id)
    if not station or not get_settings().observation_api_key.strip():
        return result.model_copy(update=_fetch_observation(region_id))
    cache_key = f"tide:observation:v1:{station[0]}:{now():%Y%m%d}"
    try:
        cached = redis_store.cache_get(cache_key)
        if isinstance(cached, dict):
            return result.model_copy(update=_validate_observation(cached, region_id))
    except Exception:
        pass  # 공개 관측 캐시 장애는 공식 API 재조회로 우회한다.
    observation = _fetch_observation(region_id)
    if observation.get("observation_status") in ("ok", "stale", "empty"):
        try:
            redis_store.cache_set(cache_key, observation, ttl=OBSERVATION_CACHE_TTL)
        except Exception:
            pass
    return result.model_copy(update=observation)


# [BARO-CHANGE-008] 공급자·날짜·지역별 캐시를 검증하고 손상·다른 지점·과거 예보를 재조회한다.
def _validate(data: dict, region_id: str) -> TideOut:
    result = TideOut.model_validate(data)
    meta = _catalog(region_id)
    if result.id != region_id or not result.available or result.data_kind != meta.data_kind:
        raise ValueError("invalid cached target")
    if not result.high and not result.low:
        raise ValueError("missing tide times")
    for value in result.high + result.low:
        parsed = datetime.strptime(value, "%H:%M")
        if parsed.strftime("%H:%M") != value:
            raise ValueError("invalid tide time")
    datetime.fromisoformat(result.updated)
    if meta.data_kind == "forecast":
        if (result.target_date != now().date().isoformat() or result.station_id != meta.station_id
                or result.station_name != meta.station_name or result.source != SOURCE):
            raise ValueError("stale or mismatched forecast")
    else:
        result.source = "예시 데이터"
    return result


def _one(region_id: str) -> TideOut:
    if region_id not in REGIONS:
        raise HTTPException(404, "그 지역의 물때 정보가 없어요. 지역을 다시 골라 주세요.")
    mode = _catalog(region_id).data_kind
    cache_key = f"tide:v4:{mode}:{now():%Y%m%d}:{region_id}"
    try:
        data = redis_store.cache_get(cache_key)
        if data is not None:
            result = _validate(data, region_id)
            return _attach_observation(result, region_id)
    except Exception:
        pass  # 공개 자료 캐시 장애만 우회한다. 인증 의존성에는 적용하지 않는다.
    try:
        result = _validate(_fetch(region_id), region_id)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "물때 자료 형식을 확인하지 못했어요. 잠시 뒤 다시 시도해 주세요.") from None
    try:
        redis_store.cache_set(cache_key, result.model_dump(exclude={
            "observation_status", "observation_message", "observation_level_cm",
            "observation_water_temp_c", "observation_time", "observation_station_id",
            "observation_station_name", "observation_source"}), ttl=CACHE_TTL)
    except Exception:
        pass
    return _attach_observation(result, region_id)


@router.get("/tide/regions", response_model=dict[str, TideOut], summary="선택 가능한 물때 지역 (자료는 지역별 조회)")
def regions():
    return {rid: _catalog(rid) for rid in REGIONS}


@router.get("/tide/{region_id}", response_model=TideOut, summary="지역 하나의 오늘 물때")
def tide(region_id: str):
    return _one(region_id)


# [BARO-CHANGE-009] 지역 카탈로그로 검증하여 예보 공급자 장애 때도 선택 지역을 저장한다.
@router.put("/me/region", response_model=RegionOut, summary="물때 카드에서 고른 지역을 내 계정에 기억")
def set_region(body: RegionIn, user: User = Depends(require_user), session: Session = Depends(get_session)):
    if body.region not in REGIONS:
        raise HTTPException(404, "그 지역의 물때 정보가 없어요. 지역을 다시 골라 주세요.")
    user.region = body.region
    session.add(user)
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise HTTPException(500, "지역을 기억하지 못했어요. 이번 방문 동안만 기억할게요.") from None
    return RegionOut(region=body.region, name=REGIONS[body.region][0])
