"""국립수산과학원 보도자료 중 해양생물 글과 개별 제1유형 텍스트만 읽는다."""
from __future__ import annotations

import html
import os
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse, urlencode

import httpx

LIST_URL = "https://www.nifs.go.kr/news/actionNewsList.do"
DETAIL_PATH = "/news/actionNewsView.do"
DATE_RANGE = "NEWS_D_DATE_BEGIN=2020-01-01&NEWS_D_DATE_END=2030-12-31"
MAX_BYTES = 5 * 1024 * 1024
STRICT_LICENSE_CHECK = os.getenv("STRICT_LICENSE_CHECK", "false").lower() in {"1", "true", "yes"}
UA = "SeaInfoAgent/1.0 (one daily check of public press releases)"
MARINE_LIFE_TERMS = ("멸치", "굴", "해조류", "고래", "돌고래", "해파리",
                     "다랑어", "조개", "백합", "새우", "패류", "바다거북", "산호", "미역", "김 양식",
                     "수산생물", "해양생물", "양식", "어류", "어패류", "어종", "어장")


class NifsNewsError(Exception):
    pass


def _read(url: str) -> str:
    try:
        with httpx.Client(timeout=15, follow_redirects=True, headers={"User-Agent": UA}) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                if urlparse(str(response.url)).hostname != "www.nifs.go.kr":
                    raise NifsNewsError("NIFS 외부로 이동했습니다.")
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise NifsNewsError("응답이 5MB를 넘었습니다.")
                return data.decode(response.encoding or "utf-8", errors="replace")
    except httpx.HTTPError as exc:
        raise NifsNewsError(f"NIFS 연결 실패: {type(exc).__name__}") from exc


def _plain(fragment: str) -> str:
    fragment = re.sub(r"(?is)<(?:script|style)\b[^>]*>.*?</(?:script|style)>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"(?s)<[^>]*>", " ", fragment))).strip()


def _detail_url(seq: str) -> str:
    if not re.fullmatch(r"\d{3,10}", seq):
        raise NifsNewsError("NIFS 기사 번호가 올바르지 않습니다.")
    return (f"https://www.nifs.go.kr{DETAIL_PATH}?MENU_ID=M0000307&NEWS_SEQ={seq}&"
            f"{DATE_RANGE}&PARENT_NEWS_HG_CODE=&NEWS_D_SUBJECT=&selectPage=1")


def _sequence(url: str) -> str:
    parsed = urlparse(url)
    seq = parse_qs(parsed.query).get("NEWS_SEQ", [""])[0]
    if parsed.scheme != "https" or parsed.hostname != "www.nifs.go.kr" or parsed.path != DETAIL_PATH:
        raise NifsNewsError("NIFS 보도자료 상세 주소가 아닙니다.")
    if url != _detail_url(seq):
        raise NifsNewsError("검증한 NIFS 기사 주소 형식이 아닙니다.")
    return seq


def marine_life_related(title: str) -> bool:
    return any(term in title for term in MARINE_LIFE_TERMS)


def list_items(url: str = LIST_URL, pages: int = 5) -> list[tuple[str, str, str]]:
    if url != LIST_URL:
        raise NifsNewsError("검증한 NIFS 목록 URL만 허용합니다.")
    items: list[tuple[str, str, str]] = []
    for number in range(1, min(pages, 5) + 1):
        query = urlencode({"selectPage": number, "NEWS_D_DATE_BEGIN": "2000-01-01",
                           "NEWS_D_DATE_END": "2099-12-31"})
        page = _read(f"{url}?{query}")
        for row in re.findall(r"(?is)<tr\b[^>]*>.*?</tr>", page):
            subject = re.search(r'(?is)<td\s+data-label="제목"\s+class="subject"[^>]*>\s*'
                                r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>', row)
            if not subject:
                continue
            seq = parse_qs(html.unescape(subject.group(1)).partition("?")[2]).get("NEWS_SEQ", [""])[0]
            dates = re.findall(r"20\d{2}-\d{2}-\d{2}", _plain(row))
            title = _plain(subject.group(2))
            if seq and dates and title:
                item = (title[:60], _detail_url(seq), dates[-1])
                if item not in items:
                    items.append(item)
    if not items:
        raise NifsNewsError("NIFS 목록에서 제목·날짜·링크를 찾지 못했습니다.")
    return items


class _BodyText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "td" and "contview" in (attrs_dict.get("class") or "").split():
            self.depth = 1
        elif tag == "td" and self.depth:
            self.depth += 1
        elif tag in {"p", "br", "div"} and self.depth:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self.depth:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.depth:
            self.parts.append(data)


def licensed_text(url: str, strict_license_check: bool | None = None) -> str:
    if strict_license_check is None:
        strict_license_check = STRICT_LICENSE_CHECK
    _sequence(url)
    page = _read(url)
    board_start = page.find('<div class="board-view">')
    license_start = page.find('id="footerKongSe"', board_start)
    if board_start < 0:
        raise NifsNewsError("NIFS 본문 또는 개별 이용 조건을 찾지 못했습니다.")
    license_area = page[license_start:license_start + 1000] if license_start >= 0 else ""
    if re.search(r'licenseType[234]\.do|제\s*[234]\s*유형', license_area):
        raise NifsNewsError("개별 기사에 제한적인 공공누리 유형이 표시되어 있습니다.")
    if strict_license_check and (not re.search(r'licenseType1\.do', license_area)
                                 or not re.search(r'제1유형\s*:\s*출처표시', _plain(license_area))):
        raise NifsNewsError("개별 기사에 공공누리 제1유형 표시가 없습니다.")
    parser = _BodyText()
    parser.feed(page[board_start:license_start if license_start >= 0 else None])
    body = re.sub(r"\s+", " ", html.unescape("".join(parser.parts))).strip()
    if re.search(r"무단\s*전재|재\s*배포\s*금지|저작권자\s*\(c\)|연합뉴스", body, re.I):
        raise NifsNewsError("본문에 전재·재배포 제한 또는 민간 언론사 표시가 있습니다.")
    if len(body) < 30:
        raise NifsNewsError("NIFS 텍스트 본문을 분리하지 못했습니다.")
    return body[:12000]
