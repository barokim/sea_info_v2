"""U-17 로그인 · 회원가입 (이종민 담당).

한 화면 안에서 모드만 바꿔요:
  로그인(이메일 + 비밀번호) / 회원가입 ①정보 → ②메일 확인 → ③캐릭터 → 완료 / 비밀번호 찾기
로그인하면 하던 화면(after_login → back_to)으로 돌아가요. 담기 중이었으면 담기 화면(U-04)으로 이어져요.

메일 인증 · 비밀번호 찾기는 '메일 속 링크를 누르면 끝'이에요 (코드 입력 없음).
  링크는 /verify 화면(views/verify.py)을 열고, 인증이 끝나면 이 화면의 ③ 캐릭터 고르기로 이어져요.
  Supabase 모드는 Supabase가, 로컬 모드는 우리 서버가 Gmail로 링크를 보내요.
  메일 미연결 개발 모드면 메일 대신 화면에 링크 버튼을 보여줘요.

시안 캡처용: 주소에 ?shot=signup1|signup2|signup3|done|error|dup|expired|reset|reset_sent|continue
"""
import html
import re
from urllib.parse import parse_qs, urlparse

import streamlit as st

from components import nav, ui
from services import admin_data, auth, db
from services.api import ApiError

S = st.session_state
user = auth.current_user()
CHARS = admin_data.CHARACTERS
STEPS = ["정보 입력", "메일 확인", "캐릭터 고르기"]
SB = auth.supabase_mode()
KEYS = ("login_mode", "login_tab", "login_step", "login_signup", "login_error", "login_su_error",
        "login_verify_error", "login_nick_error", "login_reset_sent", "login_email", "login_pw",
        "login_su_email", "login_su_pw", "login_su_pw2", "login_ag_all", "login_ag_terms", "login_ag_privacy",
        "login_ag_age", "login_ag_mkt", "login_nick", "login_char", "login_reset_email", "login_reset_error",
        "login_verify_dev", "login_unverified", "login_reset_dev", "login_notice")
SAMPLE_PW = "seaday2026"


def reset_all() -> None:
    for k in KEYS:
        S.pop(k, None)


def target() -> tuple | None:
    """로그인 뒤 돌아갈 곳 (key, params)."""
    for k in ("after_login", "back_to"):
        t = S.get(k)
        if isinstance(t, (tuple, list)) and len(t) == 2 and t[0] in nav.ALL and t[0] != "login":
            return t[0], dict(t[1] or {})
    return None


def go_back() -> None:
    t = target()
    S.pop("after_login", None)
    reset_all()
    db.clear_cache()
    if not t:
        nav.go("home")
        return
    key, params = t
    if key == "identify" and S.get("identify_result"):
        S["identify_step"] = "save"  # 담기 중이었으면 분석 결과 그대로 담기 화면으로
    nav.go(key, **params)


def valid_email(email: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email.strip()))


def at(email: str) -> str:
    """좁은 화면에서 메일 주소가 @ 뒤에서 줄바꿈되게 (가린 주소의 *는 굵은 글씨로 읽히지 않게)."""
    return email.replace("*", "\\*").replace("_", "\\_").replace("@", "@​")


def dev_link_box(url: str | None) -> None:
    """메일을 보내지 않는 로컬 개발 모드에서만 서버가 링크를 같이 줘요 (메일 속 링크를 누른 것과 같아요)."""
    if not url:
        return
    q = parse_qs(urlparse(url).query)
    with st.container(border=True, key="login_dev_link"):
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.markdown(ui.chip("개발 모드", "demo"), unsafe_allow_html=True)
            ui.muted("메일 대신 여기에 인증 링크를 보여줘요")
        st.code(url, language=None, wrap_lines=True)
        nav.link("verify", "메일 속 링크 누르기 (개발 모드)", icon=":material/link:",
                 token_hash=q.get("token_hash", [""])[0], type=q.get("type", ["email"])[0])


# ---------- 시안 캡처용 상태 만들기 (실제 서버에 한 번만 요청해요) ----------
def _shot_signup(email: str) -> None:
    try:
        out = auth.signup(email, SAMPLE_PW, agree=True, marketing=True)
        S["login_verify_dev"] = out.get("dev_link")
    except ApiError:  # 이미 보냈거나(30초) 인증까지 마친 시안 메일이면 화면만 보여줘요
        pass


shot = st.query_params.get("shot")
if shot and S.get("_shot_login") != shot:
    S["_shot_login"] = shot
    reset_all()
    sample = "sea.family@example.com"
    real = auth.dev_mode()  # 배포 환경에서는 시안용 요청을 보내지 않아요
    if shot in ("signup1", "signup2", "signup3", "done", "dup", "expired"):
        S["login_mode"] = "signup"
        S["login_step"] = {"signup1": 1, "dup": 1, "signup2": 2, "expired": 2, "signup3": 3, "done": 4}[shot]
        S["login_signup"] = {"email": sample, "marketing": True, "nickname": "모래성짓기", "character": "🐬"}
        if shot in ("signup1", "dup"):
            S["login_su_email"] = "explorer@example.com" if shot == "dup" else sample
            S["login_su_pw"] = S["login_su_pw2"] = SAMPLE_PW
            for k in ("login_ag_all", "login_ag_terms", "login_ag_privacy", "login_ag_age"):
                S[k] = True
        if shot == "dup":
            S["login_su_error"] = "dup"
        if shot == "signup2" and real:
            _shot_signup(sample)
        if shot == "expired":
            S["login_verify_error"] = "아직 인증이 끝나지 않았어요. 메일 속 링크를 먼저 눌러 주세요. 링크 시간이 지났다면 ‘메일 다시 보내기’를 눌러 주세요."
        if shot == "signup3":
            S["login_nick"], S["login_char"] = "모래성짓기", "🐬"
    elif shot == "error":
        S["login_mode"] = "login"
        S["login_email"] = "explorer@example.com"
        S["login_error"] = "이메일이나 비밀번호가 맞지 않아요. 다시 입력하거나 아래 ‘비밀번호 찾기’를 눌러 주세요."
    elif shot in ("reset", "reset_sent"):
        S["login_mode"] = "reset"
        S["login_reset_email"] = "explorer@example.com"
        if shot == "reset_sent":
            S["login_reset_sent"] = "explorer@example.com"
            if real:
                try:
                    S["login_reset_dev"] = auth.reset_password("explorer@example.com").get("dev_link")
                except ApiError:
                    pass
    elif shot == "continue":
        S["after_login"] = ("identify", {})

mode = S.setdefault("login_mode", "login")
step = S.setdefault("login_step", 1)


# ---------- 공통 조각 ----------
def step_chips(now: int) -> None:
    items = []
    for i, name in enumerate(STEPS, 1):
        if i < now:
            items.append(ui.chip(f"✓ {i}. {name}", "ok"))
        elif i == now:
            items.append(ui.chip(f"{i}. {name}", "sea"))
        else:
            items.append(ui.chip(f"{i}. {name}"))
    ui.chips(*items)
    st.progress(min(now, 3) / 3)


def side_panel() -> None:
    if mode == "signup":
        eyebrow, head, body = "회원가입", "3단계면 끝나요", "메일 속 링크를 누르면 인증이 끝나요. 그다음 닉네임과 바다 캐릭터를 골라요."
    elif mode == "reset":
        eyebrow, head, body = "비밀번호 찾기", "메일로 다시 정해요", "가입한 메일로 링크를 보내 드려요. 링크를 누르고 새 비밀번호를 정해요."
    else:
        eyebrow, head, body = "회원이 되면", "바다 친구를 모아 봐요", "만난 생물을 담고, 관찰 이야기를 나눌 수 있어요."
    st.markdown(f'<div class="sia-hero"><div class="eyebrow">{eyebrow}</div><h2>{head}</h2><p>{body}</p></div>',
                unsafe_allow_html=True)
    st.space("small")
    lim = db.settings()
    with st.container(border=True):
        admin_data.item_row("🐠", "나의 수족관에 담기", "알아본 생물을 생물 카드로 모아요", tone="aqua")
        admin_data.item_row("⭐", "관찰 이야기 공유하기", "만난 순간을 사진과 함께 나눠요", tone="coral")
        admin_data.item_row("🦀", f"하루 {lim['limit_member']}번 알아보기",
                            f"비회원은 하루 {lim['limit_guest']}번까지예요", tone="sand")


# ---------- 로그인 ----------
def to_verify(email: str) -> None:
    """인증을 마치지 않은 계정: 인증 메일을 다시 받고 가입 ②단계로."""
    try:
        out = auth.resend_verify(email)
    except ApiError as e:
        S["login_error"] = e.message
        if e.code == "already_verified":
            S["login_unverified"] = None
        return
    S["login_mode"], S["login_step"] = "signup", 2
    S["login_signup"] = {"email": email, "marketing": False, "pw": S.get("login_pw", "")}
    S["login_verify_dev"] = out.get("dev_link")
    S["login_error"] = S["login_unverified"] = None
    st.toast("인증 메일을 다시 보냈어요")


def show_login() -> None:
    t = target() if S.get("after_login") else None
    if t and t[0] != "home":
        st.info(f"로그인하면 ‘{nav.ALL[t[0]][1]}’ 화면으로 돌아가 하던 일을 이어서 해요.", icon=":material/redo:")
    if S.get("login_notice"):
        st.success(S["login_notice"], icon=":material/check_circle:")
    with st.form("login_form", border=False):
        st.text_input("이메일", key="login_email", placeholder="you@example.com", autocomplete="email")
        st.text_input("비밀번호", key="login_pw", type="password", placeholder="비밀번호를 입력해 주세요")
        st.checkbox("로그인 상태 유지", key="login_keep")
        msg_box = st.empty()
        sent = st.form_submit_button("로그인", type="primary", width="stretch", icon=":material/login:")
    if sent:
        email, pw = S.get("login_email", "").strip(), S.get("login_pw", "")
        S["_keep_login"] = bool(S.get("login_keep"))
        S["login_notice"] = S["login_unverified"] = None
        out = None
        if not email or not pw:
            S["login_error"] = "이메일과 비밀번호를 모두 입력해 주세요."
        elif not valid_email(email):
            S["login_error"] = "이메일 주소를 한 번 더 확인해 주세요. 예) you@example.com"
        else:
            try:
                out = auth.login(email, pw)
                S["login_error"] = None
            except ApiError as e:
                S["login_error"] = e.message
                if e.code == "email_not_verified":
                    S["login_unverified"] = email
        if out:
            go_back()
    if S.get("login_error"):
        msg_box.error(S["login_error"], icon=":material/error:")
    if S.get("login_unverified"):
        if st.button("인증 메일 다시 받기", type="primary", key="login_unverified_go",
                     icon=":material/mark_email_unread:"):
            to_verify(S["login_unverified"])
            st.rerun()
    with st.container(horizontal=True, horizontal_alignment="distribute", gap="small"):
        if st.button("비밀번호 찾기", type="tertiary", key="login_to_reset", icon=":material/key:"):
            S["login_mode"] = "reset"
            S["login_error"] = S["login_unverified"] = None
            S["login_reset_email"] = S.get("login_email", "")
            st.rerun()
        if st.button("처음이에요 · 회원가입", type="tertiary", key="login_to_signup", icon=":material/person_add:"):
            S["login_mode"] = "signup"
            S["login_step"] = 1
            st.rerun()

    st.divider()
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.markdown("**간편 로그인**")
        st.markdown(ui.chip("2차에 열려요", "demo"), unsafe_allow_html=True)
    with st.container(horizontal=True, gap="small"):
        for name in ("구글", "카카오", "네이버"):
            st.button(name, key=f"login_social_{name}", disabled=True, width="stretch", help="2차에 열려요")
    admin_data.muted("구글 · 카카오 · 네이버 로그인은 2차에 열려요. 지금은 이메일로 로그인해 주세요.")
    if auth.dev_mode() and not SB:
        st.caption("로컬 시험 계정: explorer@example.com / sea12345 (회원) · admin@example.com / admin12345 (관리자)")


# ---------- 회원가입 ① 정보 입력 ----------
def _all_agree() -> None:
    for k in ("login_ag_terms", "login_ag_privacy", "login_ag_age", "login_ag_mkt"):
        S[k] = S.get("login_ag_all", False)


def show_signup1() -> None:
    err = S.get("login_su_error")
    field, msg = err if isinstance(err, (tuple, list)) else (("email", "dup") if err == "dup" else ("", ""))
    st.text_input("이메일", key="login_su_email", placeholder="you@example.com", autocomplete="email")
    if msg == "dup":
        st.error("이미 가입한 메일이에요. 로그인하거나 비밀번호를 찾아 주세요.", icon=":material/error:")
        with st.container(horizontal=True, gap="small"):
            if st.button("이 메일로 로그인하기", key="login_dup_login"):
                S["login_mode"], S["login_email"], S["login_su_error"] = "login", S.get("login_su_email", ""), None
                st.rerun()
            if st.button("비밀번호 찾기", key="login_dup_reset"):
                S["login_mode"], S["login_reset_email"], S["login_su_error"] = "reset", S.get("login_su_email", ""), None
                st.rerun()
    elif field == "email":
        st.error(msg, icon=":material/error:")
    st.text_input("비밀번호", key="login_su_pw", type="password", placeholder="영문과 숫자를 섞어 8자 이상")
    st.text_input("비밀번호 확인", key="login_su_pw2", type="password", placeholder="한 번 더 똑같이 입력해 주세요")
    if field == "pw":
        st.error(msg, icon=":material/error:")
    st.markdown("**약관 동의**")
    with st.container(border=True):
        st.checkbox("모두 동의해요", key="login_ag_all", on_change=_all_agree)
        st.checkbox("[필수] 이용약관에 동의해요", key="login_ag_terms")
        st.checkbox("[필수] 개인정보 수집 · 이용에 동의해요", key="login_ag_privacy")
        st.checkbox("[필수] 만 14세 이상이에요", key="login_ag_age",
                    help="만 14세 미만 어린이는 보호자 계정으로 함께 써 주세요.")
        st.checkbox("[선택] 바다 소식 메일 받기", key="login_ag_mkt")
        with st.expander("약관 내용 보기"):
            st.markdown("**이용약관** 회원은 다른 이용자를 존중하며, 생물을 해치거나 채집을 권하는 글을 올리지 않습니다.  \n"
                        "**개인정보** 이메일과 닉네임을 회원 확인과 알림에만 이용하며, 탈퇴하면 바로 파기합니다.  \n"
                        "**사진** 생물 알아보기에 올린 사진은 이름을 찾는 데만 쓰이며, 외부 AI 서비스로 전송됩니다.")
    required = all(S.get(k) for k in ("login_ag_terms", "login_ag_privacy", "login_ag_age"))
    if st.button("인증 메일 받기", type="primary", width="stretch", disabled=not required, key="login_su_next",
                 icon=":material/mail:"):
        email = S.get("login_su_email", "").strip()
        pw, pw2 = S.get("login_su_pw", ""), S.get("login_su_pw2", "")
        if not valid_email(email):
            S["login_su_error"] = ("email", "이메일 주소를 한 번 더 확인해 주세요. 예) you@example.com")
        elif len(pw) < 8 or not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
            S["login_su_error"] = ("pw", "비밀번호는 영문과 숫자를 섞어 8자 이상으로 만들어 주세요.")
        elif pw != pw2:
            S["login_su_error"] = ("pw", "비밀번호가 서로 달라요. ‘비밀번호 확인’에 한 번 더 똑같이 입력해 주세요.")
        else:
            try:
                out = auth.signup(email, pw, agree=True, marketing=bool(S.get("login_ag_mkt")))
            except ApiError as e:
                if e.code == "email_exists":
                    S["login_su_error"] = "dup"
                else:
                    S["login_su_error"] = ("pw" if "비밀번호" in e.message else "email", e.message)
            else:
                S["login_su_error"] = None
                # 링크를 다른 기기에서 눌렀을 때 '인증을 마쳤어요'로 바로 로그인하려고 잠깐 기억해요
                S["login_signup"] = {"email": out.get("email", email), "marketing": bool(S.get("login_ag_mkt")), "pw": pw}
                S["login_verify_dev"] = out.get("dev_link")
                S["login_verify_error"] = None
                S["login_step"] = 2
                st.toast("인증 메일을 보냈어요")
        st.rerun()
    if not required:
        st.caption("필수 항목 세 개에 동의하면 다음으로 넘어갈 수 있어요.")


# ---------- 회원가입 ② 메일 확인 (링크를 누르면 끝) ----------
def _resend(email: str) -> None:
    try:
        out = auth.resend_verify(email)
        S["login_verify_dev"] = out.get("dev_link")
        S["login_verify_error"] = None
        st.toast("인증 메일을 다시 보냈어요. 새 메일의 링크를 눌러 주세요.")
    except ApiError as e:
        S["login_verify_error"] = e.message


def show_signup2() -> None:
    info = S.get("login_signup", {})
    email = info.get("email", "")
    st.info(f"**{at(email)}** 로 인증 메일을 보냈어요. 메일 속 **[메일 인증하기]** 링크를 눌러 주세요.",
            icon=":material/mark_email_read:")
    admin_data.muted("링크를 누르면 인증이 끝나고 바로 다음 단계(닉네임 · 캐릭터)로 넘어가요. "
                     "휴대폰 등 다른 기기에서 눌렀다면 이 화면에서 ‘인증을 마쳤어요’를 눌러 주세요.")
    dev_link_box(S.get("login_verify_dev"))
    if S.get("login_verify_error"):
        st.error(S["login_verify_error"], icon=":material/error:")
    if st.button("인증을 마쳤어요", type="primary", width="stretch", key="login_verified", icon=":material/verified:"):
        if not info.get("pw"):  # 새로 고침 등으로 비밀번호를 잊었으면 로그인 화면에서 이어서 해요
            S["login_mode"], S["login_email"] = "login", email
            S["login_notice"] = "링크를 눌러 인증을 마쳤다면 이메일과 비밀번호로 로그인해 주세요."
            st.rerun()
        try:
            auth.login(email, info["pw"])
        except ApiError as e:
            S["login_verify_error"] = ("아직 인증이 끝나지 않았어요. 메일 속 링크를 먼저 눌러 주세요."
                                       if e.code == "email_not_verified" else e.message)
        else:
            info.pop("pw", None)
            S["login_step"] = 3
        st.rerun()
    st.space("small")
    with st.container(horizontal=True, gap="small"):
        if st.button("메일 다시 보내기", key="login_resend", icon=":material/refresh:"):
            _resend(email)
            st.rerun()
        if st.button("이메일 바꾸기", key="login_change_email", type="tertiary", icon=":material/edit:"):
            S["login_step"] = 1
            S["login_su_email"] = email
            S["login_verify_error"] = None
            st.rerun()
    with st.expander("메일이 오지 않나요?"):
        st.markdown("- 스팸함이나 프로모션함을 열어 봐 주세요.\n"
                    "- 메일 주소에 틀린 글자가 없는지 확인해 주세요.\n"
                    "- 몇 분이 지나도 없으면 ‘메일 다시 보내기’를 눌러 주세요.\n"
                    "- 링크는 한 번만 쓸 수 있어요. 이미 눌렀다면 ‘인증을 마쳤어요’를 눌러 주세요.")


# ---------- 회원가입 ③ 닉네임 · 캐릭터 ----------
def show_signup3() -> None:
    st.success("메일 인증을 마쳤어요. 마지막으로 나를 보여줄 이름과 캐릭터를 골라 주세요.", icon=":material/check_circle:")
    st.text_input("닉네임", key="login_nick", max_chars=10, placeholder="예) 모래성짓기",
                  help="2~10자. 커뮤니티와 수족관에서 이 이름으로 보여요.")
    S.setdefault("login_char", "🐢")
    st.markdown("**바다 캐릭터 고르기**")
    st.pills("바다 캐릭터", list(CHARS), key="login_char", required=True, label_visibility="collapsed",
             format_func=lambda c: f"{c} {CHARS[c]}")
    nick = S.get("login_nick", "").strip()
    with st.container(border=True):
        admin_data.item_row(S.get("login_char") or "🐢", nick or "닉네임", "다른 사람에게 이렇게 보여요", tone="sand", size=64)
    if S.get("login_nick_error"):
        st.error(S["login_nick_error"], icon=":material/error:")
    if st.button("가입 완료", type="primary", width="stretch", key="login_su_done", icon=":material/how_to_reg:"):
        char = S.get("login_char") or "🐢"
        if not 2 <= len(nick) <= 10:
            S["login_nick_error"] = "닉네임은 2~10자로 정해 주세요."
        else:
            try:
                auth.update_profile(nickname=nick, character=char)
            except ApiError as e:
                S["login_nick_error"] = ("가입을 마치려면 먼저 메일 인증을 해 주세요." if e.status == 401 else e.message)
            else:
                S["login_nick_error"] = None
                S.setdefault("login_signup", {}).update(nickname=nick, character=char)
                S["login_step"] = 4
        st.rerun()


def show_done() -> None:
    info = S.get("login_signup", {})
    me = auth.current_user() or {}
    nick = html.escape(me.get("nickname") or info.get("nickname", "바다 친구"))
    char = me.get("character") or info.get("character", "🐢")
    st.markdown(f'<div class="sia-celebrate"><div class="big">🎉</div><h3>가입을 축하해요!</h3>'
                f'<p>{char} <b>{nick}</b>님, 반가워요.<br>'
                f'이제 만난 바다 생물을 나의 수족관에 담을 수 있어요.</p></div>', unsafe_allow_html=True)
    st.space("small")
    t = target()
    if t and t[0] != "home":
        label = f"하던 일 이어서 하기 · {nav.ALL[t[0]][1]}"
        if st.button(label, type="primary", width="stretch", key="login_done_back", icon=":material/redo:"):
            go_back()
        if st.button("생물 알아보기", width="stretch", key="login_done_identify", icon=":material/photo_camera:"):
            reset_all()
            nav.go("identify")
    else:
        if st.button("첫 생물 알아보기", type="primary", width="stretch", key="login_done_identify",
                     icon=":material/photo_camera:"):
            reset_all()
            nav.go("identify")
        if st.button("홈으로", width="stretch", key="login_done_home", icon=":material/home:"):
            reset_all()
            nav.go("home")


def show_signup() -> None:
    if step <= 3:
        step_chips(step)
    {1: show_signup1, 2: show_signup2, 3: show_signup3}.get(step, show_done)()
    if step <= 2:
        st.divider()
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            ui.muted("이미 가입했나요?")
            if st.button("로그인하기", type="tertiary", key="login_su_to_login"):
                S["login_mode"] = "login"
                st.rerun()


# ---------- 비밀번호 찾기 ----------
def show_reset() -> None:
    if st.button("로그인으로 돌아가기", icon=":material/arrow_back:", type="tertiary", key="login_reset_back"):
        S["login_mode"] = "login"
        S["login_reset_sent"] = None
        st.rerun()
    st.markdown('<h2 class="sia-h2">비밀번호 찾기</h2>', unsafe_allow_html=True)
    admin_data.muted("가입한 이메일을 적어 주세요. 비밀번호를 새로 정하는 링크를 보내 드려요.")
    st.space("small")
    st.text_input("가입한 이메일", key="login_reset_email", placeholder="you@example.com")
    sent_to = S.get("login_reset_sent")
    if sent_to:
        st.success(f"**{at(sent_to)}** 로 메일을 보냈어요. 메일 속 **[비밀번호 다시 정하기]** 링크를 눌러 새 비밀번호를 정해 주세요.",
                   icon=":material/mark_email_read:")
        admin_data.muted("가입한 메일이라면 몇 분 안에 도착해요. 링크는 1시간 동안 한 번만 쓸 수 있어요. 메일이 없으면 스팸함을 확인해 주세요.")
        dev_link_box(S.get("login_reset_dev"))
        st.space("small")
    err = S.get("login_reset_error")
    if err:
        st.error(err, icon=":material/error:")
    label = "메일 다시 보내기" if sent_to else "재설정 메일 보내기"
    if st.button(label, type="secondary" if sent_to else "primary", width="stretch", key="login_reset_send",
                 icon=":material/send:"):
        email = S.get("login_reset_email", "").strip()
        if not valid_email(email):
            S["login_reset_error"] = "이메일 주소를 한 번 더 확인해 주세요. 예) you@example.com"
        else:
            try:
                out = auth.reset_password(email)
            except ApiError as e:
                S["login_reset_error"] = e.message
            else:
                S["login_reset_error"] = None
                S["login_reset_sent"] = out.get("email", email)
                S["login_reset_dev"] = out.get("dev_link")
                st.toast("재설정 메일을 보냈어요")
        st.rerun()
    if sent_to and st.button("로그인하러 가기", type="primary", width="stretch", key="login_reset_done",
                             icon=":material/login:"):
        S["login_mode"] = "login"
        S["login_email"] = sent_to
        S["login_reset_sent"] = None
        st.rerun()


# ---------- 이미 로그인한 경우 ----------
def show_logged_in() -> None:
    ui.page_header("로그인", "이미 로그인했어요.")
    col, _ = st.columns([3, 2])
    with col:
        with st.container(border=True):
            admin_data.item_row(user["character"], f"{user['nickname']}님, 반가워요", user.get("email", ""), tone="sand",
                                size=64)
            with st.container(horizontal=True, gap="small"):
                if st.button("하던 일 이어서 하기" if target() else "홈으로", type="primary", key="login_in_back"):
                    go_back()
                if st.button("내 정보", key="login_in_me", icon=":material/person:"):
                    nav.go("mypage")
                if st.button("다른 계정으로 로그인", key="login_in_switch", type="tertiary"):
                    auth.logout()
                    st.rerun()


# ---------- 화면 그리기 ----------
if user and not (mode == "signup" and step >= 3):
    show_logged_in()
else:
    titles = {"login": ("로그인", "로그인하면 만난 생물을 담고, 이야기를 나눌 수 있어요."),
              "signup": ("회원가입", "짧게 가입하고, 하던 일로 바로 돌아가요."),
              "reset": ("비밀번호 찾기", "걱정 마세요. 메일로 금방 다시 정할 수 있어요.")}
    ui.page_header(*titles.get(mode, titles["login"]))
    left, right = st.columns([5, 4], gap="large")
    with left:
        with st.container(border=True):
            if mode in ("login", "signup") and not (mode == "signup" and step == 4):
                S["login_tab"] = mode
                st.segmented_control("로그인 또는 회원가입", ["login", "signup"], key="login_tab", required=True,
                                     format_func={"login": "로그인", "signup": "회원가입"}.get,
                                     label_visibility="collapsed", width="stretch",
                                     on_change=lambda: S.update(login_mode=S.get("login_tab") or "login"))
            if mode == "signup":
                show_signup()
            elif mode == "reset":
                show_reset()
            else:
                show_login()
    with right:
        side_panel()
