"""바다 놀이터 · 퀴즈 관리 API 모양 (pydantic, 이정민 담당).

랭킹 한 줄은 시안 때 예시 데이터와 같은 [닉네임, 점수, 날짜] 모양이에요.
화면은 `for nick, score, when in rows` 로 그대로 써요.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

GAMES = ("quiz", "puzzle")
GAME_NAMES = {"quiz": "퀴즈", "puzzle": "퍼즐"}

RankRow = tuple[str, int, str]  # [닉네임, 점수, 날짜 '11. 02. 09:00']


def check_game(game: str) -> str:
    if game not in GAMES:
        raise ValueError("없는 게임이에요. 퀴즈(quiz)나 퍼즐(puzzle) 중에서 골라 주세요.")
    return game


class QuizOut(BaseModel):
    """퀴즈 한 문제. 어린이 퀴즈라 정답 · 해설을 같이 보내고 화면에서 바로 맞춰 봐요."""
    id: int
    q: str
    options: list[str]
    answer: int
    explain: str = ""
    active: bool = True


class ScoreIn(BaseModel):
    game: str = Field(description="quiz | puzzle")
    score: int

    @field_validator("game")
    @classmethod
    def _game(cls, v: str) -> str:
        return check_game(v)

    @model_validator(mode="after")
    def _range(self):
        if self.game == "quiz" and not (0 <= self.score <= 100 and self.score % 20 == 0):
            raise ValueError("퀴즈 점수가 맞지 않아요. 0점에서 100점까지 20점 단위여야 해요.")
        if self.game == "puzzle" and not (10 <= self.score <= 100):
            raise ValueError("퍼즐 점수가 맞지 않아요. 10점에서 100점 사이여야 해요.")
        return self


class ScoreOut(BaseModel):
    rank: int = Field(description="Top 5 안이면 순위(1~5), 밖이면 0")
    top: list[RankRow]


class BestOut(BaseModel):
    game: str
    best: Optional[int] = None


# ---------- 관리자: 퀴즈 문제 ----------
def _clean_options(v: list[str]) -> list[str]:
    opts = [str(o).strip() for o in v]
    if any(not o for o in opts):
        raise ValueError("빈 보기가 있어요. 보기를 모두 적거나 빈 칸을 지워 주세요.")
    if not 3 <= len(opts) <= 4:
        raise ValueError("보기는 3개나 4개여야 해요. 보기 개수를 맞춰 주세요.")
    if len(set(opts)) != len(opts):
        raise ValueError("같은 보기가 두 번 있어요. 보기를 서로 다르게 적어 주세요.")
    if any(len(o) > 40 for o in opts):
        raise ValueError("보기가 너무 길어요. 보기는 40자 안으로 적어 주세요.")
    return opts


def _clean_text(v: str, field: str) -> str:
    v = (v or "").strip()
    if field == "q":
        empty, long_, limit = "문제가 비어 있어요. 문제를 적어 주세요.", "문제가 너무 길어요. 80자 안으로 적어 주세요.", 80
    else:
        empty, long_, limit = ("해설이 비어 있어요. 답을 고른 뒤 보여줄 설명을 적어 주세요.",
                               "해설이 너무 길어요. 160자 안으로 적어 주세요.", 160)
    if not v:
        raise ValueError(empty)
    if len(v) > limit:
        raise ValueError(long_)
    return v


class QuizIn(BaseModel):
    q: str
    options: list[str]
    answer: int
    explain: str
    active: bool = True

    @field_validator("q", "explain")
    @classmethod
    def _text(cls, v: str, info) -> str:
        return _clean_text(v, info.field_name)

    @field_validator("options")
    @classmethod
    def _opts(cls, v: list[str]) -> list[str]:
        return _clean_options(v)

    @model_validator(mode="after")
    def _answer(self):
        if not 0 <= self.answer < len(self.options):
            raise ValueError("정답 번호가 보기 범위를 벗어났어요. 정답 보기를 다시 골라 주세요.")
        return self


class QuizPatch(BaseModel):
    """고칠 칸만 보내요. 보내지 않은 칸은 그대로예요."""
    q: Optional[str] = None
    options: Optional[list[str]] = None
    answer: Optional[int] = None
    explain: Optional[str] = None
    active: Optional[bool] = None

    @field_validator("q", "explain")
    @classmethod
    def _text(cls, v, info):
        return None if v is None else _clean_text(v, info.field_name)

    @field_validator("options")
    @classmethod
    def _opts(cls, v):
        return None if v is None else _clean_options(v)
