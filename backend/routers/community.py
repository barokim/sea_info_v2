"""커뮤니티 API (차유진 담당). 조회 API는 편성훈이 먼저 만들어 뒀어요(모양 그대로). 글쓰기 · 댓글 · 공감 · 신고는 여기서 해요.

검사는 모두 서버에서 해요: 게시판 상태 · 권한(모두/회원/관리자) · 금칙어 · 연속 글쓰기 간격(Redis) · 사용자 정의 항목(pydantic).
칸별 안내는 {"code": "invalid_fields", "message", "errors": {칸: 안내}} 모양으로 보내요 (backend/schemas/community.py).
"""
from __future__ import annotations

import pathlib

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import Session, func, select

from backend.config import get_settings
from backend.community_models import CommentReply
from backend.core import gemini, redis_store
from backend.core.convert import board_out, comment_out, post_out
from backend.core.security import optional_user, require_user
from backend.core.timefmt import as_kst, now
from backend.db import get_session, new_id
from backend.models import AdminLog, Board, Comment, Like, Observation, Post, Report, Species, User
from backend.routers.core import settings_data
from backend.schemas.common import BoardOut, OkOut, PostOut
from backend.schemas.community import (DEFAULT_PERM, DEFAULT_RULES, CommentIn, CommentView, LikedOut, LikeOut, PhotoOut, PostCreated,
                                       PostIn, PostPatch, PostText, PostView, ReportedOut, ReportIn, active,
                                       check_extra, field_detail, ko_errors)


class KoRoute(APIRoute):
    """입력 검사 오류(422)를 한국어 안내 + 칸별 안내(errors)로 바꿔요. 게시판 관리 라우터도 같이 써요."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                return await original(request)
            except RequestValidationError as e:
                return JSONResponse(status_code=422, content={"detail": field_detail(ko_errors(e.errors()))})

        return handler


router = APIRouter(tags=["커뮤니티"], route_class=KoRoute)
PHOTO_TTL = 3600  # 올린 사진을 글에 붙일 수 있는 시간(초)


# ---------- 도우미 ----------
def is_admin(u: User | None) -> bool:
    return bool(u and u.role == "admin")


def allowed(u: User | None, level: str) -> bool:
    if level == "모두":
        return True
    if level == "회원":
        return u is not None
    return is_admin(u)


def perm_of(b: Board, key: str) -> str:
    return (b.perm or {}).get(key, DEFAULT_PERM[key])


def rules_of(b: Board) -> dict:
    return {**DEFAULT_RULES, **(b.rules or {})}


def fail(errors: dict[str, str], status: int = 422):
    raise HTTPException(status, field_detail(errors))


def view(p: Post, session: Session) -> PostView:
    """화면에 보내는 글 모양 (PostOut + 고친 글 표시). '_'로 시작하는 값은 서버 전용이라 빼요."""
    o = post_out(p, session).model_dump()
    o["extra"] = {k: v for k, v in (o.get("extra") or {}).items() if not str(k).startswith("_")}
    u = session.get(User, p.user_id)
    return PostView(**o, edited=bool((p.extra or {}).get("_edited")), author_role=u.role if u else "user",
                    author_grade=u.grade if u else "")


def comment_view(c: Comment, session: Session, parent_id: str | None = None) -> CommentView:
    if c.deleted:
        # 답글이 남은 원댓글은 자리만 표시하고, 원문과 작성자 정보는 보내지 않아요.
        return CommentView(id=c.id, post=c.post_id, user="", author=None, body="", created="", created_at="", deleted=True)
    return CommentView(**comment_out(c, session).model_dump(),
                       created_at=as_kst(c.created_at).isoformat(timespec="minutes"), parent_id=parent_id)


def banned_in(session: Session, text: str) -> str | None:
    for w in settings_data(session).get("banned", []):
        if w and w in (text or ""):
            return w
    return None


def banned_errors(session: Session, texts: dict[str, str]) -> dict[str, str]:
    errs = {}
    for k, t in texts.items():
        if w := banned_in(session, t):
            errs[k] = f"‘{w}’ 같은 말은 쓸 수 없어요. 내용을 바꿔 주세요."
    return errs


def live_post(post_id: str, session: Session) -> Post:
    p = session.get(Post, post_id)
    if not p or p.deleted:
        raise HTTPException(404, "글을 찾지 못했어요. 지워졌거나 숨겨진 글일 수 있어요.")
    return p


def readable_post(post_id: str, viewer: User | None, session: Session) -> Post:
    """글 상세와 댓글 조회에 같은 읽기 권한을 적용해요."""
    p = live_post(post_id, session)
    mine = bool(viewer and viewer.id == p.user_id)
    if is_admin(viewer) or mine:
        return p
    b = session.get(Board, p.board_id)
    if p.hidden or not b or b.status != "운영 중":
        raise HTTPException(404, "글을 찾지 못했어요. 지워졌거나 숨겨진 글일 수 있어요.")
    level = perm_of(b, "read")
    if not allowed(viewer, level):
        msg = "이 게시판의 글은 로그인하면 읽을 수 있어요." if level == "회원" else "이 게시판의 글은 운영자만 읽을 수 있어요."
        raise HTTPException(403, {"code": "read_forbidden", "message": msg, "board": b.id, "level": level})
    return p


def visible_post(post_id: str, user: User | None, session: Session) -> tuple[Post, Board]:
    """공감 · 댓글 · 신고할 수 있는 글 (숨김 · 닫힌 게시판 글은 관리자만)."""
    p = live_post(post_id, session)
    b = session.get(Board, p.board_id)
    if not is_admin(user) and (p.hidden or not b or b.status != "운영 중"):
        raise HTTPException(404, "글을 찾지 못했어요. 지워졌거나 숨겨진 글일 수 있어요.")
    if not allowed(user, perm_of(b, "read")):
        raise HTTPException(403, "이 게시판의 글을 읽을 수 있는 사람만 할 수 있어요.")
    return p, b


def can_edit(p: Post, user: User) -> None:
    if p.user_id != user.id and not is_admin(user):
        raise HTTPException(403, "내가 쓴 글만 고치거나 지울 수 있어요.")


def take_photo(photo_id: str | None, user: User) -> str:
    """올려 둔 사진을 글에 붙여요. 본인이 1시간 안에 올린 사진만 돼요."""
    if not photo_id:
        return ""
    owner = redis_store.cache_get(f"postphoto:{photo_id}")
    path = pathlib.Path(get_settings().upload_dir) / f"{photo_id}.jpg"
    if owner != user.id or not path.exists():
        fail({"photo": "사진 보관 시간이 지났어요. 사진을 다시 골라 주세요."})
    return f"{photo_id}.jpg"


def drop_photo_file(path: str, session: Session, keep_post: str | None = None) -> None:
    """글에서 뺀 사진 파일을 지워요. 수족관 관찰 기록이 같은 사진을 쓰면 남겨요."""
    if not path:
        return
    if session.exec(select(Observation).where(Observation.photo_path == path)).first():
        return
    if session.exec(select(Post).where(Post.photo_path == path, Post.id != (keep_post or ""))).first():
        return
    try:
        (pathlib.Path(get_settings().upload_dir) / path).unlink(missing_ok=True)
    except OSError:
        pass


def admin_log(session: Session, actor: User, action: str, target: str, before: str = "", after: str = "") -> None:
    session.add(AdminLog(screen="게시물·신고", actor=actor.nickname, action=action, target=target,
                         before=before, after=after, reason="게시글 화면에서"))


# ---------- 조회 (편성훈이 만든 모양 그대로) ----------
@router.get("/boards", response_model=list[BoardOut], summary="게시판 목록 (all=true면 운영 중이 아닌 것도)")
def boards(all: bool = False, session: Session = Depends(get_session)):
    rows = sorted(session.exec(select(Board)).all(), key=lambda b: b.order)
    return [board_out(b) for b in rows if all or b.status == "운영 중"]


@router.get("/boards/{board_id}", response_model=BoardOut, summary="게시판 하나")
def board_one(board_id: str, session: Session = Depends(get_session)):
    b = session.get(Board, board_id)
    if not b:
        raise HTTPException(404, "게시판을 찾지 못했어요.")
    return board_out(b)


@router.get("/posts", response_model=list[PostView],
            summary="게시글 목록 (게시판 상태 · 목록/읽기 권한을 검사하고, board를 주면 검색 항목 · 공지 고정도 따라요)")
def posts(board: str | None = None, q: str = "", sort: str = "latest", user: str | None = None,
          include_hidden: bool = False, limit: int = Query(200, le=500), offset: int = 0,
          viewer: User | None = Depends(optional_user), session: Session = Depends(get_session)):
    b = session.get(Board, board) if board else None
    stmt = select(Post).where(Post.deleted == False)  # noqa: E712
    if board:
        stmt = stmt.where(Post.board_id == board)
    if not is_admin(viewer):
        # 목록 응답에 본문도 포함되므로, 게시판을 생략해도 목록/읽기 권한을 모두 검사해요.
        candidates = [b] if b else session.exec(select(Board)).all()
        readable_ids = [x.id for x in candidates if x.status == "운영 중"
                        and allowed(viewer, perm_of(x, "list")) and allowed(viewer, perm_of(x, "read"))]
        stmt = stmt.where(Post.board_id.in_(readable_ids))
    if user:
        stmt = stmt.where(Post.user_id == user)
    if not (include_hidden and is_admin(viewer)):
        stmt = stmt.where(Post.hidden == False)  # noqa: E712
    rows = list(session.exec(stmt).all())
    q = (q or "").strip()
    if q:
        names = {s.id: s.name for s in session.exec(select(Species)).all()}
        where = (b.search_fields or ["제목"]) if b else ["제목", "생물 이름"]
        nicks = {u.id: u.nickname for u in session.exec(select(User)).all()} if "닉네임" in where else {}

        def hit(p: Post) -> bool:
            parts = {"제목": p.title, "내용": p.body or "", "생물 이름": names.get(p.species_id or "", ""),
                     "닉네임": nicks.get(p.user_id, "")}
            return any(q in parts[w] for w in where if w in parts)
        rows = [p for p in rows if hit(p)]
    key = (lambda p: (-p.likes, -as_kst(p.created_at).timestamp())) if sort == "likes" else (lambda p: -as_kst(p.created_at).timestamp())
    rows.sort(key=key)
    if not b or b.pin_notice:
        rows.sort(key=lambda p: not p.pinned)
    return [view(p, session) for p in rows[offset: offset + limit]]


@router.get("/posts/recent", response_model=list[PostOut], summary="최근 관찰 이야기 (홈)")
def recent(n: int = 6, session: Session = Depends(get_session)):
    stmt = select(Post).where(Post.board_id == "obs", Post.hidden == False, Post.deleted == False)  # noqa: E712
    rows = sorted(session.exec(stmt).all(), key=lambda p: as_kst(p.created_at), reverse=True)[:n]
    return [post_out(p, session) for p in rows]


@router.get("/posts/{post_id}", response_model=PostView,
            summary="게시글 하나 (닫힌 게시판 · 읽기 권한은 관리자 · 글쓴이 말고는 막아요)")
def post_one(post_id: str, viewer: User | None = Depends(optional_user), session: Session = Depends(get_session)):
    return view(readable_post(post_id, viewer, session), session)


@router.get("/posts/{post_id}/comments", response_model=list[CommentView], summary="댓글 목록 (부모 글의 읽기 권한을 따라요)")
def comments(post_id: str, viewer: User | None = Depends(optional_user), session: Session = Depends(get_session)):
    readable_post(post_id, viewer, session)
    rows = sorted(session.exec(select(Comment).where(Comment.post_id == post_id)).all(),
                  key=lambda c: (as_kst(c.created_at), c.id))
    if not rows:
        return []
    parents = {link.comment_id: link.parent_id for link in session.exec(
        select(CommentReply).where(CommentReply.comment_id.in_([c.id for c in rows]))).all()}
    replies: dict[str, list[Comment]] = {}
    for c in rows:
        if not c.deleted and c.id in parents:
            replies.setdefault(parents[c.id], []).append(c)
    out = []
    for c in rows:
        if c.id in parents or (c.deleted and c.id not in replies):
            continue
        out.append(comment_view(c, session))
        out.extend(comment_view(reply, session, c.id) for reply in replies.get(c.id, []))
    return out


# ---------- 사진 ----------
@router.post("/posts/photos", response_model=PhotoOut, summary="글에 붙일 사진 올리기 (1시간 안에 글에 붙여요)")
async def photo_upload(file: UploadFile = File(...), user: User = Depends(require_user),
                       session: Session = Depends(get_session)):
    s = get_settings()
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    formats = settings_data(session).get("formats", ["jpg", "jpeg", "png"])
    if ext not in formats:
        fail({"photo": f"{' · '.join(f.upper() for f in formats)} 사진만 올릴 수 있어요."}, 415)
    data = await file.read()
    max_mb = int(settings_data(session).get("max_mb", s.max_upload_mb))
    if len(data) > max_mb * 1024 * 1024:
        fail({"photo": f"사진이 너무 커요. {max_mb}MB보다 작은 사진을 골라 주세요."}, 413)
    try:
        small = gemini.shrink(data)  # 다시 저장하면서 위치 같은 사진 정보(EXIF)도 지워져요
    except Exception:
        fail({"photo": "사진을 열 수 없어요. 다른 사진을 골라 주세요."}, 415)
    pid = new_id("pp_", 10)
    up = pathlib.Path(s.upload_dir)
    up.mkdir(parents=True, exist_ok=True)
    (up / f"{pid}.jpg").write_bytes(small)
    redis_store.cache_set(f"postphoto:{pid}", user.id, ttl=PHOTO_TTL)
    return PhotoOut(id=pid)


# ---------- 글쓰기 · 고치기 · 지우기 ----------
def check_text_and_extra(b: Board, title: str, body: str, extra: dict, session: Session) -> tuple[PostText | None, dict, dict]:
    """제목 · 내용 · 추가 항목을 한 번에 검사해서 안내를 모두 모아요."""
    errs: dict[str, str] = {}
    text = None
    try:
        text = PostText(title=title, body=body)
    except ValidationError as e:
        errs.update(ko_errors(e.errors(), request=False))
    clean, extra_errs = check_extra(b.fields, extra)
    errs.update(extra_errs)
    texts = {"title": title, "body": body}
    texts.update({f"extra.{f['key']}": clean.get(f["key"], "") for f in active(b.fields) if f.get("type") in ("short", "long")})
    for k, msg in banned_errors(session, texts).items():
        errs.setdefault(k, msg)
    return text, clean, errs


@router.post("/posts", response_model=PostCreated, summary="글쓰기 (관찰 이야기는 생물 알아보기의 공유로만)")
def post_create(body: PostIn, user: User = Depends(require_user), session: Session = Depends(get_session)):
    b = session.get(Board, body.board)
    if not b:
        fail({"board": "게시판을 찾지 못했어요. 다른 게시판을 골라 주세요."}, 404)
    if b.id == "obs":
        fail({"board": "관찰 이야기는 ‘생물 알아보기’에서 수족관에 담으면서 공유해요. 다른 게시판을 골라 주세요."}, 409)
    if b.status != "운영 중":
        fail({"board": f"‘{b.name}’ 게시판은 지금 글을 받지 않아요. 다른 게시판을 골라 주세요."}, 409)
    level = "관리자" if b.id == "notice" else perm_of(b, "write")
    if not allowed(user, level):
        raise HTTPException(403, f"{b.name}에는 운영자만 글을 쓸 수 있어요.")
    text, extra, errs = check_text_and_extra(b, body.title, body.body, body.extra, session)
    if body.photo_id and not allowed(user, perm_of(b, "photo")):
        errs["photo"] = f"{b.name}에는 사진을 올릴 수 없어요. 사진을 빼고 올려 주세요."
    elif body.photo_id and not body.photo_consent:
        errs["photo"] = "사진을 올리려면 바로 위 동의에 체크해 주세요."
    if body.species and not session.get(Species, body.species):
        errs["species"] = "생물 정보를 찾지 못했어요. 다시 골라 주세요."
    if errs:
        fail(errs)
    photo = take_photo(body.photo_id, user)
    interval = int(rules_of(b).get("interval") or 0)
    gap_key = f"post:{user.id}"
    if not redis_store.gap_ok(gap_key, interval):
        left = max(redis_store.r().ttl(f"gap:{gap_key}"), 1)
        raise HTTPException(429, {"code": "too_fast", "message": f"조금 전에 글을 올렸어요. {left}초 뒤에 다시 올려 주세요.",
                                  "wait": left})
    pid = new_id("p")
    try:
        session.add(Post(id=pid, board_id=b.id, user_id=user.id, title=text.title, body=text.body, extra=extra,
                         species_id=body.species or None, place=body.place.strip(),
                         place_level=body.place_level if body.place.strip() else "none", photo_path=photo))
        session.commit()
    except Exception as e:
        session.rollback()
        redis_store.r().delete(f"gap:{gap_key}")  # 저장하지 못했으면 간격도 세지 않아요
        print(f"[글쓰기 오류] {e}", flush=True)
        raise HTTPException(500, "글을 올리지 못했어요. 입력한 내용은 그대로 있어요. 다시 시도해 주세요.")
    return PostCreated(id=pid)


@router.patch("/posts/{post_id}", response_model=PostView, summary="글 고치기 (글쓴이 · 관리자)")
def post_update(post_id: str, body: PostPatch, user: User = Depends(require_user), session: Session = Depends(get_session)):
    p = live_post(post_id, session)
    can_edit(p, user)
    b = session.get(Board, p.board_id)
    if not is_admin(user) and (not b or b.status != "운영 중"):
        raise HTTPException(409, "지금은 이 게시판의 글을 고칠 수 없어요. 게시판이 다시 열리면 고쳐 주세요.")
    old_extra = {k: v for k, v in (p.extra or {}).items() if not str(k).startswith("_")}
    live = {f["key"] for f in active(b.fields)}
    sent = body.extra if body.extra is not None else {k: v for k, v in old_extra.items() if k in live}
    text, clean, errs = check_text_and_extra(b, p.title if body.title is None else body.title,
                                             p.body if body.body is None else body.body, sent, session)
    if body.photo_id and not allowed(user, perm_of(b, "photo")):
        errs["photo"] = f"{b.name}에는 사진을 올릴 수 없어요. 사진을 빼고 저장해 주세요."
    elif body.photo_id and not body.photo_consent:
        errs["photo"] = "사진을 올리려면 바로 위 동의에 체크해 주세요."
    if errs:
        fail(errs)
    photo = take_photo(body.photo_id, user) if body.photo_id else None
    old_photo = p.photo_path
    keep = {k: v for k, v in old_extra.items() if k not in live}  # ‘사용 안 함’ 항목 값은 그대로
    try:
        p.title, p.body = text.title, text.body
        p.extra = {**keep, **clean, "_edited": now().isoformat(timespec="minutes")}
        flag_modified(p, "extra")
        if photo:
            p.photo_path = photo
        if user.id != p.user_id:
            admin_log(session, user, "글 고치기", p.title)
        session.add(p)
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"[글 고치기 오류] {e}", flush=True)
        raise HTTPException(500, "고친 내용을 저장하지 못했어요. 입력한 내용은 그대로 있어요. 다시 시도해 주세요.")
    if photo and old_photo and old_photo != photo:
        drop_photo_file(old_photo, session, keep_post=p.id)
    session.refresh(p)
    return view(p, session)


@router.delete("/posts/{post_id}", response_model=OkOut,
               summary="글 지우기 (글쓴이 · 관리자). 관찰 이야기 글이면 관찰 기록은 남기고 ‘나만 보기’로")
def post_delete(post_id: str, user: User = Depends(require_user), session: Session = Depends(get_session)):
    p = live_post(post_id, session)
    can_edit(p, user)
    photo = p.photo_path
    kept = 0
    try:
        p.deleted = True
        for o in session.exec(select(Observation).where(Observation.post_id == p.id)).all():
            o.post_id = None  # 수족관 관찰 기록은 그대로, 공유만 끝나요 (나만 보기)
            session.add(o)
            kept += 1
        if photo and not kept:
            p.photo_path = ""
        if user.id != p.user_id:
            admin_log(session, user, "글 지우기", p.title)
        session.add(p)
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"[글 지우기 오류] {e}", flush=True)
        raise HTTPException(500, "글을 지우지 못했어요. 잠시 뒤 다시 시도해 주세요.")
    if photo and not kept:
        drop_photo_file(photo, session)
    return OkOut(message="글을 지웠어요. 수족관의 관찰 기록은 그대로 남고 ‘나만 보기’로 바뀌었어요." if kept else "글을 지웠어요.")


# ---------- 댓글 ----------
@router.post("/posts/{post_id}/comments", response_model=CommentView, summary="댓글 달기")
def comment_add(post_id: str, body: CommentIn, user: User = Depends(require_user), session: Session = Depends(get_session)):
    p, b = visible_post(post_id, user, session)
    if not rules_of(b)["comments"]:
        raise HTTPException(409, "이 게시판은 댓글을 받지 않아요.")
    if not allowed(user, perm_of(b, "comment")):
        raise HTTPException(403, f"{b.name}에는 운영자만 댓글을 달 수 있어요.")
    if body.parent_id:
        parent = session.get(Comment, body.parent_id)
        if not parent or parent.deleted or parent.post_id != p.id:
            raise HTTPException(404, "답글을 달 댓글을 찾지 못했어요. 지워졌거나 다른 게시글의 댓글이에요.")
        if session.get(CommentReply, parent.id):
            raise HTTPException(409, "답글에는 다시 답글을 달 수 없어요. 원래 댓글에 답글을 남겨 주세요.")
    if errs := banned_errors(session, {"body": body.body}):
        fail(errs)
    c = Comment(id=new_id("c"), post_id=p.id, user_id=user.id, body=body.body)
    try:
        session.add(c)
        if body.parent_id:
            session.flush()
            session.add(CommentReply(comment_id=c.id, parent_id=body.parent_id))
        p.comments = (p.comments or 0) + 1
        session.add(p)
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"[댓글 오류] {e}", flush=True)
        raise HTTPException(500, "댓글을 달지 못했어요. 잠시 뒤 다시 시도해 주세요.")
    session.refresh(c)
    return comment_view(c, session, body.parent_id)


@router.delete("/comments/{comment_id}", response_model=OkOut, summary="댓글 지우기 (쓴 사람 · 관리자)")
def comment_delete(comment_id: str, user: User = Depends(require_user), session: Session = Depends(get_session)):
    c = session.get(Comment, comment_id)
    if not c or c.deleted:
        raise HTTPException(404, "댓글을 찾지 못했어요. 이미 지워졌을 수 있어요.")
    if c.user_id != user.id and not is_admin(user):
        raise HTTPException(403, "내가 쓴 댓글만 지울 수 있어요.")
    try:
        c.deleted = True
        session.add(c)
        p = session.get(Post, c.post_id)
        if p:
            p.comments = max((p.comments or 1) - 1, 0)
            session.add(p)
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"[댓글 지우기 오류] {e}", flush=True)
        raise HTTPException(500, "댓글을 지우지 못했어요. 잠시 뒤 다시 시도해 주세요.")
    return OkOut(message="댓글을 지웠어요")


# ---------- 공감 ----------
@router.get("/posts/{post_id}/like", response_model=LikedOut, summary="내가 공감했는지")
def like_state(post_id: str, user: User = Depends(require_user), session: Session = Depends(get_session)):
    hit = session.exec(select(Like).where(Like.post_id == post_id, Like.user_id == user.id)).first()
    return LikedOut(liked=bool(hit))


@router.post("/posts/{post_id}/like", response_model=LikeOut, summary="공감하기 · 다시 누르면 취소 (한 사람 한 번)")
def like_toggle(post_id: str, user: User = Depends(require_user), session: Session = Depends(get_session)):
    p, b = visible_post(post_id, user, session)
    if not rules_of(b)["likes"]:
        raise HTTPException(409, "이 게시판은 공감을 받지 않아요.")
    hit = session.exec(select(Like).where(Like.post_id == p.id, Like.user_id == user.id)).first()
    try:
        if hit:
            session.delete(hit)
            p.likes = max((p.likes or 0) - 1, 0)
        else:
            session.add(Like(post_id=p.id, user_id=user.id))
            p.likes = (p.likes or 0) + 1
        session.add(p)
        session.commit()
    except IntegrityError:  # 두 번 빨리 눌렀어요: 이미 공감한 상태예요
        session.rollback()
        session.refresh(p)
        return LikeOut(liked=True, likes=p.likes)
    except Exception as e:
        session.rollback()
        print(f"[공감 오류] {e}", flush=True)
        raise HTTPException(500, "공감하지 못했어요. 잠시 뒤 다시 시도해 주세요.")
    return LikeOut(liked=not hit, likes=p.likes)


# ---------- 신고 ----------
@router.get("/posts/{post_id}/report", response_model=ReportedOut, summary="내가 신고했는지")
def report_state(post_id: str, user: User = Depends(require_user), session: Session = Depends(get_session)):
    hit = session.exec(select(Report).where(Report.post_id == post_id, Report.user_id == user.id)).first()
    return ReportedOut(reported=bool(hit))


@router.post("/posts/{post_id}/report", response_model=OkOut,
             summary="신고하기 (한 글에 한 번). 쌓인 신고가 운영 설정 횟수 이상이면 자동으로 숨겨요")
def report_add(post_id: str, body: ReportIn, user: User = Depends(require_user), session: Session = Depends(get_session)):
    p, b = visible_post(post_id, user, session)
    if not rules_of(b)["reports"]:
        raise HTTPException(409, "이 게시판은 신고를 받지 않아요. 문제가 있으면 제보·건의로 알려 주세요.")
    if p.user_id == user.id:
        raise HTTPException(409, "내가 쓴 글은 신고할 수 없어요. 고치거나 지워 주세요.")
    limit = int(settings_data(session).get("report_hide", 5))
    try:
        session.add(Report(post_id=p.id, user_id=user.id, reason=body.reason))
        session.flush()  # 같은 사람이 같은 글을 또 신고하면 여기서 막혀요 (고유 조건)
        p.report_count = session.exec(select(func.count()).select_from(Report).where(Report.post_id == p.id)).one()
        # 자동 숨김은 '대기' 중인 신고만 세요 (관리자가 '문제없음'으로 처리한 신고는 빼요)
        pending = session.exec(select(func.count()).select_from(Report)
                               .where(Report.post_id == p.id, Report.status == "대기")).one()
        hidden_now = bool(limit and pending >= limit and not p.hidden)
        if hidden_now:
            p.hidden = True
        session.add(p)
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, {"code": "already_reported", "message": "이미 신고한 글이에요. 운영자가 확인하고 있어요."})
    except Exception as e:
        session.rollback()
        print(f"[신고 오류] {e}", flush=True)
        raise HTTPException(500, "신고를 남기지 못했어요. 잠시 뒤 다시 시도해 주세요.")
    if hidden_now:
        return OkOut(message="신고했어요. 신고가 쌓여서 글을 잠시 숨겼어요. 운영자가 확인할게요.")
    return OkOut(message="신고했어요. 운영자가 확인할게요.")
