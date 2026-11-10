"""DB 행 → API 모양 바꾸기 (편성훈). 여러 라우터가 같이 써요."""
from __future__ import annotations

from sqlmodel import Session

from backend.core import redis_store
from backend.core.timefmt import ago, as_kst
from backend.models import Board, Comment, News, Observation, Post, Species, User, species_dict
from backend.schemas.common import (BoardOut, CommentOut, NewsOut, ObservationOut, PostOut, SpeciesOut,
                                    UserPublic)


def file_url(path: str) -> str:
    return f"/files/{path}" if path else ""


def user_public(u: User | None) -> UserPublic | None:
    return UserPublic(id=u.id, nickname=u.nickname, character=u.character, aquarium_public=u.aquarium_public) if u else None


def species_out(s: Species) -> SpeciesOut:
    return SpeciesOut(**species_dict(s))


def board_out(b: Board) -> BoardOut:
    return BoardOut(**b.model_dump())


def post_out(p: Post, session: Session) -> PostOut:
    return PostOut(id=p.id, board=p.board_id, user=p.user_id, author=user_public(session.get(User, p.user_id)),
                   title=p.title, body=p.body, species=p.species_id, place=p.place, place_level=p.place_level,
                   extra={k: v for k, v in (p.extra or {}).items() if not k.startswith('_')},  # '_'로 시작하는 건 내부용 표시
                   photo_url=file_url(p.photo_path), likes=p.likes, comments=p.comments,
                   report_count=p.report_count, pinned=p.pinned, hidden=p.hidden, created=ago(p.created_at),
                   created_at=as_kst(p.created_at).isoformat(timespec="minutes"))


def comment_out(c: Comment, session: Session) -> CommentOut:
    return CommentOut(id=c.id, post=c.post_id, user=c.user_id, author=user_public(session.get(User, c.user_id)),
                      body=c.body, created=ago(c.created_at))


def news_out(n: News) -> NewsOut:
    try:
        v = redis_store.views("news", n.id)
    except Exception:
        v = 0
    return NewsOut(id=n.id, title=n.title, summary=n.summary, source=n.source, url=n.url, date=n.date, ai=n.ai,
                   public=n.public, views=v)


def obs_out(o: Observation) -> ObservationOut:
    return ObservationOut(id=o.id, user=o.user_id, species=o.species_id, date=o.date, place=o.place, memo=o.memo,
                          post_id=o.post_id, photo_url=file_url(o.photo_path))
