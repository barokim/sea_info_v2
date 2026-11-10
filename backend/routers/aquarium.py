"""나의 수족관 API (김바로 담당). 조회 API(/me/observations · /me/aquarium · aquarium_cards)는 편성훈이 먼저 만들었어요.

김바로가 이어서 만든 것:
  - 기록 고치기 · 생물 카드 옮기기 · 지우기 · 공유하기 · 공유 취소 (U-06 · U-07)
  - 수족관 공개 설정, 다른 사람 수족관 · 공개 수족관 목록 (U-11)

미확인 생물: 이름을 모르는 기록은 진짜 생물 행 'sp_unknown'(❔ 미확인 생물)에 묶어요.
처음 필요할 때 이 파일이 만들어요(unknown_species). 이름을 정하면 PATCH species_id 로 그 생물 카드로 옮겨요.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from backend.core.convert import obs_out, species_out
from backend.core.security import require_user
from backend.core.timefmt import as_kst
from backend.db import get_session, new_id
from backend.models import Board, Observation, Post, Species, User
from backend.schemas.aquarium import (AquariumOwner, ObservationPatch, PublicAquariumItem, PublicAquariumOut, PublicIn,
                                      PublicOut, SharedCard, SharedRecord, ShareIn, ShareOut)
from backend.schemas.common import AquariumCard, ObservationOut, OkOut

router = APIRouter(tags=["나의 수족관"])

UNKNOWN_ID = "sp_unknown"


def unknown_species(session: Session) -> Species:
    """‘미확인 생물’ 행을 돌려줘요. 없으면 지금 만들어요 (다른 변경보다 먼저 불러요)."""
    sp = session.get(Species, UNKNOWN_ID)
    if sp:
        return sp
    session.add(Species(id=UNKNOWN_ID, name="미확인 생물", emoji="❔", tone="navy", confidence="low",
                        safety_level="caution", safety_reason="어떤 생물인지 모를 때는 만지지 말고 눈으로만 봐요.",
                        summary="아직 이름을 정하지 않은 생물이에요.", candidates=[], source="system"))
    try:
        session.commit()
    except IntegrityError:  # 동시에 다른 요청이 먼저 만들었어요
        session.rollback()
    return session.get(Species, UNKNOWN_ID)


def aquarium_cards(user_id: str, session: Session, shared_only: bool = False) -> list[AquariumCard]:
    obs = session.exec(select(Observation).where(Observation.user_id == user_id)).all()
    groups: dict[str, list[Observation]] = {}
    for o in obs:
        if shared_only:
            p = session.get(Post, o.post_id) if o.post_id else None
            if not p or p.hidden or p.deleted:
                continue
        groups.setdefault(o.species_id, []).append(o)
    cards = []
    for sid, recs in groups.items():
        sp = session.get(Species, sid)
        if not sp:
            continue
        recs.sort(key=lambda r: r.date, reverse=True)
        shared = any(r.post_id and (p := session.get(Post, r.post_id)) and not p.hidden and not p.deleted for r in recs)
        cards.append(AquariumCard(species=species_out(sp), records=[obs_out(r) for r in recs], count=len(recs),
                                  last=recs[0].date, shared=bool(shared)))
    return sorted(cards, key=lambda c: c.last, reverse=True)


@router.get("/me/observations", response_model=list[ObservationOut], summary="내 관찰 기록")
def my_observations(user: User = Depends(require_user), session: Session = Depends(get_session)):
    rows = session.exec(select(Observation).where(Observation.user_id == user.id)).all()
    return [obs_out(o) for o in sorted(rows, key=lambda o: o.date, reverse=True)]


@router.get("/me/aquarium", response_model=list[AquariumCard], summary="나의 수족관 (생물별로 묶음)")
def my_aquarium(user: User = Depends(require_user), session: Session = Depends(get_session)):
    unknown_species(session)  # 미확인 기록을 담을 수 있게 미리 준비해요 (한 번만 만들어져요)
    return aquarium_cards(user.id, session)


# ---------- 내 기록 고치기 · 지우기 · 공유 ----------
def _mine(obs_id: str, user: User, session: Session) -> Observation:
    o = session.get(Observation, obs_id)
    if not o or o.user_id != user.id:
        raise HTTPException(404, "관찰 기록을 찾지 못했어요. 이미 지웠을 수 있어요. 수족관을 새로 열어 주세요.")
    return o


def _live_post(o: Observation, session: Session) -> Post | None:
    p = session.get(Post, o.post_id) if o.post_id else None
    return p if p and not p.hidden and not p.deleted else None


def _commit(session: Session, fail: str) -> None:
    try:
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"[수족관 저장 오류] {e}", flush=True)
        raise HTTPException(500, fail)


@router.patch("/me/observations/{obs_id}", response_model=ObservationOut, summary="관찰 기록 고치기 · 다른 생물 카드로 옮기기")
def update_observation(obs_id: str, body: ObservationPatch, user: User = Depends(require_user),
                       session: Session = Depends(get_session)):
    if body.species_id == UNKNOWN_ID:
        unknown_species(session)
    o = _mine(obs_id, user, session)
    if body.species_id is not None and body.species_id != o.species_id:
        if not session.get(Species, body.species_id):
            raise HTTPException(404, "고른 생물을 찾지 못했어요. 생물 이름을 다시 골라 주세요.")
        post = session.get(Post, o.post_id) if o.post_id else None
        if body.species_id == UNKNOWN_ID and _live_post(o, session):
            raise HTTPException(409, "공유 중인 기록은 미확인 생물로 옮길 수 없어요. 먼저 공유를 취소해 주세요.")
        o.species_id = body.species_id
        if post:  # 공유한 글도 같은 생물로 맞춰요
            post.species_id = body.species_id
            session.add(post)
    if body.date is not None:
        o.date = body.date.isoformat()
    if body.place is not None:
        o.place = body.place
    if body.memo is not None:
        o.memo = body.memo
    session.add(o)
    _commit(session, "저장하지 못했어요. 입력한 내용은 그대로 있어요. 다시 시도해 주세요.")
    session.refresh(o)
    return obs_out(o)


@router.delete("/me/observations/{obs_id}", response_model=OkOut, summary="관찰 기록 지우기 (공유한 글도 함께 내려요)")
def delete_observation(obs_id: str, user: User = Depends(require_user), session: Session = Depends(get_session)):
    o = _mine(obs_id, user, session)
    post = session.get(Post, o.post_id) if o.post_id else None
    had_post = bool(post and not post.deleted and not post.hidden)
    if post:  # 기록을 지우면 그 기록으로 올린 글도 지운 글로 바꿔요 (다른 사람에게 더는 안 보여요)
        post.deleted = True
        session.add(post)
    session.delete(o)
    _commit(session, "지우지 못했어요. 잠시 뒤 다시 시도해 주세요.")
    return OkOut(message="관찰 기록을 지웠어요." + (" 관찰 이야기에 올린 글도 함께 내렸어요." if had_post else ""))


@router.post("/me/observations/{obs_id}/share", response_model=ShareOut, summary="관찰 기록을 ‘관찰 이야기’에 공유하기")
def share_observation(obs_id: str, body: ShareIn, user: User = Depends(require_user),
                      session: Session = Depends(get_session)):
    o = _mine(obs_id, user, session)
    if o.species_id == UNKNOWN_ID:
        raise HTTPException(409, "이름을 정하면 공유할 수 있어요. 먼저 생물 이름을 골라 주세요.")
    if _live_post(o, session):
        raise HTTPException(409, "이미 공유 중인 기록이에요. 관찰 이야기에서 글을 확인해 주세요.")
    board = session.get(Board, "obs")
    if not board or board.status != "운영 중":
        raise HTTPException(409, "지금은 관찰 이야기 게시판에 올릴 수 없어요. 게시판이 다시 열리면 공유해 주세요.")
    sp = session.get(Species, o.species_id)
    region = o.place.split(" · ")[0].strip() if body.place_level == "region" and o.place else ""
    post_id = new_id("p")
    session.add(Post(id=post_id, board_id="obs", user_id=user.id, title=body.title,
                     body=o.memo or (sp.summary if sp else ""), species_id=o.species_id, place=region,
                     place_level="region" if region else "none", photo_path=o.photo_path))
    o.post_id = post_id
    session.add(o)
    _commit(session, "공유하지 못했어요. 기록은 그대로 있어요. 다시 시도해 주세요.")  # 글과 기록 연결을 한 번에 저장
    session.refresh(o)
    return ShareOut(post_id=post_id, observation=obs_out(o))


@router.post("/me/observations/{obs_id}/unshare", response_model=ObservationOut, summary="공유 취소 (기록은 ‘나만 보기’로 남아요)")
def unshare_observation(obs_id: str, user: User = Depends(require_user), session: Session = Depends(get_session)):
    o = _mine(obs_id, user, session)
    if not o.post_id:
        raise HTTPException(409, "공유 중인 기록이 아니에요. 화면을 새로 고쳐 주세요.")
    post = session.get(Post, o.post_id)
    if post:  # 글과 사진은 다른 사람에게 바로 안 보여요. 다시 공유하면 새 글로 올라가요.
        post.hidden = True
        session.add(post)
    o.post_id = None
    session.add(o)
    _commit(session, "공유를 취소하지 못했어요. 잠시 뒤 다시 시도해 주세요.")
    session.refresh(o)
    return obs_out(o)


@router.put("/me/aquarium/public", response_model=PublicOut, summary="내 수족관 공개 · 비공개")
def set_public(body: PublicIn, user: User = Depends(require_user), session: Session = Depends(get_session)):
    user.aquarium_public = body.public
    session.add(user)
    _commit(session, "공개 설정을 바꾸지 못했어요. 잠시 뒤 다시 시도해 주세요.")
    return PublicOut(public=body.public, message="이제 다른 사람도 내 수족관을 볼 수 있어요" if body.public
                     else "수족관을 나만 보도록 바꿨어요")


# ---------- 다른 사람 수족관 (U-11) ----------
def _when(d: str) -> str:
    try:
        y, m, dd = d.split("-")
        return f"{int(m)}월 {int(dd)}일"
    except ValueError:
        return d


def _owner(u: User) -> AquariumOwner:
    return AquariumOwner(id=u.id, nickname=u.nickname, character=u.character, aquarium_public=u.aquarium_public,
                         grade=u.grade)


def shared_cards(user_id: str, session: Session) -> list[SharedCard]:
    """그 회원이 지금 ‘공유 중’인 기록(관찰 이야기에 보이는 글)만 생물별로 묶어요."""
    posts = session.exec(select(Post).where(Post.user_id == user_id, Post.board_id == "obs",
                                            Post.hidden == False, Post.deleted == False)).all()  # noqa: E712
    linked = {o.post_id: o for o in session.exec(select(Observation).where(Observation.user_id == user_id)).all()
              if o.post_id}
    groups: dict[str, list[SharedRecord]] = {}
    species: dict[str, Species] = {}
    for p in posts:
        sp = session.get(Species, p.species_id) if p.species_id else None
        if not sp or sp.id == UNKNOWN_ID:
            continue
        o = linked.get(p.id)
        d = o.date if o else as_kst(p.created_at).date().isoformat()
        species[sp.id] = sp
        groups.setdefault(sp.id, []).append(SharedRecord(
            title=p.title, memo=p.body, date=d, when=_when(d), place=p.place if p.place_level == "region" else "",
            likes=p.likes, post_id=p.id))
    cards = []
    for sid, recs in groups.items():
        recs.sort(key=lambda r: r.date, reverse=True)
        cards.append(SharedCard(species=species_out(species[sid]), records=recs, count=len(recs), last=recs[0].when))
    cards.sort(key=lambda c: c.records[0].date, reverse=True)
    return cards


@router.get("/users/{user_id}/aquarium", response_model=PublicAquariumOut, summary="다른 사람 수족관 (공유 중인 기록만)")
def user_aquarium(user_id: str, session: Session = Depends(get_session)):
    u = session.get(User, user_id)
    if not u:
        raise HTTPException(404, "이 수족관을 찾지 못했어요. 주소를 한 번 더 확인해 주세요.")
    if not u.aquarium_public:
        raise HTTPException(403, {"code": "private",
                                  "message": "비공개 수족관이에요. 이 회원이 수족관을 공개하면 구경할 수 있어요."})
    cards = shared_cards(u.id, session)
    return PublicAquariumOut(owner=_owner(u), cards=cards, species_count=len(cards),
                             record_count=sum(c.count for c in cards))


@router.get("/aquariums/public", response_model=list[PublicAquariumItem], summary="구경할 수 있는 수족관 목록")
def public_aquariums(session: Session = Depends(get_session)):
    users = session.exec(select(User).where(User.aquarium_public == True, User.role != "admin")).all()  # noqa: E712
    out = []
    for u in users:
        cards = shared_cards(u.id, session)
        out.append(PublicAquariumItem(owner=_owner(u), species_count=len(cards), record_count=sum(c.count for c in cards)))
    return sorted(out, key=lambda x: (-x.species_count, x.owner.nickname))
