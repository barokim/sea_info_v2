"""담당 로컬 DB 전용: 미표시 공식 보도자료를 비공개 검토용으로 저장한다."""
from __future__ import annotations

from sqlmodel import Session, select

from backend import mabik_news, nifs_news, news_collector
from backend.core import gemini
from backend.db import new_id
from backend.models import News

NIFS_NAME = "국립수산과학원 / 보도자료 (검토용)"
MABIK_NAME = "국립해양생물자원관 / 보도자료 (검토용)"


def collect(session: Session, log=print) -> dict[str, int]:
    """최신 목록을 확인한다. 재이용 조건 미확인 글은 public=False를 유지한다."""
    seen = set(session.exec(select(News.url)).all())
    counts = {NIFS_NAME: 0, MABIK_NAME: 0}
    sources = (
        (NIFS_NAME, lambda: nifs_news.list_items(pages=5),
         lambda title: nifs_news.marine_life_related(title),
         lambda url: nifs_news.licensed_text(url, strict_license_check=False)),
        (MABIK_NAME, lambda: [(x.title, x.url, x.date) for x in
                             news_collector.fetch_mabik("https://www.mabik.re.kr/bbs/BBSMSTR_000000000347/list.do")],
         lambda title: news_collector._ocean_related(title),
         lambda url: mabik_news.licensed_text(url, strict_license_check=False)),
    )
    for name, fetch, related, read in sources:
        try:
            candidates = fetch()
        except Exception as exc:
            log(f"  · {name}: 목록 오류 {type(exc).__name__}: {exc}")
            continue
        log(f"  · {name}: 최근 목록 {len(candidates)}건 확인")
        for title, url, date in candidates:
            if counts[name] >= 20:
                break
            if url in seen or not related(title):
                continue
            try:
                body = read(url)
            except Exception as exc:
                log(f"  · {name}: 건너뜀 {title} — {type(exc).__name__}: {exc}")
                continue
            summary = gemini.summarize(body)
            ai = bool(summary and summary != body[:120] and not summary.startswith(body[:120]))
            session.add(News(id=new_id("n"), title=title, summary=summary[:400], body=body,
                             source=name, url=url, date=date, ai=ai, public=False))
            seen.add(url)
            counts[name] += 1
            log(f"  ✓ {name}: 비공개 검토용 저장 {title}")
    return counts
