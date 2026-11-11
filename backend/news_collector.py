"""바다 소식 수집 (이정민 담당). 두 곳이 같은 코드를 써요.

    - 관리자 화면 A-05 ‘수집 기록’의 [다시 수집]  → POST /admin/news/collect
    - 매일 한국 시간 오전 6시 예약 실행          → jobs/collect_news.py

하는 일
    1. 사용 중인 출처(NewsSource)를 골라요. 이용 조건 확인일이 없는 출처는 모으지 않아요.
    2. 출처마다 RSS · Atom 또는 허용된 기관의 HTML 목록을 읽어요.
    3. 이미 저장한 원문 주소(url)는 건너뛰어요.
    4. 공공기관은 AI가 요약하고, 일반 언론사는 저작권 보호를 위해 원문 발췌(스니펫)+아웃링크로 저장해요.
    5. 이번 수집 기록(NewsRun)을 세션에 넣어요.
"""
from __future__ import annotations

import html
import hashlib
import os
import re
import tempfile
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import urlparse

import httpx
from sqlmodel import Session, select

from backend.core import gemini
from backend import korea_news, nifs_news, mabik_news
from backend.core.timefmt import KST, now, today
from backend.db import new_id
from backend.models import News, NewsRun, NewsSource
from backend.schemas.news import RunOut

TIMEOUT = 12  # 출처 하나를 기다리는 최대 시간(초)
MAX_BYTES = 5 * 1024 * 1024  # RSS 한 번에 5MB까지만 읽어요
MAX_ITEMS = 25  # 5개 × 5페이지(25개)를 넉넉히 채울 수 있도록 상향
UA = "SeaInfoAgent/1.0 (sea news collector; reads RSS of sources whose terms were checked)"
EXAMPLE_HOSTS = ("example.com", "example.org", "example.net")
MABIK_HOSTS = {"mabik.re.kr", "www.mabik.re.kr"}
MABIK_PATHS = {
    "/bbs/BBSMSTR_000000000347/list.do",
    "/prog/bbsArticle/BBSMSTR_000000000347/list.do",
}
RIGHTS_REVIEW_HOSTS = {
    "mabik.re.kr", "hdhy.co.kr", "newspenguin.com", "isusanin.com", "haesanews.com",
    "mof.go.kr", "kmi.re.kr", "nifs.go.kr", "kiost.ac.kr", "korea.kr", "data.go.kr",
}
# 해양생물 및 해양환경 키워드 대폭 확장
OCEAN_TERMS = (
    "해양", "바다", "수산", "어촌", "어업", "양식", "갯벌", "해안", "연안", "해역",
    "해수", "해저", "해류", "해양생물", "생물", "생태", "고래", "돌고래", "상괭이", "바다거북",
    "물범", "물개", "상어", "해파리", "산호", "해조", "미역", "다시마", "잘피", "바다숲",
    "원생생물", "미생물", "플랑크톤", "신종", "미기록종", "희귀", "멸종위기", "보호종",
    "어류", "치어", "방류", "연어", "참다랑어", "오징어", "명태", "고등어", "멸치", "전복", "굴", "김",
    "블루카본", "해상풍력", "선박", "항만", "어선", "해녀", "섬", "독도", "조석", "적조", "고수온",
    "수족관", "씨큐리움", "바이오", "유전자", "표본", "기탁", "오염", "쓰레기", "폐기물", "방제",
    "탄소중립", "기후변화", "환경", "생태계", "해양수산부",
)


class SourceError(Exception):
    """출처 하나를 가져오지 못했어요. reason은 관리자 화면에 그대로 보여요."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@contextmanager
def collection_lock(session: Session, timeout: float = 300):
    """같은 DB를 쓰는 앱·예약 작업의 수집/커밋을 직렬화한다.

    잠금 파일은 프로젝트 밖 OS 임시 폴더에 둔다. 호출자는 이 문맥 안에서
    collect와 commit/rollback을 모두 끝내야 중복 URL 판정이 안전하다.
    """
    bind = session.get_bind()
    db_path = getattr(getattr(bind, "url", None), "database", None)
    if not db_path:
        raise RuntimeError("수집 DB 경로를 확인할 수 없습니다.")
    key = hashlib.sha256(str(Path(db_path).resolve()).casefold().encode()).hexdigest()[:24]
    lock_path = Path(tempfile.gettempdir()) / f"sea_info_news_{key}.lock"
    with open(lock_path, "a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        started = time.monotonic()
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (OSError, BlockingIOError):
                if time.monotonic() - started >= timeout:
                    raise TimeoutError("다른 뉴스 수집이 진행 중입니다. 잠시 뒤 다시 시도해 주세요.")
                time.sleep(0.2)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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


def _base_host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    for domain in RIGHTS_REVIEW_HOSTS:
        if host == domain or host.endswith("." + domain):
            return domain
    return host.removeprefix("www.")


def _mabik_items(page: str) -> list[RawItem]:
    """보도자료 목록의 제목·날짜·고유 주소만 읽는다."""
    items = []
    for row in re.findall(r"(?is)<tr\b[^>]*>.*?</tr>", page):
        ident = (
            re.search(r"fn_search_detail\('([A-Za-z0-9_]+)'\)", row)
            or re.search(r"nttId=([A-Za-z0-9_]+)", row)
        )
        title = (
            re.search(r'(?is)<strong\s+class="bbs-subject-txt"[^>]*>(.*?)</strong>', row)
            or re.search(r'(?is)<td\s+class="[^"]*ta_l[^"]*"[^>]*>(.*?)</td>', row)
            or re.search(r'(?is)<a\b[^>]*>(.*?)</a>', row)
        )
        date = (
            re.search(r'(?is)<td\s+data-cell-header="등록일"[^>]*>(.*?)</td>', row)
            or re.search(r"(\d{4}-\d{2}-\d{2})", row)
        )
        if not (ident and title and date):
            continue
        when = clean_html(date.group(1))
        date_match = re.search(r"\d{4}-\d{2}-\d{2}", when)
        if not date_match:
            continue
        when = date_match.group(0)
        name = clean_html(title.group(1))
        if not name:
            continue
        detail = f"https://www.mabik.re.kr/bbs/BBSMSTR_000000000347/view.do?nttId={ident.group(1)}"
        items.append(RawItem(title=name[:60], url=detail, text="", date=when))
    if not items:
        raise SourceError("보도자료 목록에서 제목·날짜·링크를 찾지 못했어요. 사이트 구조를 확인해 주세요.")
    return items


def fetch_mabik(url: str, timeout: float = TIMEOUT) -> list[RawItem]:
    """국립해양생물자원관 최신 목록 1~2페이지(최대 20건)를 읽는다."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in MABIK_HOSTS or parsed.path not in MABIK_PATHS:
        raise SourceError("국립해양생물자원관 보도자료 목록 주소만 사용할 수 있어요.")
    items: list[RawItem] = []
    for number in (1, 2):
        try:
            response = httpx.get(f"{url}?pageIndex={number}", timeout=timeout,
                                 follow_redirects=True, headers={"User-Agent": UA})
            response.raise_for_status()
        except httpx.HTTPError as e:
            if items:
                break
            raise SourceError(f"보도자료 목록 연결 실패 ({type(e).__name__}).") from e
        if len(response.content) > MAX_BYTES:
            raise SourceError("보도자료 목록이 5MB를 넘었어요.")
        try:
            items.extend(_mabik_items(response.text))
        except SourceError:
            if not items:
                raise
            break
    return list({item.url: item for item in items}.values())


def fetch_mabik_body(url: str, timeout: float = TIMEOUT) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in MABIK_HOSTS:
        raise SourceError("보도자료 상세 주소가 올바르지 않아요.")
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True, headers={"User-Agent": UA})
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise SourceError(f"보도자료 상세 연결 실패 ({type(e).__name__}).") from e
    if len(response.content) > MAX_BYTES:
        raise SourceError("보도자료 상세가 5MB를 넘었어요.")
    if any(forbid in response.text for forbid in ("제2유형", "제3유형", "제4유형", "변경금지", "상업적 이용금지", "무단전재")):
        raise SourceError("자유이용(제1유형) 제한 문구가 포함되어 건너뛰었어요.")
    match = (
        re.search(r'(?is)<div\s+class="ui bbs--view--content"[^>]*>(.*?)</div>', response.text)
        or re.search(r'(?is)<div\s+class="[^"]*bbs_content[^"]*"[^>]*>(.*?)</div>', response.text)
        or re.search(r'(?is)<div\s+class="[^"]*view_con[^"]*"[^>]*>(.*?)</div>', response.text)
    )
    body = clean_html(match.group(1)) if match else ""
    if not body:
        raise SourceError("보도자료 상세 본문을 찾지 못했어요. 사이트 구조를 확인해 주세요.")
    return body


def fetch_source(url: str) -> list[RawItem]:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host in ("korea.kr", "www.korea.kr") or "korea.kr" in url:
        try:
            return [RawItem(title=title, url=detail, text="", date=date)
                    for title, detail, date in korea_news.list_items(korea_news.LIST_URL)]
        except korea_news.KoreaNewsError as e:
            raise SourceError(str(e)) from e
    if host in ("nifs.go.kr", "www.nifs.go.kr") or "nifs.go.kr" in url:
        try:
            return [RawItem(title=title, url=detail, text="", date=date)
                    for title, detail, date in nifs_news.list_items(nifs_news.LIST_URL)]
        except nifs_news.NifsNewsError as e:
            raise SourceError(str(e)) from e
    if parsed.hostname in MABIK_HOSTS:
        return fetch_mabik(url)
    return fetch_feed(url)


def _approved_host(host: str) -> bool:
    approved = {part.strip().lower() for part in os.getenv("SEA_INFO_APPROVED_NEWS_HOSTS", "").split(",") if part.strip()}
    return host in approved


def _approved_urls() -> set[str]:
    return {url.strip() for url in os.getenv("SEA_INFO_APPROVED_NEWS_URLS", "").split(";")
            if url.strip().startswith("https://")}


def _ocean_related(title: str) -> bool:
    cleaned = title.replace("국립해양생물자원관", "").replace("국립수산과학원", "").replace("해양수산부", "")
    return any(term in cleaned for term in OCEAN_TERMS)


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
            fetch: Callable[[str], list[RawItem]] = fetch_source, summarize: Callable[[str], str] | None = None,
            max_items: int = MAX_ITEMS, log: Callable[[str], None] = lambda m: None) -> dict:
    """출처를 돌며 새 소식을 모아 세션에 넣어요 (commit은 부르는 쪽에서)."""
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
    approved_urls = _approved_urls()
    for src in picked:
        if not src.checked:
            _fail(failed, src.name, "이용 조건 확인일이 비어 있어요. 이용 조건을 확인하고 날짜를 적은 뒤 다시 수집해 주세요.", log)
            continue
        host = _base_host(src.url)
        host_approved = _approved_host(host)

        # 1. 공공기관 (정책브리핑, 수산과학원, 해양생물자원관)
        korea_checked = src.url == korea_news.LIST_URL
        nifs_checked = src.url == nifs_news.LIST_URL
        mabik_checked = (urlparse(src.url).hostname in MABIK_HOSTS
                         and urlparse(src.url).path in MABIK_PATHS)

        # 2. 민간 언론사 (해사신문, 현대해양, 뉴스펭귄 등) - 원문 발췌(스니펫+아웃링크)로 수집 허용!
        media_checked = host in ("haesanews.com", "hdhy.co.kr", "newspenguin.com", "isusanin.com")
        item_checked = korea_checked or nifs_checked or mabik_checked

        if host in RIGHTS_REVIEW_HOSTS and not item_checked and not host_approved and not any(_base_host(u) == host for u in approved_urls):
            _fail(failed, src.name, "기사 저장·AI 요약·공개 이용 허락이 확인되지 않았어요. 기관 전체 허락 또는 게시물별 허락을 확인해 주세요.", log)
            continue
        try:
            raws = fetch(src.url)
        except SourceError as e:
            _fail(failed, src.name, e.reason, log)
            continue
        except Exception as e:
            _fail(failed, src.name, f"알 수 없는 문제로 가져오지 못했어요. 잠시 뒤 다시 수집해 주세요. ({type(e).__name__})", log)
            continue
        got = 0
        for raw in raws:
            if got >= max_items:
                break
            if host in RIGHTS_REVIEW_HOSTS and not item_checked and not host_approved and raw.url not in approved_urls:
                continue
            if nifs_checked and not (nifs_news.marine_life_related(raw.title) or _ocean_related(raw.title)):
                continue
            if host in RIGHTS_REVIEW_HOSTS and not nifs_checked and not _ocean_related(raw.title):
                continue
            if raw.url in seen:
                continue
            if korea_checked:
                try:
                    raw.text = korea_news.licensed_text(raw.url)
                except korea_news.KoreaNewsError as e:
                    log(f"  · {src.name}: {raw.title} 건너뜀 — {e}")
                    continue
            if nifs_checked:
                try:
                    raw.text = nifs_news.licensed_text(raw.url, strict_license_check=True)
                except nifs_news.NifsNewsError as e:
                    log(f"  · {src.name}: {raw.title} 건너뜀 — {e}")
                    continue
            if mabik_checked:
                try:
                    raw.text = mabik_news.licensed_text(raw.url, strict_license_check=True)
                except mabik_news.MabikNewsError as e:
                    log(f"  · {src.name}: {raw.title} 건너뜀 — {e}")
                    continue
            seen.add(raw.url)
            fallback = raw.text[:120] + ("…" if len(raw.text) > 120 else "")

            # 요약 처리: 공공기관은 AI 요약 시도, 민간 언론사는 저작권 보호를 위해 원문 발췌로만 처리
            summary = ""
            is_ai = False

            if media_checked:
                # 민간 언론사(해사신문, 현대해양): 저작권법 제28조(인용)에 따라 원문 앞부분 발췌 + 아웃링크로만 안전하게 저장
                summary = fallback
                is_ai = False
            else:
                # 공공기관: 공공누리 제1유형에 따라 AI 요약 수행
                if korea_checked:
                    try:
                        from backend.korea_ai import summarize_licensed
                        summary = summarize_licensed(raw.text)
                    except Exception:
                        summary = ""
                if not summary or summary == fallback:
                    try:
                        summary = summarize(raw.text) or ""
                    except Exception:
                        summary = ""
                if not summary or summary == fallback:
                    summary = fallback
                is_ai = bool(summary and summary != fallback and len(summary.strip()) > 20)

            items.append(News(id=new_id("n"), title=raw.title, summary=summary[:400], body=raw.text, source=src.name,
                              url=raw.url, date=raw.date, ai=is_ai, public=True))
            got += 1
        log(f"  ✓ {src.name}: 새 소식 {got}건" + (f" (이미 있는 {len(raws) - got}건은 건너뜀)" if len(raws) > got else ""))

    run = NewsRun(date=f"{now():%Y-%m-%d %H:%M}", ok=len(items), fail=len(failed), failed=failed)
    if not dry_run:
        session.add_all(items)
        session.add(run)
        session.flush()
    return {"ok": run.ok, "fail": run.fail, "failed": failed, "added": [n.title for n in items], "items": items,
            "run": run}


# ---------- 기록 모양 ----------
def run_out(run: NewsRun) -> RunOut:
    names, reasons = [], {}
    for f in run.failed or []:
        if isinstance(f, dict):
            names.append(f.get("name", ""))
            if f.get("reason"):
                reasons[f.get("name", "")] = f["reason"]
        else:
            names.append(str(f))
    return RunOut(id=run.id or 0, date=run.date, ok=run.ok, fail=run.fail, failed=names, reasons=reasons)
