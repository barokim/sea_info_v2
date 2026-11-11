"""A-05 콘텐츠 관리 (이정민 담당).

탭 네 개: 퀴즈 문제 · 바다 소식 검토 · 수집 출처 · 수집 기록
모두 FastAPI 서버의 관리자 API(/admin/quiz · /admin/news …)를 불러요 (services/games_data.py · news_data.py).
여기서 고친 내용은 서버(SQLite)에 바로 저장돼 U-13 퀴즈 팝업과 U-15 바다 소식에 그대로 보여요.
관리자가 한 일은 서버가 관리 기록(AdminLog)에 남겨요.

시안 캡처용: 주소에 ?shot=quiz_edit|news_review|news_edit|sources|runs
"""
from datetime import date, datetime, time, timedelta, timezone

import pandas as pd
import streamlit as st

from components import auth_gate, ui
from services import ai, db, games_data, news_data
from services.api import ApiError

auth_gate.admin_only()

S = st.session_state
TABS = {"quiz": "퀴즈 문제", "news": "바다 소식 검토", "sources": "수집 출처", "runs": "수집 기록"}
KST = timezone(timedelta(hours=9))


def _bump(name: str) -> None:
    """표 · 입력 칸을 처음 상태로 돌리고 싶을 때 key 번호를 올려요."""
    S[name] = S.get(name, 0) + 1


def _news_rows() -> list[dict]:
    """숨긴 소식까지 모두, 최신순 (서버가 정렬해 줘요)."""
    return news_data.admin_list()


def _today() -> date:
    return datetime.now(KST).date()


# ---------- 시안 캡처용 상태 만들기 ----------
shot = st.query_params.get("shot")
if shot and S.get("contents_shot") != shot:
    S["contents_shot"] = shot
    S["contents_tab"] = {"quiz_edit": "quiz", "news_review": "news", "news_edit": "news",
                         "sources": "sources", "runs": "runs"}.get(shot, "quiz")
    S.pop("contents_edit", None)
    if shot == "quiz_edit":
        S["contents_quiz_sel"] = 3
        _bump("contents_quiz_ver")
    if shot in ("news_review", "news_edit"):
        try:
            first = _news_rows()[:1]
        except ApiError:
            first = []
        S["contents_news_sel"] = first[0]["id"] if first else None
        _bump("contents_news_ver")
    if shot == "news_edit":
        S["contents_edit"] = S["contents_news_sel"]

S.setdefault("contents_tab", "quiz")

ui.page_header("콘텐츠 관리", "퀴즈 문제를 관리하고, 자동으로 모인 바다 소식을 검토해요.")
tab = st.segmented_control("보기", list(TABS), format_func=TABS.get, key="contents_tab", required=True,
                           label_visibility="collapsed")
st.space("small")


# ---------- 퀴즈 문제 ----------
def quiz_tab() -> None:
    qs = games_data.admin_quiz()
    on = sum(1 for q in qs if q.get("active", True))
    ui.chips(ui.chip(f"전체 {len(qs)}문제"), ui.chip(f"✓ 사용 중 {on}문제", "ok"),
             ui.chip(f"쉬는 중 {len(qs) - on}문제", "warn" if len(qs) - on else ""))
    st.space("small")
    if on < 5:
        st.warning(f"사용 중인 문제가 {on}개뿐이에요. 퀴즈는 5문제씩 내니 5개 이상 켜 주세요.",
                   icon=":material/warning:")
    left, right = st.columns([5, 3], gap="large")
    with left:
        ui.section("등록된 문제")
        sel = S.get("contents_quiz_sel")
        sel = sel if sel is not None and sel < len(qs) else None
        ev = st.dataframe(
            [{"문제": q["q"], "정답": q["options"][q["answer"]],
              "사용": "✓ 사용" if q.get("active", True) else "쉬는 중"} for q in qs],
            hide_index=True, on_select="rerun", selection_mode="single-row",
            selection_default={"selection": {"rows": [sel]}} if sel is not None else None,
            column_config={"문제": st.column_config.TextColumn(width=240),
                           "정답": st.column_config.TextColumn(width=130),
                           "사용": st.column_config.TextColumn(width=72)},
            key=f"contents_quiz_df_{S.get('contents_quiz_ver', 0)}")
        rows = ev.selection.rows
        S["contents_quiz_sel"] = rows[0] if rows else None
        ui.muted("줄을 고르면 그 문제를 고칠 수 있어요. 퀴즈는 사용 중인 문제에서 5개를 무작위로 내요.")

    with right:
        idx = S.get("contents_quiz_sel")
        q = qs[idx] if idx is not None and idx < len(qs) else None
        with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
            st.markdown(f'<h2 class="sia-h2">{"문제 고치기" if q else "새 문제 추가"}</h2>', unsafe_allow_html=True)
            if q and st.button("새 문제 쓰기", icon=":material/add:", key="contents_quiz_new"):
                S["contents_quiz_sel"] = None
                _bump("contents_quiz_ver")
                st.rerun()
        fk = f"{q['id'] if q else 'new'}_{S.get('contents_quiz_form', 0)}"
        with st.form(f"contents_quiz_form_{fk}"):
            text = st.text_input("문제", value=q["q"] if q else "", max_chars=80,
                                 placeholder="예) 소라게는 무엇을 집으로 삼을까요?", key=f"contents_qt_{fk}")
            opts = []
            for j in range(4):
                old = q["options"][j] if q and j < len(q["options"]) else ""
                opts.append(st.text_input(f"보기 {j + 1}" + (" (선택)" if j == 3 else ""), value=old,
                                          max_chars=40, key=f"contents_qo_{fk}_{j}"))
            ans = st.radio("정답", [0, 1, 2, 3], format_func=lambda j: f"보기 {j + 1}", horizontal=True,
                           index=q["answer"] if q else 0, key=f"contents_qa_{fk}")
            explain = st.text_area("해설", value=q["explain"] if q else "", height=90, max_chars=160,
                                   placeholder="답을 고른 뒤 보여줄 짧은 설명이에요.", key=f"contents_qe_{fk}")
            active = st.toggle("퀴즈에 내기 (사용 여부)", value=q.get("active", True) if q else True,
                               key=f"contents_qv_{fk}")
            saved = st.form_submit_button("고친 내용 저장하기" if q else "문제 추가하기", type="primary",
                                          width="stretch")
        if saved:
            filled = [(j, o.strip()) for j, o in enumerate(opts) if o.strip()]
            if not text.strip():
                st.error("문제가 비어 있어요. 문제를 적어 주세요.")
            elif len(filled) < 3:
                st.error("보기가 모자라요. 보기를 3개 이상 적어 주세요.")
            elif not opts[ans].strip():
                st.error("정답으로 고른 보기가 비어 있어요. 정답 보기를 적거나 다른 보기를 골라 주세요.")
            elif not explain.strip():
                st.error("해설이 비어 있어요. 답을 고른 뒤 보여줄 설명을 적어 주세요.")
            else:
                new = {"q": text.strip(), "options": [o for _, o in filled],
                       "answer": [j for j, _ in filled].index(ans), "explain": explain.strip(), "active": active}
                try:
                    if q:
                        games_data.update_quiz(q["id"], **new)
                    else:
                        games_data.add_quiz(**new)
                except ApiError as e:
                    st.error(e.message)
                else:
                    if q:
                        st.toast("문제를 저장했어요. 다음 퀴즈부터 바뀐 내용으로 나와요.", icon=":material/check:")
                    else:
                        S["contents_quiz_sel"] = None
                        _bump("contents_quiz_form")
                        st.toast("새 문제를 추가했어요.", icon=":material/check:")
                    _bump("contents_quiz_ver")
                    st.rerun()


# ---------- 바다 소식 검토 ----------
def _edit_close() -> None:
    S.pop("contents_edit", None)


@st.dialog("소식 고치기", width="medium", on_dismiss=_edit_close)
def edit_dialog(nid: str) -> None:
    try:
        item = next((n for n in _news_rows() if n["id"] == nid), None)
    except ApiError as e:
        st.error(e.message)
        return
    if not item:
        st.warning("소식을 찾지 못했어요. 목록을 새로고침해 주세요.")
        return
    with st.form("contents_edit_form", border=False):
        title = st.text_input("제목", value=item["title"], max_chars=60)
        summary = st.text_area("요약", value=item["summary"], height=130, max_chars=max(200, len(item["summary"])),
                               help="두세 문장으로 적어 주세요. 바다 소식 목록에는 앞의 두 줄만 보여요.")
        source = st.text_input("출처", value=item["source"])
        url = st.text_input("원문 주소", value=item["url"])
        save = st.form_submit_button("고친 내용 저장하기", type="primary", width="stretch")
    if save:
        if not title.strip() or not summary.strip():
            st.error("제목이나 요약이 비어 있어요. 내용을 적어 주세요.")
        elif not url.startswith(("http://", "https://")):
            st.error("원문 주소가 맞지 않아요. http:// 또는 https://로 시작하는 주소를 적어 주세요.")
        else:
            try:
                news_data.update(nid, title=title.strip(), summary=summary.strip(), source=source.strip(),
                                 url=url.strip())
            except ApiError as e:
                st.error(e.message)
            else:
                _edit_close()
                st.toast("고친 내용을 저장했어요. 바다 소식에 바로 보여요.", icon=":material/check:")
                st.rerun()
    st.caption("출처와 원문 링크는 꼭 함께 보여요. 원문과 다른 내용이 되지 않게 고쳐 주세요.")


def _set_public(nid: str, public: bool) -> None:
    try:
        news_data.update(nid, public=public)
    except ApiError as e:
        st.error(e.message)
        return
    if public:
        st.toast("다시 공개했어요.", icon=":material/visibility:")
    else:
        st.toast("소식을 숨겼어요. 바다 소식에서 보이지 않아요.", icon=":material/visibility_off:")
    st.rerun()


def news_tab() -> None:
    try:
        run = (news_data.runs() or [None])[0]  # 실패한 수집도 포함한 마지막 기록
    except ApiError:
        run = None
    rows = _news_rows()
    hidden = sum(1 for n in rows if not n["public"])
    chips = [ui.chip(f"공개 중 {len(rows) - hidden}건", "ok"), ui.chip(f"숨김 {hidden}건", "warn" if hidden else "")]
    if run:
        chips.insert(0, ui.chip(f"마지막 수집 {news_data.date_label(run['date'])}"))
        if run["fail"]:
            chips.append(ui.chip(f"✕ 실패 출처 {run['fail']}곳", "danger"))
    ui.chips(*chips)
    ui.muted("매일 오전 6시에 모은 소식은 AI가 요약해 바로 공개돼요. 문제가 있으면 여기서 숨기거나 고쳐 주세요.")
    st.space("small")

    sel_id = S.get("contents_news_sel")
    ids = [n["id"] for n in rows]
    default = ids.index(sel_id) if sel_id in ids else None
    ev = st.dataframe(
        [{"제목": n["title"], "출처": n["source"], "날짜": news_data.date_label(n["date"]), "조회수": n["views"],
          "요약": "AI 요약" if n.get("ai") else "운영자 작성",
          "공개 상태": "✓ 공개 중" if n["public"] else "숨김"} for n in rows],
        hide_index=True, on_select="rerun", selection_mode="single-row",
        selection_default={"selection": {"rows": [default]}} if default is not None else None,
        column_config={"조회수": st.column_config.NumberColumn(format="%d", width="small")},
        key=f"contents_news_df_{S.get('contents_news_ver', 0)}")
    picked = ev.selection.rows
    S["contents_news_sel"] = rows[picked[0]]["id"] if picked else None
    item = next((n for n in rows if n["id"] == S["contents_news_sel"]), None)

    if not item:
        ui.muted("목록에서 소식을 고르면 숨기기 · 고치기 · 다시 요약을 할 수 있어요.")
    else:
        with st.container(border=True):
            ui.chips(ui.chip("✓ 공개 중", "ok") if item["public"] else ui.chip("숨김", "warn"),
                     ui.chip("AI 요약", "sea") if item.get("ai") else ui.chip("운영자 작성"),
                     *([ui.chip("운영자가 고침")] if item.get("edited") else []))
            st.markdown(f"**{item['title']}**")
            st.write(item["summary"])
            ui.muted(f"{item['source']} · {news_data.date_label(item['date'])} · 조회 {item['views']:,}")
            with st.container(horizontal=True, gap="small"):
                if item["public"]:
                    if st.button("숨기기", icon=":material/visibility_off:", key="contents_hide"):
                        _set_public(item["id"], False)
                elif st.button("다시 공개하기", icon=":material/visibility:", key="contents_show"):
                    _set_public(item["id"], True)
                if st.button("고치기", icon=":material/edit:", key="contents_edit_btn"):
                    S["contents_edit"] = item["id"]
                    st.rerun()
                if st.button("다시 요약", icon=":material/auto_awesome:", key="contents_resum"):
                    try:
                        with st.spinner("AI가 다시 요약하고 있어요…"):
                            news_data.resummarize(item["id"])
                    except ApiError as e:
                        st.error(e.message)
                    else:
                        st.toast("AI가 다시 요약했어요. 내용을 한 번 확인해 주세요." if ai.real_ai_on() else
                                 "AI 키가 없어서 원문 앞부분으로 요약을 바꿨어요. 내용을 한 번 확인해 주세요.",
                                 icon=":material/auto_awesome:")
                        st.rerun()
                st.link_button("원문 보기", item["url"], icon=":material/open_in_new:")

    st.space("small")
    with st.expander("직접 등록", icon=":material/add:"):
        ver = S.get("contents_add_ver", 0)
        with st.form(f"contents_add_form_{ver}", border=False):
            title = st.text_input("제목", max_chars=60, placeholder="예) 이번 주말 해변 정화 활동 안내")
            c1, c2 = st.columns(2)
            source = c1.text_input("출처", placeholder="예) 예시 기관 B")
            when = c2.date_input("날짜", value=_today(), max_value=_today(), format="YYYY.MM.DD")
            url = st.text_input("원문 주소", placeholder="https://")
            body = st.text_area("내용", height=110, placeholder="원문 내용 일부나 직접 정리한 요약을 적어 주세요.")
            use_ai = st.toggle("AI로 두세 문장 요약하기", value=True)
            add = st.form_submit_button("등록하고 공개하기", type="primary", width="stretch")
        if add:
            if not title.strip() or not source.strip() or not body.strip():
                st.error("제목 · 출처 · 내용 중 비어 있는 칸이 있어요. 모두 적어 주세요.")
            elif not url.startswith(("http://", "https://")):
                st.error("원문 주소가 맞지 않아요. http:// 또는 https://로 시작하는 주소를 적어 주세요.")
            else:
                try:
                    with st.spinner("등록하고 있어요…"):
                        nid = news_data.add(title.strip(), source.strip(), url.strip(), body.strip(), use_ai, when)
                except ApiError as e:
                    st.error(e.message)
                else:
                    S["contents_news_sel"] = nid
                    _bump("contents_news_ver")
                    _bump("contents_add_ver")
                    st.toast("등록했어요. 바다 소식에 바로 보여요.", icon=":material/check:")
                    st.rerun()

    if S.get("contents_edit"):
        edit_dialog(S["contents_edit"])


# ---------- 수집 출처 ----------
COLS = ["이름", "주소", "이용 조건 확인일", "사용"]


def _cell(v, default=""):
    """표에서 비워 둔 칸(None · NaN)을 빈 값으로."""
    return default if v is None or (not isinstance(v, (list, dict)) and pd.isna(v)) else v


def sources_tab() -> None:
    src = news_data.sources()
    ui.section("수집 출처")
    ui.muted("이용 조건을 확인한 공공기관 · 매체만 ‘사용’으로 켜 주세요. 켜 둔 출처에서만 매일 오전 6시에 소식을 모아요.")
    st.space("small")
    base = pd.DataFrame([{"id": s["id"], "이름": s["name"], "주소": s["url"],
                          "이용 조건 확인일": date.fromisoformat(s["checked"]) if s["checked"] else None,
                          "사용": s["active"]} for s in src], columns=["id", *COLS])
    edited = st.data_editor(
        base, num_rows="dynamic", hide_index=True, key=f"contents_src_{S.get('contents_src_ver', 0)}",
        column_order=COLS,  # id는 숨겨 두고 저장할 때 같은 출처를 찾는 데만 써요
        column_config={
            "이름": st.column_config.TextColumn(required=True, width="medium"),
            "주소": st.column_config.LinkColumn(width="medium", validate=r"^https?://"),
            "이용 조건 확인일": st.column_config.DateColumn(format="YYYY.MM.DD", max_value=_today()),
            "사용": st.column_config.CheckboxColumn(default=False, width="small"),
        })
    changed = not edited.equals(base)
    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        if st.button("변경 내용 저장하기", type="primary", icon=":material/save:", key="contents_src_save",
                     disabled=not changed):
            clean = edited.dropna(subset=["이름"])  # 아무것도 적지 않은 새 줄은 빼요
            if any(not str(n).strip() for n in clean["이름"]):
                st.error("이름이 빈 출처가 있어요. 이름을 적어 주세요.")
            else:
                rows = [{"id": int(r["id"]) if _cell(r["id"], None) is not None else None,
                         "name": str(r["이름"]).strip(), "url": str(_cell(r["주소"])).strip(),
                         "checked": str(r["이용 조건 확인일"])[:10] if _cell(r["이용 조건 확인일"], None) else None,
                         "active": bool(_cell(r["사용"], False))} for _, r in clean.iterrows()]
                try:
                    news_data.save_sources(rows)
                except ApiError as e:
                    st.error(e.message)
                else:
                    _bump("contents_src_ver")
                    st.toast("수집 출처를 저장했어요. 다음 수집부터 반영돼요.", icon=":material/check:")
                    st.rerun()
        if changed:
            ui.muted("저장하지 않은 변경이 있어요.")
    on = [s["name"] for s in src if s["active"]]
    st.caption(f"지금 사용 중: {', '.join(on) if on else '없음'} · 줄 맨 아래 ‘+’로 새 출처를 더할 수 있어요.")


# ---------- 수집 기록 ----------
def _retry(name: str) -> None:
    """[다시 수집]: 그 출처만 지금 다시 모아요. 결과는 새 수집 기록으로 남아요."""
    try:
        out = news_data.collect([name])
    except ApiError as e:
        S["contents_retry_toast"] = (name, None, e.message)
        return
    reason = out["failed"][0]["reason"] if out["failed"] else ""
    S["contents_retry_toast"] = (name, out, reason)


def _collect_all() -> None:
    """[지금 전체 수집하기]: 서버에서 수집을 시작하고 바로 돌아와요."""
    try:
        news_data.start_collect_all()
    except ApiError as e:
        S["contents_retry_toast"] = ("전체 출처", None, e.message)
        return
    S["contents_collect_waiting"] = True


def _next_collect() -> datetime:
    n = datetime.now(KST)
    six = datetime.combine(n.date(), time(6), tzinfo=KST)
    return six if n < six else six + timedelta(days=1)


def runs_tab() -> None:
    status = news_data.collect_status()
    if status["state"] == "running":
        st.info("전체 출처를 수집하는 중이에요. 잠시 뒤 ‘상태 새로고침’을 눌러 결과를 확인해 주세요.")
        if st.button("상태 새로고침", icon=":material/refresh:", key="contents_collect_refresh"):
            st.rerun()
    elif S.pop("contents_collect_waiting", False):
        if status["state"] == "done":
            st.toast(f"전체 수집 완료 · 새 소식 {status['ok']}건 · 실패 {status['fail']}곳", icon=":material/check:")
        elif status["state"] == "error":
            st.error(status.get("message", "수집에 실패했어요."))
        else:
            st.warning("서버가 재시작되어 진행 상태를 확인할 수 없어요. 아래 수집 기록을 확인해 주세요.")
    runs = news_data.runs()
    last = runs[0] if runs else None
    nxt = _next_collect()
    m1, m2, m3 = st.columns(3)
    m1.metric("마지막 수집", news_data.date_label(last["date"])[5:] if last else "—", border=True,
              help=news_data.date_label(last["date"]) if last else None)
    m2.metric("다음 수집 (매일 오전 6시)", f"{nxt:%m.%d} 06:00", border=True)
    m3.metric("공개 중인 소식", f"{len(db.news())}건", border=True)
    st.space("small")

    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        ui.section("날짜별 기록")
        if st.button("지금 전체 수집하기", type="primary", icon=":material/refresh:", key="contents_collect_all_btn",
                     disabled=status["state"] == "running"):
            _collect_all()
            st.rerun()

    ui.muted("한국 시간 오전 6시에 켜 둔 출처에서 모아요. 실패해도 이전 소식은 그대로 보여요.")
    if not runs:
        ui.empty_state("🗂️", "아직 수집 기록이 없어요. 내일 오전 6시에 첫 기록이 남아요.")
    for run in runs[:20]:
        with st.container(border=True):
            with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
                st.markdown(f"**{news_data.date_label(run['date'])}**")
                ui.chips(ui.chip(f"✓ 성공 {run['ok']}건", "ok"),
                         ui.chip(f"✕ 실패 {run['fail']}건", "danger" if run["fail"] else ""))
            if not run["failed"]:
                ui.muted("모든 출처에서 잘 모았어요.")
            for k, name in enumerate(run["failed"]):
                why = run.get("reasons", {}).get(name) or "소식을 가져오지 못했어요. 주소나 이용 조건을 확인해 주세요."
                with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
                    st.markdown(f":material/error: **{name}** · {why}")
                    st.button("다시 수집", icon=":material/refresh:", key=f"contents_retry_{run['id']}_{k}",
                              on_click=_retry, args=(name,))
    if len(runs) > 20:
        st.caption(f"최근 20번만 보여요. (전체 {len(runs)}번)")
    note = S.pop("contents_retry_toast", None)
    if note:
        name, out, reason = note
        if out and not out["fail"]:
            st.toast(f"‘{name}’에서 소식을 다시 모았어요. 새 소식 {out['ok']}건", icon=":material/check:")
        else:
            st.toast(f"‘{name}’에서 다시 모으지 못했어요. {reason}", icon=":material/error:")


try:
    {"quiz": quiz_tab, "news": news_tab, "sources": sources_tab, "runs": runs_tab}[tab]()
except ApiError as e:  # 서버가 꺼져 있거나 권한이 없을 때
    st.error(e.message, icon=":material/error:")

st.space("medium")
st.caption("퍼즐 사진 관리 · 생물 정보 고치기는 2차에 열려요.")
