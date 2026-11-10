"""A-06 문의 관리 (김바로 담당).

목록(접수번호 · 유형 · 제목 · 상태 · 날짜 · Jira)에서 한 줄을 고르면 아래에 내용 · 답변 · 상태 · Jira가 열려요.
저장하면 고객 화면(제보·건의의 처리 확인, 내 정보 › 내 문의)에 바로 보여요.
‘완료’ + 답변으로 저장하면 서버가 제보한 사람에게 결과 메일을 보내요 (한 번만).
Jira: 실패한 건은 [Jira 다시 보내기](이슈가 없을 때만), 등록된 건은 [Jira 상태 가져오기](끝났으면 완료로).

시안 캡처용: ?shot=detail (첫 번째 문의를 고른 상태)
            ?shot=jira_failed (Jira 등록에 실패한 문의를 고른 상태. 없으면 첫 문의를 실패 예시로 보여줘요)
"""
import streamlit as st

from components import auth_gate, ui
from services import auth
from services import inquiry_data as inq
from services.api import ApiError

admin = auth_gate.admin_only()

S = st.session_state
shot = st.query_params.get("shot")
STATUSES = inq.STATUSES
STATUS_KIND = {"접수": "", "처리 중": "warn", "완료": "ok"}
DEMO_ERROR = "Jira 오류 401: 인증 정보가 맞지 않아요 (시안 예시)"

if S.get("ainq_toast"):
    st.toast(S.pop("ainq_toast"))


def jira_connected() -> bool:
    try:
        return auth.health().get("modes", {}).get("jira") == "on"
    except ApiError:
        return False


def run(action, rid: str, ok_prefix: str = "") -> None:
    """버튼 동작 하나: 성공하면 알림, 실패하면 이 화면에 안내를 남기고 다시 그려요."""
    try:
        out = action(rid)
    except ApiError as e:
        S["ainq_flash"] = ("error", e.message)
    else:
        if out.get("ok", True):
            S["ainq_toast"] = ok_prefix + out["message"]
        else:
            S["ainq_flash"] = ("error", out["message"])
    st.rerun()


ui.page_header("문의 관리", "제보·건의에 답하고 처리 상태를 바꿔요.")

try:
    rows = inq.admin_list()
except ApiError as e:
    st.error(e.message, icon=":material/cloud_off:")
    st.stop()

with st.container(horizontal=True, gap="small"):
    for s in STATUSES:
        st.metric(s, f"{sum(1 for r in rows if r['status'] == s)}건", border=True)
    failed_n = sum(1 for r in rows if r.get("jira_status") == "failed")
    if failed_n:
        st.metric("Jira 실패", f"{failed_n}건", border=True)

c1, c2 = st.columns([3, 2], gap="medium")
with c1:
    status = st.segmented_control("상태", ["전체"] + STATUSES, default="전체", required=True, key="ainq_status")
with c2:
    kind = st.selectbox("유형", ["전체"] + inq.KINDS, key="ainq_kind")

shown = [r for r in rows if (status == "전체" or r["status"] == status) and (kind == "전체" or r["type"] == kind)]

if not shown:
    ui.empty_state("🐚", "조건에 맞는 문의가 없어요. 상태나 유형을 바꿔 보세요.")
    st.stop()

# 시안 캡처용: Jira 실패 상태 (진짜 실패 건이 없으면 첫 문의를 실패 예시로 보여줘요)
demo_failed = False
shot_row = None
if shot == "detail":
    shot_row = 0
elif shot == "jira_failed":
    shot_row = next((i for i, r in enumerate(shown) if r.get("jira_status") == "failed"), None)
    if shot_row is None:
        shot_row, demo_failed = 0, True
        shown[0] = {**shown[0], "jira_status": "failed", "jira_key": "", "jira_url": "", "jira_error": DEMO_ERROR}

table = [{"접수번호": r["id"], "유형": r["type"], "제목": r["title"], "상태": r["status"], "날짜": r["date"],
          "보낸 사람": r.get("sender", ""), "답변": "있음" if r.get("answer") else "없음",
          "Jira": r.get("jira_key") or inq.JIRA_ADMIN.get(r.get("jira_status", "off"), ("", ""))[0]} for r in shown]
default = {"selection": {"rows": [shot_row]}} if shot_row is not None else None
picked = st.dataframe(table, hide_index=True, on_select="rerun", selection_mode="single-row",
                      key=f"ainq_table_{status}_{kind}", selection_default=default)
sel = list(picked.selection.rows) if picked else []
if not sel and shot_row is not None:  # 시안 캡처용: 줄을 고른 상태
    sel = [shot_row]
st.caption("한 줄을 고르면 아래에서 내용을 보고 답할 수 있어요. 스마트폰에서는 표를 옆으로 밀어 볼 수 있어요.")

if not sel:
    st.info("목록에서 문의를 골라 주세요.", icon=":material/touch_app:")
    st.stop()

item = shown[sel[0]]
rid = item["id"]
jst = item.get("jira_status", "off")
jira_label, jira_kind = inq.JIRA_ADMIN.get(jst, ("Jira 미연결", ""))

st.space("small")
ui.section(f"{rid} 처리하기")
flash = S.pop("ainq_flash", None)
if flash:
    st.error(flash[1], icon=":material/error:")
with st.container(border=True):
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center", gap="small"):
        st.markdown(f"**{item['title']}**", width="content")
        ui.chips(ui.chip(item["type"], "sea"), ui.chip(item["status"], STATUS_KIND.get(item["status"], "")),
                 ui.chip(jira_label, jira_kind))
    ui.muted(f"{item.get('sender', '')} · {item['date']} 접수")
    st.write(item["body"])

    # ---------- Jira ----------
    with st.container(border=True, gap="small"):
        if item.get("jira_key"):
            line = f"**Jira 이슈** · {item['jira_key']}" + (" · 끝남" if jst == "done" else "")
            if item.get("jira_url"):
                line = f"**Jira 이슈** · [{item['jira_key']}]({item['jira_url']})" + (" · 끝남" if jst == "done" else "")
            st.markdown(line)
            st.caption("Jira에서 이슈를 끝내면 [Jira 상태 가져오기]나 웹훅으로 이 문의가 ‘완료’가 돼요.")
        elif jst == "failed":
            st.markdown("**Jira 이슈** · 만들지 못했어요")
            st.error(item.get("jira_error") or "Jira에 보내지 못했어요.", icon=":material/sync_problem:")
            st.caption("제보는 잘 저장돼 있어요. [Jira 다시 보내기]를 누르면 이슈를 한 번만 만들어요.")
            if demo_failed:
                st.caption("시안 예시 상태예요. Jira가 연결되어 있지 않으면 다시 보내기는 안내만 보여요.")
        else:
            st.markdown("**Jira 이슈** · 미연결")
            st.caption("Jira가 연결되어 있지 않아 제보만 저장했어요. 서버 환경변수 JIRA_*를 넣으면 새 제보부터 이슈가 만들어져요."
                       if not jira_connected() else "아직 Jira로 보내지 않은 문의예요. [Jira 다시 보내기]로 보낼 수 있어요.")

    left, right = st.columns([3, 1], gap="medium")
    with left:
        answer = st.text_area("답변", value=item.get("answer", ""), height=120, key=f"ainq_answer_{rid}",
                              placeholder="고객에게 보일 답변을 적어 주세요. 해요체로 짧게 써요.")
    with right:
        new_status = st.selectbox("상태", STATUSES, index=STATUSES.index(item["status"]) if item["status"] in STATUSES else 0,
                                  key=f"ainq_state_{rid}")
        if new_status == "완료" and not answer.strip():
            st.caption("완료로 바꿀 때는 답변을 함께 적어 주면 좋아요. 답변이 있어야 결과 메일이 가요.")
    with st.container(horizontal=True, gap="small"):
        if st.button("저장하기", type="primary", icon=":material/save:", key=f"ainq_save_{rid}"):
            run(lambda r: inq.admin_save(r, new_status, answer.strip()), rid)
        if not item.get("jira_key") and (jst == "failed" or (jst == "off" and jira_connected())):
            if st.button("Jira 다시 보내기", icon=":material/sync:", key=f"ainq_jira_retry_{rid}"):
                run(inq.jira_retry, rid)
        elif item.get("jira_key") and jst != "done":
            if st.button("Jira 상태 가져오기", icon=":material/cloud_download:", key=f"ainq_jira_sync_{rid}"):
                run(inq.jira_sync, rid)
    if item.get("mail_sent"):
        st.caption(":material/mark_email_read: 답변 메일을 보냈어요. 다시 저장해도 메일은 한 번만 가요.")
    else:
        st.caption("저장하면 제보·건의의 ‘처리 확인’과 내 정보 › 내 문의에 바로 보여요. "
                   "‘완료’ + 답변으로 저장하면 제보한 사람에게 결과 메일이 가요.")
