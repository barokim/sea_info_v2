"""공통 조회 API (편성훈): 상태 확인 · 생물 · 회원 공개 정보 · 공개 설정."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlmodel import Session, select

from backend.config import get_settings
from backend.core import redis_store
from backend.core.convert import species_out, user_public
from backend.db import get_session
from backend.models import Setting, Species, User
from backend.schemas.common import HealthOut, SettingsPublic, SpeciesOut, UserPublic

router = APIRouter(tags=["공통"])


@router.get("/health", response_model=HealthOut, summary="서버 상태와 연동 모드")
def health(session: Session = Depends(get_session)):
    s = get_settings()
    try:
        session.exec(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return HealthOut(ok=db_ok and redis_store.ping(), app_env=s.app_env, db=db_ok, redis=redis_store.ping(), modes={
        "auth": "supabase" if s.supabase_on else "local",
        "mail": "smtp" if s.smtp_on else "dev",
        "ai": "gemini" if s.gemini_on else "example",
        "jira": "on" if s.jira_on else "off",
    })


@router.get("/species", response_model=list[SpeciesOut], summary="생물 목록")
def species_list(session: Session = Depends(get_session)):
    return [species_out(s) for s in session.exec(select(Species)).all()]


@router.get("/species/{species_id}", response_model=SpeciesOut, summary="생물 하나")
def species_one(species_id: str, session: Session = Depends(get_session)):
    s = session.get(Species, species_id)
    if not s:
        raise HTTPException(404, "생물 정보를 찾지 못했어요.")
    return species_out(s)


@router.get("/users/{user_id}", response_model=UserPublic, summary="회원 공개 정보 (닉네임 · 캐릭터)")
def user_one(user_id: str, session: Session = Depends(get_session)):
    u = session.get(User, user_id)
    if not u:
        return UserPublic(id=user_id, nickname="알 수 없음", character="🌊")
    return user_public(u)


def settings_data(session: Session) -> dict:
    row = session.get(Setting, 1)
    return dict(row.data) if row else {}


@router.get("/settings/public", response_model=SettingsPublic, summary="화면에 필요한 운영 설정")
def settings_public(session: Session = Depends(get_session)):
    d = settings_data(session)
    return SettingsPublic(limit_member=d.get("limit_member", 20), limit_guest=d.get("limit_guest", 3),
                          max_mb=d.get("max_mb", 10), formats=d.get("formats", ["jpg", "jpeg", "png"]),
                          report_hide=d.get("report_hide", 5), default_region=d.get("default_region", "jeju"))
