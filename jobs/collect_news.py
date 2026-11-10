"""바다 소식 자동 수집 (이정민 담당) — Streamlit · API 서버 없이 혼자 도는 스크립트예요.

하는 일 (실제 수집 코드는 backend/news_collector.py에 있고, 관리자 화면의 [다시 수집]도 같은 코드를 써요)
    1. 사용 중이고 이용 조건 확인일이 있는 출처(NewsSource)를 골라요
    2. 출처마다 RSS · Atom을 읽고, 이미 저장한 원문 주소는 건너뛰어요
    3. 새 소식마다 AI가 두세 문장으로 요약해요          backend.core.gemini.summarize
    4. 요약한 소식을 SQLite에 저장해요 (바로 공개)       News(public=True, ai=True)
    5. 이번 수집 기록(성공 · 실패 · 실패 이유)을 남겨요  NewsRun
    한 출처가 실패해도 나머지 출처는 계속 모아요. 실패한 출처는 A-05 ‘수집 기록’에 이유와 [다시 수집]으로 보여요.
    저장은 한 번에 해요 (중간에 문제가 생기면 이번 수집분은 모두 되돌려요).

환경변수 (API 서버와 같은 .env를 읽어요)
    DATABASE_URL   예) sqlite:///./data/sea_info.db   ← 서버와 같은 DB를 가리켜야 화면에 보여요
    GEMINI_API_KEY 없으면 요약 대신 앞부분을 잘라 써요

예약 실행 (매일 한국 시간 오전 6시)
    서버의 crontab에 한 줄을 넣어요.  (crontab -e)

        0 6 * * * cd /srv/sea_info && .venv/bin/python jobs/collect_news.py >> logs/collect_news.log 2>&1

    ※ cron은 ‘서버 시간대’ 기준으로 돌아요. 먼저 서버 시간대가 한국(Asia/Seoul)인지 확인해요.
        timedatectl | grep "Time zone"             # Asia/Seoul (KST, +0900) 이어야 해요
        sudo timedatectl set-timezone Asia/Seoul   # 아니라면 바꾸거나,
      서버 시간대를 바꿀 수 없으면 crontab 맨 위에  CRON_TZ=Asia/Seoul  을 적어요 (cronie 기준).
      UTC 서버에 그대로 두려면 시간을 21시로 적어요:  0 21 * * *  (전날 21:00 UTC = 오늘 06:00 KST)
    이 스크립트도 시작할 때 시간대를 확인하고, 한국 시간이 아니면 경고를 남겨요.
    배포 사이트에 cron이 없으면 그 사이트의 ‘예약 작업(Scheduled job)’ 기능에 같은 명령을 넣어요.

미리 돌려 보기 (아무것도 저장하지 않아요)
    cd /home/user/sea_info && python jobs/collect_news.py --dry-run
    python jobs/collect_news.py --dry-run --sample   # 예시 기사 한 건으로 요약까지 확인
    python jobs/collect_news.py --dry-run --fetch    # 실제로 출처를 읽고 요약까지 (저장은 안 해요)

끝 코드: 0 = 모두 성공(또는 미리 돌려 보기) · 1 = 실패한 출처가 있음 · 2 = 저장하지 못함
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # jobs/ 안에서 실행해도 backend/를 찾을 수 있게

from sqlmodel import Session, select  # noqa: E402

from backend import news_collector  # noqa: E402
from backend.core.gemini import summarize  # noqa: E402  (관리자 화면과 같은 요약 함수)
from backend.core.timefmt import now  # noqa: E402
from backend.db import engine, init_db  # noqa: E402
from backend.models import NewsSource  # noqa: E402

SAMPLE = {  # --sample 일 때 쓰는 예시 기사 (실제 기사가 아니에요)
    "title": "예시: 주말 갯벌 체험 전 물때 확인 안내",
    "url": "https://example.com/news/sample",
    "text": "주말 갯벌 체험을 계획한 가족은 물이 빠지는 간조 전후 시간을 먼저 확인해야 해요. "
            "물이 들어오는 시간에는 갯벌에 오래 머물지 말고, 돌아올 길과 시간을 미리 정해 두자는 안내예요. "
            "체험 뒤에는 만난 생물을 제자리에 놓아 주세요.",
}


def log(msg: str) -> None:
    print(f"[{now():%Y-%m-%d %H:%M:%S} KST] {msg}", flush=True)


def check_timezone() -> None:
    """서버 시간대가 한국 시간(+09:00)이 아니면 경고만 남겨요 (수집은 계속해요)."""
    offset = -time.altzone if time.localtime().tm_isdst > 0 else -time.timezone
    if offset != 9 * 3600:
        log(f"주의: 서버 시간대가 UTC{offset / 3600:+.0f}이에요. cron이 한국 시간 오전 6시에 돌도록 "
            "서버 시간대(Asia/Seoul)나 CRON_TZ를 확인해 주세요.")


def dry_run(session: Session, sample: bool) -> int:
    """출처를 읽지도, 저장하지도 않고 무엇을 할지만 보여줘요."""
    sources = list(session.exec(select(NewsSource).order_by(NewsSource.id)).all())
    on = [s for s in sources if s.active]
    log(f"(미리 돌려 보기) 등록된 출처 {len(sources)}곳 · 사용 중 {len(on)}곳")
    for s in sources:
        if not s.active:
            note = "사용 안 함 → 건너뛰어요"
        elif not s.checked:
            note = "이용 조건 확인일이 없어요 → 실패로 기록돼요"
        elif news_collector.is_example(s.url):
            note = "예시 주소(example.com) → 실패로 기록돼요. 실제 RSS 주소로 바꿔 주세요"
        else:
            note = "가져올 예정"
        log(f"  · {s.name} ({s.url}) — {note}")
    if sample:
        log(f"  예시 기사 요약: {SAMPLE['title']} → {summarize(SAMPLE['text'])}")
    log("(미리 돌려 보기) 아무것도 저장하지 않았어요.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="바다 소식 자동 수집 (매일 한국 시간 오전 6시)")
    ap.add_argument("--dry-run", action="store_true", help="저장 없이 흐름만 확인해요 (출처도 읽지 않아요)")
    ap.add_argument("--sample", action="store_true", help="--dry-run과 함께: 예시 기사 한 건으로 요약까지 확인해요")
    ap.add_argument("--fetch", action="store_true", help="--dry-run과 함께: 실제로 출처를 읽고 요약까지 해요 (저장은 안 해요)")
    ap.add_argument("--source", action="append", metavar="이름", help="이 출처만 모아요 (여러 번 쓸 수 있어요)")
    args = ap.parse_args(argv)

    check_timezone()
    init_db()  # 테이블이 없으면 만들어요 (처음 켠 서버와 같은 동작)
    with Session(engine) as session:
        if args.dry_run and not args.fetch:
            return dry_run(session, args.sample)

        log("수집을 시작해요" + (" (미리 돌려 보기: 저장 안 함)" if args.dry_run else ""))
        out = news_collector.collect(session, args.source, dry_run=args.dry_run, summarize=summarize, log=log)
        for n in out["items"]:
            log(f"  {'(저장 안 함) ' if args.dry_run else ''}+ {n.source} · {n.title} → {n.summary}")
        if args.dry_run:
            log(f"(미리 돌려 보기) {json.dumps({k: out[k] for k in ('ok', 'fail', 'failed')}, ensure_ascii=False)}")
            return 0
        try:
            session.commit()  # 새 소식과 수집 기록을 한 번에 저장해요
        except Exception as e:
            session.rollback()
            log(f"저장하지 못했어요. 이번 수집분은 모두 되돌렸어요: {e}")
            return 2
    log(f"끝났어요. 새 소식 {out['ok']}건 · 실패 {out['fail']}곳")
    return 0 if out["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
