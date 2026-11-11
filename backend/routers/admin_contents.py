"""A-05 콘텐츠 관리 API (이정민 담당, 관리자만): 퀴즈 문제 · 바다 소식 검토 · 수집 출처 · 수집 기록.

고친 내용은 바로 U-13 퀴즈와 U-15 바다 소식에 보여요. 관리자가 한 일은 AdminLog에 한 줄씩 남겨요.
"""
from __future__ import annotations

import json
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from backend import news_collector
from backend.core import gemini
from backend.core.convert import news_out
from backend.core.security import require_admin
from backend.core.timefmt import as_kst, today
from backend.db import engine, get_session, new_id
from backend.models import AdminLog, News, NewsRun, NewsSource, QuizQuestion, User
from backend.routers.games import quiz_out
from backend.routers.news import forget_top
from backend.schemas.games import QuizIn, QuizOut, QuizPatch
from backend.schemas.news import (AdminNewsOut, CollectIn, CollectOut, FailedSource, NewsCreateIn, NewsPatch, RunOut,
                                  SourceIn, SourceOut)

router = APIRouter(prefix="/admin", tags=["관리자 · 콘텐츠"])
SCREEN = "콘텐츠 관리"
EDIT_ACTION = "소식 고치기"
_collect_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="news-collect")
_collect_lock = Lock()
_collect_future: Future | None = None


def _log(session: Session, admin: User, action: str, target: str = "", before=None, after=None, reason: str = "") -> None:
    def s(v):
        return "" if v is None else (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str))[:1000]

    session.add(AdminLog(screen=SCREEN, actor=admin.nickname, action=action, target=target, before=s(before),
                         after=s(after), reason=reason))


def _commit(session: Session, what: str) -> None:
    """한 번에 저장해요. 하나라도 실패하면 모두 되돌려요."""
    try:
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"[콘텐츠 관리 저장 오류] {e}", flush=True)
        raise HTTPException(500, f"{what}하지 못했어요. 입력한 내용은 그대로 있어요. 다시 시도해 주세요.")


# ---------- 퀴즈 문제 ----------
def _quiz(session: Session, quiz_id: int) -> QuizQuestion:
    q = session.get(QuizQuestion, quiz_id)
    if not q:
        raise HTTPException(404, "문제를 찾지 못했어요. 목록을 새로고침해 주세요.")
    return q


@router.get("/quiz", response_model=list[QuizOut], summary="퀴즈 문제 모두 (쉬는 문제 포함)")
def quiz_list(admin: User = Depends(require_admin), session: Session = Depends(get_session)):
    return [quiz_out(q) for q in session.exec(select(QuizQuestion).order_by(QuizQuestion.id)).all()]


@router.post("/quiz", response_model=QuizOut, status_code=201, summary="새 문제 추가 (보기 3~4개)")
def quiz_add(body: QuizIn, admin: User = Depends(require_admin), session: Session = Depends(get_session)):
    q = QuizQuestion(**body.model_dump())
    session.add(q)
    session.flush()
    _log(session, admin, "퀴즈 문제 추가", str(q.id), after=body.q)
    _commit(session, "문제를 추가")
    session.refresh(q)
    return quiz_out(q)


@router.patch("/quiz/{quiz_id}", response_model=QuizOut, summary="문제 고치기 · 사용 여부 바꾸기")
def quiz_edit(quiz_id: int, body: QuizPatch, admin: User = Depends(require_admin), session: Session = Depends(get_session)):
    q = _quiz(session, quiz_id)
    before = quiz_out(q).model_dump()
    new = {**before, **body.model_dump(exclude_unset=True, exclude_none=True)}
    if not 0 <= new["answer"] < len(new["options"]):
        raise HTTPException(422, "정답 번호가 보기 범위를 벗어났어요. 정답 보기를 다시 골라 주세요.")
    q.q, q.options, q.answer, q.explain, q.active = new["q"], list(new["options"]), new["answer"], new["explain"], new["active"]
    session.add(q)
    changed = {k: new[k] for k in new if new[k] != before[k]}
    if changed:
        action = ("퀴즈 문제 켜기" if q.active else "퀴즈 문제 쉬게 하기") if set(changed) == {"active"} else "퀴즈 문제 고치기"
        _log(session, admin, action, str(q.id), before={k: before[k] for k in changed}, after=changed)
    _commit(session, "문제를 저장")
    session.refresh(q)
    return quiz_out(q)


# ---------- 바다 소식 검토 ----------
def _edited_ids(session: Session) -> set[str]:
    rows = session.exec(select(AdminLog.target).where(AdminLog.screen == SCREEN, AdminLog.action == EDIT_ACTION)).all()
    return set(rows)


def admin_news_out(n: News, edited: set[str]) -> AdminNewsOut:
    return AdminNewsOut(**news_out(n).model_dump(), body=n.body, edited=n.id in edited,
                        created_at=as_kst(n.created_at).isoformat(timespec="minutes") if n.created_at else "")


def _news(session: Session, news_id: str) -> News:
    n = session.get(News, news_id)
    if not n:
        raise HTTPException(404, "소식을 찾지 못했어요. 목록을 새로고침해 주세요.")
    return n


@router.get("/news", response_model=list[AdminNewsOut], summary="모든 소식 (숨긴 소식 포함, 최신순)")
def news_all(admin: User = Depends(require_admin), session: Session = Depends(get_session)):
    edited = _edited_ids(session)
    rows = sorted(session.exec(select(News)).all(), key=lambda n: (n.date, as_kst(n.created_at)), reverse=True)
    return [admin_news_out(n, edited) for n in rows]


@router.post("/news", response_model=AdminNewsOut, status_code=201, summary="소식 직접 등록 (바로 공개)")
def news_add(body: NewsCreateIn, admin: User = Depends(require_admin), session: Session = Depends(get_session)):
    if session.exec(select(News).where(News.url == body.url)).first():
        raise HTTPException(409, "같은 원문 주소의 소식이 이미 있어요. 목록에서 그 소식을 고쳐 주세요.")
    use_ai = body.use_ai and bool(body.body)
    if use_ai:
        summary = gemini.summarize(body.body)[:400]
    else:
        summary = body.summary or body.body
        summary = summary if len(summary) <= 400 else summary[:399] + "…"
    n = News(id=new_id("n"), title=body.title, summary=summary, body=body.body or body.summary, source=body.source,
             url=body.url, date=(body.date or today()).isoformat(), ai=use_ai, public=True)
    session.add(n)
    _log(session, admin, "소식 직접 등록", n.id, after=body.title)
    _commit(session, "소식을 등록")
    forget_top()
    session.refresh(n)
    return admin_news_out(n, set())


@router.patch("/news/{news_id}", response_model=AdminNewsOut, summary="소식 고치기 · 숨기기 · 다시 공개")
def news_edit(news_id: str, body: NewsPatch, admin: User = Depends(require_admin), session: Session = Depends(get_session)):
    n = _news(session, news_id)
    data = body.model_dump(exclude_unset=True, exclude_none=True)
    if not data:
        raise HTTPException(422, "고칠 내용이 없어요. 바꿀 칸을 적어 주세요.")
    before = {k: getattr(n, k) for k in data}
    changed = {k: v for k, v in data.items() if before[k] != v}
    if "url" in changed and session.exec(select(News).where(News.url == changed["url"], News.id != n.id)).first():
        raise HTTPException(409, "같은 원문 주소의 다른 소식이 이미 있어요. 원문 주소를 확인해 주세요.")
    for k, v in changed.items():
        setattr(n, k, v)
    session.add(n)
    if changed:
        content = {k: v for k, v in changed.items() if k != "public"}
        if content:
            _log(session, admin, EDIT_ACTION, n.id, before={k: before[k] for k in content}, after=content)
        if "public" in changed:
            _log(session, admin, "소식 다시 공개" if n.public else "소식 숨기기", n.id, before=before["public"], after=n.public)
    _commit(session, "소식을 저장")
    if "public" in changed:
        forget_top()
    session.refresh(n)
    return admin_news_out(n, _edited_ids(session))


@router.post("/news/{news_id}/resummarize", response_model=AdminNewsOut, summary="원문으로 AI 다시 요약")
def news_resummarize(news_id: str, admin: User = Depends(require_admin), session: Session = Depends(get_session)):
    n = _news(session, news_id)
    text = n.body or n.summary
    if not text.strip():
        raise HTTPException(422, "요약할 원문이 없어요. 고치기에서 요약을 직접 적어 주세요.")
    before = n.summary
    n.summary = (gemini.summarize(text) or before)[:400]
    n.ai = True
    session.add(n)
    _log(session, admin, "소식 다시 요약", n.id, before=before, after=n.summary)
    _commit(session, "다시 요약")
    session.refresh(n)
    return admin_news_out(n, _edited_ids(session))


# ---------- 수집 출처 ----------
def source_out(s: NewsSource) -> SourceOut:
    return SourceOut(id=s.id, name=s.name, url=s.url, checked=s.checked or "", active=s.active)


@router.get("/news/sources", response_model=list[SourceOut], summary="수집 출처 목록")
def sources(admin: User = Depends(require_admin), session: Session = Depends(get_session)):
    return [source_out(s) for s in session.exec(select(NewsSource).order_by(NewsSource.id)).all()]


@router.put("/news/sources", response_model=list[SourceOut], summary="수집 출처 한 번에 저장 (목록에 없는 출처는 지워요)")
def sources_save(body: list[SourceIn], admin: User = Depends(require_admin), session: Session = Depends(get_session)):
    names = [s.name for s in body]
    if len(set(names)) != len(names):
        dup = next(n for n in names if names.count(n) > 1)
        raise HTTPException(422, f"‘{dup}’ 출처가 두 번 있어요. 이름을 서로 다르게 적어 주세요.")
    old = {s.id: s for s in session.exec(select(NewsSource)).all()}
    by_name = {s.name: s for s in old.values()}
    before = [source_out(s).model_dump() for s in old.values()]
    kept: set[int] = set()
    for item in body:
        row = old.get(item.id) if item.id is not None else None  # id가 있으면 그 출처, 없으면 같은 이름의 출처를 고쳐요
        if row is None or row.id in kept:
            same = by_name.get(item.name)
            row = same if same is not None and same.id not in kept else None
        if row is None:
            row = NewsSource(name=item.name, url=item.url)
        row.name, row.url, row.active = item.name, item.url, item.active
        row.checked = item.checked.isoformat() if item.checked else ""
        session.add(row)
        session.flush()
        kept.add(row.id)
    for sid, row in old.items():
        if sid not in kept:
            session.delete(row)
    after = [{"name": s.name, "url": s.url, "checked": s.checked.isoformat() if s.checked else "", "active": s.active}
             for s in body]
    _log(session, admin, "수집 출처 저장", f"{len(body)}곳", before=before, after=after)
    _commit(session, "수집 출처를 저장")
    return [source_out(s) for s in session.exec(select(NewsSource).order_by(NewsSource.id)).all()]


# ---------- 수집 기록 · 다시 수집 ----------
def _collect_in_background(actor: str) -> dict:
    """요청 세션과 분리해 수집하고 결과를 저장한다."""
    with Session(engine) as session:
        try:
            with news_collector.collection_lock(session):
                out = news_collector.collect(session, max_items=news_collector.MAX_ITEMS)
                session.add(AdminLog(screen=SCREEN, actor=actor, action="지금 수집", target="사용 중인 출처 모두",
                                     after=json.dumps({"ok": out["ok"], "fail": out["fail"], "failed": out["failed"]},
                                                      ensure_ascii=False, default=str)[:1000]))
                session.commit()
            if out["ok"]:
                forget_top()
            return {"state": "done", "ok": out["ok"], "fail": out["fail"], "run_id": out["run"].id}
        except Exception:
            session.rollback()
            print("[전체 뉴스 수집 오류] 저장하지 못했습니다.", flush=True)
            return {"state": "error", "message": "수집 결과를 저장하지 못했어요. 서버 로그를 확인해 주세요."}


@router.post("/news/collect/start", summary="전체 출처 수집을 백그라운드에서 시작")
def collect_start(admin: User = Depends(require_admin)):
    global _collect_future
    with _collect_lock:
        if _collect_future is not None and not _collect_future.done():
            return {"state": "running", "started": False}
        _collect_future = _collect_pool.submit(_collect_in_background, admin.nickname)
    return {"state": "running", "started": True}


@router.get("/news/collect/status", summary="전체 출처 수집 진행 상태")
def collect_status(admin: User = Depends(require_admin)):
    with _collect_lock:
        future = _collect_future
    if future is None:
        return {"state": "idle"}
    if not future.done():
        return {"state": "running"}
    return future.result()


@router.get("/news/runs", response_model=list[RunOut], summary="수집 기록 (최신순)")
def runs(admin: User = Depends(require_admin), session: Session = Depends(get_session)):
    rows = sorted(session.exec(select(NewsRun)).all(), key=lambda r: (r.date, r.id or 0), reverse=True)
    return [news_collector.run_out(r) for r in rows]


@router.post("/news/collect", response_model=CollectOut, summary="지금 수집하기 (출처 이름을 주면 그 출처만 다시)")
def collect(body: CollectIn | None = None, admin: User = Depends(require_admin), session: Session = Depends(get_session)):
    names = body.source_names if body else None
    if names is not None and not [n for n in names if n.strip()]:
        raise HTTPException(422, "다시 모을 출처를 골라 주세요.")
    try:
        with news_collector.collection_lock(session):
            out = news_collector.collect(session, names, max_items=5 if names else news_collector.MAX_ITEMS)
            target = ", ".join(names) if names else "사용 중인 출처 모두"
            _log(session, admin, "다시 수집" if names else "지금 수집", target,
                 after={"ok": out["ok"], "fail": out["fail"], "failed": out["failed"]})
            _commit(session, "수집 결과를 저장")
    except Exception as e:  # collect는 출처별로 실패를 기록하지만, DB 문제 같은 것은 여기서 막아요
        session.rollback()
        print(f"[수집 오류] {e}", flush=True)
        raise HTTPException(500, "수집하지 못했어요. 이전 소식은 그대로예요. 잠시 뒤 다시 시도해 주세요.")
    if out["ok"]:
        forget_top()
    session.refresh(out["run"])
    return CollectOut(ok=out["ok"], fail=out["fail"], failed=[FailedSource(**f) for f in out["failed"]],
                      added=out["added"], run=news_collector.run_out(out["run"]))
