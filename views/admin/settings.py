"""A-07 운영 설정 (이종민 담당).

서비스 규칙(횟수 · 사진 조건 · 신고 기준 · 금칙어 · 물때 기본 지역)을 코드 수정 없이 바꿔요.
[저장]하면 서버(PUT /admin/settings)가 검사한 뒤 바로 적용하고, 아래 변경 기록에 누가 · 언제 · 전 → 후가 남아요.

시안 캡처용: 주소에 ?shot=saved|error (관리자로 보려면 &as=admin)
"""
import pandas as pd
import streamlit as st

from components import auth_gate, nav, ui
from services import admin_data, db
from services.api import ApiError

me = auth_gate.admin_only()
S = st.session_state
try:
    s = admin_data.settings_full()  # 금칙어까지 모두 (관리자만)
    regions = db.regions()
except ApiError as e:
    st.error(e.message, icon=":material/cloud_off:")
    st.stop()
FORMATS = ["jpg", "jpeg", "png", "heic", "webp"]
FIELDS = {  # 설정 키: (위젯 키, 기록에 쓸 이름, 보여주는 모양)
    "limit_member": ("admin_settings_member", "회원 하루 횟수", lambda v: f"{v}회"),
    "limit_guest": ("admin_settings_guest", "비회원 하루 횟수", lambda v: f"{v}회"),
    "formats": ("admin_settings_formats", "사진 형식", lambda v: ", ".join(x.upper() for x in v)),
    "max_mb": ("admin_settings_maxmb", "사진 최대 크기", lambda v: f"{v}MB"),
    "report_hide": ("admin_settings_report", "신고 자동 숨김 기준", lambda v: f"{v}회"),
    "banned": ("admin_settings_banned", "금칙어", lambda v: ", ".join(v) or "(없음)"),
    "default_region": ("admin_settings_region", "물때 기본 지역", lambda v: regions.get(v, {}).get("name", v)),
}


def load_widgets() -> None:
    """지금 저장된 값으로 입력칸을 채워요."""
    for k, (wk, _, _) in FIELDS.items():
        if k != "banned":
            S[wk] = list(s.get(k, [])) if k == "formats" else s.get(k)
    S["admin_settings_banned_base"] = list(s.get("banned", []))
    S["admin_settings_ver"] = S.get("admin_settings_ver", 0) + 1


def save(values: dict) -> int:
    """서버에 저장하고 바뀐 항목 수를 돌려줘요. 서버가 막으면 ApiError (e.code: limit · formats · region …)."""
    global s
    out = admin_data.save_settings(values)
    s = out["settings"]
    return int(out["changed"])


FIELD_OF_CODE = {"limit": "limit", "formats": "formats"}


# 입력칸 값은 위젯을 만들기 전에만 채울 수 있어요 (저장 · 되돌리기는 다음 실행 때 채워요)
if S.pop("admin_settings_reload", False) or any(w not in S for k, (w, _, _) in FIELDS.items() if k != "banned"):
    load_widgets()

# ---------- 시안 캡처용 상태 만들기 ----------
shot = st.query_params.get("shot")
if shot and S.get("_shot_admin_settings") != shot:
    S["_shot_admin_settings"] = shot
    if shot == "saved":  # 실제로 저장해요 (같은 값이면 두 번째부터는 바뀌는 게 없어요)
        want = {k: s[k] for k in FIELDS}
        want.update(report_hide=3, banned=list(dict.fromkeys(list(s.get("banned", [])) + ["홍보"])))
        try:
            n = save(want)
            S["admin_settings_msg"] = ("ok", n or 2)
        except ApiError as e:
            S["admin_settings_msg"] = ("err", e.message, FIELD_OF_CODE.get(e.code, ""))
        load_widgets()
    elif shot == "error":
        S["admin_settings_guest"] = 30
        S["admin_settings_msg"] = ("err", "비회원 하루 횟수는 회원보다 많을 수 없어요. 숫자를 다시 정해 주세요.", "limit")

ui.page_header("운영 설정", "서비스 규칙을 코드 수정 없이 바꿔요. 저장하면 바로 적용돼요.")
ui.chips(ui.chip("저장하면 모든 사용자에게 바로 적용", "warn"), ui.chip("바꾼 내용은 변경 기록에 남아요"))
st.space("small")

msg = S.pop("admin_settings_msg", None)
err_field = msg[2] if msg and msg[0] == "err" else None

left, right = st.columns(2, gap="large")
with left:
    ui.section("생물 알아보기 횟수")
    with st.container(border=True):
        c1, c2 = st.columns(2, gap="small")
        with c1:
            st.number_input("회원 · 하루 (회)", min_value=1, max_value=200, step=1, key="admin_settings_member",
                            help="기본 20회")
        with c2:
            st.number_input("비회원 · 하루 (회)", min_value=0, max_value=50, step=1, key="admin_settings_guest",
                            help="기본 3회. 0이면 비회원은 예시 체험만 할 수 있어요.")
        admin_data.muted("하루 횟수는 밤 12시에 다시 채워져요. 예시 사진 체험은 횟수에서 빠져요.")
        if err_field == "limit":
            st.error(msg[1], icon=":material/error:")

    ui.section("사진 조건")
    with st.container(border=True):
        st.multiselect("올릴 수 있는 형식", FORMATS, key="admin_settings_formats", format_func=str.upper)
        if err_field == "formats":
            st.error(msg[1], icon=":material/error:")
        st.number_input("최대 크기 (MB)", min_value=1, max_value=30, step=1, key="admin_settings_maxmb",
                        help="기본 10MB")
        admin_data.muted(f"이보다 큰 사진은 ‘사진이 너무 커요. {S['admin_settings_maxmb']}MB보다 작은 사진을 골라 주세요.’라고 안내해요.")

    ui.section("신고 자동 숨김")
    with st.container(border=True):
        st.number_input("같은 글에 신고가 몇 번 쌓이면 숨길까요? (회)", min_value=1, max_value=50, step=1,
                        key="admin_settings_report", help="기본 5회")
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            ui.muted("자동으로 숨긴 글은 ‘게시물·신고’에서 확인하고 복구할 수 있어요.")
            nav.link("admin_posts", "게시물·신고", icon=":material/flag:")

with right:
    ui.section("금칙어")
    with st.container(border=True):
        admin_data.muted("글 · 댓글 · 닉네임에 이 말이 들어가면 올릴 수 없어요. 맨 아래 빈 줄에 새 말을 적고, 줄을 골라 지울 수 있어요.")
        base = pd.DataFrame({"금칙어": S["admin_settings_banned_base"]})
        edited = st.data_editor(base, num_rows="dynamic", hide_index=True, width="stretch",
                                key=f"admin_settings_banned_{S['admin_settings_ver']}",
                                column_config={"금칙어": st.column_config.TextColumn("금칙어", max_chars=20)})
        words = []
        for w in edited["금칙어"].tolist():
            w = str(w).strip() if w is not None and str(w) != "nan" else ""
            if w and w not in words:
                words.append(w)
        st.caption(f"지금 {len(words)}개")

    ui.section("물때 지역")
    with st.container(border=True):
        st.selectbox("처음 보여줄 지역", list(regions), key="admin_settings_region",
                     format_func=lambda r: regions[r]["name"],
                     help="물때 화면을 처음 열었을 때 이 지역을 보여줘요. 회원은 자기 지역이 먼저 보여요.")
        st.dataframe(pd.DataFrame([{"지역": v["name"], "만조(물 들어옴)": " · ".join(v["high"]),
                                    "간조(물 빠짐)": " · ".join(v["low"])} for v in regions.values()]),
                     hide_index=True, width="stretch")
        latest = max(v["updated"] for v in regions.values())
        admin_data.muted(f"지역 {len(regions)}곳 · 물때 정보는 하루 한 번 새로 받아 와요 · {latest} 기준")

# ---------- 저장 ----------
st.space("small")
values = {"limit_member": int(S["admin_settings_member"]), "limit_guest": int(S["admin_settings_guest"]),
          "formats": list(S["admin_settings_formats"]), "max_mb": int(S["admin_settings_maxmb"]),
          "report_hide": int(S["admin_settings_report"]), "banned": words,
          "default_region": S["admin_settings_region"]}
pending = [FIELDS[k][1] for k, v in values.items() if s.get(k) != v]

if msg and msg[0] == "ok":
    st.success(f"저장했어요. {msg[1]}가지 설정이 바로 적용됐어요.", icon=":material/check_circle:")
elif msg and msg[0] == "err" and err_field in ("limit", "formats"):
    st.error("저장하지 못했어요. 빨간 안내가 있는 칸을 고친 뒤 다시 저장해 주세요.", icon=":material/error:")
elif msg and msg[0] == "err":
    st.error(f"저장하지 못했어요. {msg[1]}", icon=":material/error:")
elif msg and msg[0] == "same":
    st.info("바뀐 내용이 없어요.", icon=":material/info:")
if pending:
    st.warning(f"아직 저장하지 않은 항목이 있어요: {', '.join(pending)}", icon=":material/edit_note:")

with st.container(horizontal=True, gap="small"):
    if st.button("저장", type="primary", key="admin_settings_save", icon=":material/save:"):
        if values["limit_guest"] > values["limit_member"]:
            S["admin_settings_msg"] = ("err", "비회원 하루 횟수는 회원보다 많을 수 없어요. 숫자를 다시 정해 주세요.", "limit")
        elif not values["formats"]:
            S["admin_settings_msg"] = ("err", "사진 형식을 하나 이상 골라 주세요.", "formats")
        else:
            try:
                n = save(values)
            except ApiError as e:  # 서버도 같은 규칙으로 한 번 더 검사해요
                S["admin_settings_msg"] = ("err", e.message, FIELD_OF_CODE.get(e.code, "other"))
            else:
                if n:
                    S["admin_settings_reload"] = True
                    S["admin_settings_msg"] = ("ok", n)
                else:
                    S["admin_settings_msg"] = ("same", 0)
        st.rerun()
    if st.button("저장 전으로 되돌리기", key="admin_settings_undo", icon=":material/undo:", disabled=not pending):
        S["admin_settings_reload"] = True
        st.rerun()

# ---------- 변경 기록 ----------
st.space("small")
ui.section("변경 기록")
changes = admin_data.settings_logs()
if changes:
    st.dataframe(pd.DataFrame(changes), hide_index=True, width="stretch",
                 column_order=["언제", "누가", "항목", "바꾸기 전", "바꾼 후"])
else:
    admin_data.muted("아직 변경 기록이 없어요. 설정을 저장하면 여기에 남아요.")
admin_data.muted("누가 · 언제 · 무엇을 바꿨는지 모두 남아요. 기록은 지울 수 없어요.")
