"""A-04 회원 관리 · 2차 화면 (이종민 담당).

검색(닉네임 · 이메일) → 회원 고르기 → 상세(가입일 · 글 수 · 신고 받은 수) → 이용 정지(기간 · 사유) / 정지 풀기
관리자 권한 지정은 최고 관리자만 할 수 있어요 (안내만).

시안 캡처용: 주소에 ?shot=selected|suspend (관리자로 보려면 &as=admin)
데이터: GET /admin/members · /admin/logs?screen=회원, 바꾸기: POST /admin/members/{id}/suspend · /unsuspend
"""
import html

import pandas as pd
import streamlit as st

from components import auth_gate, nav, ui
from services import admin_data
from services.api import ApiError

me = auth_gate.admin_only()
S = st.session_state
PERIODS = ["3일", "7일", "30일", "영구"]
WHY = ["스팸·광고 반복", "욕설·비방", "개인정보 노출", "도배", "기타"]


def close_dialog() -> None:
    S.pop("admin_members_dialog", None)


# ---------- 시안 캡처용 상태 만들기 ----------
shot = st.query_params.get("shot")
if shot and S.get("_shot_admin_members") != shot:
    S["_shot_admin_members"] = shot
    if shot in ("selected", "suspend"):
        S["admin_members_sel"] = "u_2"
        if shot == "suspend":
            S["admin_members_dialog"] = "suspend"
            S["admin_members_period"] = "7일"
            S["admin_members_why"] = "스팸·광고 반복"
            S["admin_members_memo"] = "자유 수다에 같은 홍보 글을 여러 번 올림"

if S.get("admin_members_toast"):
    st.toast(S.pop("admin_members_toast"))
if S.get("admin_members_error"):
    st.error(S.pop("admin_members_error"), icon=":material/error:")

try:
    everyone = admin_data.member_rows()
except ApiError as e:
    st.error(e.message, icon=":material/cloud_off:")
    st.stop()


def find(uid: str) -> dict | None:
    return next((u for u in everyone if u["id"] == uid), None)


# ---------- 팝업: 이용 정지 ----------
@st.dialog("이용 정지", on_dismiss=close_dialog)
def suspend_dialog(u: dict) -> None:
    admin_data.item_row(u.get("character", "🌊"), u.get("nickname", ""), "이 회원의 이용을 잠시 멈춰요", tone="sand", size=48)
    st.space("small")
    st.segmented_control("정지 기간", PERIODS, key="admin_members_period", required=True, width="stretch")
    st.selectbox("사유", WHY, key="admin_members_why")
    st.text_area("자세한 사유 (회원에게 보내는 메일에 들어가요)", key="admin_members_memo", max_chars=200,
                 placeholder="예) 같은 홍보 글을 여러 번 올렸어요.")
    period = S.get("admin_members_period") or "7일"
    st.info(f"{admin_data.suspend_until(period)} 글 · 댓글 · 공유를 할 수 없고, 보기만 할 수 있어요. 회원에게 알림 메일이 가요.",
            icon=":material/info:")
    with st.container(horizontal=True, gap="small"):
        if st.button("이용 정지하기", type="primary", key="admin_members_go", icon=":material/block:"):
            why = S.get("admin_members_why", "")
            memo = S.get("admin_members_memo", "").strip()
            try:
                admin_data.suspend(u["id"], period, why, memo)
                S["admin_members_toast"] = f"{u.get('nickname', '')}님의 이용을 정지했어요"
            except ApiError as e:
                S["admin_members_error"] = e.message
            close_dialog()
            st.rerun()
        if st.button("그만두기", key="admin_members_cancel"):
            close_dialog()
            st.rerun()


ui.page_header("회원 관리", "문제 있는 회원을 찾아 이용을 잠시 멈추거나 풀어요.")
members = everyone
n_sus = sum(1 for m in members if m["suspended"])
ui.chips(ui.chip("2차 화면", "demo"), ui.chip(f"회원 {len(members)}명"),
         ui.chip(f"이용 정지 {n_sus}명", "danger" if n_sus else ""))
st.space("small")

# ---------- 검색 · 목록 ----------
f1, f2 = st.columns([3, 2], gap="small")
with f1:
    q = st.text_input("검색", key="admin_members_q", placeholder="닉네임이나 이메일", icon=":material/search:")
with f2:
    status = st.selectbox("상태", ["전체", "이용 중", "이용 정지", "신고 받은 회원"], key="admin_members_status")

rows = []
for m in members:
    if q and q not in m["nickname"] and q.lower() not in m["email"].lower():
        continue
    if status == "이용 중" and m["suspended"] or status == "이용 정지" and not m["suspended"] or \
            status == "신고 받은 회원" and not m["reports"]:
        continue
    rows.append({"id": m["id"], "회원": f"{m['character']} {m['nickname']}", "이메일": admin_data.mask_email(m["email"]),
                 "가입일": m["joined"], "글": m["posts"], "신고 받음": m["reports"], "권한": m["role"],
                 "상태": ("✕ " if m["suspended"] else "✓ ") + m["status"]})
df = pd.DataFrame(rows, columns=["id", "회원", "이메일", "가입일", "글", "신고 받음", "권한", "상태"])
ids = df["id"].tolist()
sel_id = S.get("admin_members_sel")

if df.empty:
    ui.empty_state("🐚", "찾는 회원이 없어요. 닉네임이나 이메일을 다시 확인해 주세요.")
else:
    event = st.dataframe(df, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                         key="admin_members_table",
                         selection_default={"selection": {"rows": [ids.index(sel_id)]}} if sel_id in ids else None,
                         column_order=["회원", "이메일", "가입일", "글", "신고 받음", "권한", "상태"],
                         column_config={"글": st.column_config.NumberColumn(width="small"),
                                        "신고 받음": st.column_config.NumberColumn(width="small")})
    picked = list(event.selection.rows)
    if picked != S.get("_admin_members_prev"):
        prev = S.get("_admin_members_prev")
        S["_admin_members_prev"] = picked
        if picked:
            S["admin_members_sel"] = ids[picked[0]]
        elif prev:
            S["admin_members_sel"] = None
    st.caption("줄 왼쪽을 눌러 회원을 고르면 아래에 자세한 정보가 나와요. 이메일은 일부만 보여요.")

# ---------- 회원 상세 ----------
u = find(S.get("admin_members_sel") or "")
if u:
    m = u
    st.space("small")
    with st.container(border=True, key="admin_members_panel"):
        c1, c2 = st.columns([3, 2], gap="large")
        with c1:
            with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
                admin_data.item_row(m["character"], m["nickname"], f"{m['email'] or '-'} · 가입일 {m['joined']}", tone="sand", size=64)
                ui.chips(ui.chip(m["role"], "coral" if m["role"] == "관리자" else ""),
                         ui.chip(m["status"], "danger" if m["suspended"] else "ok"))
            with st.container(horizontal=True, gap="small"):
                st.metric("쓴 글", f"{m['posts']}개", border=True, width=110)
                st.metric("신고 받은 수", f"{m['reports']}회", border=True, width=130)
            if m["recent"]:
                st.markdown("**최근 글** " + " · ".join(f"‘{html.escape(t)}’" for t in m["recent"]))
            admin_data.muted(f"수족관 {'공개 중' if m['public'] else '나만 보기'}")
            if m["suspended"]:
                st.warning(f"{m['suspended']['until']} 이용 정지 중이에요 · 사유: {m['suspended']['reason']}",
                           icon=":material/block:")
        with c2:
            st.markdown("**이용 제한**")
            if m["role"] == "관리자":
                admin_data.muted("관리자 계정은 정지할 수 없어요.")
            elif m["id"] == me["id"]:
                admin_data.muted("내 계정은 정지할 수 없어요.")
            elif m["suspended"]:
                if st.button("정지 풀기", type="primary", width="stretch", key="admin_members_lift",
                             icon=":material/lock_open:"):
                    try:
                        admin_data.unsuspend(m["id"])
                        S["admin_members_toast"] = "이용 정지를 풀었어요"
                    except ApiError as e:
                        S["admin_members_error"] = e.message
                    st.rerun()
            elif st.button("이용 정지", type="primary", width="stretch", key="admin_members_suspend",
                           icon=":material/block:"):
                S["admin_members_dialog"] = "suspend"
                st.rerun()
            nav.link("admin_posts", "게시물·신고에서 글 찾기", icon=":material/flag:")
            st.divider()
            st.markdown("**권한**")
            st.button("운영 관리자로 지정", disabled=True, width="stretch", key="admin_members_role",
                      help="최고 관리자만 할 수 있어요")
            admin_data.muted("운영 관리자 지정은 최고 관리자만 할 수 있어요.")

# ---------- 회원 조치 기록 ----------
st.space("small")
ui.section("회원 조치 기록")
log = admin_data.log_rows(("회원",))
if log:
    st.dataframe(pd.DataFrame(log), hide_index=True, width="stretch")
else:
    admin_data.muted("아직 회원 조치 기록이 없어요. 이용 정지나 해제를 하면 여기에 남아요.")

if u and S.get("admin_members_dialog") == "suspend":
    suspend_dialog(u)
