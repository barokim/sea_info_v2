"""권리 표시를 개별 확인한 텍스트 기사만 담당 로컬 미리보기 DB에 등록한다.

공동 DB를 실수로 변경하지 않도록 대상 경로를 고정한다. 자동 수집기가 아니다.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlmodel import Session, select

from backend.models import News


PREVIEW_DB = ROOT / "data" / "preview_local" / "sea_info_preview.db"

# 각 원문에서 텍스트에 한하여 공공누리 제1유형이라고 명시한 것을 2026-11-10 확인.
# 사진·이미지·영상·첨부파일은 수집하거나 저장하지 않는다.
REVIEWED = (
    {
        "id": "n_ko_148965977",
        "title": "한국의 갯벌, 세계유산 확대 등재 권고",
        "summary": "국제자연보전연맹은 한국의 갯벌 세계유산 범위를 여수·고흥·무안·서산 갯벌까지 확대할 것을 권고했습니다. 2026년 6월 발표 당시 최종 결정은 세계유산위원회에 예정돼 있었습니다. 원문의 텍스트는 공공누리 제1유형입니다.",
        "source": "국가유산청·해양수산부 / 정책브리핑",
        "url": "https://www.korea.kr/news/policyNewsView.do?newsId=148965977",
        "date": "2026-06-05",
    },
    {
        "id": "n_ko_156782514",
        "title": "고수온 피해 양식 어가에 1차 재난 지원금",
        "summary": "해양수산부는 2026년 여름 고수온 피해를 입은 양식 어가 338곳에 1차 재난 지원금 137억 원을 지원한다고 발표했습니다. 원문의 텍스트는 공공누리 제1유형입니다.",
        "source": "해양수산부 / 정책브리핑",
        "url": "https://www.korea.kr/briefing/pressReleaseView.do?newsId=156782514",
        "date": "2026-09-20",
    },
)


def main() -> None:
    if not PREVIEW_DB.is_file():
        raise SystemExit(f"별도 미리보기 DB가 없습니다: {PREVIEW_DB}")
    engine = create_engine(f"sqlite:///{PREVIEW_DB.as_posix()}")
    with Session(engine) as session:
        existing = set(session.exec(select(News.id)).all())
        added = 0
        for item in REVIEWED:
            if item["id"] in existing:
                continue
            session.add(News(**item, body=item["summary"], ai=False, public=True))
            added += 1
        session.commit()
    print(f"권리 확인 기사 {added}건 등록, 대상: 별도 로컬 미리보기 DB")


if __name__ == "__main__":
    main()
