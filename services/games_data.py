"""바다 놀이터 · 퀴즈 관리 창구 (이정민 담당). FastAPI 서버(backend/routers/games.py · admin_contents.py)를 불러요.

U-12~14 바다 놀이터와 A-05 콘텐츠 관리(퀴즈 문제)가 같이 써요. 홈의 놀이터 칸도 top_scores()를 쓰면 돼요.
    games_data.quiz(5)                      # 사용 중인 문제 5개 (정답 · 해설 포함)
    games_data.submit("quiz", 80)           # 회원 점수 저장 → {"rank": 0~5, "top": [...]}
    games_data.top_scores("puzzle")         # Top 5 [[닉네임, 점수, 날짜], ...]
    games_data.best("quiz")                 # 내 최고 점수 (비회원 · 기록 없음은 None)
실패하면 ApiError를 던져요 → 화면에서 st.error(e.message).
"""
from __future__ import annotations

from services import api, db
from services.api import ApiError

__all__ = ["ApiError", "quiz", "submit", "top_scores", "best", "admin_quiz", "add_quiz", "update_quiz"]


# ---------- 게임 ----------
def quiz(n: int = 5, shuffle: bool = True) -> list[dict]:
    """퀴즈 문제 n개. shuffle=False면 등록 순서대로 (시안 캡처용)."""
    return api.get("/games/quiz", params={"n": n, "shuffle": shuffle})


def submit(game: str, score: int) -> dict:
    """회원이 끝까지 한 판의 점수를 저장해요. {"rank": Top 5 안이면 1~5 · 밖이면 0, "top": [...]}"""
    out = api.post("/games/scores", json={"game": game, "score": score})
    db.clear_cache()
    return out


def top_scores(game: str) -> list[list]:
    """게임별 Top 5. 점수가 같으면 먼저 달성한 사람이 위예요."""
    return db._cached(f"games_top:{game}", lambda: api.get("/games/top", params={"game": game}), ttl=10)


def best(game: str) -> int | None:
    """내 최고 점수. 로그인하지 않았거나 기록이 없으면 None."""
    try:
        return db._cached(f"games_best:{game}", lambda: api.get("/games/best", params={"game": game})["best"], ttl=10)
    except ApiError as e:
        if e.status == 401:
            return None
        raise


# ---------- 관리자: 퀴즈 문제 ----------
def admin_quiz() -> list[dict]:
    """모든 문제 (쉬는 문제 포함, 등록 순서대로)."""
    return api.get("/admin/quiz")


def add_quiz(q: str, options: list[str], answer: int, explain: str, active: bool = True) -> dict:
    out = api.post("/admin/quiz", json={"q": q, "options": options, "answer": answer, "explain": explain,
                                        "active": active})
    db.clear_cache()
    return out


def update_quiz(quiz_id: int, **fields) -> dict:
    """고칠 칸만 넘겨요. 예) update_quiz(3, active=False)"""
    out = api.patch(f"/admin/quiz/{quiz_id}", json=fields)
    db.clear_cache()
    return out
