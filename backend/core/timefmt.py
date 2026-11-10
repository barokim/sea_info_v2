"""시간 도우미. 모든 시간은 한국 시간(KST) 기준이에요."""
from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def now() -> datetime:
    return datetime.now(KST)


def as_kst(dt: datetime | None) -> datetime | None:
    """DB에서 읽은 시간을 한국 시간으로 맞춰요 (시간대가 없으면 한국 시간으로 봐요)."""
    if dt is None:
        return None
    return dt.replace(tzinfo=KST) if dt.tzinfo is None else dt.astimezone(KST)


def today() -> date:
    return now().date()


def seconds_to_midnight() -> int:
    n = now()
    tomorrow = datetime.combine(n.date() + timedelta(days=1), datetime.min.time(), tzinfo=KST)
    return max(int((tomorrow - n).total_seconds()), 1)


def ago(dt: datetime | None) -> str:
    """'방금 · 12분 전 · 3시간 전 · 어제 · 4일 전 · 2026. 10. 2.'"""
    if not dt:
        return ""
    dt = as_kst(dt)
    sec = (now() - dt).total_seconds()
    if sec < 60:
        return "방금"
    if sec < 3600:
        return f"{int(sec // 60)}분 전"
    if sec < 86400:
        return f"{int(sec // 3600)}시간 전"
    days = (now().date() - dt.date()).days
    if days == 1:
        return "어제"
    if days < 7:
        return f"{days}일 전"
    return f"{dt.year}. {dt.month}. {dt.day}."


def parse_label(label: str) -> datetime:
    """예시 데이터의 '2시간 전' 같은 글을 실제 시간으로 바꿔요 (처음 데이터 넣을 때만 사용)."""
    import re

    n = now()
    if not label or label == "방금":
        return n
    if m := re.match(r"(\d+)분 전", label):
        return n - timedelta(minutes=int(m.group(1)))
    if m := re.match(r"(\d+)시간 전", label):
        return n - timedelta(hours=int(m.group(1)))
    if label == "어제":
        return n - timedelta(days=1)
    if m := re.match(r"(\d+)일 전", label):
        return n - timedelta(days=int(m.group(1)))
    return n
