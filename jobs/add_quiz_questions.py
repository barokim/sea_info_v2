"""[이정민 신규] 검토한 바다 퀴즈 4문제를 지정한 DB에 추가한다.

기본 실행은 문제만 확인한다. 실제 저장에는 --db와 --apply가 모두 필요하다.
예: python jobs/add_quiz_questions.py --db C:/path/to/test.db --apply
공동 DB에 실행하기 전 팀 데이터 담당자의 확인을 받는다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlmodel import Session, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.models import QuizQuestion
from backend.schemas.games import QuizIn


QUESTIONS = [
    {
        "q": "고래는 물속에서 계속 숨을 쉴 수 있을까요?",
        "options": ["네, 아가미로 숨 쉬어요", "아니요, 물 위로 올라와 숨 쉬어요", "산호에서 산소를 얻어요", "먹이에서 산소를 얻어요"],
        "answer": 1,
        "explain": "고래는 포유류라 공기를 마셔요. 물 위로 올라와 머리 위 숨구멍으로 숨을 쉬어요.",
        "source": "https://www.nifs.go.kr/board/actionBoard0018PopupPrevew.do?BBS_ID=20230109171017188YAW",
    },
    {
        "q": "해마 새끼를 배의 육아낭에서 품는 쪽은 누구일까요?",
        "options": ["수컷 해마", "암컷 해마", "다른 물고기", "산호"],
        "answer": 0,
        "explain": "해마는 수컷의 배에 있는 육아낭에서 새끼를 품어요.",
        "source": "https://www.nifs.go.kr/board/actionBoard0013View.do?BBS_ID=20211228012618791XBJ&MENU_ID=M0000116",
    },
    {
        "q": "산호초의 단단한 뼈대를 만드는 것은 무엇일까요?",
        "options": ["산호 폴립", "바닷물의 거품", "모래알", "고래의 뼈"],
        "answer": 0,
        "explain": "작은 산호 동물인 폴립이 탄산칼슘 뼈대를 만들고, 이것이 쌓여 산호초가 돼요.",
        "source": "https://oceanservice.noaa.gov/facts/coralmadeof.html",
    },
    {
        "q": "바닷물의 밀물과 썰물에 가장 크게 관련된 힘은 무엇일까요?",
        "options": ["달과 태양의 중력", "배가 지나가는 힘", "물고기가 헤엄치는 힘", "바닷물의 색"],
        "answer": 0,
        "explain": "달과 태양의 중력이 바닷물의 오르내림에 영향을 줘요. 지역 지형도 밀물·썰물 시각을 바꿀 수 있어요.",
        "source": "https://oceanservice.noaa.gov/facts/moon-tide.html",
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description="바다 퀴즈 4문제 확인·추가")
    parser.add_argument("--db", type=Path, help="대상 SQLite 파일의 절대 경로")
    parser.add_argument("--apply", action="store_true", help="지정한 DB에 새 문제를 저장")
    args = parser.parse_args()
    validated = [QuizIn(**{k: row[k] for k in ("q", "options", "answer", "explain")}) for row in QUESTIONS]
    for number, row in enumerate(validated, 1):
        print(f"{number}. {row.q} / 정답: {row.options[row.answer]}")
        print(f"   근거: {QUESTIONS[number - 1]['source']}")
    if not args.apply:
        print("검토 모드: DB를 변경하지 않았습니다.")
        return 0
    if args.db is None or not args.db.is_absolute() or not args.db.is_file():
        parser.error("저장에는 존재하는 SQLite 파일의 절대 경로를 --db로 지정해야 합니다.")

    engine = create_engine("sqlite:///" + args.db.as_posix())
    try:
        if not inspect(engine).has_table("quizquestion"):
            parser.error("대상 DB에 quizquestion 테이블이 없습니다.")
        with Session(engine) as session:
            existing = set(session.exec(select(QuizQuestion.q)).all())
            added = 0
            for row in validated:
                if row.q in existing:
                    continue
                session.add(QuizQuestion(**row.model_dump()))
                existing.add(row.q)
                added += 1
            session.commit()
            print(f"새 문제 {added}개 저장 (이미 있는 문제는 제외).")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
