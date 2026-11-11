"""앱과 같은 DATABASE_URL을 쓰는 국내 해양 소식 수집기.

--preview 또는 기존 PC 예약 작업의 --log-file은 담당 미리보기 DB를 사용한다.
기본 실행은 앱의 .env DATABASE_URL을 그대로 사용한다.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
PREVIEW_DB = ROOT / "data" / "preview_local" / "sea_info_preview.db"
PREVIEW_MODE = "--preview" in sys.argv or "--log-file" in sys.argv
if PREVIEW_MODE:
    os.environ["DATABASE_URL"] = f"sqlite:///{PREVIEW_DB.as_posix()}"

from sqlmodel import Session, select

from backend import korea_news, nifs_news, mabik_news, news_collector, pending_source_monitor, relaxed_news_preview
from backend.db import engine
from backend.models import News, NewsSource
from backend.config import get_settings

SOURCE_NAME = "해양수산부 / 정책브리핑"
NIFS_SOURCE_NAME = "국립수산과학원 / 보도자료"
MABIK_SOURCE_NAME = "국립해양생물자원관 / 보도자료"
SOURCES = {SOURCE_NAME: korea_news.LIST_URL, NIFS_SOURCE_NAME: nifs_news.LIST_URL,
           MABIK_SOURCE_NAME: pending_source_monitor.MABIK_URL}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true", help="담당 미리보기 DB만 사용")
    parser.add_argument("--dry-run", action="store_true", help="DB 저장 없이 실제 기사 판정만 실행")
    parser.add_argument("--refresh-ai", action="store_true", help="기존 AI 요약도 권리 재확인 후 다시 생성")
    parser.add_argument("--refresh-nifs-ai", action="store_true", help="NIFS 요약만 다시 생성")
    parser.add_argument("--max-items", type=int, default=20, choices=range(1, 21), metavar="1-20",
                        help="시험 시 출처당 신규 기사 수 제한 (기본 20)")
    args = parser.parse_args()
    configured_url = get_settings().database_url
    if not configured_url.startswith("sqlite:///"):
        raise SystemExit("이 수집 작업은 현재 SQLite DATABASE_URL만 지원합니다.")
    db_path = Path(configured_url.removeprefix("sqlite:///"))
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    if not db_path.is_file():
        raise SystemExit(f"앱과 같은 DB 파일이 없습니다: {db_path}")
    pending = pending_source_monitor.check_pending_sources()
    for name, state in pending["sources"].items():
        print(f"  {name} 자동 확인: {state['status']} · 발견 {state.get('count', 0)}건")
        if state.get("error"):
            print(f"    오류: {state['error']}")
    if not args.dry_run:
        status_path = (PREVIEW_DB.parent if args.preview or PREVIEW_MODE else ROOT / "logs") / "pending_sources.json"
        temporary = status_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(status_path)
    with Session(engine) as session:
        for source_name, source_url in SOURCES.items():
            source = session.exec(select(NewsSource).where(NewsSource.name == source_name)).first()
            if source is None:
                session.add(NewsSource(name=source_name, url=source_url,
                                       checked="2026-11-10", active=True))
                session.flush()
            else:
                source.url = source_url
                source.active = True
        result = news_collector.collect(session, list(SOURCES), dry_run=args.dry_run,
                                        log=print, max_items=args.max_items)
        relaxed_counts = {relaxed_news_preview.NIFS_NAME: 0, relaxed_news_preview.MABIK_NAME: 0}
        if not args.dry_run and (args.preview or PREVIEW_MODE):
            relaxed_counts = relaxed_news_preview.collect(session, log=print)
        for item in result["items"]:
            print(f"  허용: {item.date} · {item.title} · {item.url}")
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
            if get_settings().gemini_on:
                from backend.korea_ai import summarize_licensed

                query = select(News).where(News.source == SOURCE_NAME, News.public == True)
                if not args.refresh_ai:
                    query = query.where(News.ai == False)
                pending = session.exec(query).all()
                nifs_query = select(News).where(News.source == NIFS_SOURCE_NAME, News.public == True)
                if not (args.refresh_ai or args.refresh_nifs_ai):
                    nifs_query = nifs_query.where(News.ai == False)
                pending += session.exec(nifs_query).all()
                mabik_query = select(News).where(News.source == MABIK_SOURCE_NAME, News.public == True)
                if not args.refresh_ai:
                    mabik_query = mabik_query.where(News.ai == False)
                pending += session.exec(mabik_query).all()
                for article in pending:
                    try:
                        # 기존 기사도 요약 전에 현재 페이지의 개별 텍스트 이용 조건을 다시 확인한다.
                        if article.source == SOURCE_NAME:
                            licensed_body = korea_news.licensed_text(article.url)
                        elif article.source == NIFS_SOURCE_NAME:
                            licensed_body = nifs_news.licensed_text(article.url, strict_license_check=True)
                        else:
                            licensed_body = mabik_news.licensed_text(article.url, strict_license_check=True)
                        summary = summarize_licensed(licensed_body)
                    except Exception as exc:
                        print(f"  · AI 요약 보류: {article.title} — {type(exc).__name__}")
                        continue
                    article.body = licensed_body
                    article.summary = summary
                    article.ai = True
                    session.add(article)
                    session.commit()
                    print(f"  ✓ AI 요약 반영: {article.title}")
    print(f"국내 출처 확인 완료: DB {db_path} · 공개 후보 {result['ok']}건, 비공개 검토용 {sum(relaxed_counts.values())}건, 출처 오류 {result['fail']}건")
    return 0 if result["fail"] == 0 else 1


if __name__ == "__main__":
    if "--log-file" in sys.argv:
        sys.argv.remove("--log-file")
        log_path = PREVIEW_DB.parent / "collect_korea.log"
        with log_path.open("a", encoding="utf-8") as log_file:
            with contextlib.redirect_stdout(log_file), contextlib.redirect_stderr(log_file):
                print(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] 예약 수집 시작", flush=True)
                try:
                    code = main()
                except Exception:
                    traceback.print_exc()
                    code = 2
                print(f"예약 수집 종료: {code}", flush=True)
        raise SystemExit(code)
    raise SystemExit(main())
