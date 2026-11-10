"""SQLite 연결과 처음 데이터 넣기 (편성훈).

서버가 처음 켜질 때 테이블을 만들고, 비어 있으면 mock/ 폴더의 예시 데이터를 넣어요.
처음 상태로 돌리고 싶으면 서버를 끄고 data/sea_info.db 파일을 지운 뒤 다시 켜요.
"""
from __future__ import annotations

import json
import pathlib
import random
import string
from datetime import datetime, timedelta

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from backend.config import get_settings

ROOT = pathlib.Path(__file__).resolve().parent.parent
MOCK = ROOT / "mock"
_s = get_settings()
if _s.database_url.startswith("sqlite:///"):
    pathlib.Path(_s.database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(_s.database_url, connect_args={"check_same_thread": False} if _s.database_url.startswith("sqlite") else {})


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):  # 여러 요청이 동시에 와도 덜 막히게
    if _s.database_url.startswith("sqlite"):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


def get_session():
    with Session(engine) as session:
        yield session


def new_id(prefix: str, n: int = 6) -> str:
    return prefix + "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _load(name: str):
    return json.loads((MOCK / f"{name}.json").read_text(encoding="utf-8"))


def init_db() -> None:
    from backend import models  # noqa: F401  (테이블 등록)

    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        if not session.exec(select(models.User)).first():
            _seed(session)
    _seed_redis()


GENERIC_COMMENTS = ["와, 멋져요!", "저도 꼭 보고 싶어요.", "좋은 정보 고마워요.", "사진이 정말 선명해요.",
                    "다음에 같이 가요!", "제자리에 놓아주셨다니 좋아요.", "아이가 정말 좋아하겠어요.", "처음 알았어요!"]


def _seed(session: Session) -> None:
    from backend import models as m
    from backend.core.security import hash_password
    from backend.core.timefmt import KST, now, parse_label

    rnd = random.Random(7)
    for sp in _load("species"):
        session.add(m.Species(id=sp["id"], name=sp["name"], emoji=sp["emoji"], tone=sp["tone"], confidence=sp["confidence"],
                              safety_level=sp["safety"]["level"], safety_reason=sp["safety"]["reason"],
                              protected=sp["protected"], summary=sp["summary"], habitat=sp["info"]["habitat"],
                              food=sp["info"]["food"], fun_fact=sp["info"]["fun_fact"], candidates=sp["candidates"]))
    # 시험 계정 비밀번호는 로컬(APP_ENV=local)에서만 만들어요. 배포 환경에서는 비밀번호 없는 예시 회원만 남아
    # 로그인할 수 없어요. 배포 후 관리자는 ADMIN_EMAILS 에 넣은 이메일로 가입해서 써요.
    demo_pw = {"u_me": "sea12345", "u_admin": "admin12345"} if get_settings().is_local else {}
    for u in _load("users"):
        session.add(m.User(id=u["id"], email=u.get("email") or f"{u['id']}@example.com", nickname=u["nickname"],
                           character=u["character"], role=u.get("role", "user"), provider="local",
                           password_hash=hash_password(demo_pw[u["id"]]) if u["id"] in demo_pw else None,
                           email_verified=True, aquarium_public=u.get("aquarium_public", False),
                           region=u.get("region", "jeju"), grade=u.get("grade", "새내기 탐험가"), points=u.get("points", 0),
                           created_at=now() - timedelta(days=rnd.randint(20, 200))))
    for b in _load("boards"):
        session.add(m.Board(id=b["id"], name=b["name"], type=b["type"], layout=b["layout"], status=b["status"],
                            order=b["order"], system=b["system"], perm=b["perm"], fields=b["fields"], desc=b["desc"],
                            rules={"comments": True, "likes": True, "reports": True, "interval": 30}))
    session.flush()
    users = [u["id"] for u in _load("users") if u["id"] != "u_admin"]
    seeded_comments = _load("comments")
    pending_comments = []
    for p in _load("posts"):
        created = parse_label(p["created"])
        post = m.Post(id=p["id"], board_id=p["board"], user_id=p["user"], title=p["title"], body=p["body"],
                      species_id=p.get("species"), place=p.get("place", ""), place_level=p.get("place_level", "none"),
                      extra=p.get("extra", {}), likes=p["likes"], pinned=p.get("pinned", False), created_at=created)
        session.add(post)
        rows = seeded_comments.get(p["id"]) or [{"user": rnd.choice(users), "body": GENERIC_COMMENTS[i % len(GENERIC_COMMENTS)]}
                                                for i in range(p.get("comments", 0))]
        pending_comments.append((post, created, rows))
    session.flush()  # 게시글을 먼저 저장해야 댓글 · 신고가 게시글을 가리킬 수 있어요
    for post, created, rows in pending_comments:
        for i, c in enumerate(rows):
            session.add(m.Comment(id=new_id("c"), post_id=post.id, user_id=c["user"], body=c["body"],
                                  created_at=min(created + timedelta(minutes=10 * (i + 1)), now())))
        post.comments = len(rows)
    for o in _load("observations"):
        session.add(m.Observation(id=o["id"], user_id=o["user"], species_id=o["species"], date=o["date"], place=o["place"],
                                  memo=o["memo"], post_id=o["post_id"], created_at=datetime.fromisoformat(o["date"]).replace(tzinfo=KST)))
    session.flush()
    for rp in _load("reports"):
        reporters = [u for u in users if u != session.get(m.Post, rp["post"]).user_id][: rp["count"]]
        for u in reporters:
            session.add(m.Report(post_id=rp["post"], user_id=u, reason=rp["reason"], created_at=datetime.fromisoformat(rp["date"]).replace(tzinfo=KST)))
        session.get(m.Post, rp["post"]).report_count = len(reporters)
    for q in _load("quiz"):
        session.add(m.QuizQuestion(q=q["q"], options=q["options"], answer=q["answer"], explain=q["explain"]))
    for n in _load("news"):
        session.add(m.News(id=n["id"], title=n["title"], summary=n["summary"], body=n["summary"], source=n["source"],
                           url=n["url"], date=n["date"], ai=n["ai"], public=n["public"]))
    for s in _load("news_sources"):
        session.add(m.NewsSource(**s))
    for r in _load("news_runs"):
        session.add(m.NewsRun(**r))
    for q in _load("inquiries"):
        created = datetime.fromisoformat(q["date"]).replace(tzinfo=KST)
        session.add(m.Inquiry(id=q["id"], type=q["type"], title=q["title"], body=q["body"], status=q["status"],
                              user_id=q["user"] or None, email=q["email"], answer=q["answer"], created_at=created,
                              updated_at=created))
    session.add(m.Setting(id=1, data=_load("settings")))
    for i, (act, tgt) in enumerate([("게시판 순서 변경", "다이빙 기록"), ("신고 처리: 문제없음", "p10"), ("운영 설정 저장", "알아보기 횟수")]):
        session.add(m.AdminLog(screen="시드", actor="운영자 바다", action=act, target=tgt, created_at=now() - timedelta(days=i + 1)))
    session.commit()


def _seed_redis() -> None:
    """랭킹 · 조회수 예시 값 (Redis가 비어 있을 때만)."""
    from backend.core import redis_store

    try:
        scores = _load("scores")
        for game, rows in scores.items():
            if redis_store.rank_count(game) == 0:
                for nick, score, when in rows:
                    redis_store.rank_add(game, nick, score, when)
        for n in _load("news"):
            redis_store.views_seed("news", n["id"], n["views"])
    except Exception as e:  # Redis가 꺼져 있으면 서버는 켜지되 /health 에 표시돼요
        print(f"[경고] Redis 예시 데이터를 넣지 못했어요: {e}", flush=True)
