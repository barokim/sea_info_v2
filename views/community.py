"""U-08 커뮤니티 · U-09 게시글 상세 (차유진 담당).

목록은 /community, 상세는 /community-post?post=<글 번호> 예요.
예전 /community?post=<글 번호> 주소도 상세로 연결해요. ?board=<게시판> 으로 탭을 고를 수 있어요.
게시판 탭 · 목록 형태 · 권한 · 운영 규칙은 모두 A-02 게시판 관리 설정을 그대로 따라요.

데이터는 FastAPI 서버에 있어요 (services/community_data.py). 공감 · 댓글 · 신고 · 지우기 검사는 서버가 해요.

시안 캡처용: ?shot=report (p1 신고 팝업, ?post= 로 다른 글 지정 가능) | empty (검색 결과 없음)
"""
import html
from datetime import datetime, timedelta, timezone

import streamlit as st

from components import auth_gate, fields, nav, ui
from services import api, auth, db
from services import community_data as cd
from services.api import ApiError

S = st.session_state
user = auth.current_user()
uid = user["id"] if user else None
admin = cd.is_admin(user)
CARD_W = 166  # 폰에서 두 장, PC에서 네 장
CONTROL_COLUMNS = [3, 1.3]  # 게시판 탭과 검색창의 너비를 맞춰요
REASON_HELP = {
    "스팸": "광고나 같은 글을 계속 올려요",
    "욕설": "욕이나 남을 깎아내리는 말이 있어요",
    "개인정보": "얼굴 · 전화번호 · 사는 곳 같은 정보가 보여요",
    "기타": "그 밖의 문제가 있어요",
}

# 다른 화면 · 이전 동작에서 넘어온 짧은 알림
if S.get("community_toast"):
    st.toast(S.pop("community_toast"))

post_id = st.query_params.get("post")

# ---------- 시안 캡처용 상태 만들기 ----------
shot = st.query_params.get("shot")
if shot and S.get("_community_shot") != shot:
    S["_community_shot"] = shot
    if shot == "report":
        if not post_id:
            post_id = "p1"
            st.query_params["post"] = post_id
        S["community_report_open"] = post_id
    elif shot == "empty":
        S["community_board"] = S["community_tab"] = "obs"
        S["community_q"] = "돌고래"


def esc(text: str) -> str:
    return html.escape(text or "").replace("\n", "<br>")


def author_of(p: dict) -> dict:
    """글쓴이 (글에 같이 온 정보 + 등급 · 역할)."""
    a = dict(p.get("author") or db.user(p["user"]))
    a.update(role=p.get("author_role", "user"), grade=p.get("author_grade", ""))
    return a


def photo_src(p: dict) -> str:
    return api.file_url(p.get("photo_url") or "")


def post_created(p: dict, with_time: bool = False) -> str:
    """API의 실제 작성 시각을 한국 시간 기준 날짜 또는 날짜·시간으로 표시해요."""
    try:
        created = datetime.fromisoformat(p.get("created_at") or "")
    except (TypeError, ValueError):
        return "날짜 정보 없음"
    kst = timezone(timedelta(hours=9))
    created = created.replace(tzinfo=kst) if created.tzinfo is None else created.astimezone(kst)
    return created.strftime("%Y.%m.%d %H:%M" if with_time else "%Y.%m.%d")


def open_post(p: dict, board_id: str) -> None:
    nav.remember_here("community", board=board_id)
    nav.go("community", post=p["id"])


def post_click_target(p: dict, board_id: str) -> None:
    """투명한 버튼을 게시글 영역 전체에 겹쳐 클릭과 키보드 이동을 지원해요."""
    if st.button(f"{p['title']} 상세 보기", key=f"community_open_{p['id']}", width="stretch"):
        open_post(p, board_id)


def counts(p: dict, b: dict) -> str:
    rules = cd.opt(b, "rules")
    bits = []
    if rules["like"]:
        bits.append(f":material/favorite: {p.get('likes', 0)}")
    if rules["comment"]:
        bits.append(f":material/chat_bubble: {p.get('comments', 0)}")
    return " &nbsp; ".join(bits)


# ---------- U-08 목록 ----------
def write_button(b: dict) -> None:
    if b["id"] == "obs":
        if st.button("생물 알아보고 공유하기", type="primary", icon=":material/photo_camera:",
                     key="community_write_obs") \
                and auth_gate.login_required("관찰 이야기를 공유할 수 있어요", here="identify"):
            nav.go("identify")
    elif b["perm"]["write"] == "관리자":
        if admin and st.button("공지 쓰기", type="primary", icon=":material/edit:", key="community_write_admin"):
            nav.go("write", board=b["id"])
    elif st.button("글쓰기", type="primary", icon=":material/edit:", key="community_write") \
            and auth_gate.login_required("글을 쓸 수 있어요", here="write", board=b["id"]):
        nav.go("write", board=b["id"])


def card_grid(rows: list[dict], b: dict) -> None:
    if b["id"] == "obs":
        observation_grid(rows, b)
        return
    with st.container(horizontal=True, gap="small"):
        for p in rows:
            sp = db.species(p.get("species") or "")
            u = author_of(p)
            with st.container(border=True, width=CARD_W, gap="small", key=f"community_post_{p['id']}"):
                if photo_src(p):
                    st.image(photo_src(p), width="stretch")
                else:
                    ui.photo(sp["emoji"] if sp else "🐚", tone=sp["tone"] if sp else "aqua", height=118)
                if sp:
                    ui.chips(ui.chip(sp["name"], "sea"))
                st.markdown(f"<b>{esc(p['title'])}</b>", unsafe_allow_html=True)
                st.caption(f"{u['character']} {u['nickname']}  \n{post_created(p)} &nbsp; {counts(p, b)}")
                post_click_target(p, b["id"])


def observation_grid(rows: list[dict], b: dict) -> None:
    """관찰 이야기는 3열로 배치하고 사진과 글 영역의 높이를 맞춰요."""
    st.html("""
        <style>
        .observation-card-body {
            display: grid;
            grid-template-rows: 200px 32px 56px 48px;
            gap: 12px;
            min-width: 0;
        }
        .observation-card-photo {
            width: 100%; height: 200px; overflow: hidden; border-radius: 14px;
        }
        .observation-card-photo img {
            display: block; width: 100%; height: 100%; object-fit: cover;
        }
        .observation-card-badge { overflow: hidden; }
        .observation-card-title {
            margin: 0; font-size: 18px; line-height: 28px; font-weight: 700;
            display: -webkit-box; -webkit-line-clamp: 2;
            -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: anywhere;
        }
        .observation-card-meta { color: #4A6274; font-size: 14px; line-height: 24px; }
        .observation-card-meta > div {
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        </style>
    """)
    for start in range(0, len(rows), 3):
        columns = st.columns(3, gap="small")
        for column, p in zip(columns, rows[start:start + 3]):
            sp = db.species(p.get("species") or "")
            u = author_of(p)
            src = photo_src(p)
            photo = (f'<img src="{html.escape(src, quote=True)}" alt="게시글 사진">' if src
                     else ui.photo_html(sp["emoji"] if sp else "🐚",
                                        tone=sp["tone"] if sp else "aqua", height=200))
            badge = ui.chip(sp["name"], "sea") if sp else ""
            rules = cd.opt(b, "rules")
            meta = [post_created(p)]
            if rules["like"]:
                meta.append(f"♡ {int(p.get('likes') or 0)}")
            if rules["comment"]:
                meta.append(f"댓글 {int(p.get('comments') or 0)}")
            with column:
                with st.container(border=True, gap="small", key=f"community_post_{p['id']}"):
                    st.html(
                        '<div class="observation-card-body">'
                        f'<div class="observation-card-photo">{photo}</div>'
                        f'<div class="observation-card-badge">{badge}</div>'
                        f'<p class="observation-card-title" title="{html.escape(p["title"], quote=True)}">'
                        f'{html.escape(p["title"])}</p>'
                        '<div class="observation-card-meta">'
                        f'<div>{html.escape(u["character"])} {html.escape(u["nickname"])}</div>'
                        f'<div>{" · ".join(meta)}</div></div></div>'
                    )
                    post_click_target(p, b["id"])


def list_rows(rows: list[dict], b: dict) -> None:
    for p in rows:
        u = author_of(p)
        sp = db.species(p.get("species") or "")
        with st.container(border=True, key=f"community_post_{p['id']}"):
            with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center",
                              gap="small"):
                with st.container(gap="small"):
                    tags = []
                    if p.get("pinned") and cd.opt(b, "pin_notice"):
                        tags.append(ui.chip("공지", "sea"))
                    if b["type"] == "질문형":
                        tags.append(ui.chip("답변 있어요", "ok") if p.get("comments")
                                    else ui.chip("답변 기다려요", "warn"))
                    if sp:
                        tags.append(ui.chip(sp["name"]))
                    if p.get("extra") and b.get("fields"):
                        first = next((f for f in fields.active(b["fields"])
                                      if not fields.is_empty(p["extra"].get(f["key"]))), None)
                        if first:
                            tags.append(ui.chip(f"{first['label']} "
                                                f"{fields.format_value(first, p['extra'][first['key']])}"))
                    if tags:
                        ui.chips(*tags)
                    st.markdown(f"<b style='font-size:17px'>{esc(p['title'])}</b>", unsafe_allow_html=True)
                    st.caption(f"{u['character']} {u['nickname']} · {post_created(p)} &nbsp; {counts(p, b)}")
            post_click_target(p, b["id"])


def show_list() -> None:
    st.html("""
        <style>
        [class*="st-key-community_post_"] {
            position: relative;
            transition: border-color .15s, box-shadow .15s;
        }
        [class*="st-key-community_post_"]:hover {
            border-color: #0B7285;
            box-shadow: 0 2px 10px rgba(11, 114, 133, .12);
        }
        [class*="st-key-community_post_"] [class*="st-key-community_open_"] {
            position: absolute; inset: 0; z-index: 1;
            width: 100%; height: 100%; margin: 0;
        }
        [class*="st-key-community_open_"] [data-testid="stButton"] {
            width: 100%; height: 100%;
        }
        [class*="st-key-community_open_"] button {
            width: 100%; height: 100%; padding: 0;
            background: transparent !important; border: 0 !important;
            border-radius: 14px; cursor: pointer;
        }
        [class*="st-key-community_open_"] button p { opacity: 0; }
        [class*="st-key-community_open_"] button:focus-visible {
            outline: 3px solid #0B7285; outline-offset: -3px;
        }
        </style>
    """)
    boards = cd.visible_boards(user)
    ids = [b["id"] for b in boards]
    notice = None
    qp = st.query_params.get("board")
    if qp and qp != S.get("_community_qp_board"):
        S["_community_qp_board"] = qp
        if qp in ids:
            S["community_board"] = S["community_tab"] = qp
        elif db.board(qp):
            notice = f"‘{db.board(qp)['name']}’ 게시판은 지금 볼 수 없어요. 다른 게시판을 둘러보세요."

    ui.page_header("커뮤니티", "바다에서 만난 친구 이야기를 구경하고, 묻고, 수다를 나눠요.")
    if notice:
        st.info(notice, icon=":material/info:")
    if not ids:
        ui.empty_state("🐚", "지금 볼 수 있는 게시판이 없어요. 잠시 뒤에 다시 와 주세요.")
        return
    cur = S.get("community_board", "obs")
    cur = cur if cur in ids else ids[0]
    if S.get("community_tab") not in ids:
        S["community_tab"] = cur
    st.html("""
        <style>
        .st-key-community_board_tabs button {
            flex: 1 1 0;
            min-height: 48px;
        }
        .st-key-community_board_tabs button p { font-size: 16px; }
        </style>
    """)
    tab_column, _ = st.columns(CONTROL_COLUMNS, vertical_alignment="center")
    with tab_column:
        with st.container(key="community_board_tabs"):
            picked = st.segmented_control(
                "게시판", ids, format_func=lambda i: db.board(i)["name"], key="community_tab",
                required=True, wrap=True, label_visibility="collapsed", width="stretch",
            )
    bid = picked or cur
    S["community_board"] = bid
    if st.query_params.get("board") != bid:
        st.query_params["board"] = bid
        S["_community_qp_board"] = bid
    b = db.board(bid)

    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        st.markdown(f'<p class="sia-muted">{esc(b.get("desc", ""))}</p>', unsafe_allow_html=True)
        write_button(b)

    if not admin and not cd.can(user, b["perm"]["read"]):
        if b["perm"]["read"] == "회원" and not user:
            ui.empty_state("🔒", "이 게시판의 글은 로그인하면 읽을 수 있어요.")
            if st.button("로그인 / 회원가입", type="primary", key="community_list_gate"):
                auth_gate.login_required("이 게시판의 글을 읽을 수 있어요", here="community", board=bid)
        else:
            ui.empty_state("🔒", "이 게시판의 글은 운영자만 읽을 수 있어요.")
        return

    where = " · ".join(cd.opt(b, "search") or ["제목"])
    c1, c2 = st.columns(CONTROL_COLUMNS, vertical_alignment="center")
    with c1:
        q = st.text_input("검색", key="community_q", placeholder=f"{where}(으)로 찾아요",
                          icon=":material/search:", label_visibility="collapsed")
    with c2:
        sort = st.segmented_control("정렬", list(cd.SORTS), format_func=cd.SORTS.get,
                                    default=cd.opt(b, "sort"), required=True, key=f"community_sort_{bid}",
                                    label_visibility="collapsed")

    size = int(cd.opt(b, "page_size") or 20)
    n_key = f"community_n_{bid}"
    filters = (q.strip(), sort or "latest", size)
    if S.get(f"{n_key}_filters") != filters:
        S[f"{n_key}_filters"] = filters
        S[n_key] = size
    n = S.get(n_key, size)
    # 표시할 글과 다음 1개를 조회하고, API의 요청당 500개 한도는 offset으로 나눠 가져와요.
    rows = []
    try:
        for offset in range(0, n + 1, 500):
            limit = min(500, n + 1 - offset)
            batch = cd.list_posts(b, q, sort or "latest", limit=limit, offset=offset)
            rows.extend(batch)
            if len(batch) < limit:
                break
    except ApiError as e:
        st.error(e.message, icon=":material/error:")
        if st.button("다시 불러오기", key="community_retry"):
            st.rerun()
        return

    if not rows:
        if q.strip():
            ui.empty_state("🐚", f"‘{q.strip()}’에 맞는 글이 없어요. 다른 말로 찾아보거나 검색어를 지워 주세요.")
            st.button("검색어 지우기", icon=":material/close:", key="community_clear",
                      on_click=lambda: S.update(community_q=""))
        else:
            ui.empty_state("🐚", "아직 글이 없어요. 첫 글을 남겨 볼까요?")
        return
    if q.strip():
        ui.muted(f"‘{q.strip()}’ 검색 결과 {n}개 표시 중" if len(rows) > n
                 else f"‘{q.strip()}’ 검색 결과 {len(rows)}개")
    if b.get("layout") == "card":
        card_grid(rows[:n], b)
    else:
        list_rows(rows[:n], b)
    if len(rows) > n:
        if st.button(f"더 보기 (현재 {n}개)", width="stretch", key="community_more",
                     icon=":material/expand_more:"):
            S[n_key] = n + size
            st.rerun()
    else:
        st.caption(f"글 {len(rows)}개를 모두 봤어요.")


# ---------- U-09 상세 ----------
@st.dialog("이 글 신고하기", on_dismiss=lambda: S.pop("community_report_open", None))
def report_dialog(pid: str) -> None:
    p, _ = cd.get_post(pid)
    if not p:
        st.info("지워졌거나 숨겨진 글이에요.", icon=":material/info:")
        return
    st.markdown(f"**{esc(p['title'])}**", unsafe_allow_html=True)
    if uid and cd.reported(pid, uid):
        st.info("이미 신고한 글이에요. 운영자가 확인하고 있어요.", icon=":material/info:")
        return
    reason = st.radio("어떤 문제가 있나요?", cd.REPORT_REASONS, index=None, key="community_report_reason",
                      captions=[REASON_HELP[r] for r in cd.REPORT_REASONS])
    if reason == "기타":
        st.text_input("어떤 문제인지 적어 주세요 (선택)", max_chars=100, key="community_report_etc")
    st.caption("신고는 한 글에 한 번만 할 수 있어요. 누가 신고했는지는 글쓴이에게 알려지지 않아요.")
    if not user:
        st.info("로그인하면 신고할 수 있어요.", icon=":material/lock:")
    with st.container(horizontal=True, gap="small"):
        if st.button("신고하기", type="primary", disabled=not reason, key="community_report_send"):
            if not user:
                nav.remember_here("community", post=pid)
                S["after_login"] = S.get("back_to")
                nav.go("login")
            try:
                msg = cd.report(pid, reason, S.get("community_report_etc", "") if reason == "기타" else "")
            except ApiError as e:
                st.error(e.message, icon=":material/error:")
            else:
                S.pop("community_report_open", None)
                S["community_toast"] = msg
                st.rerun()
        if st.button("취소", key="community_report_cancel"):
            S.pop("community_report_open", None)
            st.rerun()


@st.dialog("글 지우기")
def delete_dialog(p: dict) -> None:
    pid = p["id"]
    st.markdown("이 글을 지울까요? 지우면 되돌릴 수 없어요.")
    if p["board"] == "obs":
        st.caption("수족관의 관찰 기록은 그대로 남고 ‘나만 보기’로 바뀌어요.")
    with st.container(horizontal=True, gap="small"):
        if st.button("지우기", type="primary", icon=":material/delete:", key="community_del_ok"):
            try:
                cd.delete_post(pid)
            except ApiError as e:
                st.error(e.message, icon=":material/error:")
            else:
                S["community_toast"] = "글을 지웠어요"
                nav.go("community", board=p["board"])
        if st.button("그만두기", key="community_del_cancel"):
            st.rerun()


def go_back(p: dict) -> None:
    key, params = S.get("back_to", (None, {}))
    if key is None or key in ("login", "write") or (key == "community" and params.get("post")):
        nav.go("community", board=p["board"])
    nav.back("community")


def del_comment(cid: str) -> None:
    try:
        cd.delete_comment(cid)
        S["community_toast"] = "댓글을 지웠어요"
    except ApiError as e:
        S["community_toast"] = e.message


def submit_reply(pid: str, parent_id: str) -> None:
    key = f"community_reply_body_{parent_id}"
    try:
        cd.add_comment(pid, S.get(key) or "", parent_id=parent_id)
    except ApiError as e:
        S[f"community_reply_error_{parent_id}"] = e.message
        return
    S.pop(key, None)
    S.pop(f"community_reply_error_{parent_id}", None)
    S.pop("community_reply_open", None)
    S["community_toast"] = "답글을 달았어요"


def reply_form(pid: str, parent_id: str) -> None:
    with st.form(f"community_reply_form_{parent_id}", border=True):
        st.text_area("답글 쓰기", max_chars=300, height=90, key=f"community_reply_body_{parent_id}",
                     placeholder="이 댓글에 답글을 남겨 주세요")
        if S.get(f"community_reply_error_{parent_id}"):
            st.error(S[f"community_reply_error_{parent_id}"])
        with st.container(horizontal=True, gap="small"):
            st.form_submit_button("답글 달기", type="primary", icon=":material/reply:",
                                  on_click=submit_reply, args=(pid, parent_id))
            st.form_submit_button("취소", on_click=lambda: S.pop("community_reply_open", None))


def show_comments(p: dict, b: dict, *, read_only: bool = False) -> None:
    pid = p["id"]
    try:
        cm = cd.comments_for(p)
    except ApiError as e:
        st.info(e.message, icon=":material/info:")
        return
    st.html('<div id="community-comments" style="scroll-margin-top:80px"></div>')
    st.html("""<style>
        [class*="st-key-community_comment_row_"],
        [class*="st-key-community_reply_row_"] {
            border-bottom: 1px solid #C8DEE2;
            padding-bottom: 12px;
        }
        [class*="st-key-community_reply_row_"] {
            margin-left: 20px;
            background: #F5FAFB;
            border-left: 2px solid #C8DEE2;
            border-radius: 8px;
            padding: 10px 12px 12px;
        }
        [class*="st-key-community_comment_meta_"] button {
            min-height: 24px !important; height: 24px;
            padding: 0 4px !important; color: #6B8291;
        }
        [class*="st-key-community_comment_meta_"] button p {
            font-size: 12px !important; line-height: 20px;
        }
    </style>""")
    if not cm:
        ui.muted("아직 댓글이 없어요." if read_only else "아직 댓글이 없어요. 첫 댓글을 남겨 볼까요?")
    level = b["perm"]["comment"]
    can_reply = not read_only and (cd.can(user, level) or (not user and level == "회원"))
    for c in cm:
        is_reply = bool(c.get("parent_id"))
        deleted = bool(c.get("deleted"))
        row_type = "reply" if is_reply else "comment"
        with st.container(gap="small", key=f"community_{row_type}_row_{c['id']}"):
            if deleted:
                st.caption("삭제된 댓글이에요.")
                continue
            cu = c.get("author") or db.user(c["user"])
            st.html(
                '<div style="padding-top:6px;font-size:15px;line-height:1.5;overflow-wrap:anywhere">'
                f'{"↳ " if is_reply else ""}<strong>{html.escape(cu["nickname"])}</strong>'
                f'<div style="margin:4px 0">{esc(c["body"])}</div></div>'
            )
            with st.container(horizontal=True, width="content", gap="small", vertical_alignment="center",
                              key=f"community_comment_meta_{c['id']}"):
                st.html(f'<span style="font-size:12px;line-height:24px;color:#6B8291;white-space:nowrap">'
                        f'{post_created(c, with_time=True)}</span>', width="content")
                if can_reply and not is_reply:
                    if st.button("답글", type="tertiary", icon=":material/reply:", key=f"community_reply_{c['id']}"):
                        if auth_gate.login_required("답글을 남길 수 있어요", here="community", post=pid):
                            S["community_reply_open"] = (pid, c["id"])
                if uid and (c["user"] == uid or admin):
                    st.button("지우기", type="tertiary", icon=":material/delete:", key=f"community_cdel_{c['id']}",
                              on_click=del_comment, args=(c["id"],))
            if can_reply and user and not is_reply and S.get("community_reply_open") == (pid, c["id"]):
                reply_form(pid, c["id"])

    if read_only:
        ui.muted("지금은 기존 댓글만 볼 수 있어요.")
        return
    if cd.can(user, level):
        with st.form("community_cform", clear_on_submit=True, border=False):
            body = st.text_area("댓글 쓰기", max_chars=300, height=90, placeholder="따뜻한 한마디를 남겨 주세요",
                                key="community_cbody")
            if st.form_submit_button("댓글 달기", type="primary", icon=":material/send:"):
                try:  # 빈 댓글 · 금칙어 · 권한은 서버가 검사해요
                    cd.add_comment(pid, body)
                except ApiError as e:
                    st.error(e.message)
                else:
                    S["community_toast"] = "댓글을 달았어요"
                    st.rerun()
    elif level == "회원" and not user:
        with st.container(border=True):
            ui.muted("로그인하면 댓글을 달 수 있어요. 쓰던 글 화면으로 다시 돌아와요.")
            if st.button("로그인하고 댓글 달기", icon=":material/login:", key="community_cgate") \
                    and auth_gate.login_required("댓글을 달 수 있어요", here="community", post=pid):
                pass
    else:
        ui.muted(f"{b['name']}에는 운영자만 댓글을 달 수 있어요.")


def side_panel(p: dict) -> None:
    sp = db.species(p.get("species") or "")
    if sp:
        with st.container(border=True):
            st.markdown("**이 생물은요**")
            ui.item_row(sp["emoji"], sp["name"], sp["summary"], tone=sp["tone"])
            ui.safety_badge(sp["safety"], with_reason=False)
            st.caption(f"{sp['safety']['reason']} · 안전 정보는 참고용이에요.")
            st.markdown(f"**재미있는 사실** · {esc(sp['info']['fun_fact'])}", unsafe_allow_html=True)
            nav.link("identify", "나도 생물 알아보기", icon=":material/photo_camera:")


def show_detail(pid: str) -> None:
    p, gate = cd.get_post(pid)
    b = db.board(p["board"]) if p else None
    if st.button("목록으로", icon=":material/arrow_back:", type="tertiary", key="community_back"):
        if p:
            go_back(p)
        nav.go("community", **({"board": gate["board"]} if gate else {}))
    if gate:  # 읽기 권한이 없어요 (서버가 막았어요)
        gb = db.board(gate["board"]) or {"name": "커뮤니티"}
        ui.page_header(gb["name"])
        if gate["level"] == "회원" and not user:
            ui.empty_state("🔒", "이 게시판의 글은 로그인하면 읽을 수 있어요.")
            if st.button("로그인 / 회원가입", type="primary", key="community_read_gate") \
                    and auth_gate.login_required("이 글을 읽을 수 있어요", here="community", post=pid):
                pass
        else:
            ui.empty_state("🔒", gate["message"])
        return
    closed = b is not None and b["status"] != "운영 중"
    mine = bool(p and uid == p["user"])
    if not p or not b or ((p.get("hidden") or closed) and not (admin or mine)):
        ui.page_header("글을 볼 수 없어요")
        ui.empty_state("🐚", "지워졌거나 잠시 숨겨진 글이에요. 목록에서 다른 글을 둘러보세요.")
        return
    if not (admin or mine) and not cd.can(user, b["perm"]["read"]):
        ui.page_header(b["name"])
        ui.empty_state("🔒", "이 게시판의 글은 로그인하면 읽을 수 있어요.")
        if st.button("로그인 / 회원가입", type="primary", key="community_read_gate") \
                and auth_gate.login_required("이 글을 읽을 수 있어요", here="community", post=pid):
            pass
        return

    sp = db.species(p.get("species") or "")
    author = author_of(p)
    rules = cd.opt(b, "rules")
    interaction_locked = bool((p.get("hidden") or closed) and not admin)

    if p.get("hidden"):
        st.warning("신고가 쌓여 고객 화면에서 숨겨진 글이에요. 관리자와 글쓴이만 볼 수 있어요. "
                   "관리자가 게시물·신고 관리에서 복구할 수 있어요.", icon=":material/visibility_off:")
    elif closed:
        st.warning(f"‘{b['status']}’ 상태인 게시판의 글이에요. 고객 화면에는 보이지 않아요.",
                   icon=":material/visibility_off:")

    tags = [ui.chip(b["name"])]
    if sp:
        tags.append(ui.chip(sp["name"], "sea"))
    if p.get("pinned"):
        tags.append(ui.chip("공지", "sea"))
    if p.get("edited"):
        tags.append(ui.chip("고친 글"))
    ui.chips(*tags)
    ui.page_header(p["title"])
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        if mine:
            nav.link("aquarium", f"{author['character']} {author['nickname']}")
        elif author.get("role") == "admin":
            st.markdown(f"**{author['character']} {esc(author['nickname'])}**", unsafe_allow_html=True)
        else:
            nav.link("user_aquarium", f"{author['character']} {author['nickname']}", u=author["id"])
        meta = post_created(p, with_time=True)
        if p.get("place_level") == "region" and p.get("place"):
            meta += f" · :material/location_on: {p['place']}"
        st.caption(meta)

    if sp:
        main, side = st.columns([3, 2], gap="large")
    else:
        main, side = st.container(), None
    with main:
        if photo_src(p):
            st.image(photo_src(p), width="stretch")
        elif sp:
            ui.photo(sp["emoji"], tone=sp["tone"], height=300)
        st.markdown(f"<p style='font-size:16px;line-height:1.6;margin:.25rem 0'>{esc(p.get('body', ''))}</p>",
                    unsafe_allow_html=True)
        fields.show(b.get("fields"), p.get("extra"))

        st.space(32)
        with st.container(horizontal=True, horizontal_alignment="distribute", gap="small",
                          vertical_alignment="center"):
            with st.container(horizontal=True, width="content", gap="small", vertical_alignment="center"):
                if rules["like"] and not interaction_locked:
                    liked = bool(uid and cd.is_liked(pid))
                    if st.button(f"공감 {p.get('likes', 0)}", icon=":material/favorite:", key="community_like",
                                 type="primary" if liked else "tertiary") \
                            and auth_gate.login_required("공감할 수 있어요", here="community", post=pid):
                        try:
                            S["community_toast"] = "공감했어요" if cd.toggle_like(pid)["liked"] else "공감을 취소했어요"
                        except ApiError as e:
                            S["community_toast"] = e.message
                        st.rerun()
                if rules["comment"]:
                    st.html(
                        '<style>.community-comment-link {'
                        'display:inline-flex;align-items:center;gap:6px;min-height:44px;padding:0 8px;'
                        'color:#12344D;text-decoration:none !important;border-radius:8px;font-size:16px;}'
                        '.community-comment-link:hover {background:#EAF6F7;color:#0B7285;}'
                        '.community-comment-link:focus-visible {outline:2px solid #0B7285;}'
                        '</style>'
                        '<a class="community-comment-link" href="#community-comments" target="_self">'
                        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                        'stroke-width="1.7" aria-hidden="true">'
                        '<path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-2 2V11.5a9.5 9.5 0 0 1 19 0Z"/>'
                        '</svg>'
                        f'댓글 <strong>{int(p.get("comments") or 0)}</strong></a>',
                        width="content",
                    )
            with st.container(horizontal=True, width="content", gap="small", vertical_alignment="center"):
                if mine or admin:
                    if not (closed and not admin) and st.button("고치기", icon=":material/edit:", key="community_edit", type="tertiary"):
                        nav.go("write", edit=pid)
                    if st.button("지우기", icon=":material/delete:", key="community_delete", type="tertiary"):
                        delete_dialog(p)
                if rules["report"] and not mine and not interaction_locked:
                    done = bool(uid and cd.reported(pid))
                    if st.button("신고했어요" if done else "신고", icon=":material/flag:", type="tertiary",
                                 disabled=done, key="community_report") \
                            and auth_gate.login_required("이 글을 신고할 수 있어요", here="community", post=pid):
                        S["community_report_open"] = pid

        st.space("small")
        if rules["comment"]:
            st.html("""<style>
                .st-key-community_comments_panel {
                    background: #EAF6F7;
                    border: 1px solid #D5E9EC;
                    border-radius: 16px;
                    padding: 20px;
                }
                @media (max-width: 640px) {
                    .st-key-community_comments_panel { padding: 14px; }
                }
            </style>""")
            with st.container(key="community_comments_panel"):
                st.markdown("**댓글**")
                show_comments(p, b, read_only=interaction_locked)
        else:
            ui.muted("이 게시판은 댓글을 받지 않아요.")
    if side is not None:
        with side:
            side_panel(p)

    if S.get("community_report_open") == pid:
        report_dialog(pid)


# ---------- 화면 그리기 ----------
if post_id:
    if not globals().get("_COMMUNITY_DETAIL", False):
        nav.go("community_detail", **dict(st.query_params))
    show_detail(post_id)
else:
    if globals().get("_COMMUNITY_DETAIL", False):
        nav.go("community")
    show_list()
