"""바다 소식 창구 (이정민 담당). FastAPI 서버(backend/routers/news.py · admin_contents.py)를 불러요.

U-15 바다 소식과 A-05 콘텐츠 관리가 같이 써요. 공개 목록 · 최신 · 많이 읽은 소식은 services/db.py 의
db.news() · db.latest_news() · db.top_news()를 써요.
    news_data.get("n1")            # 공개 소식 하나 (숨긴 소식은 None, 관리자는 보여요)
    news_data.count_view("n1")     # 상세를 열면 조회수 +1 (같은 사람은 24시간에 한 번, 서버가 세요)
    news_data.add(...)             # 관리자 직접 등록
실패하면 ApiError를 던져요 → 화면에서 st.error(e.message).
"""
from __future__ import annotations

from datetime import date

from services import api, db
from services.api import ApiError

__all__ = ["ApiError"]


def date_label(value: str) -> str:
    """'2026-11-07' → '2026.11.07' / '2026-11-08 06:00' → '2026.11.08 06:00'"""
    return value.replace("-", ".")


# ---------- 바다 소식 (U-15) ----------
def get(news_id: str) -> dict | None:
    try:
        return api.get(f"/news/{news_id}")
    except ApiError as e:
        if e.status == 404:
            return None
        raise


def count_view(news_id: str) -> int | None:
    """상세를 열 때 불러요. 지금 조회수를 돌려줘요 (세지 못하면 None — 화면은 그대로 보여요)."""
    try:
        return api.post(f"/news/{news_id}/view")["views"]
    except ApiError:
        return None


def last_run() -> dict | None:
    """마지막으로 새 소식을 모은 때 {"date", "ok", "fail"} (없으면 None). 모두 실패한 수집은 건너뛰어요."""
    return db._cached("news_last_run", lambda: api.get("/news/last-run"), ttl=60)


# ---------- 관리자: 소식 검토 (A-05) ----------
def admin_list() -> list[dict]:
    """숨긴 소식까지 모두, 최신순. 한 건 모양: 공개 소식 + body · edited · created_at"""
    return api.get("/admin/news")


def add(title: str, source: str, url: str, body: str, use_ai: bool, when: date | None = None) -> str:
    """관리자가 직접 등록해요 (바로 공개). use_ai면 AI가 요약하고 ‘AI 요약’ 꼬리표가 붙어요."""
    out = api.post("/admin/news", json={"title": title, "source": source, "url": url, "body": body,
                                        "use_ai": use_ai, "date": str(when) if when else None})
    db.clear_cache()
    return out["id"]


def update(news_id: str, **fields) -> dict:
    """고칠 칸만 넘겨요. 예) update("n1", public=False) · update("n1", title="…", summary="…")"""
    out = api.patch(f"/admin/news/{news_id}", json=fields)
    db.clear_cache()
    return out


def resummarize(news_id: str) -> str:
    """원문(없으면 지금 요약)을 다시 AI에 맡겨요. 새 요약을 돌려줘요."""
    out = api.post(f"/admin/news/{news_id}/resummarize")
    db.clear_cache()
    return out["summary"]


# ---------- 관리자: 수집 출처 · 기록 ----------
def sources() -> list[dict]:
    return api.get("/admin/news/sources")


def save_sources(rows: list[dict]) -> list[dict]:
    """출처 목록을 통째로 저장해요. 한 줄: {"id"(있으면), "name", "url", "checked": "YYYY-MM-DD" | "", "active"}"""
    out = api.put("/admin/news/sources", json=rows)
    db.clear_cache()
    return out


def runs() -> list[dict]:
    """수집 기록 최신순. 한 줄: {"id", "date", "ok", "fail", "failed": [이름], "reasons": {이름: 이유}}"""
    return api.get("/admin/news/runs")


def collect(names: list[str] | None = None) -> dict:
    """지금 수집해요 (names를 주면 그 출처만 다시). {"ok", "fail", "failed": [{"name", "reason"}], "added", "run"}"""
    out = api.post("/admin/news/collect", json={"source_names": names})
    db.clear_cache()
    return out


def start_collect_all() -> dict:
    """오래 걸리는 전체 수집을 시작하고 즉시 돌아와요."""
    return api.post("/admin/news/collect/start")


def collect_status() -> dict:
    """전체 수집의 진행·완료·오류 상태를 확인해요."""
    return api.get("/admin/news/collect/status")
