"""물때 API (김바로 담당). 지금은 mock/tide.json 예시 값을 Redis에 1시간 캐시해서 줘요.

진짜 공공 API로 바꿀 때는 _fetch() 한 곳만 고치면 돼요 (아래 설명). 나머지(캐시 · 화면 모양)는 그대로예요.
회원이 물때 카드에서 고른 지역은 PUT /me/region 으로 계정(User.region)에 남겨요.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from backend.core import redis_store
from backend.core.security import require_user
from backend.db import MOCK, get_session
from backend.models import User
from backend.schemas.aquarium import RegionIn, RegionOut
from backend.schemas.common import TideOut

router = APIRouter(tags=["물때"])
CACHE_KEY, CACHE_TTL = "tide:all", 3600


def _fetch() -> dict:
    """물때 원본을 가져오는 단 하나의 자리. {지역 id: {name, high, low, wave, updated, source?}} 모양으로 돌려줘요.

    공공 API(국립해양조사원 바다누리 ‘조석 예보’ 등)로 바꾸는 방법:
      1) 지역 id ↔ 관측소 코드 표를 만들어요. 예) {"jeju": "DT_0004", "busan": "DT_0005", ...}
      2) 여기서 httpx.get(API 주소, params={"ServiceKey": 키, "ObsCode": 코드, "Date": 오늘(YYYYMMDD)}, timeout=10)
         으로 지역마다 불러서, 만조 · 간조 시각을 "HH:MM" 목록으로, 파고를 "0.5 ~ 1.0m" 같은 글로 바꿔요.
      3) source 에 "국립해양조사원" 처럼 출처를 넣어요 (화면 아래 ‘출처’에 그대로 나와요).
      4) 키는 코드에 쓰지 말고 환경변수로 받아요 (backend/config.py 에 TIDE_API_KEY 칸을 하나 늘려야 해요).
    실패하면 예외를 그대로 올려요. _all() 이 Redis에 남아 있는 마지막 값을 쓰지 못하면 화면이 ‘불러오지 못했어요’를 보여줘요.
    """
    return json.loads((MOCK / "tide.json").read_text(encoding="utf-8"))


def _all() -> dict:
    try:
        data = redis_store.cache_get(CACHE_KEY)
    except Exception:  # Redis가 꺼져 있어도 물때는 보여줘요 (캐시만 건너뛰어요)
        return _fetch()
    if data is None:
        data = _fetch()
        try:
            redis_store.cache_set(CACHE_KEY, data, ttl=CACHE_TTL)
        except Exception:
            pass
    return data


@router.get("/tide/regions", response_model=dict[str, TideOut], summary="물때 지역 전체")
def regions():
    return {k: TideOut(id=k, **v) for k, v in _all().items()}


@router.get("/tide/{region_id}", response_model=TideOut, summary="지역 하나의 오늘 물때")
def tide(region_id: str):
    d = _all().get(region_id)
    if not d:
        raise HTTPException(404, "그 지역의 물때 정보가 없어요. 지역을 다시 골라 주세요.")
    return TideOut(id=region_id, **d)


@router.put("/me/region", response_model=RegionOut, summary="물때 카드에서 고른 지역을 내 계정에 기억")
def set_region(body: RegionIn, user: User = Depends(require_user), session: Session = Depends(get_session)):
    d = _all().get(body.region)
    if not d:
        raise HTTPException(404, "그 지역의 물때 정보가 없어요. 지역을 다시 골라 주세요.")
    user.region = body.region
    session.add(user)
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise HTTPException(500, "지역을 기억하지 못했어요. 이번 방문 동안만 기억할게요.")
    return RegionOut(region=body.region, name=d["name"])
