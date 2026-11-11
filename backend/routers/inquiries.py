"""제보·건의 API (김바로 담당) — v2.5 흐름: 저장 → Jira 이슈 → 담당 그룹 메일 → 답변 메일.

1) POST /inquiries: 먼저 SQLite에 저장하고 커밋해요(접수번호 R-1108-K3F9). Jira가 꺼져 있거나 실패해도 제보는 남아요.
2) Jira가 켜져 있으면(JIRA_* 환경변수) 이슈를 만들어요. 성공 created · 실패 failed(+오류 내용) · 미연결 off.
   실패한 건은 관리자 화면(A-06)의 [Jira 다시 보내기]로 다시 보내요. 이슈 키가 이미 있으면 절대 다시 만들지 않아요.
3) 담당 그룹 메일(OPS_EMAIL)로 새 제보를 알려요. 메일 키가 없으면 개발 모드라 서버 터미널에 찍혀요.
4) 관리자가 ‘완료’ + 답변을 저장하면 제보한 사람에게 결과 메일을 보내요(mail_sent).
   Jira에서 이슈를 끝내면 [Jira 상태 가져오기] 또는 웹훅(POST /webhooks/jira?secret=…)으로 ‘완료’가 돼요.
비회원 처리 확인은 접수번호 + 이메일 → 메일로 받은 6자리 코드 2단계예요.
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session, select

from backend.config import get_settings
from backend.core import jira, mail, redis_store
from backend.core.security import optional_user, require_admin, require_user, viewer_key
from backend.core.timefmt import as_kst, now
from backend.db import get_session
from backend.models import AdminLog, Inquiry, User
from backend.schemas.common import OkOut
from backend.schemas.inquiry import (InquiryActionOut, InquiryAdminOut, InquiryCreated, InquiryIn, InquiryOut,
                                     InquiryPatch, JiraSyncOut, JiraWebhookIn, LookupIn, LookupSendOut, LookupVerifyIn)

router = APIRouter(tags=["제보·건의"])

SCREEN = "문의 관리"
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 헷갈리는 0 · O · 1 · I 는 빼요
# Jira 라벨에는 띄어쓰기를 쓸 수 없어서 유형을 영문 라벨로 바꿔요
TYPE_LABEL = {"오류 제보": "bug-report", "기능 건의": "feature-request", "생물 정보 정정": "species-fix", "기타": "etc"}
SUBMIT_GAP = 20  # 같은 사람이 연달아 보내는 것 막기 (초)
LOOKUP_SENDS, LOOKUP_WINDOW = 5, 600  # 같은 접수번호 · 메일로 10분에 코드 5번까지


# ---------- 공통 도우미 ----------
def _new_id(session: Session) -> str:
    """추측하기 어려운 접수번호: R-월일-4자리(32글자 중에서 무작위)."""
    for _ in range(20):
        rid = f"R-{now():%m%d}-" + "".join(secrets.choice(_ALPHABET) for _ in range(4))
        if not session.get(Inquiry, rid):
            return rid
    raise HTTPException(500, "접수번호를 만들지 못했어요. 잠시 뒤 다시 보내 주세요.")


def _reply_to(q: Inquiry, session: Session) -> str:
    """답변 받을 메일. 회원이면 (예전 제보처럼 비어 있을 때) 계정 메일을 써요."""
    if q.email:
        return q.email
    u = session.get(User, q.user_id) if q.user_id else None
    return u.email if u else ""


def _out(q: Inquiry) -> InquiryOut:
    return InquiryOut(id=q.id, type=q.type, title=q.title, body=q.body, status=q.status,
                      date=as_kst(q.created_at).strftime("%Y-%m-%d"), user=q.user_id or "", email=q.email,
                      answer=q.answer, jira_key=q.jira_key, jira_status=q.jira_status,
                      updated=as_kst(q.updated_at).strftime("%Y-%m-%d %H:%M"))


def _admin_out(q: Inquiry, session: Session) -> InquiryAdminOut:
    u = session.get(User, q.user_id) if q.user_id else None
    sender = u.nickname if u else f"비회원 · {q.email}"
    url = jira.browse_url(q.jira_key) if q.jira_key and get_settings().jira_base_url else ""
    # 과거 저장된 외부 오류 원문도 API 응답으로 내보내지 않아요.
    error = "Jira 연동을 완료하지 못했어요. 연결 설정을 확인하고 잠시 뒤 다시 시도해 주세요." if q.jira_error else ""
    return InquiryAdminOut(**_out(q).model_dump(), sender=sender, jira_url=url, jira_error=error,
                           mail_sent=q.mail_sent)


def _get(rid: str, session: Session) -> Inquiry:
    q = session.get(Inquiry, rid)
    if not q:
        raise HTTPException(404, "문의를 찾지 못했어요. 목록을 새로 고쳐 주세요.")
    return q


def _log(session: Session, actor: str, action: str, target: str, before: str = "", after: str = "") -> None:
    session.add(AdminLog(screen=SCREEN, actor=actor, action=action, target=target, before=before, after=after))


def _commit(session: Session, fail: str) -> None:
    try:
        session.commit()
    except Exception:
        session.rollback()
        print("[제보 저장 오류] 저장에 실패했어요.", flush=True)
        raise HTTPException(500, fail) from None


# ---------- Jira ----------
def _jira_issue(q: Inquiry) -> tuple[str, str, str, list[str]]:
    summary = f"[{q.type}] {q.title}"
    description = "\n".join([f"접수번호: {q.id}", f"유형: {q.type}", f"접수: {as_kst(q.created_at):%Y-%m-%d %H:%M}",
                             "", "내용:", q.body, "", f"연락 메일: {q.email or '(회원 · 계정 메일)'}"])
    return summary, description, "bug" if q.type == "오류 제보" else "task", ["sea-info", TYPE_LABEL.get(q.type, "etc")]


def _send_to_jira(q: Inquiry, session: Session, strict: bool = False) -> None:
    """Jira 이슈를 만들고 결과를 저장해요. 이슈 키가 이미 있으면 다시 만들지 않아요(중복 방지).

    같은 제보를 동시에 보내지 않게 Redis로 120초 잠가요. strict=True면 잠겨 있을 때 알려요.
    외부 성공 후 결과 저장 실패는 이 잠금만으로 중복을 보장할 수 없으므로 재시도 전 확인이 필요해요.
    """
    if q.jira_key:
        return
    if not jira.on():
        q.jira_status = "off"
        session.add(q)
        session.commit()
        return
    lock = f"jira-create:{q.id}"
    try:
        # [BARO-CHANGE-024] 소유 토큰이 일치하는 잠금만 해제하여 다른 요청의 잠금을 보존한다.
        got = redis_store.lock_acquire(lock, 120)
    except Exception:
        q.jira_status = "failed"
        q.jira_error = "중복 방지 잠금을 확인하지 못해 Jira 전송을 보류했어요. 잠시 뒤 다시 시도해 주세요."
        q.updated_at = now()
        session.add(q)
        _commit(session, "Jira 전송 보류 상태를 저장하지 못했어요. 목록을 새로 고쳐 주세요.")
        if strict:
            raise HTTPException(503, q.jira_error) from None
        return
    if not got:
        if strict:
            raise HTTPException(409, "이 문의를 지금 Jira로 보내고 있어요. 잠시 뒤 목록을 새로 고쳐 주세요.")
        return
    try:
        session.refresh(q)
        if q.jira_key:  # 잠그는 사이에 다른 요청이 만들었어요
            return
        summary, description, kind, labels = _jira_issue(q)
        try:
            key = jira.create_issue(summary, description, kind, labels)
            if not isinstance(key, str) or not key.strip():
                raise ValueError("missing issue key")
        except Exception:  # 외부 응답 원문에는 비밀값이 포함될 수 있어 저장하지 않아요.
            q.jira_status = "failed"
            q.jira_error = "Jira 이슈 생성을 확인하지 못했어요. Jira에서 기존 이슈를 확인한 뒤 재시도해 주세요."
        else:
            q.jira_key, q.jira_status, q.jira_error = key, "created", ""
        q.updated_at = now()
        session.add(q)
        session.commit()
    finally:
        if got:
            try:
                redis_store.lock_release(lock, got)
            except Exception:
                pass


# [BARO-CHANGE-025] 완료 메일도 잠금 안에서 DB 상태를 다시 확인하여 동시 발송 가능성을 줄인다.
# 외부 발송 성공 후 DB 기록 실패·잠금 만료는 완전한 중복 방지 대상에서 제외된다.
def _mail_result(q: Inquiry, session: Session) -> str:
    if q.status != "완료" or not q.answer or q.mail_sent:
        return ""
    lock = f"inquiry-mail:{q.id}"
    try:
        token = redis_store.lock_acquire(lock, 120)
    except Exception:
        return " 답변은 저장됐지만 중복 방지 잠금을 확인하지 못해 메일 발송을 보류했어요."
    if not token:
        return " 결과 메일을 다른 요청에서 처리 중이에요. 잠시 뒤 발송 상태를 확인해 주세요."
    try:
        session.refresh(q)
        return _deliver_mail_result(q, session)
    except Exception:
        session.rollback()
        return " 답변은 저장됐지만 메일 처리 결과를 확인하지 못했어요. 재전송 전에 발송 내역을 확인해 주세요."
    finally:
        try:
            redis_store.lock_release(lock, token)
        except Exception:
            pass


def _deliver_mail_result(q: Inquiry, session: Session) -> str:
    """‘완료’ + 답변이 있고 아직 안 보냈으면 제보한 사람에게 결과 메일을 보내요. 화면에 덧붙일 안내를 돌려줘요."""
    if q.status != "완료" or not q.answer or q.mail_sent:
        return ""
    to = _reply_to(q, session)
    if not to:
        return " 받을 메일 주소가 없어 답변 메일은 보내지 않았어요."
    where = (f"{get_settings().public_site_url.rstrip('/')}/mypage?tab=inquiries" if q.user_id
             else f"{get_settings().public_site_url.rstrip('/')}/report (접수번호 + 이메일로 확인)")
    body = (f"안녕하세요, Sea-Info Agent예요.\n\n보내 주신 제보·건의를 처리했어요.\n\n"
            f"접수번호: {q.id}\n유형: {q.type}\n제목: {q.title}\n\n운영팀 답변:\n{q.answer}\n\n"
            f"처리 상황은 여기에서도 볼 수 있어요: {where}\n알려 주셔서 고마워요.")
    try:
        res = mail.send(to, f"[Sea-Info Agent] 제보·건의 처리 결과 ({q.id})", body)
    except Exception:
        print("[답변 메일 오류] 메일 전송을 확인하지 못했어요.", flush=True)
        return " 답변 메일의 발송 여부를 확인하지 못했어요. 중복 발송을 피하려면 발송 내역 확인 후 다시 저장해 주세요."
    q.mail_sent = bool(res.get("sent"))
    if not q.mail_sent:
        if res.get("dev"):
            return " 개발 모드로만 처리했어요. 실제 답변 메일은 발송되지 않았어요."
        return " 답변 메일은 발송되지 않았어요. 메일 설정을 확인한 뒤 다시 저장해 주세요."
    session.add(q)
    _commit(session, "메일 전송 후 발송 기록을 저장하지 못했어요. 중복 발송을 피하려면 발송 내역을 먼저 확인해 주세요.")
    return " 답변 메일도 보냈어요."


# [BARO-CHANGE-026] 운영 알림의 미설정·개발 처리·발송·확인 불가를 접수 결과와 구분한다.
def _notify_ops(q: Inquiry) -> str:
    s = get_settings()
    if not s.ops_email:
        return " 운영팀 알림 메일은 미설정 상태예요. 접수 내용은 문의 관리에 저장됐어요."
    jira_line = {"created": f"Jira 이슈: {q.jira_key}", "failed": "Jira 이슈: 등록 여부 확인이 필요해요",
                 }.get(q.jira_status, "Jira 이슈: 미연결")
    body = "\n".join([f"새 제보·건의가 들어왔어요.", "", f"접수번호: {q.id}", f"유형: {q.type}", f"제목: {q.title}",
                      f"연락 메일: {q.email or '(회원)'}", jira_line, "", q.body, "",
                      f"관리 화면: {s.public_site_url.rstrip('/')}/admin-inquiries"])
    try:
        result = mail.send(s.ops_email, f"[Sea-Info Agent] 새 제보 {q.id} · [{q.type}] {q.title}", body)
        if result.get("sent"):
            return " 운영팀 알림 메일을 발송했어요."
        return " 운영팀 알림 메일은 실제 발송되지 않았어요. 접수 내용은 문의 관리에 저장됐어요."
    except Exception:  # 알림 메일이 실패해도 제보는 이미 저장됐어요
        print("[담당 그룹 메일 오류] 알림 전송을 확인하지 못했어요.", flush=True)
        return " 운영팀 알림 메일의 발송 여부는 확인하지 못했어요. 접수 내용은 저장됐어요."


def _complete_from_jira(q: Inquiry, session: Session, actor: str, action: str) -> str:
    """Jira에서 끝난 이슈 → 문의를 ‘완료’로. 답변이 있으면 결과 메일까지 보내요."""
    if q.status == "완료" and q.jira_status == "done":
        return "이미 완료된 문의예요."
    before = f"{q.status} · Jira {q.jira_status}"
    q.status, q.jira_status, q.updated_at = "완료", "done", now()
    session.add(q)
    _log(session, actor, action, q.id, before, "완료 · Jira done")
    _commit(session, "상태를 바꾸지 못했어요. 잠시 뒤 다시 시도해 주세요.")
    extra = _mail_result(q, session)
    return "Jira에서 끝난 이슈라 ‘완료’로 바꿨어요." + (extra or (" 답변을 적어 저장하면 결과 메일이 가요." if not q.answer else ""))


# ---------- 고객: 보내기 · 내 문의 · 비회원 처리 확인 ----------
@router.post("/inquiries", response_model=InquiryCreated, summary="제보·건의 보내기 (저장 → Jira → 담당 그룹 메일)")
def create_inquiry(body: InquiryIn, request: Request, user: User | None = Depends(optional_user),
                   session: Session = Depends(get_session)):
    email = user.email.lower() if user else body.email
    if not user and not email:
        raise HTTPException(422, "답변 받을 이메일을 적어 주세요. 로그인하면 이메일 없이 보낼 수 있어요.")
    try:
        if not redis_store.gap_ok(f"inquiry:{viewer_key(request, user)}", SUBMIT_GAP):
            raise HTTPException(429, f"조금 전에 제보를 보냈어요. {SUBMIT_GAP}초 뒤에 다시 보내 주세요.")
    except HTTPException:
        raise
    except Exception:  # Redis가 꺼져 있으면 도배 막기만 건너뛰어요
        pass
    q = Inquiry(id=_new_id(session), type=body.type, title=body.title, body=body.body,
                user_id=user.id if user else None, email=email, jira_status="off")
    # [BARO-CHANGE-027] 최초 저장 이후 후속 연동 실패가 접수 실패로 바뀌지 않도록 응답을 별도 보관한다.
    rid = q.id
    session.add(q)
    _commit(session, "보내지 못했어요. 적은 내용은 그대로 있어요. 다시 시도해 주세요.")  # ① 먼저 저장
    result = InquiryCreated(id=rid, jira_status="failed", message="접수 내용은 저장됐어요.")
    try:  # ② Jira (실패해도 제보는 남아요)
        _send_to_jira(q, session)
        result.jira_status, result.jira_key = q.jira_status, q.jira_key
    except Exception:
        session.rollback()
        print("[Jira 단계 오류] 연동 결과 저장을 확인하지 못했어요.", flush=True)
        result.message += " Jira 연동 결과는 확인하지 못했어요. 운영팀이 기존 이슈를 확인해야 해요."
        try:
            q = session.get(Inquiry, rid)
            if q is not None and q.jira_key:
                result.jira_status, result.jira_key = q.jira_status, q.jira_key
            if q is not None and not q.jira_key:
                q.jira_status = "failed"
                q.jira_error = "Jira 연동 결과를 확인하지 못했어요. 기존 이슈 확인 후 재시도해 주세요."
                session.add(q)
                session.commit()
        except Exception:
            session.rollback()
    try:
        result.message += _notify_ops(q)  # ③ 알림의 실패도 이미 접수된 결과를 바꾸지 않는다.
    except Exception:
        session.rollback()
        result.message += " 운영팀 알림 결과는 확인하지 못했어요."
    return result


@router.get("/me/inquiries", response_model=list[InquiryOut], summary="내 제보·건의 (회원)")
def my_inquiries(user: User = Depends(require_user), session: Session = Depends(get_session)):
    rows = session.exec(select(Inquiry).where(Inquiry.user_id == user.id)).all()
    return [_out(q) for q in sorted(rows, key=lambda q: as_kst(q.created_at), reverse=True)]


def _match(body: LookupIn, session: Session) -> Inquiry:
    q = session.get(Inquiry, body.id)
    if not q or _reply_to(q, session).lower() != body.email:
        raise HTTPException(404, "일치하는 제보를 찾지 못했어요. 접수번호와 이메일을 한 번 더 확인해 주세요.")
    return q


def _mask(email: str) -> str:
    name, _, domain = email.partition("@")
    return (name[:2] + "*" * max(len(name) - 2, 1)) + "@" + domain


@router.post("/inquiries/lookup/send", response_model=LookupSendOut, summary="비회원 처리 확인 ① 메일로 6자리 코드 받기")
def lookup_send(body: LookupIn, session: Session = Depends(get_session)):
    _match(body, session)
    key = f"{body.id}:{body.email}"
    # [BARO-CHANGE-028] 인증 저장소 장애는 조회 인증을 우회하지 않고 503으로 안내한다.
    try:
        r = redis_store.r()
        n = r.incr(f"lookupsend:{key}")
        if n == 1:
            r.expire(f"lookupsend:{key}", LOOKUP_WINDOW)
        if n > LOOKUP_SENDS:
            raise HTTPException(429, "코드를 너무 여러 번 받았어요. 10분 뒤에 다시 받아 주세요.")
        code = redis_store.code_create("lookup", key)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "처리 확인 인증을 지금 사용할 수 없어요. 잠시 뒤 다시 시도해 주세요.") from None
    try:
        res = mail.code_mail(body.email, code, "lookup")
    except Exception:
        print("[처리 확인 메일 오류] 메일 전송을 확인하지 못했어요.", flush=True)
        raise HTTPException(502, "메일을 보내지 못했어요. 잠시 뒤 다시 받아 주세요.") from None
    s = get_settings()
    dev = bool(res.get("dev") and not s.smtp_on and s.is_local)
    if not res.get("sent") and not dev:
        raise HTTPException(502, "확인 코드 메일이 발송되지 않았어요. 잠시 뒤 다시 받아 주세요.")
    return LookupSendOut(sent=bool(res.get("sent")), dev_code=code if dev else None,
                         message=("개발 모드예요. 실제 메일은 발송되지 않았어요. 화면의 코드를 입력해 주세요." if dev
                                  else f"{_mask(body.email)}로 6자리 코드를 보냈어요. 5분 안에 적어 주세요."))


@router.post("/inquiries/lookup/verify", response_model=InquiryOut, summary="비회원 처리 확인 ② 코드 확인 → 처리 상황")
def lookup_verify(body: LookupVerifyIn, session: Session = Depends(get_session)):
    q = _match(body, session)
    try:
        ok, _, msg = redis_store.code_check("lookup", f"{body.id}:{body.email}", body.code)
    except Exception:
        raise HTTPException(503, "처리 확인 인증을 지금 사용할 수 없어요. 잠시 뒤 다시 시도해 주세요.") from None
    if not ok:
        raise HTTPException(400, msg)
    return _out(q)


# ---------- 관리자 (A-06) ----------
@router.get("/admin/inquiries", response_model=list[InquiryAdminOut], summary="문의 목록 (관리자)")
def admin_list(status: str | None = None, type: str | None = None, jira_status: str | None = None, q: str = "",
               admin: User = Depends(require_admin), session: Session = Depends(get_session)):
    stmt = select(Inquiry)
    if status:
        stmt = stmt.where(Inquiry.status == status)
    if type:
        stmt = stmt.where(Inquiry.type == type)
    if jira_status:
        stmt = stmt.where(Inquiry.jira_status == jira_status)
    rows = [r for r in session.exec(stmt).all() if not q or q in r.title or q in r.id or q in r.body]
    rows.sort(key=lambda r: as_kst(r.created_at), reverse=True)
    return [_admin_out(r, session) for r in rows]


@router.patch("/admin/inquiries/{rid}", response_model=InquiryActionOut, summary="답변 · 상태 저장 (완료 + 답변이면 결과 메일)")
def admin_update(rid: str, body: InquiryPatch, admin: User = Depends(require_admin),
                 session: Session = Depends(get_session)):
    q = _get(rid, session)
    before = f"{q.status} · 답변 {'있음' if q.answer else '없음'}"
    if body.status is not None:
        q.status = body.status
    if body.answer is not None:
        q.answer = body.answer
    q.updated_at = now()
    session.add(q)
    _log(session, admin.nickname, "문의 답변 · 상태 저장", q.id, before, f"{q.status} · 답변 {'있음' if q.answer else '없음'}")
    _commit(session, "저장하지 못했어요. 적은 답변은 그대로 있어요. 다시 시도해 주세요.")
    extra = _mail_result(q, session)
    return InquiryActionOut(message=f"{q.id} 저장했어요. 고객 화면에 바로 보여요." + extra, inquiry=_admin_out(q, session))


@router.post("/admin/inquiries/{rid}/jira/retry", response_model=InquiryActionOut, summary="Jira 다시 보내기 (이슈가 없을 때만)")
def admin_jira_retry(rid: str, admin: User = Depends(require_admin), session: Session = Depends(get_session)):
    q = _get(rid, session)
    if q.jira_key:
        raise HTTPException(409, f"이미 Jira 이슈가 있어요 ({q.jira_key}). 같은 이슈를 또 만들지 않아요. "
                                 "[Jira 상태 가져오기]를 눌러 주세요.")
    if not jira.on():
        raise HTTPException(409, "Jira가 연결되어 있지 않아요. 서버 환경변수 JIRA_*를 넣고 서버를 다시 켠 뒤 시도해 주세요.")
    before = q.jira_status
    _send_to_jira(q, session, strict=True)
    ok = q.jira_status == "created"
    _log(session, admin.nickname, "Jira 다시 보내기", q.id, before, f"{q.jira_status} {q.jira_key}".strip())
    _commit(session, "결과를 저장하지 못했어요. 목록을 새로 고쳐 주세요.")
    msg = (f"Jira 이슈를 만들었어요 ({q.jira_key})." if ok
           else "Jira에 또 보내지 못했어요. 아래 오류 내용을 확인하고 잠시 뒤 다시 시도해 주세요.")
    return InquiryActionOut(ok=ok, message=msg, inquiry=_admin_out(q, session))


@router.post("/admin/inquiries/{rid}/jira/sync", response_model=JiraSyncOut, summary="Jira 상태 가져오기 (끝났으면 완료로)")
def admin_jira_sync(rid: str, admin: User = Depends(require_admin), session: Session = Depends(get_session)):
    q = _get(rid, session)
    if not q.jira_key:
        raise HTTPException(409, "아직 Jira 이슈가 없어요. 먼저 [Jira 다시 보내기]를 눌러 주세요.")
    if not jira.on():
        raise HTTPException(409, "Jira가 연결되어 있지 않아요. 서버 환경변수 JIRA_*를 넣고 서버를 다시 켠 뒤 시도해 주세요.")
    try:
        name, done = jira.issue_status(q.jira_key)
    except Exception:
        raise HTTPException(502, "Jira 상태를 가져오지 못했어요. 잠시 뒤 다시 시도해 주세요.") from None
    if done:
        msg = _complete_from_jira(q, session, admin.nickname, f"Jira 상태 가져오기: {name}")
    else:
        msg = f"Jira에서 아직 ‘{name}’ 상태예요. 끝나면 다시 가져와 주세요."
    return JiraSyncOut(message=msg, inquiry=_admin_out(q, session), jira_state=name, done=done)


@router.post("/webhooks/jira", response_model=OkOut, summary="Jira 웹훅 (이슈가 끝나면 문의를 완료로)")
def jira_webhook(payload: JiraWebhookIn, secret: str = Query("", description="JIRA_WEBHOOK_SECRET 값"),
                 session: Session = Depends(get_session)):
    expected = get_settings().jira_webhook_secret
    if not expected:
        raise HTTPException(403, "웹훅 비밀값(JIRA_WEBHOOK_SECRET)이 설정되지 않아 받지 않아요.")
    if not secrets.compare_digest(secret.encode(), expected.encode()):
        raise HTTPException(403, "웹훅 비밀값이 맞지 않아요. Jira 웹훅 주소의 ?secret= 값을 확인해 주세요.")
    key = payload.issue.key if payload.issue else ""
    q = session.exec(select(Inquiry).where(Inquiry.jira_key == key)).first() if key else None
    if not q:
        return OkOut(message="모르는 이슈라 건너뛰었어요.")
    if not payload.done():
        return OkOut(message="아직 끝나지 않은 이슈라 그대로 두었어요.")
    return OkOut(message=_complete_from_jira(q, session, "Jira 웹훅", "Jira 이슈 완료"))
