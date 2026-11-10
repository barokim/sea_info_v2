"""바다 놀이터 API (이정민 담당): 퀴즈 문제 뽑기 · 점수 기록 · Top 5 · 내 최고 점수.

랭킹(Top 5)은 Redis 정렬 집합에 있어요 (동점이면 먼저 달성한 사람이 위).
점수 기록은 SQLite ScoreLog에도 한 줄씩 남겨서 ‘내 최고 점수’를 계산해요.
게임은 화면에서 진행하고, 점수는 회원이 끝까지 했을 때만 보내요. 비회원도 게임은 할 수 있어요.
"""
from __future__ import annotations

import random

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlmodel import Session, select

from backend.core import redis_store
from backend.core.security import require_user
from backend.core.timefmt import now
from backend.db import get_session
from backend.models import QuizQuestion, ScoreLog, User
from backend.schemas.games import BestOut, QuizOut, RankRow, ScoreIn, ScoreOut, check_game

router = APIRouter(tags=["바다 놀이터"])
TOP_N = 5


def quiz_out(q: QuizQuestion) -> QuizOut:
    return QuizOut(id=q.id, q=q.q, options=list(q.options or []), answer=q.answer, explain=q.explain, active=q.active)


def _game(game: str) -> str:
    try:
        return check_game(game)
    except ValueError as e:
        raise HTTPException(404, str(e))


def _top(game: str) -> list[RankRow]:
    try:
        return [tuple(row) for row in redis_store.rank_top(game, TOP_N)]
    except Exception as e:
        print(f"[랭킹 오류] {e}", flush=True)
        raise HTTPException(503, "랭킹을 불러오지 못했어요. 잠시 뒤 새로고침해 주세요.")


@router.get("/games/quiz", response_model=list[QuizOut], summary="퀴즈 문제 n개 (사용 중인 문제에서 무작위)")
def quiz(n: int = 5, shuffle: bool = True, session: Session = Depends(get_session)):
    """어린이 퀴즈라 정답과 해설을 같이 보내고, 화면에서 바로 맞춰 봐요. shuffle=false면 등록 순서대로 (캡처용)."""
    n = max(1, min(n, 20))
    pool = list(session.exec(select(QuizQuestion).where(QuizQuestion.active == True)  # noqa: E712
                             .order_by(QuizQuestion.id)).all())
    picked = random.sample(pool, min(n, len(pool))) if shuffle else pool[:n]
    return [quiz_out(q) for q in picked]


@router.post("/games/scores", response_model=ScoreOut, summary="점수 기록 (회원만 · 끝까지 했을 때)")
def add_score(body: ScoreIn, user: User = Depends(require_user), session: Session = Depends(get_session)):
    try:  # 같은 점수가 두 번 눌려 들어가지 않게 (2초)
        fresh = redis_store.gap_ok(f"score:{user.id}:{body.game}", 2)
    except Exception:
        fresh = True  # Redis가 안 되면 아래 랭킹 저장에서 안내해요
    if not fresh:
        raise HTTPException(429, "점수를 방금 저장했어요. 한 판을 끝까지 한 뒤 다시 저장해 주세요.")
    try:
        session.add(ScoreLog(game=body.game, user_id=user.id, nickname=user.nickname, score=body.score))
        session.flush()
        rank = redis_store.rank_add(body.game, user.nickname, body.score, f"{now():%m. %d. %H:%M}")
        session.commit()  # 랭킹(Redis)에 들어간 뒤에만 기록을 저장해요
    except Exception as e:
        session.rollback()
        print(f"[점수 저장 오류] {e}", flush=True)
        raise HTTPException(503, "점수를 저장하지 못했어요. 잠시 뒤 한 번 더 해 주세요.")
    return ScoreOut(rank=rank if rank <= TOP_N else 0, top=_top(body.game))


@router.get("/games/top", response_model=list[RankRow], summary="게임별 Top 5 [닉네임, 점수, 날짜]")
def top(game: str):
    return _top(_game(game))


@router.get("/games/best", response_model=BestOut, summary="내 최고 점수 (기록이 없으면 null)")
def best(game: str, user: User = Depends(require_user), session: Session = Depends(get_session)):
    """ScoreLog의 내 기록 중 가장 높은 점수. 처음 넣은 예시 랭킹(닉네임으로만 남은 Top 5)에 내 닉네임이 있으면 그 점수도 같이 봐요."""
    g = _game(game)
    scores = [session.exec(select(func.max(ScoreLog.score)).where(ScoreLog.game == g, ScoreLog.user_id == user.id)).one()]
    try:
        scores += [s for nick, s, _ in redis_store.rank_top(g, TOP_N) if nick == user.nickname]
    except Exception:
        pass
    scores = [s for s in scores if s is not None]
    return BestOut(game=g, best=max(scores) if scores else None)
