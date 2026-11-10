"""관리자 운영 API (이종민 담당): 대시보드 · 게시물·신고 · 회원 · 운영 설정 · 조치 기록.

모든 API는 관리자만 (require_admin). 관리자가 무언가를 바꾸면 같은 저장(commit) 안에서 AdminLog 한 줄을 남겨요
(어느 화면 · 누가 · 무엇을 · 대상 · 전 → 후 · 왜). 기록은 지우는 API가 없어요.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from backend import auth_provider as ap
from backend.core import mail, redis_store
from backend.core.convert import post_out
from backend.core.security import require_admin
from backend.core.timefmt import KST, ago, as_kst, now, today
from backend.db import get_session
from backend.models import AdminLog, Board, Comment, Inquiry, Observation, Post, Report, Setting, User
from backend.schemas.admin import (ActionIn, AdminPostList, AdminPostOut, DashboardOut, DayCount, InquiryTodo,
                                   LogOut, MemberOut, Metric, ReasonCount, ReportGroupOut, ResolveIn,
                                   SettingsFull, SettingsIn, SettingsSaveOut, SuspendIn, SuspendInfo)
from backend.schemas.common import OkOut

router = APIRouter(prefix="/admin", tags=["관리자 운영"])

SCREEN_POSTS, SCREEN_REPORTS, SCREEN_MEMBERS, SCREEN_SETTINGS = "게시물", "신고", "회원", "운영 설정"
DEFAULTS = {"limit_member": 20, "limit_guest": 3, "max_mb": 10, "formats": ["jpg", "jpeg", "png"], "report_hide": 5,
            "banned": [], "default_region": "jeju"}
FOREVER = datetime(9999, 12, 31, 23, 59, tzinfo=KST)


# ---------- 공통 ----------
def _log(session: Session, me: User, screen: str, action: str, target: str = "", before: str = "", after: str = "",
         reason: str = "") -> None:
    session.add(AdminLog(screen=screen, actor=me.nickname, action=action, target=target[:120], before=before[:500],
                         after=after[:500], reason=(reason or "-")[:300]))


def _commit(session: Session, what: str) -> None:
    try:
        session.commit()  # 바꾼 내용과 조치 기록을 한 번에 저장해요
    except Exception as e:
        session.rollback()
        print(f"[관리자 {what} 오류] {type(e).__name__}: {e}", flush=True)
        raise HTTPException(500, f"{what}하지 못했어요. 아무것도 바뀌지 않았어요. 잠시 뒤 다시 시도해 주세요.")


def log_out(row: AdminLog) -> LogOut:
    at = as_kst(row.created_at)
    return LogOut(id=row.id or 0, when=f"{at:%m-%d %H:%M}", at=at.isoformat(timespec="minutes"), screen=row.screen,
                  who=row.actor, what=row.action, target=row.target, before=row.before, after=row.after,
                  why=row.reason or "-")


def _logs(session: Session, screens: list[str] | None = None, limit: int = 100) -> list[LogOut]:
    stmt = select(AdminLog)
    if screens:
        stmt = stmt.where(AdminLog.screen.in_(screens))
    rows = session.exec(stmt).all()
    rows = sorted(rows, key=lambda r: (as_kst(r.created_at), r.id or 0), reverse=True)[:limit]
    return [log_out(r) for r in rows]


def _settings(session: Session) -> dict:
    row = session.get(Setting, 1)
    return {**DEFAULTS, **(dict(row.data) if row else {})}


def _nick(session: Session, user_id: str | None) -> str:
    u = session.get(User, user_id) if user_id else None
    return u.nickname if u else "알 수 없음"


def _post_or_404(session: Session, post_id: str) -> Post:
    p = session.get(Post, post_id)
    if not p or p.deleted:
        raise HTTPException(404, "글을 찾지 못했어요. 이미 지워졌을 수 있어요. 목록을 새로 고쳐 주세요.")
    return p


# ---------- 신고 묶음 ----------
def report_groups(session: Session, status: str | None = None) -> list[ReportGroupOut]:
    rows = session.exec(select(Report)).all()
    groups: dict[tuple[str, str], list[Report]] = {}
    for r in rows:
        if status and r.status != status:
            continue
        groups.setdefault((r.post_id, r.status), []).append(r)
    boards = {b.id: b.name for b in session.exec(select(Board)).all()}
    out = []
    for (pid, st), rs in groups.items():
        p = session.get(Post, pid)
        reasons = Counter(r.reason for r in rs).most_common()
        last = max(as_kst(r.created_at) for r in rs)
        out.append(ReportGroupOut(
            post=pid, title=p.title if p else "(지워진 글)", board=boards.get(p.board_id, p.board_id) if p else "",
            author=_nick(session, p.user_id) if p else "", body=(p.body or "")[:120] if p else "",
            species=p.species_id if p else None, created=ago(p.created_at) if p else "",
            hidden=bool(p and p.hidden), deleted=bool(not p or p.deleted), reason=reasons[0][0],
            reasons=[ReasonCount(reason=k, count=v) for k, v in reasons], count=len(rs), date=f"{last:%Y-%m-%d}",
            status=st))
    pending = sorted([g for g in out if g.status == "대기"], key=lambda g: (g.date, g.count), reverse=True)
    done = sorted([g for g in out if g.status != "대기"], key=lambda g: g.date, reverse=True)
    return pending + done


@router.get("/reports", response_model=list[ReportGroupOut], summary="신고 목록 (글마다 묶음 · 대기가 먼저)")
def reports(status: str | None = Query(None, description="대기 | 숨김 | 문제없음 | 삭제 (비우면 모두)"),
            me: User = Depends(require_admin), session: Session = Depends(get_session)):
    return report_groups(session, status)


@router.post("/reports/{post_id}/resolve", response_model=OkOut, summary="신고 처리: 숨기기 또는 문제없음")
def resolve_report(post_id: str, body: ResolveIn, me: User = Depends(require_admin),
                   session: Session = Depends(get_session)):
    pending = session.exec(select(Report).where(Report.post_id == post_id, Report.status == "대기")).all()
    if not pending:
        raise HTTPException(409, "처리할 신고가 없어요. 다른 관리자가 먼저 처리했을 수 있어요. 목록을 새로 고쳐 주세요.")
    p = session.get(Post, post_id)
    top = Counter(r.reason for r in pending).most_common(1)[0][0]
    title = p.title if p else post_id
    if not p or p.deleted:  # 이미 지워진 글: 기록만 정리해요
        for r in pending:
            r.status = "삭제"
        _log(session, me, SCREEN_REPORTS, "신고 정리", title, "대기", "삭제", body.reason or "이미 지워진 글")
        _commit(session, "신고를 정리")
        return OkOut(message="지워진 글의 신고를 정리했어요.")
    if body.action == "hide":
        for r in pending:
            r.status = "숨김"
        before = "숨김" if p.hidden else "공개"
        p.hidden = True
        _log(session, me, SCREEN_REPORTS, "숨기기", title, before, "숨김",
             f"신고 {len(pending)}건 · {top}" + (f" · {body.reason}" if body.reason else ""))
        _commit(session, "신고된 글을 숨기")
        return OkOut(message="신고된 글을 숨겼어요. 사용자에게는 보이지 않아요.")
    for r in pending:
        r.status = "문제없음"
    before = "숨김" if p.hidden else "공개"
    p.hidden = False  # 신고가 쌓여 자동으로 숨겨졌던 글이면 다시 보여요
    _log(session, me, SCREEN_REPORTS, "문제없음", title, before, "공개",
         f"신고({top}) {len(pending)}건 확인 결과 문제없음" + (f" · {body.reason}" if body.reason else ""))
    _commit(session, "신고를 처리")
    return OkOut(message="문제없음으로 처리했어요." + (" 숨겨졌던 글을 다시 보이게 했어요." if before == "숨김" else ""))


# ---------- 대시보드 ----------
def _usage_sum(day: str) -> int:
    total = 0
    for key in redis_store.r().scan_iter(f"usage:*:{day}", count=500):
        try:
            total += int(redis_store.r().get(key) or 0)
        except ValueError:
            pass
    return total


def _identify_trend(days: list) -> list[DayCount]:
    """오늘 횟수는 Redis usage:*:<오늘> 을 모두 더해요. 지난 날은 대시보드를 열 때 남겨 둔 값(stats:identify:<날짜>)."""
    out = []
    for d in days:
        key = f"{d:%Y%m%d}"
        live = _usage_sum(key)
        saved = int(redis_store.r().get(f"stats:identify:{key}") or 0)
        val = max(live, saved)
        if live > saved:
            redis_store.r().set(f"stats:identify:{key}", live, ex=400 * 86400)
        out.append(DayCount(date=f"{d:%Y-%m-%d}", value=val))
    return out


def _per_day(dates: list, days: list) -> list[DayCount]:
    c = Counter(dates)
    return [DayCount(date=f"{d:%Y-%m-%d}", value=c.get(d, 0)) for d in days]


def _metric(trend: list[DayCount], value: int | None = None) -> Metric:
    return Metric(today=trend[-1].value if value is None else value, yesterday=trend[-2].value, trend=trend)


@router.get("/dashboard", response_model=DashboardOut, summary="오늘 숫자 5개 · 오늘 할 일 · 최근 조치 기록")
def dashboard(me: User = Depends(require_admin), session: Session = Depends(get_session)):
    t = today()
    days = [t - timedelta(days=i) for i in range(6, -1, -1)]
    users = [u for u in session.exec(select(User)).all() if u.id != ap.WITHDRAWN_ID and u.email_verified]  # 인증까지 마친 가입만
    posts = session.exec(select(Post).where(Post.deleted == False)).all()  # noqa: E712
    reps = session.exec(select(Report)).all()
    inqs = session.exec(select(Inquiry)).all()
    pending_groups = report_groups(session, "대기")
    pending_inq = sorted([q for q in inqs if q.status != "완료"], key=lambda q: as_kst(q.created_at), reverse=True)
    rep_trend = _per_day([as_kst(r.created_at).date() for r in reps], days)
    inq_trend = _per_day([as_kst(q.created_at).date() for q in inqs], days)
    todos = []
    for q in pending_inq:
        who = _nick(session, q.user_id) if q.user_id else f"비회원 ({ap.mask_email(q.email) or '-'})"
        todos.append(InquiryTodo(id=q.id, type=q.type, title=q.title, status=q.status,
                                 date=f"{as_kst(q.created_at):%Y-%m-%d}", who=who))
    try:
        ident = _identify_trend(days)
    except Exception as e:  # Redis가 꺼져 있어도 나머지는 보여줘요
        print(f"[대시보드] 알아보기 횟수를 읽지 못했어요: {e}", flush=True)
        ident = [DayCount(date=f"{d:%Y-%m-%d}", value=0) for d in days]
    return DashboardOut(
        date=f"{t:%Y-%m-%d}",
        signups=_metric(_per_day([as_kst(u.created_at).date() for u in users], days)),
        identifies=_metric(ident),
        new_posts=_metric(_per_day([as_kst(p.created_at).date() for p in posts], days)),
        # 대기 중인 신고 · 문의: today=지금 대기 중, yesterday=어제 새로 들어온 수, trend=날마다 새로 들어온 수
        pending_reports=Metric(today=len(pending_groups), yesterday=rep_trend[-2].value, trend=rep_trend),
        pending_inquiries=Metric(today=len(pending_inq), yesterday=inq_trend[-2].value, trend=inq_trend),
        reports=pending_groups, inquiries=todos, logs=_logs(session, limit=5),
        report_hide=int(_settings(session).get("report_hide", 5)))


# ---------- 게시물 ----------
@router.get("/posts", response_model=AdminPostList, summary="게시물 목록 (숨긴 글 포함 · 검색 · 게시판 · 상태)")
def admin_posts(q: str = "", board: str = "", status: str = Query("all", description="all | public | hidden | reported"),
                me: User = Depends(require_admin), session: Session = Depends(get_session)):
    rows = session.exec(select(Post).where(Post.deleted == False)).all()  # noqa: E712
    reps = session.exec(select(Report)).all()
    total_rep = Counter(r.post_id for r in reps)
    pend_rep = Counter(r.post_id for r in reps if r.status == "대기")
    boards = {b.id: b.name for b in session.exec(select(Board)).all()}
    nicks = {u.id: u.nickname for u in session.exec(select(User)).all()}
    items = []
    for p in sorted(rows, key=lambda p: as_kst(p.created_at), reverse=True):
        author = nicks.get(p.user_id, "알 수 없음")
        if q and q not in p.title and q not in author:
            continue
        if board and board != "all" and p.board_id != board:
            continue
        if (status == "public" and p.hidden) or (status == "hidden" and not p.hidden) or \
                (status == "reported" and not total_rep.get(p.id)):
            continue
        o = post_out(p, session).model_dump()
        o["report_count"] = total_rep.get(p.id, 0)
        items.append(AdminPostOut(**o, author_nickname=author, board_name=boards.get(p.board_id, p.board_id),
                                  pending_reports=pend_rep.get(p.id, 0)))
    live = {p.id for p in rows}
    return AdminPostList(items=items, total=len(rows), hidden=sum(1 for p in rows if p.hidden),
                         reported=len(live & set(pend_rep)))


def _close_reports(session: Session, post_id: str, status: str) -> int:
    pending = session.exec(select(Report).where(Report.post_id == post_id, Report.status == "대기")).all()
    for r in pending:
        r.status = status
    return len(pending)


@router.post("/posts/{post_id}/hide", response_model=OkOut, summary="글 숨기기 (대기 중인 신고도 ‘숨김’으로 처리)")
def hide_post(post_id: str, body: ActionIn, me: User = Depends(require_admin), session: Session = Depends(get_session)):
    p = _post_or_404(session, post_id)
    if p.hidden:
        raise HTTPException(409, "이미 숨긴 글이에요. 목록을 새로 고쳐 주세요.")
    p.hidden = True
    n = _close_reports(session, p.id, "숨김")
    _log(session, me, SCREEN_POSTS, "숨기기", p.title, "공개", "숨김", body.reason + (f" · 대기 신고 {n}건 함께 처리" if n else ""))
    _commit(session, "글을 숨기")
    return OkOut(message="글을 숨겼어요. 사용자에게는 보이지 않아요.")


@router.post("/posts/{post_id}/restore", response_model=OkOut, summary="숨긴 글 다시 보이게")
def restore_post(post_id: str, body: ActionIn, me: User = Depends(require_admin),
                 session: Session = Depends(get_session)):
    p = _post_or_404(session, post_id)
    if not p.hidden:
        raise HTTPException(409, "이미 공개 중인 글이에요. 목록을 새로 고쳐 주세요.")
    p.hidden = False
    _log(session, me, SCREEN_POSTS, "복구", p.title, "숨김", "공개", body.reason)
    _commit(session, "글을 복구")
    return OkOut(message="글을 다시 보이게 했어요.")


@router.delete("/posts/{post_id}", response_model=OkOut, summary="글 지우기 (댓글 · 대기 중인 신고도 함께 정리)")
def delete_post(post_id: str, body: ActionIn | None = None, me: User = Depends(require_admin),
                session: Session = Depends(get_session)):
    p = _post_or_404(session, post_id)
    before = "숨김" if p.hidden else "공개"
    p.deleted, p.hidden = True, True  # 기록을 위해 행은 남기고, 어디에도 보이지 않게 해요
    for c in session.exec(select(Comment).where(Comment.post_id == p.id)).all():
        c.deleted = True
    n = _close_reports(session, p.id, "삭제")
    for o in session.exec(select(Observation).where(Observation.post_id == p.id)).all():
        o.post_id = None  # 수족관 기록은 남고 ‘공유’ 표시만 빠져요
    reason = (body.reason if body else "") or "-"
    _log(session, me, SCREEN_POSTS, "삭제", p.title, before, "삭제", reason + (f" · 대기 신고 {n}건 함께 정리" if n else ""))
    _commit(session, "글을 지우")
    return OkOut(message="글을 지웠어요.")


# ---------- 회원 ----------
def _until_label(u: User) -> str:
    end = as_kst(u.suspended_until)
    return "영구" if end.year >= 9000 else f"{end:%Y-%m-%d}까지"


def _is_suspended(u: User) -> bool:
    return bool(u.suspended_until and as_kst(u.suspended_until) > now())


def member_out(u: User, session: Session, posts: list[Post] | None = None, rep_by_post: Counter | None = None) -> MemberOut:
    if posts is None:
        posts = list(session.exec(select(Post).where(Post.user_id == u.id, Post.deleted == False)).all())  # noqa: E712
    if rep_by_post is None:
        rep_by_post = Counter(r.post_id for r in session.exec(select(Report)).all())
    posts = sorted(posts, key=lambda p: as_kst(p.created_at), reverse=True)
    sus = _is_suspended(u)
    return MemberOut(id=u.id, nickname=u.nickname, character=u.character, email=u.email,
                     joined=f"{as_kst(u.created_at):%Y-%m-%d}", posts=len(posts),
                     reports=sum(rep_by_post.get(p.id, 0) for p in posts),
                     role="관리자" if u.role == "admin" else "회원", role_key="admin" if u.role == "admin" else "user",
                     status=f"이용 정지 · {_until_label(u)}" if sus else "이용 중",
                     suspended=SuspendInfo(until=_until_label(u), reason=u.suspend_reason or "-") if sus else None,
                     public=u.aquarium_public, recent=[p.title for p in posts[:3]], provider=u.provider)


@router.get("/members", response_model=list[MemberOut], summary="회원 목록 (닉네임 · 이메일 검색 · 상태)")
def members(q: str = "", status: str = Query("all", description="all | active | suspended | reported"),
            me: User = Depends(require_admin), session: Session = Depends(get_session)):
    users = [u for u in session.exec(select(User)).all() if u.id != ap.WITHDRAWN_ID and u.email_verified]  # 인증까지 마친 가입만
    posts = session.exec(select(Post).where(Post.deleted == False)).all()  # noqa: E712
    by_user: dict[str, list[Post]] = {}
    for p in posts:
        by_user.setdefault(p.user_id, []).append(p)
    rep = Counter(r.post_id for r in session.exec(select(Report)).all())
    out = []
    for u in sorted(users, key=lambda u: as_kst(u.created_at)):
        m = member_out(u, session, by_user.get(u.id, []), rep)
        if q and q not in m.nickname and q.lower() not in m.email.lower():
            continue
        if (status == "active" and m.suspended) or (status == "suspended" and not m.suspended) or \
                (status == "reported" and not m.reports):
            continue
        out.append(m)
    return out


@router.get("/members/{user_id}", response_model=MemberOut, summary="회원 한 명")
def member_one(user_id: str, me: User = Depends(require_admin), session: Session = Depends(get_session)):
    u = session.get(User, user_id)
    if not u or u.id == ap.WITHDRAWN_ID:
        raise HTTPException(404, "회원을 찾지 못했어요. 탈퇴했을 수 있어요.")
    return member_out(u, session)


@router.post("/members/{user_id}/suspend", response_model=MemberOut, summary="이용 정지 (기간 · 사유)")
def suspend(user_id: str, body: SuspendIn, me: User = Depends(require_admin), session: Session = Depends(get_session)):
    u = session.get(User, user_id)
    if not u or u.id == ap.WITHDRAWN_ID:
        raise HTTPException(404, "회원을 찾지 못했어요. 탈퇴했을 수 있어요.")
    if u.id == me.id:
        raise HTTPException(400, "내 계정은 정지할 수 없어요.")
    if u.role == "admin":
        raise HTTPException(403, "관리자 계정은 정지할 수 없어요.")
    before = f"이용 정지 · {_until_label(u)}" if _is_suspended(u) else "이용 중"
    u.suspended_until = FOREVER if body.days is None else now() + timedelta(days=body.days)
    u.suspend_reason = body.reason + (f" · {body.memo.strip()}" if body.memo.strip() else "")
    period = "영구" if body.days is None else f"{body.days}일"
    _log(session, me, SCREEN_MEMBERS, f"이용 정지 {period}", u.nickname, before, f"이용 정지 · {_until_label(u)}",
         u.suspend_reason)
    _commit(session, "이용 정지를 저장")
    session.refresh(u)
    ap.end_sessions(u.id)  # 로그인돼 있던 기기는 바로 로그아웃돼요
    try:
        mail.send(u.email, "[Sea-Info Agent] 이용이 잠시 멈췄어요",
                  f"안녕하세요, {u.nickname}님. Sea-Info Agent예요.\n\n운영 정책에 따라 {_until_label(u)} 이용이 정지됐어요.\n"
                  f"사유: {u.suspend_reason}\n\n그동안 글 · 댓글 · 공유를 할 수 없어요. 궁금한 점은 사이트의 제보·건의로 알려 주세요.")
    except Exception as e:  # 알림 메일이 실패해도 정지는 그대로예요
        print(f"[정지 알림 메일 실패] {e}", flush=True)
    return member_out(u, session)


@router.post("/members/{user_id}/unsuspend", response_model=MemberOut, summary="이용 정지 풀기")
def unsuspend(user_id: str, body: ActionIn | None = None, me: User = Depends(require_admin),
              session: Session = Depends(get_session)):
    u = session.get(User, user_id)
    if not u or u.id == ap.WITHDRAWN_ID:
        raise HTTPException(404, "회원을 찾지 못했어요. 탈퇴했을 수 있어요.")
    if not _is_suspended(u):
        raise HTTPException(409, "이미 이용 중인 회원이에요. 목록을 새로 고쳐 주세요.")
    before = f"이용 정지 · {_until_label(u)}"
    u.suspended_until, u.suspend_reason = None, ""
    _log(session, me, SCREEN_MEMBERS, "정지 풀기", u.nickname, before, "이용 중", (body.reason if body else "") or "관리자가 해제")
    _commit(session, "정지 해제를 저장")
    session.refresh(u)
    return member_out(u, session)


# ---------- 운영 설정 ----------
FIELD_LABELS = {
    "limit_member": ("회원 하루 횟수", lambda v: f"{v}회"),
    "limit_guest": ("비회원 하루 횟수", lambda v: f"{v}회"),
    "formats": ("사진 형식", lambda v: ", ".join(x.upper() for x in v)),
    "max_mb": ("사진 최대 크기", lambda v: f"{v}MB"),
    "report_hide": ("신고 자동 숨김 기준", lambda v: f"{v}회"),
    "banned": ("금칙어", lambda v: ", ".join(v) or "(없음)"),
    "default_region": ("물때 기본 지역", str),
}


def _full(d: dict) -> SettingsFull:
    return SettingsFull(**{k: d.get(k, DEFAULTS[k]) for k in DEFAULTS},
                        extra={k: v for k, v in d.items() if k not in DEFAULTS})


def _region_names() -> dict[str, str]:
    try:
        from backend.routers.tide import _all as tide_regions

        return {k: v.get("name", k) for k, v in tide_regions().items()}
    except Exception:
        return {}


@router.get("/settings", response_model=SettingsFull, summary="운영 설정 전체 (금칙어 포함)")
def get_settings_full(me: User = Depends(require_admin), session: Session = Depends(get_session)):
    return _full(_settings(session))


@router.put("/settings", response_model=SettingsSaveOut, summary="운영 설정 저장 (바뀐 항목마다 변경 기록)")
def put_settings(body: SettingsIn, me: User = Depends(require_admin), session: Session = Depends(get_session)):
    if body.limit_guest > body.limit_member:
        raise ap.fail(400, "limit", "비회원 하루 횟수는 회원보다 많을 수 없어요. 숫자를 다시 정해 주세요.")
    if not body.formats:
        raise ap.fail(400, "formats", "사진 형식을 하나 이상 골라 주세요.")
    names = _region_names()
    if names and body.default_region not in names:
        raise ap.fail(400, "region", "물때 기본 지역을 목록에서 골라 주세요.")
    row = session.get(Setting, 1) or Setting(id=1, data={})
    old = {**DEFAULTS, **dict(row.data or {})}
    new = dict(old)
    changed = 0
    for k, v in body.model_dump().items():
        if old.get(k) != v:
            label, fmt = FIELD_LABELS[k]
            show = (lambda x: names.get(x, x)) if k == "default_region" else fmt
            _log(session, me, SCREEN_SETTINGS, "운영 설정 저장", label, show(old[k]) if old.get(k) is not None else "-", show(v))
            new[k] = v
            changed += 1
    if not changed:
        return SettingsSaveOut(settings=_full(old), changed=0, message="바뀐 내용이 없어요.")
    row.data = new  # 새 dict로 바꿔야 저장돼요 (JSON 칸)
    session.add(row)
    _commit(session, "운영 설정을 저장")
    return SettingsSaveOut(settings=_full(new), changed=changed, message=f"저장했어요. {changed}가지 설정이 바로 적용됐어요.")


# ---------- 조치 기록 ----------
@router.get("/logs", response_model=list[LogOut], summary="조치 기록 (screen=게시물,신고 처럼 쉼표로 여러 개)")
def logs(screen: str = "", limit: int = Query(100, ge=1, le=500), me: User = Depends(require_admin),
         session: Session = Depends(get_session)):
    screens = [s.strip() for s in screen.split(",") if s.strip()] or None
    return _logs(session, screens, limit)
