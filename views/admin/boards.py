"""A-02 게시판 관리 (차유진 담당).

코드를 고치지 않고 게시판을 만들고, 게시판마다 사용자 정의 항목을 붙여요.
바꾼 내용은 FastAPI 서버(/admin/boards …)가 검사해서 저장하고, 커뮤니티 탭 · 글쓰기 화면에 곧바로 보여요.
변경 기록은 서버의 AdminLog(screen="게시판 관리")에 남아요. 서버 안내는 그 칸 아래에 보여줘요.

시안 캡처용: ?shot=field_dialog (다이빙 기록에 항목 추가 팝업) | field_errors (팝업 저장 검사 안내)
            | new_board (새 게시판 만들기 양식)
"""
import pandas as pd
import streamlit as st

from backend.schemas import community as rules
from components import auth_gate, fields, ui
from services import db
from services import community_data as cd
from services.api import ApiError

me = auth_gate.admin_only()
S = st.session_state

PERM_DEFAULT = {"list": "모두", "read": "모두", "write": "회원", "comment": "회원", "photo": "회원"}
NEW_DEFAULT = {"name": "", "id": "", "desc": "", "type": "일반형", "status": "준비 중", "layout": "list",
               "perm": PERM_DEFAULT, "fields": []}
SAMPLE_NEW = {"name": "갯벌 체험 후기", "id": "tidal", "desc": "갯벌 체험을 다녀온 이야기와 준비물 팁을 나눠요",
              "type": "사진형", "layout": "card", "status": "준비 중", "perm": PERM_DEFAULT, "fields": []}
STATUS_HELP = {
    "준비 중": "고객 화면에 아직 안 보여요. 항목을 다 붙인 뒤 ‘운영 중’으로 바꿔요.",
    "운영 중": "커뮤니티 탭에 보이고 글을 쓸 수 있어요.",
    "일시 중지": "고객 화면에서 잠시 사라져요. 글은 그대로 남아요.",
    "보관": "고객 화면에서 사라지고 더 쓸 수 없어요. 글은 그대로 남아요.",
}

if S.get("boards_toast"):
    st.toast(S.pop("boards_toast"))


# ---------- 시안 캡처용 상태 만들기 ----------
def open_fd(bid: str, idx: int | None) -> None:
    """항목 팝업 열기: 팝업 입력칸에 원래 값(또는 빈 값)을 채워 둬요."""
    b = db.board(bid)
    f = b["fields"][idx] if idx is not None else {"type": "short", "required": False}
    t = f.get("type", "short")
    S["boards_fd"] = {"board": bid, "idx": idx}
    S["boards_fd_errs"] = {}
    S["boards_fd_label"] = f.get("label", "")
    S["boards_fd_key"] = f.get("key", "")
    S["boards_fd_type"] = t
    S["boards_fd_req"] = bool(f.get("required"))
    S["boards_fd_help"] = f.get("help", "")
    S["boards_fd_order"] = (idx + 1) if idx is not None else len(b["fields"]) + 1
    S["boards_fd_maxlen"] = int(f.get("max_len") or fields.DEFAULT_LEN.get(t, 50))
    S["boards_fd_min"] = float(f["min"]) if t == "number" and f.get("min") is not None else None
    S["boards_fd_max"] = float(f["max"]) if t == "number" and f.get("max") is not None else None
    S["boards_fd_dmin"] = fields._date(f.get("min")) if t == "date" else None
    S["boards_fd_dmax"] = fields._date(f.get("max")) if t == "date" else None
    S["boards_fd_opts"] = "\n".join(f.get("options") or [])
    S["boards_fd_maxsel"] = f.get("max_select")


shot = st.query_params.get("shot")
if shot and S.get("_boards_shot") != shot:
    S["_boards_shot"] = shot
    if shot in ("field_dialog", "field_errors"):
        S["boards_sel"] = "dive"
        S["boards_pane"] = "사용자 정의 항목"
        open_fd("dive", None)
        if shot == "field_dialog":
            S.update(boards_fd_label="함께 본 생물", boards_fd_key="seen", boards_fd_type="multi",
                     boards_fd_opts="보라성게\n별불가사리\n군소\n말미잘\n소라게", boards_fd_maxsel=3,
                     boards_fd_help="여러 개 고를 수 있어요")
        else:
            S.update(boards_fd_label="", boards_fd_key="depth", boards_fd_type="number",
                     boards_fd_min=30.0, boards_fd_max=10.0, boards_fd_req=True)
            S["_boards_fd_check"] = True  # 서버 검사 결과를 받아서 보여줘요 (빈 이름이라 저장되지 않아요)
    elif shot == "new_board":
        S["boards_new"] = True
        S["boards_new_draft"] = SAMPLE_NEW


# ---------- 게시판 목록 (순서 · 상태) ----------
def save_table() -> None:
    state = S.get(f"boards_editor_{S.get('boards_tv', 0)}") or {}
    edits = state.get("edited_rows", {})
    rows = db.boards(active_only=False)
    S["boards_tv"] = S.get("boards_tv", 0) + 1  # 표를 새로 그려요
    if not edits:
        S["boards_toast"] = "바꾼 내용이 없어요"
        return
    order = {b["id"]: b["order"] for b in rows}
    status, moved = {}, set()
    for i, ch in edits.items():
        b = rows[int(i)]
        if ch.get("상태") and ch["상태"] != b["status"]:
            status[b["id"]] = ch["상태"]
        if ch.get("순서") is not None and int(ch["순서"]) != b["order"]:
            order[b["id"]] = int(ch["순서"])
            moved.add(b["id"])
    ids = sorted(order, key=lambda k: (order[k], 0 if k in moved else 1))
    try:  # 순서와 상태를 한 번에 저장해요 (하나라도 실패하면 둘 다 그대로)
        cd.save_order(ids, status)
        S["boards_toast"] = "순서와 상태를 저장했어요"
    except ApiError as e:
        S["boards_toast"] = e.message


def board_table() -> None:
    rows = db.boards(active_only=False)
    df = pd.DataFrame([{
        "순서": b["order"], "이름": b["name"], "고유 주소": b["id"], "유형": b["type"],
        "목록 형태": cd.LAYOUTS.get(b.get("layout"), "목록형"), "상태": b["status"],
        "글 수": cd.count_posts(b["id"]), "추가 항목": len(fields.active(b.get("fields"))),
        "구분": "기본" if b.get("system") else "추가",
    } for b in rows])
    key = f"boards_editor_{S.get('boards_tv', 0)}"
    st.data_editor(
        df, key=key, hide_index=True, width="stretch",
        disabled=["이름", "고유 주소", "유형", "목록 형태", "글 수", "추가 항목", "구분"],
        column_config={
            "순서": st.column_config.NumberColumn("순서", min_value=1, max_value=len(rows), step=1, width="small",
                                                help="숫자가 작을수록 커뮤니티 탭 앞쪽에 보여요"),
            "상태": st.column_config.SelectboxColumn("상태", options=list(cd.STATUSES), required=True,
                                                   help="일시 중지 · 보관은 고객 화면에서 사라지지만 글은 남아요"),
            "글 수": st.column_config.NumberColumn("글 수", width="small"),
            "추가 항목": st.column_config.NumberColumn("추가 항목", width="small"),
        })
    changed = bool((S.get(key) or {}).get("edited_rows"))
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.button("순서 · 상태 저장하기", icon=":material/save:", key="boards_table_save", on_click=save_table,
                  type="primary" if changed else "secondary", disabled=not changed)
        st.caption("표에서 ‘순서’와 ‘상태’ 칸을 눌러 바꾼 뒤 저장해요. 일시 중지 · 보관은 고객 화면에서 사라지지만 글은 그대로 남아요."
                   if not changed else "저장하지 않은 변경이 있어요.")


# ---------- 게시판 만들기 · 고치기 양식 ----------
FORM_ATTRS = ("name", "slug", "desc", "type", "manager", "period", "status", "layout", "page_size", "sort",
              "search", "pin", "r_comment", "r_like", "r_report", "interval") + tuple(f"perm_{k}" for k in cd.PERM_NAMES)


def read_form(prefix: str) -> dict:
    return {a: S.get(f"{prefix}_{a}") for a in FORM_ATTRS}


FIELD_ERR_SHOWN = ("name", "slug", "period", "search")


def save_board(prefix: str, bid: str | None) -> None:
    v = read_form(prefix)
    data = cd.board_payload(v, is_new=bid is None)
    try:
        if bid is None:
            new = cd.create_board(data)
        else:
            b = db.board(bid)
            after = {**b, **data, "period": " ~ ".join(data["period"]) if data["period"] else ""}
            if not data["manager"]:
                after["manager"] = b.get("manager")
            if all(rules.board_summary(b, a) == rules.board_summary(after, a) for a in rules.LOG_ATTRS):
                S.pop("boards_form_errs", None)
                S["boards_toast"] = "바꾼 내용이 없어요"
                return
            cd.update_board(bid, data)
    except cd.Problem as e:
        S["boards_form_errs"] = {"prefix": prefix, "errs": cd.board_errors(e)}
        return
    except ApiError as e:
        S["boards_form_errs"] = {"prefix": prefix, "errs": {"_other": e.message}}
        return
    S.pop("boards_form_errs", None)
    if bid is None:
        S["boards_new"] = False
        S.pop("boards_new_draft", None)
        S["boards_sel"] = new["id"]
        S["boards_pane"] = "사용자 정의 항목"
        S["boards_toast"] = f"‘{new['name']}’ 게시판을 만들었어요"
    else:
        S["boards_toast"] = "설정을 저장했어요"
    S["boards_ver"] = S.get("boards_ver", 0) + 1


def board_form(prefix: str, b: dict, is_new: bool) -> None:
    fe = S.get("boards_form_errs") or {}
    errs = fe.get("errs", {}) if fe.get("prefix") == prefix else {}
    rule = cd.opt(b, "rules")
    period = cd.opt(b, "period")
    with st.form(f"{prefix}_form", border=False):
        c1, c2 = st.columns(2)
        with c1:
            st.text_input("게시판 이름 *", value=b.get("name", ""), max_chars=20, key=f"{prefix}_name",
                          placeholder="예) 갯벌 체험 후기")
            fields.error_text(errs.get("name"))
        with c2:
            st.text_input("고유 주소 (영문) *", value=b.get("id", ""), max_chars=20, key=f"{prefix}_slug",
                          placeholder="예) tidal", disabled=not is_new,
                          help="주소에 community?board=○○ 로 쓰여요. 만든 뒤에는 바꿀 수 없어요.")
            fields.error_text(errs.get("slug"))
        st.text_area("설명", value=b.get("desc", ""), max_chars=80, height=68, key=f"{prefix}_desc",
                     placeholder="커뮤니티 탭 아래에 한 줄로 보여요")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.selectbox("유형", cd.BOARD_TYPES, index=cd.BOARD_TYPES.index(b.get("type", "일반형")),
                         key=f"{prefix}_type", help="사진형은 사진을 크게, 질문형은 ‘답변 기다려요’ 표시가 붙어요.")
        with c2:
            st.text_input("담당자", value=cd.opt(b, "manager") or me["nickname"], max_chars=20,
                          key=f"{prefix}_manager")
        with c3:
            st.date_input("운영 기간 (선택)",
                          value=tuple(fields._date(x) for x in period) if period else (),
                          format="YYYY.MM.DD", key=f"{prefix}_period")
            fields.error_text(errs.get("period"))

        st.markdown("**권한** · 누가 할 수 있는지 골라요. 기본은 읽기 모두, 쓰기 회원이에요.")
        cols = st.columns(5)
        for col, (k, label) in zip(cols, cd.PERM_NAMES.items()):
            with col:
                st.selectbox(label, cd.PERM_LEVELS, index=cd.PERM_LEVELS.index(b["perm"][k]),
                             key=f"{prefix}_perm_{k}")

        st.markdown("**상태**")
        st.segmented_control("상태", cd.STATUSES, default=b.get("status", "준비 중"), required=True,
                             key=f"{prefix}_status", label_visibility="collapsed")
        st.caption(" / ".join(f"{k}: {v}" for k, v in STATUS_HELP.items() if k in ("준비 중", "일시 중지", "보관")))

        st.markdown("**목록 설정**")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.radio("목록 형태", list(cd.LAYOUTS), format_func=cd.LAYOUTS.get, horizontal=True,
                     index=list(cd.LAYOUTS).index(b.get("layout", "list")), key=f"{prefix}_layout")
        with c2:
            st.number_input("한 페이지 개수", min_value=5, max_value=50, step=5, value=int(cd.opt(b, "page_size")),
                            key=f"{prefix}_page_size", help="이만큼 보여주고 [더 보기]로 이어서 보여줘요")
        with c3:
            st.selectbox("기본 정렬", list(cd.SORTS), format_func=cd.SORTS.get,
                         index=list(cd.SORTS).index(cd.opt(b, "sort")), key=f"{prefix}_sort")
        c1, c2 = st.columns([2, 1], vertical_alignment="center")
        with c1:
            st.multiselect("검색 항목", cd.SEARCH_FIELDS, default=cd.opt(b, "search"), key=f"{prefix}_search")
            fields.error_text(errs.get("search"))
        with c2:
            st.toggle("공지 맨 위에 고정", value=bool(cd.opt(b, "pin_notice")), key=f"{prefix}_pin")

        st.markdown("**운영 규칙**")
        with st.container(horizontal=True, gap="medium", vertical_alignment="center"):
            st.toggle("댓글 받기", value=rule["comment"], key=f"{prefix}_r_comment")
            st.toggle("공감 받기", value=rule["like"], key=f"{prefix}_r_like")
            st.toggle("신고 받기", value=rule["report"], key=f"{prefix}_r_report")
        st.number_input("연속 글쓰기 간격 (초)", min_value=0, max_value=600, step=10, value=int(rule["interval"]),
                        key=f"{prefix}_interval", help="같은 사람이 이 시간 안에 또 글을 올리지 못해요(도배 막기). 0이면 제한 없음.")
        if errs:
            more = " ".join(v for k, v in errs.items() if k not in FIELD_ERR_SHOWN)
            st.error("저장하지 못했어요. 빨간 안내를 확인해 주세요. 입력한 내용은 그대로 있어요." + (f" {more}" if more else ""),
                     icon=":material/error:")
        with st.container(horizontal=True, gap="small"):
            st.form_submit_button("게시판 만들기" if is_new else "설정 저장하기", type="primary",
                                  icon=":material/add:" if is_new else ":material/save:",
                                  on_click=save_board, args=(prefix, None if is_new else b["id"]))
            if is_new:
                st.form_submit_button("닫기", on_click=close_new)


def close_new() -> None:
    S["boards_new"] = False
    S.pop("boards_new_draft", None)
    S.pop("boards_form_errs", None)


def open_new() -> None:
    S["boards_new"] = True
    S["boards_ver"] = S.get("boards_ver", 0) + 1


# ---------- 게시판 지우기 ----------
def do_delete(bid: str) -> None:
    try:
        S["boards_toast"] = cd.delete_board(bid)
    except ApiError as e:
        S["boards_toast"] = e.message
        S["boards_deleted"] = True
        return
    S["boards_sel"] = "obs"
    S["boards_deleted"] = True


@st.dialog("게시판 지우기")
def delete_dialog(bid: str) -> None:
    if S.pop("boards_deleted", False):
        st.rerun()
    b = db.board(bid)
    st.markdown(f"**{b['name']}** 게시판을 지울까요? 지우면 되돌릴 수 없어요.")
    with st.container(horizontal=True, gap="small"):
        st.button("지우기", type="primary", icon=":material/delete:", key="boards_del_ok", on_click=do_delete,
                  args=(bid,))
        if st.button("그만두기", key="boards_del_cancel"):
            st.rerun()


def delete_area(b: dict) -> None:
    n = cd.count_posts(b["id"])
    with st.container(border=True):
        st.markdown("**게시판 지우기**")
        if b.get("system"):
            ui.muted("관찰 이야기 · 공지사항은 기본 게시판이라 지울 수 없어요. 잠시 쉬려면 상태를 ‘일시 중지’로 바꿔 주세요.")
        elif n:
            ui.muted(f"글이 {n}개 있어서 지울 수 없어요. 글을 지키면서 닫으려면 상태를 ‘보관’으로 바꿔 주세요.")
        elif st.button("이 게시판 지우기", icon=":material/delete:", key=f"boards_del_{b['id']}"):
            delete_dialog(b["id"])


# ---------- 사용자 정의 항목 ----------
def close_fd() -> None:
    for k in [k for k in S.keys() if str(k).startswith("boards_fd")]:
        if k in ("boards_fd", "boards_fd_errs"):
            S.pop(k, None)


def draft_field() -> dict:
    info = S["boards_fd"]
    b = db.board(info["board"])
    old = b["fields"][info["idx"]] if info["idx"] is not None else {}
    t = S.get("boards_fd_type") or "short"
    f = {"key": (S.get("boards_fd_key") or "").strip(), "label": (S.get("boards_fd_label") or "").strip(),
         "type": t, "required": bool(S.get("boards_fd_req")), "active": old.get("active", True)}
    if (S.get("boards_fd_help") or "").strip():
        f["help"] = S["boards_fd_help"].strip()
    if t in ("short", "long"):
        f["max_len"] = int(S.get("boards_fd_maxlen") or fields.DEFAULT_LEN[t])
    elif t == "number":
        for a in ("min", "max"):
            if S.get(f"boards_fd_{a}") is not None:
                f[a] = fields._num(float(S[f"boards_fd_{a}"]))
    elif t == "date":
        for a, k in (("min", "boards_fd_dmin"), ("max", "boards_fd_dmax")):
            if S.get(k):
                f[a] = S[k].isoformat()
    else:
        f["options"] = fields.parse_options(S.get("boards_fd_opts"))
        if t == "multi" and S.get("boards_fd_maxsel"):
            f["max_select"] = int(S["boards_fd_maxsel"])
    return f


def field_payload(f: dict) -> dict:
    """서버에 보낼 항목 정의 (안 쓰는 조건은 비워서 보내면 서버가 정리해요)."""
    return {"key": f["key"], "label": f["label"], "type": f["type"], "required": f["required"],
            "help": f.get("help", ""), "min": f.get("min"), "max": f.get("max"), "max_len": f.get("max_len"),
            "options": f.get("options", []), "max_select": f.get("max_select"), "active": f.get("active", True)}


def save_fd() -> None:
    """저장하기: 서버가 검사해서 저장해요. 안내가 오면 팝업 칸 아래에 보여줘요."""
    info = S["boards_fd"]
    b = db.board(info["board"])
    idx = info["idx"]
    f = draft_field()
    pos = max(1, int(S.get("boards_fd_order") or 1))
    try:
        if idx is None:
            cd.add_field(b["id"], field_payload(f), pos)
            S["boards_toast"] = f"‘{f['label']}’ 항목을 붙였어요"
        else:
            cd.update_field(b["id"], b["fields"][idx]["key"], {**field_payload(f), "order": pos})
            S["boards_toast"] = "항목을 저장했어요"
    except cd.Problem as e:
        S["boards_fd_errs"] = e.errors or {"_other": e.message}
        return
    except ApiError as e:
        S["boards_fd_errs"] = {"_other": e.message}
        return
    S.pop("boards_fd", None)
    S.pop("boards_fd_errs", None)


FD_ERR_SHOWN = ("label", "key", "max_len", "min", "max", "options", "max_select")


def fd_body() -> None:
    if not S.get("boards_fd"):
        st.rerun()
    if S.pop("_boards_fd_check", False):
        save_fd()
    info = S["boards_fd"]
    b = db.board(info["board"])
    idx = info["idx"]
    old = b["fields"][idx] if idx is not None else None
    used = cd.field_used(b["id"], old["key"]) if old else 0
    e = S.get("boards_fd_errs") or {}
    st.caption(f"‘{b['name']}’ 글쓰기 화면에 붙는 칸이에요. 저장하면 바로 반영돼요.")
    c1, c2 = st.columns(2)
    with c1:
        st.text_input("항목 이름 *", max_chars=20, key="boards_fd_label", placeholder="예) 관찰 수심(m)")
        fields.error_text(e.get("label"))
    with c2:
        st.text_input("고유 키 (영문) *", max_chars=30, key="boards_fd_key", placeholder="예) depth",
                      disabled=bool(used), help="글에 값을 저장할 때 쓰는 이름이에요. 영문 소문자로 적어요.")
        fields.error_text(e.get("key"))
        if used:
            st.caption(f"글 {used}개에 쓰인 항목이라 바꿀 수 없어요.")
    c1, c2 = st.columns(2)
    with c1:
        st.selectbox("유형 *", list(fields.TYPES), format_func=fields.TYPES.get, key="boards_fd_type")
    with c2:
        n = len(b["fields"]) + (0 if old else 1)
        st.number_input("표시 순서", min_value=1, max_value=max(n, 1), step=1, key="boards_fd_order",
                        help="글쓰기 화면에서 위에서부터 몇 번째에 보일지 정해요")
    t = S.get("boards_fd_type") or "short"
    st.caption(fields.TYPE_HINT[t])
    if old:
        impact = fields.type_change_impact(old, draft_field(), used)
        if impact:
            st.warning(impact, icon=":material/warning:")

    with st.container(border=True):
        st.markdown("**조건**")
        if t in ("short", "long"):
            st.number_input("최대 글자 수", min_value=1, max_value=2000, step=10, key="boards_fd_maxlen")
            fields.error_text(e.get("max_len"))
        elif t == "number":
            c1, c2 = st.columns(2)
            with c1:
                st.number_input("최솟값 (선택)", value=None, step=1.0, format="%g", key="boards_fd_min",
                                placeholder="없음")
                fields.error_text(e.get("min"))
            with c2:
                st.number_input("최댓값 (선택)", value=None, step=1.0, format="%g", key="boards_fd_max",
                                placeholder="없음")
                fields.error_text(e.get("max"))
        elif t == "date":
            c1, c2 = st.columns(2)
            with c1:
                st.date_input("시작 날짜 (선택)", value=None, format="YYYY.MM.DD", key="boards_fd_dmin")
                fields.error_text(e.get("min"))
            with c2:
                st.date_input("끝 날짜 (선택)", value=None, format="YYYY.MM.DD", key="boards_fd_dmax")
                fields.error_text(e.get("max"))
        else:
            st.text_area("선택지 *", key="boards_fd_opts", height=120, placeholder="한 줄에 하나씩 적어 주세요\n맨눈\n스노클링")
            fields.error_text(e.get("options"))
            if t == "multi":
                st.number_input("최대 선택 수 (선택)", min_value=1, max_value=20, value=None, step=1,
                                key="boards_fd_maxsel", placeholder="제한 없음")
                fields.error_text(e.get("max_select"))
    st.text_input("안내 문구 (선택)", max_chars=60, key="boards_fd_help", placeholder="예) 모르면 비워 두세요")
    st.toggle("꼭 입력해야 해요 (필수)", key="boards_fd_req")
    if S.get("boards_fd_req") and not (old and old.get("required")):
        st.caption("새로 만든 필수 항목은 앞으로 쓰는 글부터 적용돼요. 이미 쓴 글은 그대로 볼 수 있어요.")
    if e:
        more = " ".join(v for k, v in e.items() if k not in FD_ERR_SHOWN)
        st.error(f"저장하지 못했어요. 고쳐야 할 칸이 {len(e)}개 있어요. 빨간 안내를 확인해 주세요." + (f" {more}" if more else ""),
                 icon=":material/error:")
    with st.container(horizontal=True, gap="small"):
        st.button("저장하기", type="primary", icon=":material/save:", key="boards_fd_save", on_click=save_fd)
        st.button("취소", key="boards_fd_cancel", on_click=close_fd)


add_dialog = st.dialog("항목 추가", width="medium", on_dismiss=close_fd)(fd_body)
edit_dialog = st.dialog("항목 고치기", width="medium", on_dismiss=close_fd)(fd_body)


def set_active(bid: str, idx: int, on: bool) -> None:
    f = db.board(bid)["fields"][idx]
    try:
        cd.update_field(bid, f["key"], {"active": on})
        S["boards_toast"] = "다시 쓰도록 바꿨어요" if on else "‘사용 안 함’으로 바꿨어요. 이미 쓴 글의 값은 그대로 보여요."
    except ApiError as e:
        S["boards_toast"] = e.message


def del_field(bid: str, idx: int) -> None:
    f = db.board(bid)["fields"][idx]
    try:
        cd.delete_field(bid, f["key"])
        S["boards_toast"] = f"‘{f['label']}’ 항목을 지웠어요"
    except ApiError as e:
        S["boards_toast"] = e.message


def move_field(bid: str, idx: int, step: int) -> None:
    f = db.board(bid)["fields"][idx]
    try:
        cd.update_field(bid, f["key"], {"order": idx + step + 1})
    except ApiError as e:
        S["boards_toast"] = e.message


def fields_pane(b: dict) -> None:
    bid = b["id"]
    if bid == "obs":
        st.info("관찰 이야기에는 사용자 정의 항목을 붙이지 않아요. 생물 알아보기에서 공유하면 글이 자동으로 만들어져서, "
                "추가 항목을 채울 화면이 없기 때문이에요.", icon=":material/info:")
        return
    fl = b.get("fields") or []
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        st.markdown(f"**{b['name']}** 글쓰기 화면에 붙는 칸 {len(fl)}개")
        st.button("항목 추가", type="primary", icon=":material/add:", key="boards_fd_add", on_click=open_fd,
                  args=(bid, None))
    st.caption("이미 글에 쓰인 항목은 지우지 않고 ‘사용 안 함’으로 바꿔요. 새로 만든 필수 항목은 앞으로 쓰는 글부터 적용돼요.")
    if not fl:
        ui.empty_state("🐚", "아직 추가 항목이 없어요. ‘항목 추가’로 글쓰기 칸을 만들어 보세요.")
    for i, f in enumerate(fl):
        used = cd.field_used(bid, f["key"])
        on = f.get("active", True)
        with st.container(border=True, gap="small"):
            with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
                st.markdown(f"**{i + 1}. {f['label']}**")
                ui.chips(ui.chip(fields.TYPES.get(f["type"], f["type"])),
                         ui.chip("필수", "coral") if f.get("required") else ui.chip("선택"),
                         ui.chip("사용 중", "ok") if on else ui.chip("사용 안 함", "warn"))
            info = f"고유 키 `{f['key']}` · 조건 {fields.condition_text(f)}"
            if f.get("help"):
                info += f" · 안내 ‘{f['help']}’"
            info += f"  \n글 {used}개에서 쓰고 있어요" + (" · 지울 수 없고 ‘사용 안 함’만 할 수 있어요" if used else "")
            st.caption(info)
            with st.container(horizontal=True, gap="small"):
                st.button("고치기", icon=":material/edit:", key=f"boards_fe_{bid}_{i}", on_click=open_fd,
                          args=(bid, i))
                if on:
                    st.button("사용 안 함", icon=":material/visibility_off:", key=f"boards_off_{bid}_{i}",
                              on_click=set_active, args=(bid, i, False))
                else:
                    st.button("다시 사용", icon=":material/visibility:", key=f"boards_on_{bid}_{i}",
                              on_click=set_active, args=(bid, i, True))
                if i > 0:
                    st.button("위로", icon=":material/arrow_upward:", type="tertiary", key=f"boards_up_{bid}_{i}",
                              on_click=move_field, args=(bid, i, -1))
                if i < len(fl) - 1:
                    st.button("아래로", icon=":material/arrow_downward:", type="tertiary",
                              key=f"boards_dn_{bid}_{i}", on_click=move_field, args=(bid, i, 1))
                if not used:
                    st.button("지우기", icon=":material/delete:", type="tertiary", key=f"boards_fdel_{bid}_{i}",
                              on_click=del_field, args=(bid, i))
    if fields.active(fl):
        with st.expander("글쓰기 화면 미리 보기", expanded=True, icon=":material/visibility:"):
            st.caption("회원이 글을 쓸 때 이렇게 보여요. 여기서 넣은 값은 저장되지 않아요.")
            fields.render(fl, f"boards_pv_{bid}_{S.get('boards_ver', 0)}")


# ---------- 화면 그리기 ----------
ui.page_header("게시판 관리", "코드를 고치지 않고 게시판을 만들고, 게시판마다 입력 항목을 붙여요. 바꾸면 고객 화면에 바로 보여요.")

all_boards = db.boards(active_only=False)
with st.container(horizontal=True, gap="small"):
    st.metric("운영 중 게시판", f"{sum(b['status'] == '운영 중' for b in all_boards)}개", border=True, width=160)
    st.metric("전체 게시판", f"{len(all_boards)}개", border=True, width=160)
    st.metric("사용자 정의 항목", f"{sum(len(fields.active(b.get('fields'))) for b in all_boards)}개", border=True,
              width=160)

with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
    st.markdown('<h2 class="sia-h2">게시판 목록</h2>', unsafe_allow_html=True)
    if not S.get("boards_new"):
        st.button("새 게시판", type="primary", icon=":material/add:", key="boards_new_btn", on_click=open_new)

if S.get("boards_new"):
    with st.container(border=True):
        st.markdown("**새 게시판 만들기**")
        st.caption("처음엔 ‘준비 중’으로 만들고, 항목을 다 붙인 뒤 ‘운영 중’으로 바꾸면 커뮤니티 탭에 보여요.")
        draft = {**NEW_DEFAULT, **(S.get("boards_new_draft") or {})}
        board_form(f"boards_n_{S.get('boards_ver', 0)}", draft, is_new=True)

board_table()

st.space("small")
ui.section("게시판 설정")
ids = [b["id"] for b in all_boards]
if S.get("boards_sel") not in ids:
    S["boards_sel"] = "dive" if "dive" in ids else ids[0]
c1, c2 = st.columns([1, 1.4], vertical_alignment="bottom")
with c1:
    sel = st.selectbox("고칠 게시판", ids, key="boards_sel",
                       format_func=lambda i: f"{db.board(i)['name']} · {db.board(i)['status']}")
with c2:
    if S.get("boards_pane") not in ("기본 설정", "사용자 정의 항목"):
        S["boards_pane"] = "기본 설정"
    pane = st.segmented_control("보기", ["기본 설정", "사용자 정의 항목"], key="boards_pane", required=True,
                                label_visibility="collapsed")
board = db.board(sel)
if board.get("system"):
    ui.chips(ui.chip("기본 게시판", "sea"), ui.chip("지울 수 없어요"))

if pane == "사용자 정의 항목":
    fields_pane(board)
else:
    with st.container(border=True):
        board_form(f"boards_e_{sel}_{S.get('boards_ver', 0)}", board, is_new=False)
    delete_area(board)

st.space("small")
ui.section("변경 기록")
logs = cd.logs()
if logs:
    st.dataframe(pd.DataFrame([{"언제": r["when"], "누가": r["who"], "게시판": r["target"], "무엇을": r["action"],
                                "바꾸기 전": r["before"], "바꾼 뒤": r["after"]} for r in logs[:20]]),
                 hide_index=True, width="stretch")
else:
    ui.muted("아직 바꾼 내용이 없어요.")

if S.get("boards_fd"):
    (add_dialog if S["boards_fd"]["idx"] is None else edit_dialog)()
