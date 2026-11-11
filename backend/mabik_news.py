"""MABIK 보도자료의 개별 공공누리 제1유형 표시를 확인한다."""
from __future__ import annotations

import html
import os
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

import httpx

DETAIL_PATH = "/bbs/BBSMSTR_000000000347/view.do"
MAX_BYTES = 5 * 1024 * 1024
STRICT_LICENSE_CHECK = os.getenv("STRICT_LICENSE_CHECK", "false").lower() in {"1", "true", "yes"}


class MabikNewsError(Exception):
    pass


class _RightsArea(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.parts: list[str] = []
        self.image_sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "div" and "content-info" in (attrs_dict.get("class") or "").split():
            self.depth = 1
        elif tag == "div" and self.depth:
            self.depth += 1
        if self.depth and tag == "img" and attrs_dict.get("alt"):
            self.parts.append(attrs_dict["alt"] or "")
        if self.depth and tag == "img" and attrs_dict.get("src"):
            self.image_sources.append(attrs_dict["src"] or "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self.depth:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.depth:
            self.parts.append(data)


def licensed_text(url: str, strict_license_check: bool | None = None) -> str:
    if strict_license_check is None:
        strict_license_check = STRICT_LICENSE_CHECK
    parsed = urlparse(url)
    item_id = parse_qs(parsed.query).get("nttId", [""])[0]
    if (parsed.scheme != "https" or parsed.hostname != "www.mabik.re.kr"
            or parsed.path != DETAIL_PATH or not re.fullmatch(r"[A-Za-z0-9]{8,40}", item_id)):
        raise MabikNewsError("검증한 MABIK 보도자료 상세 주소가 아닙니다.")
    try:
        with httpx.Client(timeout=15, follow_redirects=True,
                          headers={"User-Agent": "SeaInfoAgent/1.0"}) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                if urlparse(str(response.url)).hostname != "www.mabik.re.kr":
                    raise MabikNewsError("MABIK 외부로 이동했습니다.")
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_BYTES:
                        raise MabikNewsError("응답이 5MB를 넘었습니다.")
                page = raw.decode(response.encoding or "utf-8", errors="replace")
    except httpx.HTTPError as exc:
        raise MabikNewsError(f"MABIK 연결 실패: {type(exc).__name__}") from exc

    rights = _RightsArea()
    rights.feed(page)
    label = re.sub(r"\s+", " ", html.unescape(" ".join(rights.parts))).strip()
    image_types = set()
    for source in rights.image_sources:
        name = urlparse(source).path.rsplit("/", 1)[-1]
        match_type = re.fullmatch(r"(?:kogl[_-]?(?:mark|type)[_-]?0?([1-4])|licenseType([1-4]))\.(?:png|gif|jpe?g|svg|do)", name, re.I)
        if match_type:
            image_types.add(int(match_type.group(1) or match_type.group(2)))
    text_type1 = re.search(r"공공누리\s*(?:제\s*)?1\s*유형|제\s*1\s*유형\s*[:：]?\s*출처\s*표시", label)
    if strict_license_check and not text_type1 and 1 not in image_types:
        raise MabikNewsError("개별 게시물에 공공누리 제1유형 표시가 없습니다.")
    if re.search(r"(?:제\s*)?[234]\s*유형", label) or image_types.intersection({2, 3, 4}):
        raise MabikNewsError("개별 게시물의 이용 유형 표시가 서로 충돌합니다.")
    match = re.search(r'(?is)<div\s+class="ui bbs--view--content"[^>]*>(.*?)</div>', page)
    if not match:
        raise MabikNewsError("MABIK 텍스트 본문을 찾지 못했습니다.")
    body = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", match.group(1)))).strip()
    if re.search(r"무단\s*전재|재\s*배포\s*금지|저작권자\s*\(c\)|연합뉴스", body, re.I):
        raise MabikNewsError("본문에 전재·재배포 제한 또는 민간 언론사 표시가 있습니다.")
    if len(body) < 30:
        raise MabikNewsError("MABIK 텍스트 본문이 너무 짧거나 분리할 수 없습니다.")
    return body[:12000]
