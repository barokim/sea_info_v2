"""생물 알아보기 API (편성훈 담당): 사진 분석 · 하루 횟수 · 수족관에 담기(+공유) · 로그인 전 임시 보관."""
from __future__ import annotations

import copy
import pathlib

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlmodel import Session, select

from backend.config import get_settings
from backend.core import gemini, redis_store
from backend.core.security import optional_user, require_user, viewer_key
from backend.db import get_session, new_id
from backend.models import Board, Observation, Post, Species, User, species_dict
from backend.routers.aquarium import aquarium_cards
from backend.routers.core import settings_data
from backend.schemas.common import (AnalysisResult, DraftIn, DraftOut, IdentifyOut, SaveIn, SaveOut, UsageOut)

router = APIRouter(tags=["생물 알아보기"])
EXAMPLES = {"소라게": "sp_hermit", "불가사리": "sp_star", "해파리": "sp_moon"}


def _limit(user: User | None, session: Session) -> int:
    d = settings_data(session)
    return int(d.get("limit_member", 20) if user else d.get("limit_guest", 3))


def _usage(request: Request, user: User | None, session: Session) -> UsageOut:
    limit = _limit(user, session)
    used = redis_store.usage_get(viewer_key(request, user))
    return UsageOut(left=max(limit - used, 0), limit=limit, used=used)


@router.get("/usage", response_model=UsageOut, summary="오늘 남은 알아보기 횟수")
def usage(request: Request, user: User | None = Depends(optional_user), session: Session = Depends(get_session)):
    return _usage(request, user, session)


def _from_answer(a: dict, session: Session, photo_id: str) -> AnalysisResult:
    known = session.exec(select(Species).where(Species.name == a["name"])).first()
    if known:
        d = species_dict(known)
        d["confidence"] = a["confidence"]
    else:
        d = {"id": gemini.new_species_id(a["name"]), "name": a["name"], "emoji": a.get("emoji") or "🌊", "tone": "aqua",
             "confidence": a["confidence"], "safety": a["safety"], "protected": a["protected"], "summary": a["summary"],
             "info": a["info"], "candidates": a.get("candidates", [])[:3]}
    return AnalysisResult(**d, photo_id=photo_id, source="gemini")


@router.post("/identify", response_model=IdentifyOut, summary="사진으로 생물 알아보기")
async def identify(request: Request, file: UploadFile | None = File(default=None), example: str | None = Form(default=None),
                   user: User | None = Depends(optional_user), session: Session = Depends(get_session)):
    s = get_settings()
    use = _usage(request, user, session)
    if example or not file:  # 예시 체험은 횟수를 쓰지 않아요
        sp = session.get(Species, EXAMPLES.get(example or "", "sp_hermit"))
        return IdentifyOut(result=AnalysisResult(**species_dict(sp), photo_id="", source="example"), left=use.left, limit=use.limit)
    if use.left <= 0:
        raise HTTPException(429, "오늘은 다 썼어요. 내일 다시 만나요!" + ("" if user else " 로그인하면 하루 20번 할 수 있어요."))
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    formats = settings_data(session).get("formats", ["jpg", "jpeg", "png"])
    if ext not in formats:
        raise HTTPException(415, f"{' · '.join(f.upper() for f in formats)} 사진만 올릴 수 있어요.")
    data = await file.read()
    max_mb = int(settings_data(session).get("max_mb") or s.max_upload_mb)  # 관리자 운영 설정 값이 먼저
    if len(data) > max_mb * 1024 * 1024:
        raise HTTPException(413, f"사진이 너무 커요. {max_mb}MB보다 작은 사진을 골라 주세요.")
    photo_id = new_id("ph_", 10)
    try:
        small = gemini.shrink(data)
    except Exception:
        raise HTTPException(415, "사진을 열 수 없어요. 다른 사진을 골라 주세요.")
    up = pathlib.Path(s.upload_dir)
    up.mkdir(parents=True, exist_ok=True)
    (up / f"{photo_id}.jpg").write_bytes(small)
    if s.gemini_on:
        try:
            result = _from_answer(gemini.analyze(data), session, photo_id)
        except gemini.NotSeaCreature:
            raise HTTPException(422, {"code": "not_sea_creature",
                                      "message": "사진에서 바다 생물을 찾지 못했어요. 생물이 크게 보이게 다시 찍어 주세요. 횟수는 줄지 않았어요."})
        except Exception as e:
            print(f"[Gemini 오류] {e}", flush=True)
            raise HTTPException(502, "알아보지 못했어요. 횟수는 줄지 않았고 사진도 그대로예요. 다시 시도해 주세요.")
    else:  # 키가 없으면 예시 결과 (사진은 저장해 둬요)
        sp = session.get(Species, "sp_hermit")
        result = AnalysisResult(**species_dict(sp), photo_id=photo_id, source="example")
    n = redis_store.usage_incr(viewer_key(request, user))  # 결과를 받은 경우에만 횟수 차감
    return IdentifyOut(result=result, left=max(use.limit - n, 0), limit=use.limit)


UNKNOWN_ID = "sp_unknown"


def _species_id_for(r: AnalysisResult, session: Session) -> str:
    """결과 화면에서 이름을 바꾸면(후보 선택 · 직접 입력 · 잘 모르겠어요) 그 이름에 맞는 생물 id를 골라요."""
    if r.name.strip() == "미확인 생물":
        return UNKNOWN_ID
    current = session.get(Species, r.id)
    if current and current.name == r.name:
        return r.id
    by_name = session.exec(select(Species).where(Species.name == r.name)).first()
    if by_name:
        return by_name.id
    return r.id if not current else gemini.new_species_id(r.name)


@router.post("/identify/save", response_model=SaveOut, summary="수족관에 담기 (+ 선택 공유를 한 번에)")
def save(body: SaveIn, user: User = Depends(require_user), session: Session = Depends(get_session)):
    r = body.result
    sid = _species_id_for(r, session)  # 이름을 바꿨거나 '미확인'이면 알맞은 생물 카드로
    before = {c.species.id for c in aquarium_cards(user.id, session)}
    photo = f"{r.photo_id}.jpg" if r.photo_id and (pathlib.Path(get_settings().upload_dir) / f"{r.photo_id}.jpg").exists() else ""
    try:
        if not session.get(Species, sid):  # 처음 보는 생물(또는 미확인)이면 생물 목록에 먼저 넣어요
            if sid == UNKNOWN_ID:
                session.add(Species(id=UNKNOWN_ID, name="미확인 생물", emoji="❔", tone="aqua", confidence="low",
                                    safety_level="caution", safety_reason="만지지 말고 눈으로만 봐 주세요",
                                    summary="아직 이름을 모르는 생물이에요. 나중에 이름을 정할 수 있어요.", source="seed"))
            else:
                session.add(Species(id=sid, name=r.name, emoji=r.emoji, tone=r.tone, confidence=r.confidence,
                                    safety_level=r.safety.level, safety_reason=r.safety.reason, protected=r.protected,
                                    summary=r.summary, habitat=r.info.habitat, food=r.info.food,
                                    fun_fact=r.info.fun_fact, candidates=r.candidates, source="gemini"))
            session.flush()  # 생물을 먼저 저장해야 관찰 기록이 가리킬 수 있어요
        post_id = None
        if body.share:
            board = session.get(Board, "obs")
            if not board or board.status != "운영 중":
                raise HTTPException(409, "지금은 관찰 이야기 게시판에 올릴 수 없어요. 공유를 끄고 담아 주세요.")
            post_id = new_id("p")
            region = body.place.split(" · ")[0] if body.place_level == "region" and body.place else ""
            session.add(Post(id=post_id, board_id="obs", user_id=user.id, title=body.title.strip(),
                             body=body.memo or r.summary, species_id=sid, place=region,
                             place_level="region" if region else "none", photo_path=photo))
        session.add(Observation(id=new_id("ob"), user_id=user.id, species_id=sid, date=body.date.isoformat(),
                                place=body.place, memo=body.memo, post_id=post_id, photo_path=photo))
        session.commit()  # 담기와 공유는 한 번에 저장돼요. 하나라도 실패하면 둘 다 저장되지 않아요.
    except HTTPException:
        session.rollback()
        raise
    except Exception as e:
        session.rollback()
        print(f"[담기 오류] {e}", flush=True)
        raise HTTPException(500, "저장하지 못했어요. 입력한 내용은 그대로 있어요. 다시 시도해 주세요.")
    cards = aquarium_cards(user.id, session)
    card = next(c for c in cards if c.species.id == sid)
    return SaveOut(new_species=sid not in before, total_species=len(cards), count=card.count, post_id=post_id)


@router.post("/drafts", response_model=DraftOut, summary="로그인 전 분석 결과 30분 보관")
def draft_put(body: DraftIn):
    return DraftOut(id=redis_store.temp_put(body.result.model_dump(), ttl=1800))


@router.get("/drafts/{draft_id}", response_model=AnalysisResult, summary="보관한 분석 결과 되살리기")
def draft_get(draft_id: str):
    d = redis_store.temp_get(draft_id)
    if not d:
        raise HTTPException(404, "보관 시간이 지났어요. 다시 알아봐 주세요.")
    return AnalysisResult(**copy.deepcopy(d))
