"""A-03 게시물 · 신고 관리 (이종민 담당).

게시물 목록(검색 · 게시판 · 상태) → 한 줄 고르기 → [숨기기] [복구] [삭제]
신고 처리 → [숨기기] [문제없음],  조치 기록(누가 · 언제 · 무엇을 · 왜)은 서버 AdminLog에 남아요
데이터: GET /admin/posts · /admin/reports · /admin/logs, 바꾸기: POST /admin/posts/{id}/hide|restore · DELETE /admin/posts/{id}
        · POST /admin/reports/{post_id}/resolve

시안 캡처용: 주소에 ?shot=selected|delete (관리자로 보려면 &as=admin),  ?post=p9 로 그 글을 골라서 열어요
"""
import html

import pandas as pd
import streamlit as st

from components import auth_gate, nav, ui
from services import admin_data, db
from services.api import ApiError

me = auth_gate.admin_only()
S = st.session_state
REASONS = admin_data.ACTION_REASONS


def close_dialog() -> None:
    S.pop("admin_posts_dialog", None)


def flash(msg: str) -> None:
    S["admin_posts_toast"] = msg


# ---------- 시안 캡처용 상태 · 바로 열기 ----------
shot = st.query_params.get("shot")
if shot and S.get("_shot_admin_posts") != shot:
    S["_shot_admin_posts"] = shot
    if shot in ("selected", "delete"):
        S["admin_posts_sel"] = "p9"
        S["admin_posts_reason"] = "스팸·광고"
        if shot == "delete":
            S["admin_posts_dialog"] = "delete"
focus = st.query_params.get("post")
if focus and S.get("_admin_posts_focus") != focus and db.post(focus):
    S["_admin_posts_focus"] = focus
    S["admin_posts_sel"] = focus

if S.get("admin_posts_toast"):
    st.toast(S.pop("admin_posts_toast"))
if S.get("admin_posts_error"):
    st.error(S.pop("admin_posts_error"), icon=":material/error:")


def act(fn, *args) -> None:
    """서버에 조치를 보내고 안내를 띄운 뒤 다시 그려요. 실패하면 서버의 안내 문구를 보여줘요."""
    try:
        flash(fn(*args) or "처리했어요")
    except ApiError as e:
        S["admin_posts_error"] = e.message
    st.rerun()


# 필터 값은 위젯보다 먼저 읽어요 (위쪽 숫자 꼬리표에 쓰려고)
try:
    listing = admin_data.admin_posts(S.get("admin_posts_q", ""), S.get("admin_posts_board", "all"),
                                     S.get("admin_posts_status", "전체"))
    all_reports = admin_data.reports()
except ApiError as e:
    st.error(e.message, icon=":material/cloud_off:")
    st.stop()
items = listing["items"]


def find_post(pid: str) -> dict | None:
    hit = next((p for p in items if p["id"] == pid), None)
    if hit or not pid:
        return hit
    p = db.post(pid)  # 필터 밖의 글 (관리자는 숨긴 글도 받아요)
    if not p:
        return None
    return {**p, "author_nickname": db.user(p["user"])["nickname"], "board_name": admin_data.board_name(p["board"]),
            "pending_reports": sum(r["count"] for r in all_reports if r["post"] == pid and r["status"] == "대기")}


# ---------- 팝업: 글 지우기 ----------
@st.dialog("글 지우기", on_dismiss=close_dialog)
def delete_dialog(p: dict) -> None:
    st.markdown(f"**‘{html.escape(p['title'])}’** 글을 지울까요?")
    st.error("지우면 되돌릴 수 없어요. 댓글과 신고 기록도 함께 지워져요.", icon=":material/delete_forever:")
    admin_data.muted("숨기기만 해도 다른 사람에게는 보이지 않아요. 숨긴 글은 나중에 복구할 수 있어요.")
    why = st.selectbox("지우는 이유", REASONS, key="admin_posts_del_reason")
    with st.container(horizontal=True, gap="small"):
        if st.button("지우기", key="admin_posts_del_go", icon=":material/delete:"):
            close_dialog()
            S["admin_posts_sel"] = None
            act(admin_data.delete_post, p["id"], why)
        if st.button("그만두기", type="primary", key="admin_posts_del_cancel"):
            close_dialog()
            st.rerun()


ui.page_header("게시물·신고 관리", "문제 있는 글과 신고를 빠르게 처리해요. 게시판 설정은 ‘게시판 관리’에서 해요.")
pending = [r for r in all_reports if admin_data.report_status(r) == "대기"]
hidden_n = listing["hidden"]
ui.chips(ui.chip(f"전체 글 {listing['total']}개"), ui.chip(f"숨긴 글 {hidden_n}개", "warn" if hidden_n else ""),
         ui.chip(f"대기 중인 신고 {len(pending)}건", "danger" if pending else "ok"))
st.space("small")

# ---------- 게시물 목록 ----------
ui.section("게시물 목록")
f1, f2, f3 = st.columns([3, 2, 2], gap="small")
with f1:
    q = st.text_input("검색", key="admin_posts_q", placeholder="제목이나 작성자 닉네임", icon=":material/search:")
with f2:
    boards = {"all": "전체 게시판", **{b["id"]: b["name"] for b in db.boards(active_only=False)}}
    board = st.selectbox("게시판", list(boards), format_func=boards.get, key="admin_posts_board")
with f3:
    status = st.selectbox("상태", ["전체", "공개 중", "숨김", "신고 있음"], key="admin_posts_status")

rows = []
for p in items:  # 검색 · 게시판 · 상태 필터는 서버가 적용했어요
    rows.append({"id": p["id"], "게시판": p.get("board_name") or p["board"], "제목": p["title"],
                 "작성자": p.get("author_nickname", ""), "작성": p.get("created", ""), "공감": p.get("likes", 0),
                 "댓글": p.get("comments", 0), "신고": p.get("report_count", 0),
                 "상태": "✕ 숨김" if p.get("hidden") else "✓ 공개 중"})
df = pd.DataFrame(rows, columns=["id", "게시판", "제목", "작성자", "작성", "공감", "댓글", "신고", "상태"])

sel_id = S.get("admin_posts_sel")
ids = df["id"].tolist()
default = {"selection": {"rows": [ids.index(sel_id)]}} if sel_id in ids else None
if df.empty:
    ui.empty_state("🐚", "조건에 맞는 글이 없어요. 검색어나 필터를 바꿔 보세요.")
else:
    event = st.dataframe(
        df, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
        key="admin_posts_table", selection_default=default, height=35 * (len(df) + 1) + 3,
        column_order=["게시판", "제목", "작성자", "작성", "공감", "댓글", "신고", "상태"],
        column_config={"제목": st.column_config.TextColumn(width="medium"),
                       "공감": st.column_config.NumberColumn(width="small"),
                       "댓글": st.column_config.NumberColumn(width="small"),
                       "신고": st.column_config.NumberColumn(width="small")})
    picked = list(event.selection.rows)
    if picked != S.get("_admin_posts_prev"):
        prev = S.get("_admin_posts_prev")
        S["_admin_posts_prev"] = picked
        if picked:
            S["admin_posts_sel"] = ids[picked[0]]
        elif prev:  # 사용자가 선택을 풀었을 때만 비워요
            S["admin_posts_sel"] = None
    st.caption("줄 왼쪽을 눌러 글을 고르면 아래에서 숨기기 · 복구 · 삭제를 할 수 있어요.")

# ---------- 고른 글 처리 ----------
sel = find_post(S.get("admin_posts_sel") or "")
if sel:
    emoji, tone = admin_data.post_look(sel)
    with st.container(border=True, key="admin_posts_panel"):
        with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
            st.markdown("**고른 글**")
            ui.chips(ui.chip("✕ 숨김", "danger") if sel.get("hidden") else ui.chip("✓ 공개 중", "ok"),
                     ui.chip(f"신고 {sel.get('report_count', 0)}회", "warn"),
                     ui.chip(f"대기 {sel['pending_reports']}건", "danger") if sel.get("pending_reports") else "")
        c1, c2 = st.columns([3, 2], gap="large")
        with c1:
            admin_data.item_row(emoji, sel["title"], f"{sel.get('board_name') or sel['board']} · "
                                f"{sel.get('author_nickname', '')} · {sel.get('created', '')}", tone=tone)
            st.markdown(f"> {html.escape(sel.get('body', ''))}")
            nav.link("community", "사용자 화면에서 보기", icon=":material/open_in_new:", post=sel["id"])
        with c2:
            why = st.selectbox("조치 사유 (기록에 남아요)", REASONS, key="admin_posts_reason")
            with st.container(horizontal=True, gap="small"):
                if st.button("숨기기", type="primary", disabled=bool(sel.get("hidden")), key="admin_posts_hide",
                             icon=":material/visibility_off:"):
                    act(admin_data.hide_post, sel["id"], why)
                if st.button("복구", type="primary" if sel.get("hidden") else "secondary",
                             disabled=not sel.get("hidden"), key="admin_posts_restore", icon=":material/visibility:"):
                    act(admin_data.restore_post, sel["id"], why)
                if st.button("삭제", key="admin_posts_delete", icon=":material/delete:"):
                    S["admin_posts_dialog"] = "delete"
                    st.rerun()
            admin_data.muted("숨기면 목록에서 빠지고, 쓴 사람에게는 ‘운영자가 숨긴 글’로 보여요.")

st.space("small")
left, right = st.container(), st.container()

# ---------- 신고 처리 ----------
with left:
    ui.section("신고 처리")
    limit = db.settings()["report_hide"]
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        ui.muted(f"같은 글에 신고가 {limit}번 쌓이면 자동으로 숨겨져요.")
        nav.link("admin_settings", "기준 바꾸기", icon=":material/settings:")
    if not pending:
        ui.empty_state("🐚", "처리할 신고가 없어요.")
    grid = st.container(horizontal=True, gap="medium")
    for i, r in enumerate(pending):
        emoji, tone = admin_data.post_look(r)
        with grid, st.container(border=True, width=340):
            reasons = " · ".join(f"{x['reason']} {x['count']}" for x in r.get("reasons", [])[1:])
            ui.chips(ui.chip(r.get("reason", ""), "danger"), ui.chip(f"신고 {r.get('count', 1)}회", "warn"),
                     ui.chip(r.get("date", "")), ui.chip("✕ 숨김", "danger") if r.get("hidden") else "")
            if r.get("deleted"):
                admin_data.muted("이미 지워진 글이에요.")
                if st.button("목록에서 정리", key=f"admin_posts_rclean_{i}"):
                    act(admin_data.resolve_report, r["post"], "dismiss", "이미 지워진 글")
                continue
            admin_data.item_row(emoji, r["title"], f"{r.get('board', '')} · {r.get('author', '')} · {r.get('created', '')}",
                                tone=tone, size=48)
            admin_data.muted(f"미리보기 · {r.get('body', '')}" + (f"  (다른 사유: {reasons})" if reasons else ""))
            with st.container(horizontal=True, gap="small"):
                if st.button("숨기기", type="primary", key=f"admin_posts_rhide_{i}_{r['post']}",
                             icon=":material/visibility_off:"):
                    act(admin_data.resolve_report, r["post"], "hide")
                if st.button("문제없음", key=f"admin_posts_rok_{i}_{r['post']}", icon=":material/check:"):
                    act(admin_data.resolve_report, r["post"], "dismiss")
                if st.button("목록에서 보기", type="tertiary", key=f"admin_posts_rsel_{i}_{r['post']}"):
                    S["admin_posts_sel"] = r["post"]
                    st.rerun()
    done = [r for r in all_reports if admin_data.report_status(r) != "대기"]
    if done:
        with st.expander(f"처리한 신고 {sum(r['count'] for r in done)}건"):
            for r in done:
                admin_data.muted(f"{r.get('date', '')} · {r.get('title', '(지워진 글)')} · {r.get('reason', '')} "
                                 f"{r.get('count', 1)}건 → {admin_data.report_status(r)}")

# ---------- 조치 기록 ----------
with right:
    st.space("small")
    ui.section("조치 기록")
    log = admin_data.log_rows(("게시물", "신고"))
    if log:
        st.dataframe(pd.DataFrame(log), hide_index=True, width="stretch",
                     column_order=["언제", "누가", "무엇을", "대상", "왜"])
    else:
        admin_data.muted("아직 조치 기록이 없어요.")
    admin_data.muted("누가 · 언제 · 무엇을 · 왜 했는지 모두 남아요. 기록은 지울 수 없어요.")

if sel and S.get("admin_posts_dialog") == "delete":
    delete_dialog(sel)
