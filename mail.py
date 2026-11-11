"""메일 보내기 (편성훈). Google SMTP(Gmail)를 써요.

로컬 모드의 인증 링크 · 제보 알림 · 답변 알림 메일을 보내요.
SMTP_USER · SMTP_PASSWORD(Gmail 앱 비밀번호)가 없으면 '개발 모드':
메일을 실제로 보내지 않고 로컬 개발 모드에서만 Redis 'dev:mails'에 남겨요.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from backend.config import get_settings
from backend.core import redis_store
from backend.core.timefmt import now

log = logging.getLogger("sea_info.mail")


def send(to: str, subject: str, body: str) -> dict:
    """{'sent': 실제로 보냈는지, 'dev': 개발 모드였는지}"""
    s = get_settings()
    if not to:
        return {"sent": False, "dev": False}
    if not s.smtp_on:
        # [BARO-SCOPE-EXTENSION] 주요 5개 파일 밖의 승인된 연관 수정.
        # 변경 이유: inquiries.py의 메일 오류 처리와 연결되는 공통 메일 로그에서 개인정보를 제거한다.
        # [BARO-CHANGE-023] 메일 주소·코드·링크·본문을 로그에 출력하지 않고 운영 모드는 개발 보관도 하지 않는다.
        log.warning("SMTP 미설정으로 실제 메일을 발송하지 않았습니다.")
        if not s.is_local:
            return {"sent": False, "dev": False}
        redis_store.dev_mail_push({"to": to, "subject": subject, "body": body, "at": now().isoformat(timespec="seconds")})
        return {"sent": False, "dev": True}
    msg = EmailMessage()
    msg["From"] = s.mail_from or s.smtp_user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
        smtp.starttls()
        smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(msg)
    return {"sent": True, "dev": False}


def link_mail(to: str, url: str, purpose: str) -> dict:
    """로컬 모드에서 우리가 보내는 인증 링크 메일 (Supabase 모드에서는 Supabase가 보내요)."""
    if purpose == "reset":
        subject, what, button, limit = "[Sea-Info Agent] 비밀번호 다시 정하기", "비밀번호를 새로 정하려면", "비밀번호 다시 정하기", "1시간"
    else:
        subject, what, button, limit = "[Sea-Info Agent] 메일 인증을 해 주세요", "가입을 마치려면", "메일 인증하기", "24시간"
    body = (f"안녕하세요, Sea-Info Agent예요.\n\n{what} 아래 링크를 눌러 주세요. 링크는 {limit} 동안 한 번만 쓸 수 있어요.\n\n"
            f"[{button}]\n{url}\n\n직접 요청하지 않았다면 이 메일은 지워 주세요.")
    return send(to, subject, body)


def code_mail(to: str, code: str, purpose: str) -> dict:
    what = {"lookup": "제보·건의 처리 확인"}.get(purpose, "인증")
    body = (f"안녕하세요, Sea-Info Agent예요.\n\n{what} 코드는 아래 6자리예요. 5분 안에 입력해 주세요.\n\n"
            f"    {code}\n\n직접 요청하지 않았다면 이 메일은 지워 주세요.")
    return send(to, f"[Sea-Info Agent] {what} 코드 {code}", body)
