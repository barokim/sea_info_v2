"""Jira 연동 (편성훈 뼈대 → 김바로 제보 라우터에서 사용).

Jira Cloud REST API v3 · 기본 인증(JIRA_EMAIL + JIRA_API_TOKEN). 키가 없으면 on() 이 False.
"""
from __future__ import annotations

import httpx

from backend.config import get_settings


class JiraError(Exception):
    pass


def on() -> bool:
    return get_settings().jira_on


def _adf(text: str) -> dict:
    """Jira v3 본문 형식(ADF)으로 바꿔요. 줄마다 한 문단."""
    return {"type": "doc", "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": line}]} if line
                        else {"type": "paragraph", "content": []} for line in text.splitlines()]}


def _req(method: str, path: str, **kw) -> dict:
    s = get_settings()
    try:
        resp = httpx.request(method, s.jira_base_url.rstrip("/") + path, auth=(s.jira_email, s.jira_api_token),
                             headers={"Accept": "application/json"}, timeout=20, **kw)
    except httpx.HTTPError as e:
        raise JiraError(f"Jira에 연결하지 못했어요: {e}") from e
    if resp.status_code >= 400:
        raise JiraError(f"Jira 오류 {resp.status_code}: {resp.text[:300]}")
    return resp.json() if resp.content else {}


def create_issue(summary: str, description: str, kind: str, labels: list[str] | None = None) -> str:
    """이슈를 만들고 키(예: SEA-12)를 돌려줘요. kind: 'bug' | 'task'"""
    s = get_settings()
    issue_type = s.jira_issue_type_bug if kind == "bug" else s.jira_issue_type_default
    data = _req("POST", "/rest/api/3/issue", json={"fields": {
        "project": {"key": s.jira_project_key}, "summary": summary[:250], "issuetype": {"name": issue_type},
        "description": _adf(description), "labels": labels or ["sea-info"]}})
    return data["key"]


def issue_status(key: str) -> tuple[str, bool]:
    """(상태 이름, 끝났는지)"""
    data = _req("GET", f"/rest/api/3/issue/{key}", params={"fields": "status"})
    st = data["fields"]["status"]
    return st["name"], st.get("statusCategory", {}).get("key") == "done"


def browse_url(key: str) -> str:
    return f"{get_settings().jira_base_url.rstrip('/')}/browse/{key}" if key else ""
