"""게시판 관리 API (A-02, 차유진 담당). 관리자만 써요.

코드를 고치지 않고 게시판을 만들고, 게시판마다 사용자 정의 항목을 붙여요.
바꾼 내용은 모두 AdminLog(screen="게시판 관리")에 남아요 → GET /admin/boards/logs
게시판 목록은 GET /boards?all=true 를 그대로 써요.
"""
from __future__ import annotations

import copy

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import Session, select

from backend.core.convert import board_out
from backend.core.security import require_admin
from backend.core.timefmt import as_kst
from backend.db import get_session
from backend.models import AdminLog, Board, Post, User
from backend.routers.community import KoRoute, fail
from backend.schemas.common import BoardOut, OkOut
from backend.schemas.community import (DEFAULT_PERM, DEFAULT_RULES, LAYOUTS, LOG_ATTRS, SYSTEM_BOARDS,
                                       AdminLogOut, BoardIn, BoardPatch, BoardUsage, FieldDef, FieldPatch,
                                       FieldSaveOut, OrderIn, board_summary, field_brief, is_empty, normalize_field,
                                       type_change_impact, validate_definition)

router = APIRouter(prefix="/admin/boards", tags=["게시판 관리"], route_class=KoRoute)
SCREEN = "게시판 관리"


# ---------- 도우미 ----------
def log(session: Session, who: User, target: str, action: str, before: str = "—", after: str = "—") -> None:
    session.add(AdminLog(screen=SCREEN, actor=who.nickname, action=action, target=target,
                         before=before or "—", after=after or "—"))


def save(session: Session, what: str) -> None:
    try:
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"[게시판 관리 오류] {what}: {e}", flush=True)
        raise HTTPException(500, f"{what}하지 못했어요. 입력한 내용은 그대로 있어요. 잠시 뒤 다시 시도해 주세요.")


def get_board(board_id: str, session: Session) -> Board:
    b = session.get(Board, board_id)
    if not b:
        raise HTTPException(404, "게시판을 찾지 못했어요. 화면을 새로 고친 뒤 다시 골라 주세요.")
    return b


def as_dict(b: Board) -> dict:
    return copy.deepcopy(b.model_dump())


def period_text(v) -> str:
    return f"{v[0].isoformat()} ~ {v[1].isoformat()}" if v else ""


def post_rows(board_id: str, session: Session) -> list[Post]:
    return list(session.exec(select(Post).where(Post.board_id == board_id, Post.deleted == False)).all())  # noqa: E712


def used_count(rows: list[Post], key: str) -> int:
    return sum(1 for p in rows if not is_empty((p.extra or {}).get(key)))


def set_fields(b: Board, fields: list[dict]) -> None:
    b.fields = fields
    flag_modified(b, "fields")


def renumber(session: Session, ordered: list[Board]) -> None:
    for n, x in enumerate(ordered, 1):
        x.order = n
        session.add(x)


# ---------- 조회 ----------
@router.get("/stats", response_model=dict[str, BoardUsage], summary="게시판별 글 수와 항목별 사용 글 수")
def stats(_: User = Depends(require_admin), session: Session = Depends(get_session)):
    rows = list(session.exec(select(Post).where(Post.deleted == False)).all())  # noqa: E712
    out = {}
    for b in session.exec(select(Board)).all():
        mine = [p for p in rows if p.board_id == b.id]
        out[b.id] = BoardUsage(posts=len(mine), fields={f["key"]: used_count(mine, f["key"]) for f in (b.fields or [])})
    return out


@router.get("/logs", response_model=list[AdminLogOut], summary="게시판 관리 변경 기록 (최근 순)")
def logs(limit: int = 50, _: User = Depends(require_admin), session: Session = Depends(get_session)):
    rows = session.exec(select(AdminLog).where(AdminLog.screen == SCREEN)).all()
    rows = sorted(rows, key=lambda r: (as_kst(r.created_at), r.id or 0), reverse=True)[: max(1, min(limit, 200))]
    return [AdminLogOut(when=as_kst(r.created_at).strftime("%Y-%m-%d %H:%M"), who=r.actor, target=r.target,
                        action=r.action, before=r.before or "—", after=r.after or "—") for r in rows]


# ---------- 게시판 만들기 · 고치기 · 순서 · 지우기 ----------
@router.post("", response_model=BoardOut, summary="새 게시판 만들기")
def board_create(body: BoardIn, admin: User = Depends(require_admin), session: Session = Depends(get_session)):
    errs = {}
    if session.get(Board, body.id):
        errs["id"] = "이미 쓰고 있는 주소예요. 다른 주소를 적어 주세요."
    if session.exec(select(Board).where(Board.name == body.name)).first():
        errs["name"] = "같은 이름의 게시판이 있어요. 다른 이름을 적어 주세요."
    if errs:
        fail(errs, 409)
    n = len(session.exec(select(Board)).all())
    b = Board(id=body.id, name=body.name, type=body.type, layout=body.layout, status=body.status, order=n + 1,
              system=False, desc=body.desc, manager=body.manager or admin.nickname, period=period_text(body.period),
              page_size=body.page_size, sort=body.sort, search_fields=list(body.search_fields),
              pin_notice=body.pin_notice, perm=body.perm.model_dump(), rules=body.rules.model_dump(), fields=[])
    session.add(b)
    log(session, admin, b.name, "게시판 만들기", "—", f"{b.type} · {LAYOUTS[b.layout]} · {b.status}")
    save(session, "게시판을 만들")
    session.refresh(b)
    return board_out(b)


@router.put("/order", response_model=list[BoardOut], summary="게시판 순서 (+ 상태) 한 번에 저장")
def board_order(body: OrderIn, admin: User = Depends(require_admin), session: Session = Depends(get_session)):
    rows = {b.id: b for b in session.exec(select(Board)).all()}
    if sorted(body.ids) != sorted(rows) or len(set(body.ids)) != len(body.ids):
        raise HTTPException(409, "게시판 목록이 그사이 바뀌었어요. 화면을 새로 고친 뒤 다시 저장해 주세요.")
    unknown = [k for k in body.status if k not in rows]
    if unknown:
        raise HTTPException(409, "게시판 목록이 그사이 바뀌었어요. 화면을 새로 고친 뒤 다시 저장해 주세요.")
    for bid, st in body.status.items():
        b = rows[bid]
        if st != b.status:
            log(session, admin, b.name, "상태 바꾸기", b.status, st)
            b.status = st
            session.add(b)
    for n, bid in enumerate(body.ids, 1):
        b = rows[bid]
        if b.order != n:
            log(session, admin, b.name, "순서 바꾸기", f"{b.order}번째", f"{n}번째")
            b.order = n
            session.add(b)
    save(session, "순서와 상태를 저장")
    return [board_out(b) for b in sorted(session.exec(select(Board)).all(), key=lambda x: x.order)]


@router.patch("/{board_id}", response_model=BoardOut, summary="게시판 설정 고치기 (보낸 칸만)")
def board_update(board_id: str, body: BoardPatch, admin: User = Depends(require_admin),
                 session: Session = Depends(get_session)):
    b = get_board(board_id, session)
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"] != b.name and session.exec(select(Board).where(Board.name == data["name"])).first():
        fail({"name": "같은 이름의 게시판이 있어요. 다른 이름을 적어 주세요."}, 409)
    if "period" in data:
        data["period"] = period_text(body.period)
    if "manager" in data and not data["manager"]:
        data["manager"] = admin.nickname
    for k in ("perm", "rules"):
        if k in data and data[k] is not None:
            data[k] = {**(DEFAULT_PERM if k == "perm" else DEFAULT_RULES), **data[k]}
    data = {k: v for k, v in data.items() if v is not None}
    before = as_dict(b)
    after = {**before, **data}
    changed = [a for a in LOG_ATTRS if board_summary(before, a) != board_summary(after, a)]
    if not changed:
        return board_out(b)
    for a in changed:
        log(session, admin, after["name"], f"{LOG_ATTRS[a]} 바꾸기", board_summary(before, a), board_summary(after, a))
        setattr(b, a, data[a])
        if a in ("perm", "rules", "search_fields"):
            flag_modified(b, a)
    session.add(b)
    save(session, "설정을 저장")
    session.refresh(b)
    return board_out(b)


@router.delete("/{board_id}", response_model=OkOut, summary="게시판 지우기 (기본 게시판 · 글이 있는 게시판은 못 지워요)")
def board_delete(board_id: str, admin: User = Depends(require_admin), session: Session = Depends(get_session)):
    b = get_board(board_id, session)
    if b.system or b.id in SYSTEM_BOARDS:
        raise HTTPException(409, "관찰 이야기 · 공지사항은 기본 게시판이라 지울 수 없어요. 잠시 쉬려면 상태를 ‘일시 중지’로 바꿔 주세요.")
    live = len(post_rows(b.id, session))
    if live:
        raise HTTPException(409, f"글이 {live}개 있어서 지울 수 없어요. 글을 지키면서 닫으려면 상태를 ‘보관’으로 바꿔 주세요.")
    if session.exec(select(Post).where(Post.board_id == b.id)).first():
        raise HTTPException(409, "지운 글의 기록(신고 · 댓글)이 남아 있어서 지울 수 없어요. 상태를 ‘보관’으로 바꿔 주세요.")
    name, status = b.name, b.status
    session.delete(b)
    session.flush()
    renumber(session, sorted(session.exec(select(Board)).all(), key=lambda x: x.order))
    log(session, admin, name, "게시판 지우기", status, "지움")
    save(session, "게시판을 지우")
    return OkOut(message=f"‘{name}’ 게시판을 지웠어요")


# ---------- 사용자 정의 항목 ----------
def _no_obs(b: Board) -> None:
    if b.id == "obs":
        raise HTTPException(409, "관찰 이야기에는 사용자 정의 항목을 붙이지 않아요. 생물 알아보기에서 공유하면 글이 자동으로 만들어져서 "
                                 "추가 항목을 채울 화면이 없기 때문이에요.")


def _find(b: Board, key: str) -> int:
    idx = next((i for i, f in enumerate(b.fields or []) if f.get("key") == key), None)
    if idx is None:
        raise HTTPException(404, "항목을 찾지 못했어요. 화면을 새로 고친 뒤 다시 골라 주세요.")
    return idx


@router.post("/{board_id}/fields", response_model=FieldSaveOut, summary="항목 추가")
def field_add(board_id: str, body: FieldDef, admin: User = Depends(require_admin), session: Session = Depends(get_session)):
    b = get_board(board_id, session)
    _no_obs(b)
    f = body.stored()
    fl = copy.deepcopy(b.fields or [])
    if errs := validate_definition(f, fl):
        fail(errs)
    pos = min(max((body.order or len(fl) + 1) - 1, 0), len(fl))
    fl.insert(pos, f)
    set_fields(b, fl)
    session.add(b)
    log(session, admin, b.name, "항목 추가", "—", field_brief(f))
    save(session, "항목을 저장")
    session.refresh(b)
    return FieldSaveOut(board=board_out(b))


@router.patch("/{board_id}/fields/{key}", response_model=FieldSaveOut,
              summary="항목 고치기 · 사용 안 함/다시 사용(active) · 순서(order). 글에 쓰인 항목은 지우지 않고 사용 안 함으로")
def field_update(board_id: str, key: str, body: FieldPatch, admin: User = Depends(require_admin),
                 session: Session = Depends(get_session)):
    b = get_board(board_id, session)
    _no_obs(b)
    fl = copy.deepcopy(b.fields or [])
    idx = _find(b, key)
    old = fl[idx]
    patch = body.model_dump(exclude_unset=True)
    pos = (patch.pop("order") - 1) if patch.get("order") else idx
    for a in ("min", "max"):
        if a in patch and hasattr(patch[a], "isoformat"):
            patch[a] = patch[a].isoformat()
    new = normalize_field({**old, **patch}) if patch else dict(old)
    used = used_count(post_rows(b.id, session), key)
    others = [x for j, x in enumerate(fl) if j != idx]
    errs = validate_definition(new, others)
    if used and new["key"] != old["key"]:
        errs["key"] = "글에 쓰인 항목이라 고유 키를 바꿀 수 없어요."
    if errs:
        fail(errs)
    fl.pop(idx)
    pos = min(max(pos, 0), len(fl))
    fl.insert(pos, new)
    impact = type_change_impact(old, new, used)
    only_active = set(patch) <= {"active"} and pos == idx
    only_order = not patch and pos != idx
    if only_active and new.get("active", True) != old.get("active", True):
        on = new.get("active", True)
        log(session, admin, b.name, "항목 다시 사용" if on else "항목 사용 안 함",
            new["label"] + (" · 사용 안 함" if on else " · 사용 중"), new["label"] + (" · 사용 중" if on else " · 사용 안 함"))
    elif only_order:
        log(session, admin, b.name, "항목 순서 바꾸기", f"{new['label']} {idx + 1}번째", f"{new['label']} {pos + 1}번째")
    elif old["key"] != new["key"] or field_brief(old) != field_brief(new) or pos != idx or old.get("help") != new.get("help") \
            or old.get("active", True) != new.get("active", True):
        log(session, admin, b.name, "항목 고치기", f"{idx + 1}. {field_brief(old)} · 키 {old['key']}",
            f"{pos + 1}. {field_brief(new)} · 키 {new['key']}")
    else:
        return FieldSaveOut(board=board_out(b), impact=None)
    set_fields(b, fl)
    session.add(b)
    save(session, "항목을 저장")
    session.refresh(b)
    return FieldSaveOut(board=board_out(b), impact=impact)


@router.delete("/{board_id}/fields/{key}", response_model=FieldSaveOut,
               summary="항목 지우기 (아직 어떤 글에도 쓰이지 않은 항목만)")
def field_delete(board_id: str, key: str, admin: User = Depends(require_admin), session: Session = Depends(get_session)):
    b = get_board(board_id, session)
    fl = copy.deepcopy(b.fields or [])
    idx = _find(b, key)
    used = used_count(post_rows(b.id, session), key)
    if used:
        raise HTTPException(409, f"글 {used}개에서 쓰고 있는 항목이라 지울 수 없어요. ‘사용 안 함’으로 바꿔 주세요. 이미 쓴 글의 값은 그대로 보여요.")
    f = fl.pop(idx)
    set_fields(b, fl)
    session.add(b)
    log(session, admin, b.name, "항목 지우기", field_brief(f), "—")
    save(session, "항목을 지우")
    session.refresh(b)
    return FieldSaveOut(board=board_out(b))

