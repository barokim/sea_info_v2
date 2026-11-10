"""U-18 내 정보 (이종민 담당).

프로필 · 내 활동 · 내 문의 · 설정 · (2차) 포인트 · 등급을 한 화면에서 봐요.

시안 캡처용: 주소에 ?shot=withdraw|withdraw2|password|edit|comments  (회원으로 보려면 &as=member)
데이터: /me/posts · /me/comments · /me/aquarium · /me/inquiries, 바꾸기: PATCH /auth/me · /auth/password/change · DELETE /auth/me
"""
import html

import streamlit as st

from components import nav, ui
from services import admin_data, auth, db
from services.api import ApiError

S = st.session_state
user = auth.current_user()
CHARS = admin_data.CHARACTERS
STATUS = {"접수": ("접수됨", ""), "처리 중": ("처리 중", "warn"), "완료": ("✓ 답변 완료", "ok")}


def close_dialog() -> None:
    for k in ("mypage_dialog", "mypage_wd_step", "mypage_wd_ok", "mypage_wd_word", "mypage_pw_error",
              "mypage_wd_error", "mypage_pw_sent"):
        S.pop(k, None)


# ---------- 시안 캡처용 상태 만들기 ----------
shot = st.query_params.get("shot")
if shot and S.get("_shot_mypage") != shot:
    S["_shot_mypage"] = shot
    close_dialog()
    if shot in ("withdraw", "withdraw2"):
        S["mypage_dialog"] = "withdraw"
        S["mypage_wd_step"] = 2 if shot == "withdraw2" else 1
        S["mypage_wd_ok"] = shot == "withdraw2"
    elif shot == "password":
        S["mypage_dialog"] = "password"
    elif shot == "edit":
        S["mypage_edit_open"] = True
    elif shot == "comments":
        S["mypage_act"] = "comments"

# ---------- 비회원 ----------
ui.page_header("내 정보", "프로필과 활동, 제보·건의 결과를 한곳에서 봐요.")
if not user:
    col, _ = st.columns([3, 2])
    with col:
        ui.empty_state("🐢", "로그인하면 내 프로필과 활동, 제보·건의 결과를 볼 수 있어요.")
        if st.button("로그인 / 회원가입", type="primary", width="stretch", key="mypage_login", icon=":material/login:"):
            nav.remember_here("mypage")
            S["after_login"] = ("mypage", {})
            nav.go("login")
        admin_data.muted("로그인 없이 보낸 제보·건의는 접수 번호로 확인할 수 있어요.")
        nav.link("report", "접수 번호로 결과 보기", icon=":material/campaign:")
    st.stop()

uid = user["id"]
try:
    cards = db.aquarium(uid)
    records = db.observations(uid)
    posts = admin_data.my_posts(uid)
    comments = admin_data.my_comments(uid)
except ApiError as e:
    st.error(e.message, icon=":material/cloud_off:")
    st.stop()
try:
    mine_inq = db.inquiries(uid)
except ApiError:  # 제보·건의 API(김바로)가 아직 없으면 빈 목록으로 보여줘요
    mine_inq = []

if S.pop("mypage_toast", None):
    st.toast(S.pop("mypage_toast_msg", "바꿨어요"))


def flash(msg: str) -> None:
    S["mypage_toast"], S["mypage_toast_msg"] = True, msg


def update_me(**fields) -> bool:
    """서버에 저장하고 내 정보를 새로 받아요. 실패하면 안내를 띄우고 False."""
    try:
        user.update(auth.update_profile(**fields))
        return True
    except ApiError as e:
        S["mypage_toast"], S["mypage_toast_msg"] = True, e.message
        return False


def toggle_public() -> None:
    want = bool(S.get("mypage_public"))
    if update_me(aquarium_public=want):
        flash("수족관을 공개했어요" if want else "수족관을 나만 보기로 바꿨어요")
    else:
        S["mypage_public"] = not want  # 저장하지 못했으면 스위치를 되돌려요


# ---------- 팝업: 회원 탈퇴 (두 번 확인) ----------
@st.dialog("회원 탈퇴", on_dismiss=close_dialog)
def withdraw_dialog() -> None:
    step = S.get("mypage_wd_step", 1)
    ui.chips(ui.chip(f"{step} / 2 단계", "warn"), ui.chip("한 번 더 확인해요" if step == 2 else "지워지는 내용 확인"))
    if step == 1:
        st.warning("탈퇴하면 아래 내용이 모두 지워지고 되돌릴 수 없어요.", icon=":material/warning:")
        st.markdown(f"- 나의 수족관 생물 카드 **{len(cards)}종**, 관찰 기록 **{len(records)}개**\n"
                    f"- 포인트 **{user.get('points', 0)}P**와 등급 ‘{user.get('grade', '-')}’\n"
                    f"- 내가 쓴 글 **{len(posts)}개**와 댓글 **{len(comments)}개**는 ‘탈퇴한 회원’ 이름으로 남아요")
        admin_data.muted("글을 지우고 싶다면 탈퇴 전에 먼저 지워 주세요.")
        st.selectbox("떠나는 이유 (선택)", ["골라 주세요", "자주 쓰지 않아요", "원하는 기능이 없어요", "AI 결과가 잘 안 맞아요",
                                        "다른 계정을 쓸게요", "기타"], key="mypage_wd_reason")
        st.checkbox("위 내용을 모두 확인했어요", key="mypage_wd_ok")
        with st.container(horizontal=True, gap="small"):
            if st.button("다음", type="primary", disabled=not S.get("mypage_wd_ok"), key="mypage_wd_next"):
                S["mypage_wd_step"] = 2
                st.rerun()
            if st.button("그만둘래요", key="mypage_wd_cancel1"):
                close_dialog()
                st.rerun()
    else:
        st.error("정말 탈퇴할까요? 이 단계가 마지막이에요. 누르면 바로 지워지고 되돌릴 수 없어요.", icon=":material/dangerous:")
        st.text_input("확인을 위해 ‘탈퇴’라고 적어 주세요", key="mypage_wd_word", placeholder="탈퇴")
        with st.container(horizontal=True, gap="small"):
            if st.button("탈퇴하기", disabled=S.get("mypage_wd_word", "").strip() != "탈퇴", key="mypage_wd_go",
                         icon=":material/person_remove:"):
                reason = S.get("mypage_wd_reason", "골라 주세요")
                try:
                    auth.withdraw("" if reason == "골라 주세요" else reason)
                except ApiError as e:
                    S["mypage_wd_error"] = e.message
                    st.rerun()
                close_dialog()
                db.clear_cache()
                nav.go("home")
        if S.get("mypage_wd_error"):
            st.error(S["mypage_wd_error"], icon=":material/error:")
            if st.button("그만둘래요", type="primary", key="mypage_wd_cancel2"):
                close_dialog()
                st.rerun()


# ---------- 팝업: 비밀번호 바꾸기 ----------
@st.dialog("비밀번호 바꾸기", on_dismiss=close_dialog)
def password_dialog() -> None:
    if user.get("provider") == "supabase" or auth.supabase_mode():
        password_by_mail()
        return
    st.text_input("지금 비밀번호", type="password", key="mypage_pw_now")
    st.text_input("새 비밀번호", type="password", key="mypage_pw_new", placeholder="영문과 숫자를 섞어 8자 이상")
    st.text_input("새 비밀번호 확인", type="password", key="mypage_pw_new2")
    if S.get("mypage_pw_error"):
        st.error(S["mypage_pw_error"], icon=":material/error:")
    with st.container(horizontal=True, gap="small"):
        if st.button("비밀번호 바꾸기", type="primary", key="mypage_pw_save"):
            now, new, new2 = (S.get(k, "") for k in ("mypage_pw_now", "mypage_pw_new", "mypage_pw_new2"))
            if not now:
                S["mypage_pw_error"] = "지금 쓰는 비밀번호를 먼저 입력해 주세요."
            elif len(new) < 8 or new.isdigit() or new.isalpha():
                S["mypage_pw_error"] = "새 비밀번호는 영문과 숫자를 섞어 8자 이상으로 만들어 주세요."
            elif new != new2:
                S["mypage_pw_error"] = "새 비밀번호가 서로 달라요. 한 번 더 똑같이 입력해 주세요."
            else:
                try:
                    out = auth.change_password(now, new)
                except ApiError as e:
                    S["mypage_pw_error"] = e.message
                else:
                    close_dialog()
                    for k in ("mypage_pw_now", "mypage_pw_new", "mypage_pw_new2"):
                        S.pop(k, None)
                    flash(out.get("message") or "비밀번호를 바꿨어요. 다음 로그인부터 새 비밀번호를 써 주세요.")
            st.rerun()
        if st.button("그만두기", key="mypage_pw_cancel"):
            close_dialog()
            st.rerun()
    admin_data.muted("비밀번호가 기억나지 않으면 로그아웃한 뒤 ‘비밀번호 찾기’를 눌러 주세요. 바꾸면 다른 기기의 로그인은 끝나요.")


def password_by_mail() -> None:
    """Supabase 계정: 비밀번호는 재설정 메일의 링크로 바꿔요."""
    st.info("이 계정은 비밀번호를 메일로 바꿔요. 아래 버튼을 누르면 가입한 메일로 재설정 링크를 보내 드려요.",
            icon=":material/mail_lock:")
    if S.get("mypage_pw_sent"):
        st.success(f"**{user.get('email', '')}** 로 메일을 보냈어요. 메일 속 링크를 눌러 새 비밀번호를 정해 주세요.",
                   icon=":material/mark_email_read:")
    if S.get("mypage_pw_error"):
        st.error(S["mypage_pw_error"], icon=":material/error:")
    with st.container(horizontal=True, gap="small"):
        if st.button("재설정 메일 보내기", type="primary", key="mypage_pw_mail", icon=":material/send:"):
            try:
                auth.reset_password(user.get("email", ""))
                S["mypage_pw_sent"], S["mypage_pw_error"] = True, None
            except ApiError as e:
                S["mypage_pw_error"] = e.message
            st.rerun()
        if st.button("닫기", key="mypage_pw_cancel"):
            close_dialog()
            st.rerun()


# ---------- 프로필 ----------
with st.container(border=True):
    left, right = st.columns([1, 1], vertical_alignment="center", gap="medium")
    with left:
        nick = html.escape(user["nickname"])
        st.markdown(f'<div class="sia-item">{ui.photo_html(user["character"], "sand", 88, width=88)}'
                    f'<div><h2 class="sia-h2">{nick}</h2><span class="sia-muted">{html.escape(user.get("email", ""))}'
                    f'</span></div></div>', unsafe_allow_html=True)
        st.space("small")
        ui.chips(ui.chip(user.get("grade", "새내기 탐험가"), "sea"),
                 ui.chip("수족관 공개 중", "ok") if user.get("aquarium_public") else ui.chip("수족관 나만 보기"),
                 ui.chip("관리자", "coral") if user.get("role") == "admin" else "")
    with right:
        with st.container(horizontal=True, gap="small"):
            st.metric("생물 카드", f"{len(cards)}종", border=True, width=90)
            st.metric("관찰 기록", f"{len(records)}개", border=True, width=90)
            st.metric("쓴 글", f"{len(posts)}개", border=True, width=90)
    with st.expander("프로필 바꾸기", icon=":material/edit:", expanded=bool(S.pop("mypage_edit_open", False))):
        S.setdefault("mypage_nick", user["nickname"])
        S.setdefault("mypage_char", user["character"] if user["character"] in CHARS else "🐢")
        c1, c2 = st.columns([1, 1], gap="medium")
        with c1:
            st.text_input("닉네임", key="mypage_nick", max_chars=10, help="2~10자. 커뮤니티와 수족관에서 이 이름으로 보여요.")
            st.text_input("이메일", value=user.get("email", ""), disabled=True, key="mypage_email")
            st.caption("이메일은 바꿀 수 없어요. 꼭 바꿔야 하면 제보·건의로 알려 주세요.")
        with c2:
            st.markdown("**바다 캐릭터**")
            st.pills("바다 캐릭터", list(CHARS), key="mypage_char", required=True, label_visibility="collapsed",
                     format_func=lambda c: f"{c} {CHARS[c]}")
        if S.get("mypage_nick_error"):
            st.error(S["mypage_nick_error"], icon=":material/error:")
        if st.button("프로필 저장", type="primary", key="mypage_save_profile", icon=":material/save:"):
            new = S.get("mypage_nick", "").strip()
            if not 2 <= len(new) <= 10:
                S["mypage_nick_error"] = "닉네임은 2~10자로 정해 주세요."
            else:
                try:
                    user.update(auth.update_profile(nickname=new, character=S.get("mypage_char") or user["character"]))
                except ApiError as e:
                    S["mypage_nick_error"] = e.message
                    S["mypage_edit_open"] = True
                else:
                    S["mypage_nick_error"] = None
                    db.clear_cache()
                    flash("프로필을 바꿨어요")
            st.rerun()

st.space("small")
main, side = st.columns([3, 2], gap="large")

# ---------- 내 활동 · 내 문의 ----------
with main:
    ui.section("내 활동")
    S.setdefault("mypage_act", "posts")
    act = st.segmented_control("내 활동 보기", ["posts", "comments"], key="mypage_act", required=True,
                               label_visibility="collapsed",
                               format_func={"posts": f"내가 쓴 글 {len(posts)}", "comments": f"내 댓글 {len(comments)}"}.get)
    if act == "posts":
        if not posts:
            ui.empty_state("🐚", "아직 쓴 글이 없어요. 만난 생물 이야기를 들려줄까요?", "글쓰기", "write", key="mypage_empty_write")
        for p in posts:
            emoji, tone = admin_data.post_look(p)
            with st.container(border=True):
                with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
                    admin_data.item_row(emoji, p["title"], f"{admin_data.board_name(p['board'])} · {p.get('created', '')} · "
                                f"공감 {p.get('likes', 0)} · 댓글 {p.get('comments', 0)}", tone=tone)
                    nav.link("community", "글 보기", icon=":material/arrow_forward:", post=p["id"])
                if p.get("hidden"):
                    ui.chips(ui.chip("✕ 운영자가 숨긴 글이에요", "danger"))
                    admin_data.muted("다른 사람에게 보이지 않아요. 궁금한 점은 제보·건의로 알려 주세요.")
    else:
        if not comments:
            ui.empty_state("🐚", "아직 남긴 댓글이 없어요.")
        for p, c in comments:
            with st.container(border=True):
                with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
                    admin_data.text_row(c["body"], f"‘{p['title']}’에 남긴 댓글 · {c.get('created', '')}")
                    nav.link("community", "글 보기", icon=":material/arrow_forward:", post=p["id"])
                if p.get("hidden"):
                    admin_data.muted("운영자가 숨긴 글에 남긴 댓글이에요. 다른 사람에게는 글이 보이지 않아요.")

    st.space("small")
    ui.section("내 문의", "제보·건의 하기", "report")
    if not mine_inq:
        ui.empty_state("🐚", "아직 보낸 제보·건의가 없어요.")
    for r in mine_inq:
        label, kind = STATUS.get(r.get("status", "접수"), (r.get("status", ""), ""))
        with st.container(border=True):
            ui.chips(ui.chip(label, kind), ui.chip(r.get("type", "")))
            st.markdown(f"**{html.escape(r['title'])}**")
            admin_data.muted(f"{r.get('date', '')} · 접수 번호 {r['id']}")
            if r.get("answer"):
                st.success(f"**운영자 답변** · {r['answer']}", icon=":material/support_agent:")
            else:
                admin_data.muted("답변을 준비하고 있어요. 답변이 오면 여기와 메일로 알려 드려요.")
            with st.expander("보낸 내용"):
                st.write(r.get("body", ""))

# ---------- 설정 · 포인트 ----------
with side:
    ui.section("설정")
    with st.container(border=True):
        S.setdefault("mypage_public", bool(user.get("aquarium_public")))
        st.toggle("내 수족관 공개", key="mypage_public", on_change=toggle_public)
        admin_data.muted("켜면 다른 사람이 내 생물 카드와 닉네임을 볼 수 있어요. 만난 장소와 메모는 보이지 않아요.")
        st.divider()
        if st.button("비밀번호 바꾸기", width="stretch", key="mypage_pw", icon=":material/lock:"):
            S["mypage_dialog"] = "password"
            st.rerun()
        if st.button("로그아웃", width="stretch", key="mypage_logout", icon=":material/logout:"):
            auth.logout()
            nav.go("home")
        if st.button("회원 탈퇴", type="tertiary", key="mypage_withdraw", icon=":material/person_remove:"):
            S["mypage_dialog"], S["mypage_wd_step"] = "withdraw", 1
            st.rerun()

    st.space("small")
    ui.section("포인트 · 등급")
    with st.container(border=True):
        ui.chips(ui.chip("2차에 열려요", "demo"))
        pts = int(user.get("points", 0) or 0)
        goal = 500
        st.markdown(f'<div class="sia-item" style="gap:32px"><div><span class="sia-muted">포인트</span>'
                    f'<h2 class="sia-h2">{pts}P</h2></div><div><span class="sia-muted">등급</span>'
                    f'<h2 class="sia-h2">{html.escape(user.get("grade", "새내기 탐험가"))}</h2></div></div>',
                    unsafe_allow_html=True)
        st.space("small")
        st.progress(min(pts / goal, 1.0), text=f"다음 등급 ‘바다 해설사’까지 {max(goal - pts, 0)}P")
        admin_data.muted("생물을 담고 이야기를 나누면 포인트가 쌓여요. 적립 내역은 2차에 볼 수 있어요.")
        st.button("적립 내역 보기", disabled=True, width="stretch", key="mypage_points", help="2차에 열려요")

# ---------- 팝업 띄우기 ----------
if S.get("mypage_dialog") == "withdraw":
    withdraw_dialog()
elif S.get("mypage_dialog") == "password":
    password_dialog()
