"""Redis 도우미 (편성훈). Redis 명령을 몰라도 이 함수들만 쓰면 돼요.

키 이름 규칙: 용도:대상:값  예) usage:user:u_me:20261108
"""
from __future__ import annotations

import json
import secrets
import time
from functools import lru_cache
from typing import Any

import redis

from backend.config import get_settings
from backend.core.timefmt import seconds_to_midnight, today


@lru_cache
def r() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def ping() -> bool:
    try:
        return bool(r().ping())
    except Exception:
        return False


# ---------- 로그인 세션 ----------
def session_create(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    r().setex(f"session:{token}", get_settings().session_days * 86400, user_id)
    return token


def session_user(token: str) -> str | None:
    return r().get(f"session:{token}") if token else None


def session_delete(token: str) -> None:
    r().delete(f"session:{token}")


# ---------- 확인 코드 (비회원 문의 조회). 메일 인증 · 비밀번호 찾기는 1회용 링크(routers/auth.py) ----------
def code_create(purpose: str, key: str, ttl: int = 300, payload: dict | None = None) -> str:
    code = f"{secrets.randbelow(1_000_000):06d}"
    r().setex(f"code:{purpose}:{key}", ttl, json.dumps({"code": code, "tries": 0, "payload": payload or {}}))
    return code


def code_check(purpose: str, key: str, code: str, max_tries: int = 5) -> tuple[bool, dict, str]:
    """(맞음?, 같이 저장한 값, 틀렸을 때 안내 문구)"""
    k = f"code:{purpose}:{key}"
    raw = r().get(k)
    if not raw:
        return False, {}, "인증 시간이 지났어요. 코드를 다시 받아 주세요."
    data = json.loads(raw)
    if data["tries"] >= max_tries:
        r().delete(k)
        return False, {}, "여러 번 틀려서 코드가 막혔어요. 코드를 다시 받아 주세요."
    if secrets.compare_digest(data["code"], code.strip()):
        r().delete(k)
        return True, data["payload"], ""
    data["tries"] += 1
    r().setex(k, max(r().ttl(k), 1), json.dumps(data))
    return False, {}, f"코드가 맞지 않아요. ({max_tries - data['tries']}번 남았어요)"


# ---------- 하루 알아보기 횟수 (한국 시간 자정에 초기화) ----------
def usage_get(subject: str) -> int:
    return int(r().get(f"usage:{subject}:{today():%Y%m%d}") or 0)


def usage_incr(subject: str) -> int:
    k = f"usage:{subject}:{today():%Y%m%d}"
    n = r().incr(k)
    r().expire(k, seconds_to_midnight() + 60)
    return n


# ---------- 게임 랭킹 (정렬 집합) ----------
def rank_add(game: str, nickname: str, score: int, when: str) -> int:
    """점수를 넣고 순위(1부터)를 돌려줘요. 동점이면 먼저 달성한 사람이 위."""
    member = json.dumps({"nickname": nickname, "score": score, "when": when, "t": time.time()}, ensure_ascii=False)
    r().zadd(f"rank:{game}", {member: score * 1e10 + (1e10 - time.time())})
    rank = r().zrevrank(f"rank:{game}", member)
    return (rank or 0) + 1


def rank_top(game: str, n: int = 5) -> list[list]:
    rows = r().zrevrange(f"rank:{game}", 0, n - 1)
    return [[(m := json.loads(x))["nickname"], m["score"], m["when"]] for x in rows]


def rank_count(game: str) -> int:
    return r().zcard(f"rank:{game}")


# ---------- 조회수 (같은 사람은 24시간에 한 번) ----------
def view_once(kind: str, item_id: str, viewer: str) -> bool:
    if r().set(f"seen:{kind}:{item_id}:{viewer}", 1, nx=True, ex=86400):
        r().zincrby(f"views:{kind}", 1, item_id)
        return True
    return False


def views(kind: str, item_id: str) -> int:
    return int(r().zscore(f"views:{kind}", item_id) or 0)


def views_seed(kind: str, item_id: str, n: int) -> None:
    if r().zscore(f"views:{kind}", item_id) is None:
        r().zadd(f"views:{kind}", {item_id: n})


# ---------- 임시 보관 (로그인 전 분석 결과 등) ----------
def temp_put(data: dict, ttl: int = 1800, prefix: str = "draft") -> str:
    tid = secrets.token_urlsafe(8)
    r().setex(f"{prefix}:{tid}", ttl, json.dumps(data, ensure_ascii=False))
    return tid


def temp_get(tid: str, prefix: str = "draft") -> dict | None:
    raw = r().get(f"{prefix}:{tid}")
    return json.loads(raw) if raw else None


# ---------- 짧은 캐시 · 연속 요청 막기 ----------
def cache_get(key: str) -> Any:
    raw = r().get(f"cache:{key}")
    return json.loads(raw) if raw else None


def cache_set(key: str, value: Any, ttl: int = 600) -> None:
    r().setex(f"cache:{key}", ttl, json.dumps(value, ensure_ascii=False))


def gap_ok(key: str, seconds: int) -> bool:
    """seconds 안에 같은 key로 다시 오면 False (글 도배 막기 등)."""
    return seconds <= 0 or bool(r().set(f"gap:{key}", 1, nx=True, ex=seconds))


# ---------- 개발용: 보내지 못한 메일 보관 ----------
def dev_mail_push(item: dict) -> None:
    r().lpush("dev:mails", json.dumps(item, ensure_ascii=False))
    r().ltrim("dev:mails", 0, 49)


def dev_mails(n: int = 20) -> list[dict]:
    return [json.loads(x) for x in r().lrange("dev:mails", 0, n - 1)]
