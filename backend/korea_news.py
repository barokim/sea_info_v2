"""정책브리핑의 해양수산부 보도자료: 목록과 개별 텍스트 이용조건 확인.

공식 RSS가 중단된 페이지의 HTML 어댑터다. 사진·첨부파일은 읽지 않는다.
HTML 구조나 이용 문구가 바뀌면 수집을 멈추는 보수적 방식이다.
"""
from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, urlparse

import httpx

LIST_URL = "https://m.korea.kr/briefing/pressReleaseList.do?repCode=A00023&repCodeType=%EC%A0%95%EB%B6%80%EB%B6%80%EC%B2%98"
DETAIL_PATH = "/briefing/pressReleaseView.do"
LICENSE_TEXT = "이 자료는 텍스트에 한하여 공공누리 제1유형(출처표시)의 조건에 따라 이용할 수 있습니다."
MAX_BYTES = 5 * 1024 * 1024
TIMEOUT = 15
UA = "SeaInfoAgent/1.0 (contact project maintainer; one daily check of public press releases)"


class KoreaNewsError(Exception):
    pass


def _read(url: str) -> str:
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": UA}) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                if urlparse(str(response.url)).hostname not in {"m.korea.kr", "www.korea.kr"}:
                    raise KoreaNewsError("공식 정책브리핑 외부로 이동했습니다.")
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise KoreaNewsError("응답이 5MB를 넘었습니다.")
                return data.decode(response.encoding or "utf-8", errors="replace")
    except httpx.HTTPError as exc:
        raise KoreaNewsError(f"정책브리핑 연결 실패: {type(exc).__name__}") from exc


def _detail_url(url: str) -> str:
    parsed = urlparse(url)
    news_id = parse_qs(parsed.query).get("newsId", [""])[0]
    if parsed.scheme != "https" or parsed.hostname not in {"m.korea.kr", "www.korea.kr"} or parsed.path != DETAIL_PATH or not re.fullmatch(r"\d{6,12}", news_id):
        raise KoreaNewsError("정책브리핑 보도자료 주소가 아닙니다.")
    return f"https://www.korea.kr{DETAIL_PATH}?newsId={news_id}"


def _plain(fragment: str) -> str:
    fragment = re.sub(r"(?s)<!--.*?-->", " ", fragment)
    fragment = re.sub(r"(?is)<(?:script|style)\b[^>]*>.*?</(?:script|style)>", " ", fragment)
    fragment = re.sub(r"(?s)<[^>]*>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(html.unescape(fragment))).strip()


def list_items(url: str = LIST_URL, pages: int = 1) -> list[tuple[str, str, str]]:
    """공식 해수부 목록에서 제목, 고유 URL, 발행일을 추출한다."""
    if url != LIST_URL:
        raise KoreaNewsError("검증한 해양수산부 목록 URL만 허용합니다.")
    items = []
    pattern = re.compile(
        r'(?is)<a\s+href="(?P<href>/briefing/pressReleaseView\.do\?newsId=\d+[^\"]*)"[^>]*>'
        r'.*?<strong>(?P<title>.*?)</strong>.*?<span\s+class="source">\s*'
        r'<span>(?P<date>\d{4}\.\d{2}\.\d{2})</span>\s*<span>(?P<agency>.*?)</span>',
    )
    for number in range(1, min(pages, 5) + 1):
        page = _read(f"{url}&pageIndex={number}")
        for match in pattern.finditer(page):
            if _plain(match.group("agency")) != "해양수산부":
                continue
            title = _plain(match.group("title"))
            detail = _detail_url("https://m.korea.kr" + html.unescape(match.group("href")))
            item = (title[:60], detail, match.group("date").replace(".", "-"))
            if title and item not in items:
                items.append(item)
    if not items:
        raise KoreaNewsError("목록에서 해양수산부 기사 제목·날짜·링크를 찾지 못했습니다.")
    return items


def licensed_text(url: str) -> str:
    """개별 기사에서 텍스트 제1유형 표시와 본문 영역을 확인한 뒤 텍스트만 반환한다."""
    canonical = _detail_url(url)
    mobile = canonical.replace("https://www.korea.kr/", "https://m.korea.kr/")
    page = _read(mobile)
    start = page.find('class="view_cont"')
    rights_end = page.find("<!--// E: copyright -->", start)
    if start < 0 or rights_end < 0:
        raise KoreaNewsError("개별 이용 조건 영역을 찾지 못했습니다.")
    rights = re.sub(r"\s+", "", _plain(page[start:rights_end]))
    if re.sub(r"\s+", "", LICENSE_TEXT) not in rights:
        raise KoreaNewsError("개별 기사에 텍스트 공공누리 제1유형 표시가 없습니다.")
    remark = page.find("remark", start)
    if remark < 0 or remark > rights_end:
        raise KoreaNewsError("허용된 텍스트 본문 영역을 찾지 못했습니다.")
    body_end = page.rfind("<", start, remark)
    opening_end = page.find(">", start, body_end)
    if opening_end < 0:
        raise KoreaNewsError("본문 HTML 시작을 찾지 못했습니다.")
    fragment = page[opening_end + 1:body_end]
    body = _plain(fragment)
    if len(body) < 100:
        raise KoreaNewsError("허용된 텍스트 본문을 분리하지 못했습니다.")
    return body[:12000]
