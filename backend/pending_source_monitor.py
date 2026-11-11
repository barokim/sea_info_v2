"""권리 미확인 출처의 목록만 확인한다. 본문·이미지는 저장하지 않는다."""
from __future__ import annotations

import re
import os
from datetime import datetime
from html import unescape
from urllib.parse import urljoin

import httpx

from backend.news_collector import fetch_mabik

MABIK_URL = "https://www.mabik.re.kr/bbs/BBSMSTR_000000000347/list.do"
MEIS_URL = "https://www.meis.go.kr/inform/monthlyMarineLife.do"
STRICT_LICENSE_CHECK = os.getenv("MEIS_STRICT_LICENSE_CHECK", "false").lower() in {"1", "true", "yes"}


def check_pending_sources() -> dict:
    """자동 발견 결과를 반환한다. 공개 News 레코드는 만들지 않는다."""
    result = {"checked_at": datetime.now().astimezone().isoformat(), "sources": {}}
    try:
        items = fetch_mabik(MABIK_URL)
        result["sources"]["MABIK"] = {
            "status": "rights_pending", "list_url": MABIK_URL,
            "count": len(items),
            "items": [{"title": x.title, "date": x.date, "url": x.url} for x in items],
            "reason": "개별 게시물의 재이용 조건을 확인하지 못해 본문·요약·공개 보류",
        }
    except Exception as exc:
        result["sources"]["MABIK"] = {"status": "error", "list_url": MABIK_URL,
                                       "error": f"{type(exc).__name__}: {exc}"}

    try:
        with httpx.Client(timeout=15, follow_redirects=True,
                          headers={"User-Agent": "SeaInfoAgent/1.0"}) as client:
            page = client.get(MEIS_URL)
            page.raise_for_status()
            items = []
            years = sorted({int(value) for value in re.findall(r"20\d{2}", page.text)
                            if 2016 <= int(value) <= datetime.now().year}, reverse=True)
            for year in years:
                response = client.post(MEIS_URL, data={"viewMode": "list", "searchType": str(year)},
                                       headers={"X-Requested-With": "XMLHttpRequest", "Referer": MEIS_URL})
                response.raise_for_status()
                for tab, label in re.findall(r'<button[^>]*rel="(imageTab\d+)"[^>]*>(.*?)</button>',
                                             response.text, re.I | re.S):
                    title = unescape(re.sub(r"<[^>]+>", "", label)).strip()
                    if title:
                        items.append({"title": title, "year": year, "url": MEIS_URL, "tab": tab})
                if len(items) >= 20:
                    break
        items = items[:20]
        result["sources"]["MEIS"] = {
            "status": "rights_pending" if items else "no_current_items",
            "list_url": MEIS_URL, "count": len(items), "items": items,
            "reason": "월별 자료의 게시물별 이용 조건과 직접 링크가 미확인되어 본문·이미지·요약·공개 보류",
        }
    except Exception as exc:
        result["sources"]["MEIS"] = {"status": "error", "list_url": MEIS_URL,
                                      "error": f"{type(exc).__name__}: {exc}"}
    return result
