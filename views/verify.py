"""메일 링크 인증 화면 (이종민 담당). 주소: /verify?token_hash=...&type=email|recovery

메일 속 [메일 인증하기] · [비밀번호 다시 정하기] 링크가 이 화면을 열어요. 코드를 입력하지 않아요.
  type=email (옛 이름 signup) → 인증 끝 + 바로 로그인 → 회원가입 ③ 닉네임 · 캐릭터 고르기(로그인 화면)로 이어져요
  type=recovery               → 새 비밀번호 정하기
링크의 인증값(token_hash)은 서버(POST /auth/verify-link)가 확인해요.
  Supabase 모드: Supabase가 보낸 메일의 인증값을 Supabase에 확인 (메일 템플릿 설정은 설치 가이드 3장)
  로컬 모드:     우리 서버가 보낸 1회용 인증값을 Redis에서 확인

시안 캡처용: ?shot=expired|reset|reset_done|nolink
"""
import re

import streamlit as st

from components import nav, ui
from services import admin_data, auth
from services.api import ApiError

S = st.session_state
qp = st.query_params
token = qp.get("token_hash", "")
kind = qp.get("type", "email")
kind = kind if kind in ("email", "signup", "recovery") else "email"
shot = qp.get("shot")

if shot and S.get("_shot_verify") != shot:  # 시안 캡처용 상태 (서버에 요청하지 않아요)
    S["_shot_verify"] = shot
    for k in ("verify_error", "verify_reset", "verify_done"):
        S.pop(k, None)
    if shot == "expired":
        S["verify_error"] = ("email", "이미 사용했거나 시간이 지난 링크예요. 인증을 마쳤다면 로그인해 주세요. "
                                      "아니라면 메일을 다시 받아 주세요.", "link_expired")
    elif shot in ("reset", "reset_done"):
        S["verify_reset"] = {"reset_id": "", "email_masked": "ex******@example.com"}
        S["verify_done"] = shot == "reset_done"

# ---------- 링크 확인 (같은 링크는 한 번만 서버에 보내요) ----------
if token and S.get("_verify_token") != token:
    S["_verify_token"] = token
    for k in ("verify_error", "verify_reset", "verify_done"):
        S.pop(k, None)
    try:
        out = auth.verify_link(token, kind)
    except ApiError as e:
        S["verify_error"] = (kind, e.message, e.code)
        out = None
    if out and out.get("kind") == "signup":
        me = out.get("user") or {}
        S["login_mode"], S["login_step"] = "signup", 3
        S["login_signup"] = {"email": me.get("email", "")}
        S["login_char"] = me.get("character") or "🐢"
        st.toast("메일 인증을 마쳤어요")
        nav.go("login")  # 회원가입 ③ 닉네임 · 캐릭터 고르기로
    elif out:
        S["verify_reset"] = out


def to_login(mode: str = "login", notice: str | None = None) -> None:
    S["login_mode"] = mode
    S["login_step"] = 1
    if notice:
        S["login_notice"] = notice
    nav.go("login")


def show_error(k: str, message: str) -> None:
    recovery = k == "recovery"
    ui.page_header("비밀번호 다시 정하기" if recovery else "메일 인증", "링크를 확인하지 못했어요.")
    st.error(message, icon=":material/link_off:")
    with st.container(horizontal=True, gap="small"):
        if recovery:
            if st.button("비밀번호 찾기 다시 하기", type="primary", key="verify_to_reset", icon=":material/key:"):
                to_login("reset")
            if st.button("로그인하기", key="verify_to_login", icon=":material/login:"):
                to_login()
        else:
            if st.button("로그인하기", type="primary", key="verify_to_login", icon=":material/login:"):
                to_login()
            if st.button("처음부터 가입하기", key="verify_to_signup", icon=":material/person_add:"):
                to_login("signup")
    admin_data.muted("인증을 아직 마치지 않았다면 로그인 화면에서 이메일과 비밀번호를 넣으면 ‘인증 메일 다시 받기’ 버튼이 나와요."
                     if not recovery else "재설정 링크는 1시간 동안 한 번만 쓸 수 있어요.")


def show_reset(data: dict) -> None:
    ui.page_header("비밀번호 다시 정하기", "새 비밀번호를 정하면 끝나요.")
    if S.get("verify_done"):
        st.success("비밀번호를 새로 정했어요. 새 비밀번호로 로그인해 주세요.", icon=":material/check_circle:")
        if st.button("로그인하러 가기", type="primary", width="stretch", key="verify_reset_login", icon=":material/login:"):
            for k in ("verify_reset", "verify_done"):
                S.pop(k, None)
            to_login(notice="비밀번호를 새로 정했어요. 새 비밀번호로 로그인해 주세요.")
        return
    masked = (data.get("email_masked") or "내 계정").replace("*", "\\*").replace("_", "\\_")  # 가린 주소의 *가 굵은 글씨로 읽히지 않게
    st.info(f"**{masked}** 의 새 비밀번호를 정해 주세요. 15분 안에 저장해 주세요.",
            icon=":material/lock_reset:")
    with st.form("verify_reset_form", border=False):
        st.text_input("새 비밀번호", key="verify_pw", type="password", placeholder="영문과 숫자를 섞어 8자 이상")
        st.text_input("새 비밀번호 확인", key="verify_pw2", type="password", placeholder="한 번 더 똑같이 입력해 주세요")
        box = st.empty()
        sent = st.form_submit_button("새 비밀번호 저장", type="primary", width="stretch", icon=":material/save:")
    if sent:
        pw, pw2 = S.get("verify_pw", ""), S.get("verify_pw2", "")
        if len(pw) < 8 or not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
            S["verify_reset_error"] = ("새 비밀번호는 영문과 숫자를 섞어 8자 이상으로 만들어 주세요.", "")
        elif pw != pw2:
            S["verify_reset_error"] = ("새 비밀번호가 서로 달라요. 한 번 더 똑같이 입력해 주세요.", "")
        else:
            try:
                auth.reset_confirm(data.get("reset_id", ""), pw)
            except ApiError as e:
                S["verify_reset_error"] = (e.message, e.code)
            else:
                S["verify_reset_error"] = None
                S["verify_done"] = True
        st.rerun()
    err = S.get("verify_reset_error")
    if err:
        box.error(err[0], icon=":material/error:")
        if err[1] in ("expired", "validation") or err[1] == "link_expired":
            if st.button("비밀번호 찾기 다시 하기", key="verify_reset_again", icon=":material/key:"):
                S.pop("verify_reset_error", None)
                to_login("reset")


def show_no_link() -> None:
    """주소에 인증값이 없을 때 (Supabase 기본 메일 템플릿 그대로면 이 화면으로 와요)."""
    ui.page_header("메일 인증", "메일 속 링크로 이 화면이 열렸나요?")
    st.info("링크를 눌러 이 화면이 열렸다면 인증이 끝났을 수 있어요. 이메일과 비밀번호로 로그인해 주세요.",
            icon=":material/mark_email_read:")
    admin_data.muted("로그인이 안 되면 로그인 화면에서 ‘인증 메일 다시 받기’를 눌러 주세요.")
    if st.button("로그인하기", type="primary", key="verify_nolink_login", icon=":material/login:"):
        to_login()


left, _ = st.columns([5, 3])
with left:
    with st.container(border=True):
        if S.get("verify_error"):
            show_error(S["verify_error"][0], S["verify_error"][1])
        elif S.get("verify_reset"):
            show_reset(S["verify_reset"])
        else:
            show_no_link()
