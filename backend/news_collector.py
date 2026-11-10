"""바다 소식 수집 (이정민 담당). 두 곳이 같은 코드를 써요.

    - 관리자 화면 A-05 ‘수집 기록’의 [다시 수집]  → POST /admin/news/collect
    - 매일 한국 시간 오전 6시 예약 실행          → jobs/collect_news.py

하는 일
    1. 사용 중인 출처(NewsSource)를 골라요. 이용 조건 확인일이 없는 출처는 모으지 않아요.
    2. 출처마다 RSS · Atom 주소를 읽어요 (httpx + xml.etree).
    3. 이미 저장한 원문 주소(url)는 건너뛰어요.
    4. 새 소식마다 AI가 두세 문장으로 요약해요 (backend.core.gemini.summarize).
    5. News(공개 · AI 요약)와 이번 수집 기록(NewsRun) 한 줄을 세션에 넣어요.

한 출처가 실패해도(예시 주소, 연결 실패, 형식 오류 …) 나머지 출처는 계속 모으고, 실패 이유를 기록에 남겨요.
저장(commit)은 부르는 쪽이 한 번에 해요. 그래서 관리 기록(AdminLog)과 같이 묶어서 저장할 수 있어요.

    from sqlmodel import Session
    from backend.db import engine
    from backend import news_collector

    with Session(engine) as s:
        out = news_collector.collect(s)          # 사용 중인 출처 모두
        s.commit()
        print(out["ok"], out["fail"], out["failed"])
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Callable, Iterable, Optional
from urllib.parse import urlparse

import httpx
from sqlmodel import Session, select

from backend.core import gemini
from backend.core.timefmt import KST, now, today
from backend.db import new_id
from backend.models import News, NewsRun, NewsSource
from backend.schemas.news import RunOut

TIMEOUT = 10  # 출처 하나를 기다리는 최대 시간(초)
MAX_BYTES = 5 * 1024 * 1024  # RSS 한 번에 5MB까지만 읽어요
MAX_ITEMS = 10  # 출처 하나에서 한 번에 넣는 새 소식 수
UA = "SeaInfoAgent/1.0 (sea news collector; reads RSS of sources whose terms were checked)"
EXAMPLE_HOSTS = ("example.com", "example.org", "example.net")


class SourceError(Exception):
    """출처 하나를 가져오지 못했어요. reason은 관리자 화면에 그대로 보여요."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class RawItem:
    title: str
    url: str
    text: str
    date: str  # YYYY-MM-DD (한국 시간)


# ---------- 가져오기 ----------
def is_example(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in EXAMPLE_HOSTS)


def fetch_feed(url: str, timeout: float = TIMEOUT) -> list[RawItem]:
    """RSS · Atom 주소 하나를 읽어 소식 목록으로 바꿔요. 실패하면 SourceError(이유)."""
    if is_example(url):
        raise SourceError("예시 주소(example.com)라서 가져오지 않았어요. 수집 출처에서 실제 RSS 주소로 바꿔 주세요.")
    if urlparse(url).scheme not in ("http", "https"):
        raise SourceError("주소가 http:// 또는 https://로 시작하지 않아요. 수집 출처에서 주소를 고쳐 주세요.")
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": UA}) as client:
            with client.stream("GET", url) as r:
                if r.status_code >= 400:
                    raise SourceError(f"출처 서버가 오류로 답했어요 (HTTP {r.status_code}). 주소가 바뀌었는지 확인해 주세요.")
                data = b""
                for chunk in r.iter_bytes():
                    data += chunk
                    if len(data) > MAX_BYTES:
                        raise SourceError("받은 내용이 너무 커요 (5MB 넘음). 소식 목록(RSS) 주소가 맞는지 확인해 주세요.")
    except SourceError:
        raise
    except httpx.TimeoutException:
        raise SourceError(f"응답이 너무 늦어서({TIMEOUT}초) 가져오지 못했어요. 잠시 뒤 다시 수집해 주세요.")
    except httpx.HTTPError as e:
        raise SourceError(f"주소에 연결하지 못했어요. 주소가 맞는지, 사이트가 열려 있는지 확인해 주세요. ({type(e).__name__})")
    return parse_feed(data)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def _child(el: ET.Element, *names: str) -> Optional[ET.Element]:
    for c in el:
        if _local(c.tag) in names:
            return c
    return None


def _text(el: Optional[ET.Element]) -> str:
    return "".join(el.itertext()).strip() if el is not None else ""


def clean_html(s: str) -> str:
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s or "")
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def _date(raw: str) -> str:
    raw = (raw or "").strip()
    if raw:
        for parse in (parsedate_to_datetime, lambda x: datetime.fromisoformat(x.replace("Z", "+00:00"))):
            try:
                dt = parse(raw)
                dt = dt.replace(tzinfo=KST) if dt.tzinfo is None else dt.astimezone(KST)
                return f"{min(dt.date(), today()):%Y-%m-%d}"
            except (TypeError, ValueError, IndexError):
                continue
    return f"{today():%Y-%m-%d}"


def _link(el: ET.Element) -> str:
    best = ""
    for c in el:
        if _local(c.tag) != "link":
            continue
        href = c.get("href")
        if href:  # Atom
            if c.get("rel", "alternate") == "alternate":
                return href.strip()
            best = best or href.strip()
        elif (c.text or "").strip():  # RSS
            return c.text.strip()
    if not best:
        guid = _child(el, "guid")
        if guid is not None and (guid.text or "").startswith(("http://", "https://")):
            best = guid.text.strip()
    return best


def parse_feed(data: bytes) -> list[RawItem]:
    """RSS 2.0 · RSS 1.0(RDF) · Atom을 읽어요."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise SourceError("RSS · Atom 형식이 아니에요. 웹페이지 주소가 아니라 소식 목록(RSS) 주소인지 확인해 주세요.")
    if _local(root.tag) not in ("rss", "rdf", "feed"):
        raise SourceError("RSS · Atom 형식이 아니에요. 소식 목록(RSS) 주소인지 확인해 주세요.")
    out: list[RawItem] = []
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        title = clean_html(_text(_child(el, "title")))
        url = _link(el)
        body = _text(_child(el, "encoded", "content")) or _text(_child(el, "description", "summary"))
        when = _text(_child(el, "pubdate", "published", "updated", "date"))
        if title and url.startswith(("http://", "https://")):
            out.append(RawItem(title=title[:60], url=url[:500], text=clean_html(body) or title, date=_date(when)))
    return out


# ---------- 모으기 ----------
def _fail(failed: list[dict], name: str, reason: str, log: Callable[[str], None]) -> None:
    failed.append({"name": name, "reason": reason})
    log(f"  ✕ {name}: {reason}")


def collect(session: Session, source_names: Optional[Iterable[str]] = None, *, dry_run: bool = False,
            fetch: Callable[[str], list[RawItem]] = fetch_feed, summarize: Callable[[str], str] | None = None,
            max_items: int = MAX_ITEMS, log: Callable[[str], None] = lambda m: None) -> dict:
    """출처를 돌며 새 소식을 모아 세션에 넣어요 (commit은 부르는 쪽에서).

    source_names: 비우면 사용 중인 출처 모두, 이름을 주면 그 출처만 (관리자 [다시 수집]).
    dry_run: 가져오고 요약까지만 하고 세션에는 아무것도 넣지 않아요.
    돌려주는 값: {"ok": 새 소식 수, "fail": 실패한 출처 수, "failed": [{"name", "reason"}],
                  "added": [제목], "items": [News], "run": NewsRun}
    절대 예외를 밖으로 던지지 않아요 (출처별로 실패를 기록해요).
    """
    summarize = summarize or gemini.summarize
    sources = list(session.exec(select(NewsSource).order_by(NewsSource.id)).all())
    failed: list[dict] = []
    if source_names is not None:
        wanted = [n for n in dict.fromkeys(source_names) if n]
        by_name = {s.name: s for s in sources}
        picked = []
        for name in wanted:
            if name not in by_name:
                _fail(failed, name, "수집 출처 목록에 없는 이름이에요. 수집 출처 탭에서 이름을 확인해 주세요.", log)
            elif not by_name[name].active:
                _fail(failed, name, "사용을 꺼 둔 출처예요. 수집 출처 탭에서 ‘사용’을 켠 뒤 다시 수집해 주세요.", log)
            else:
                picked.append(by_name[name])
    else:
        picked = [s for s in sources if s.active]

    seen = set(session.exec(select(News.url)).all())
    items: list[News] = []
    for src in picked:
        if not src.checked:
            _fail(failed, src.name, "이용 조건 확인일이 비어 있어요. 이용 조건을 확인하고 날짜를 적은 뒤 다시 수집해 주세요.", log)
            continue
        try:
            raws = fetch(src.url)
        except SourceError as e:
            _fail(failed, src.name, e.reason, log)
            continue
        except Exception as e:  # 어떤 문제가 생겨도 다음 출처는 계속 모아요
            _fail(failed, src.name, f"알 수 없는 문제로 가져오지 못했어요. 잠시 뒤 다시 수집해 주세요. ({type(e).__name__})", log)
            continue
        got = 0
        for raw in raws:
            if got >= max_items:
                break
            if raw.url in seen:
                continue
            seen.add(raw.url)
            try:
                summary = summarize(raw.text) or raw.text[:120]
            except Exception:
                summary = raw.text[:120]
            items.append(News(id=new_id("n"), title=raw.title, summary=summary[:400], body=raw.text, source=src.name,
                              url=raw.url, date=raw.date, ai=True, public=True))
            got += 1
        log(f"  ✓ {src.name}: 새 소식 {got}건" + (f" (이미 있는 {len(raws) - got}건은 건너뜀)" if len(raws) > got else ""))

    run = NewsRun(date=f"{now():%Y-%m-%d %H:%M}", ok=len(items), fail=len(failed), failed=failed)
    if not dry_run:
        session.add_all(items)
        session.add(run)
        session.flush()  # run.id를 받으려고 (저장은 부르는 쪽 commit에서)
    return {"ok": run.ok, "fail": run.fail, "failed": failed, "added": [n.title for n in items], "items": items,
            "run": run}


# ---------- 기록 모양 ----------
def run_out(run: NewsRun) -> RunOut:
    """예시 데이터는 실패 출처를 이름만, 새 기록은 {name, reason}으로 남겨요. 화면에는 같은 모양으로 줘요."""
    names, reasons = [], {}
    for f in run.failed or []:
        if isinstance(f, dict):
            names.append(f.get("name", ""))
            if f.get("reason"):
                reasons[f.get("name", "")] = f["reason"]
        else:
            names.append(str(f))
    return RunOut(id=run.id or 0, date=run.date, ok=run.ok, fail=run.fail, failed=names, reasons=reasons)
