"""U-16 제보·건의 (김바로 담당).

주소: report     생물 알아보기 결과에서 올 때: report?type=생물 정보 정정&name=소라게 (유형 · 이름을 미리 채워요)
보내면 서버가 먼저 저장(접수번호)하고, Jira가 연결돼 있으면 담당 팀 작업(이슈)을 만들고, 담당 그룹에 메일을 보내요.
처리 확인: 회원 → 내 정보(U-18) › 내 문의 / 비회원 → 접수번호 + 이메일 → 메일로 받은 6자리 코드 (2단계)

시안 캡처용: ?shot=done (접수 완료) | lookup (비회원 처리 확인 결과, 예시 R-1106-Q7MX / guest@example.com)
            | lookup_code (비회원 처리 확인 2단계: 코드 입력, 개발 모드면 코드 안내 상자)
"""
import streamlit as st

from components import nav, ui
from services import db, auth
from services import inquiry_data as inq
from services.api import ApiError

S = st.session_state
user = auth.current_user()
shot = st.query_params.get("shot")
qtype = st.query_params.get("type", "")
qname = st.query_params.get("name", "")

KINDS = inq.KINDS
STEPS = ["접수", "처리 중", "완료"]
STATUS_KIND = {"접수": "", "처리 중": "warn", "완료": "ok"}
DEMO = ("R-1106-Q7MX", "guest@example.com")
FIELDS = ("report_kind", "report_title", "report_body", "report_photo", "report_email")
LOOKUP = ("report_lookup_step", "report_lookup_q", "report_lookup_sent", "report_lookup_result", "report_lookup_error")


def valid_email(e: str) -> bool:
    return "@" in e and "." in e.split("@")[-1]


def reset_lookup() -> None:
    for k in LOOKUP:
        S.pop(k, None)


def send_code(rid: str, email: str) -> bool:
    """처리 확인 ① 메일로 코드 보내기. 성공하면 2단계(코드 입력)로 넘어가요."""
    try:
        out = inq.lookup_send(rid, email)
    except ApiError as e:
        S["report_lookup_error"] = e.message
        return False
    S["report_lookup_q"] = (rid.strip().upper(), email.strip().lower())
    S["report_lookup_sent"] = out
    S["report_lookup_step"] = "code"
    S.pop("report_lookup_error", None)
    return True


def check_code(code: str) -> None:
    """처리 확인 ② 코드 확인 → 처리 상황."""
    rid, email = S["report_lookup_q"]
    try:
        S["report_lookup_result"] = inq.lookup_verify(rid, email, code)
    except ApiError as e:
        S["report_lookup_error"] = e.message
        return
    S["report_lookup_step"] = "result"
    S.pop("report_lookup_error", None)


# ---------- 시안 캡처용 상태 만들기 ----------
if shot and S.get("_report_shot") != shot:
    S["_report_shot"] = shot
    S.pop("report_done", None)
    S.pop("report_errors", None)
    reset_lookup()
    if shot == "done":
        title, body = "‘소라게’ 정보가 달라요", "AI가 소라게라고 했는데 집게 다리 색이 달라 보여요."
        email = "" if user else "parent@example.com"
        try:  # 회원은 이미 보낸 같은 제보가 있으면 그걸 보여줘요 (캡처할 때마다 쌓이지 않게)
            hit = next((r for r in inq.mine() if r["title"] == title), None) if user else None
            out = hit or inq.add("생물 정보 정정", title, body, email=email)
            S["report_done"] = {"id": out["id"], "kind": "생물 정보 정정", "title": title, "email": email,
                                "jira_status": out.get("jira_status", "off"), "jira_key": out.get("jira_key", "")}
        except ApiError as e:
            st.error(e.message)
    elif shot in ("lookup", "lookup_code") and not user:
        if send_code(*DEMO) and shot == "lookup":
            dev = (S.get("report_lookup_sent") or {}).get("dev_code")
            if dev:  # 개발 모드에서만 코드를 바로 알 수 있어요. 아니면 코드 입력 단계에서 멈춰요
                check_code(dev)


# ---------- 보내기 (버튼 콜백: 확인한 뒤 칸 아래에 안내를 보여요) ----------
def submit() -> None:
    kind = S.get("report_kind") or KINDS[0]
    title = (S.get("report_title") or "").strip()
    body = (S.get("report_body") or "").strip()
    email = (S.get("report_email") or "").strip()
    err = {}
    if not title:
        err["title"] = "제목을 적어 주세요."
    if not body:
        err["body"] = "어떤 일인지 내용을 적어 주세요."
    if not user:
        if not email:
            err["email"] = "답변 받을 이메일을 적어 주세요."
        elif not valid_email(email):
            err["email"] = "이메일 주소를 한 번 더 확인해 주세요."
    S["report_errors"] = err
    if err:
        return
    try:
        out = inq.add(kind, title, body, email="" if user else email)
    except ApiError as e:
        S["report_errors"] = {"form": e.message or "보내지 못했어요. 적은 내용은 그대로 있어요. 다시 시도해 주세요."}
        return
    S["report_done"] = {"id": out["id"], "kind": kind, "title": title, "email": "" if user else email,
                        "jira_status": out.get("jira_status", "off"), "jira_key": out.get("jira_key", "")}
    for k in FIELDS:
        S.pop(k, None)


def field_error(name: str) -> None:
    msg = S.get("report_errors", {}).get(name)
    if msg:
        st.error(msg, icon=":material/error:")


def status_steps(status: str) -> None:
    now = STEPS.index(status) if status in STEPS else 0
    ui.chips(*[ui.chip(("✓ " if i < now else "") + s, "sea" if i <= now else "") for i, s in enumerate(STEPS)])


def jira_note(status: str, key: str = "") -> None:
    """담당 팀 작업 목록(Jira)에 올라갔는지 한 줄로 알려요."""
    note = inq.JIRA_NOTE.get(status or "off", inq.JIRA_NOTE["off"])
    st.caption(f":material/assignment: {note}" + (f" (작업 번호 {key})" if key else ""))


def inquiry_box(item: dict) -> None:
    with st.container(border=True):
        with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center",
                          gap="small"):
            st.markdown(f"**{item['title']}**", width="content")
            ui.chips(ui.chip(item["status"], STATUS_KIND.get(item["status"], "")))
        ui.muted(f"{item['id']} · {item['type']} · {item['date']}")
        status_steps(item["status"])
        if item.get("answer"):
            st.info(f"**운영팀 답변**\n\n{item['answer']}", icon=":material/support_agent:")
        elif item["status"] == "처리 중":
            st.caption("운영팀이 살펴보고 있어요. 답변이 달리면 여기에서 볼 수 있어요.")
        else:
            st.caption("아직 답변이 없어요. 확인하는 대로 답해 드릴게요.")
        if item.get("jira_status") in ("created", "done"):
            jira_note(item["jira_status"], item.get("jira_key", ""))


# ---------- 왼쪽: 양식 또는 접수 완료 ----------
def show_form() -> None:
    kind_idx = KINDS.index(qtype) if qtype in KINDS else 0
    if qname:
        st.info(f"‘{qname}’ 생물 정보 정정으로 채워 두었어요. 내용만 확인해 주세요.", icon=":material/edit_note:")
    with st.container(border=True):
        st.selectbox("유형", KINDS, index=kind_idx, key="report_kind",
                     help="생물 이름이나 안전 정보가 틀렸다면 ‘생물 정보 정정’을 골라 주세요.")
        st.text_input("제목", value=f"‘{qname}’ 정보가 달라요" if qname else "", max_chars=50, key="report_title",
                      placeholder="예: 사진 올리기가 멈춰요")
        field_error("title")
        body_default = f"AI가 알려준 이름: {qname}\n제가 생각하는 이름: \n어디서 봤나요: " if qname else ""
        st.text_area("내용", value=body_default, max_chars=1000, height=140, key="report_body",
                     placeholder="언제, 어떤 화면에서, 무슨 일이 있었나요?")
        field_error("body")
        st.file_uploader("사진 (선택, 1장)", max_upload_size=db.settings()["max_mb"], type=["jpg", "jpeg", "png"], key="report_photo",
                         help="화면을 찍은 사진이 있으면 더 빨리 살펴볼 수 있어요.")
        if not user:
            st.text_input("답변 받을 이메일", key="report_email", placeholder="example@email.com")
            field_error("email")
            st.caption("이메일은 답변과 처리 확인 코드를 보내는 데만 써요. 로그인하면 이메일 없이 보낼 수 있어요.")
        field_error("form")
        st.button("제보 보내기", type="primary", icon=":material/send:", width="stretch", key="report_send",
                  on_click=submit)


def show_done(d: dict) -> None:
    st.success("제보를 보냈어요! 알려 주셔서 고마워요.", icon=":material/check_circle:")
    with st.container(border=True):
        st.markdown("**접수번호**")
        st.code(d["id"], language=None)
        st.caption("오른쪽 위 복사 버튼으로 접수번호를 복사해 두세요. 처리 상황을 확인할 때 필요해요.")
        status_steps("접수")
        jira_note(d.get("jira_status", "off"), d.get("jira_key", ""))
        st.markdown(f"**유형** · {d['kind']}  \n**제목** · {d['title']}"
                    + (f"  \n**답변 받을 이메일** · `{d['email']}`" if d.get("email") else ""))
    st.markdown("**다음에는 이렇게 돼요**")
    where = "내 정보 › 내 문의" if user else "이 화면의 ‘처리 확인’(접수번호 + 이메일 + 메일로 받은 코드)"
    steps = ["운영팀이 내용을 확인해요.",
             "확인을 시작하면 상태가 ‘처리 중’으로 바뀌어요.",
             f"답변이 달리면 {where}에서 볼 수 있고, 처리가 끝나면 메일로도 알려 드려요."]
    if d["kind"] == "생물 정보 정정":
        steps.insert(2, "맞는 정보로 확인되면 생물 정보에 반영해요.")
    st.markdown("\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1)))
    with st.container(horizontal=True, gap="small"):
        if st.button("다른 제보 보내기", icon=":material/add:", key="report_again"):
            S.pop("report_done", None)
            S.pop("report_errors", None)
            st.rerun()
        if user:
            nav.link("mypage", "내 문의 보러 가기", icon=":material/person:", tab="inquiries")
        nav.link("home", "홈으로", icon=":material/home:")


# ---------- 오른쪽: 처리 확인 ----------
def lookup_error() -> None:
    if S.get("report_lookup_error"):
        st.warning(S["report_lookup_error"], icon=":material/info:")


def show_lookup_form() -> None:
    with st.container(border=True):
        st.markdown("**접수번호로 확인하기**")
        st.caption("제보할 때 받은 접수번호와 이메일을 적으면, 그 메일로 6자리 확인 코드를 보내 드려요.")
        rid = st.text_input("접수번호", key="report_lookup_id", placeholder="예: R-1106-Q7MX")
        em = st.text_input("이메일", key="report_lookup_email", placeholder="example@email.com")
        if st.button("확인 코드 받기", icon=":material/mail:", key="report_lookup_go", width="stretch"):
            if not rid.strip() or not em.strip():
                S["report_lookup_error"] = "접수번호와 이메일을 모두 적어 주세요."
            elif send_code(rid, em):
                st.rerun()
        st.caption(f"체험용 예시: `{DEMO[0]}` / `{DEMO[1]}`")
    lookup_error()


def show_lookup_code() -> None:
    rid, email = S["report_lookup_q"]
    sent = S.get("report_lookup_sent") or {}
    with st.container(border=True):
        st.markdown("**메일로 받은 코드 적기**")
        ui.chips(ui.chip(rid, "sea"), ui.chip(email))
        st.caption(sent.get("message") or "메일로 6자리 코드를 보냈어요. 5분 안에 적어 주세요.")
        if sent.get("dev_code"):
            st.info(f"개발 모드라 메일 대신 여기에 코드를 보여 드려요: **{sent['dev_code']}**",
                    icon=":material/developer_mode:")
        code = st.text_input("6자리 코드", max_chars=6, key="report_lookup_code", placeholder="예: 123456")
        if st.button("처리 상황 보기", type="primary", icon=":material/search:", key="report_lookup_check",
                     width="stretch"):
            if not code.strip():
                S["report_lookup_error"] = "메일로 받은 6자리 코드를 적어 주세요."
            else:
                check_code(code)
                if S.get("report_lookup_step") == "result":
                    st.rerun()
        with st.container(horizontal=True, gap="small"):
            if st.button("코드 다시 받기", icon=":material/refresh:", key="report_lookup_resend"):
                if send_code(rid, email):
                    st.toast("새 코드를 보냈어요. 먼저 받은 코드는 쓸 수 없어요.")
                    st.rerun()
            if st.button("접수번호 다시 적기", icon=":material/edit:", key="report_lookup_back"):
                reset_lookup()
                st.rerun()
        st.caption("메일이 오지 않으면 스팸함을 확인해 주세요.")
    lookup_error()


def show_check() -> None:
    ui.section("처리 확인")
    if user:
        try:
            mine = inq.mine()
        except ApiError as e:
            st.error(e.message)
            return
        if not mine:
            ui.empty_state("🐚", "아직 보낸 제보가 없어요.")
        for item in mine[:3]:
            inquiry_box(item)
        nav.link("mypage", "내 정보 › 내 문의에서 모두 보기", icon=":material/arrow_forward:", tab="inquiries")
        return
    step = S.get("report_lookup_step", "form")
    if step == "result" and isinstance(S.get("report_lookup_result"), dict):
        inquiry_box(S["report_lookup_result"])
        if st.button("다른 제보 확인하기", icon=":material/search:", key="report_lookup_again"):
            reset_lookup()
            st.rerun()
    elif step == "code" and S.get("report_lookup_q"):
        show_lookup_code()
    else:
        show_lookup_form()


# ---------- 화면 그리기 ----------
ui.page_header("제보·건의", "오류나 바라는 점을 알려 주세요. 꼼꼼히 읽고 답해 드릴게요.")
left, right = st.columns([3, 2], gap="large")
with left:
    if S.get("report_done"):
        show_done(S["report_done"])
    else:
        show_form()
with right:
    show_check()
