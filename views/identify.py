"""U-02 ~ U-05 생물 알아보기 (편성훈 담당).

한 파일 안에서 단계(step)만 바꿔요:  upload → result → save → (완료 팝업)
페이지를 옮기지 않으니 중간에 결과가 사라지지 않아요.

시안 캡처용: 주소에 ?shot=analyzing|result|result_low|save|save_share|done|gate
"""
import time
from datetime import date

import streamlit as st

from components import auth_gate, nav, ui
from services import ai, auth, db
from services.api import ApiError

S = st.session_state
user = auth.current_user()
EXAMPLES = {"소라게": "🦀", "불가사리": "⭐", "해파리": "🪼"}


def reset() -> None:
    for k in ("identify_step", "identify_result", "identify_example", "identify_done", "identify_place_auto"):
        S.pop(k, None)


# ---------- 시안 캡처용 상태 만들기 ----------
shot = st.query_params.get("shot")
if shot and S.get("_shot_applied") != shot:
    S["_shot_applied"] = shot
    reset()
    if shot != "analyzing":
        S["identify_example"] = "해파리" if shot == "result_low" else "소라게"
        S["identify_result"] = ai.analyze(S["identify_example"])
        if shot == "result_low":
            S["identify_result"]["confidence"] = "low"
        S["identify_place_auto"] = "제주 · 협재 해변"
        S["identify_step"] = {"result": "result", "result_low": "result", "gate": "result"}.get(shot, "save")
        if shot == "save_share":
            S["identify_share"] = True
        if shot == "done":
            S["identify_done"] = {"new_species": True, "total_species": 4, "count": 1, "post_id": None,
                                  "name": "소라게"}

step = S.setdefault("identify_step", "upload")


# ---------- U-05 담기 완료 팝업 ----------
@st.dialog("담기 완료", on_dismiss=reset)
def show_done(info: dict) -> None:
    if info["new_species"]:
        head = "새로운 바다 친구!"
        body = f"{info['name']}가 내 수족관에 들어왔어요.<br>지금까지 <b>{info['total_species']}종</b>을 만났어요."
    else:
        head = "관찰 기록이 늘었어요"
        body = f"{info['name']} 관찰 기록이 하나 늘었어요.<br><b>{info['count']}번째</b> 만남이에요."
    if info.get("post_id"):
        body += "<br>관찰 이야기에도 올렸어요."
    st.markdown(f'<div class="sia-celebrate"><div class="big">🎉</div><h3>{head}</h3><p>{body}</p></div>',
                unsafe_allow_html=True)
    if st.button("수족관 보기", type="primary", width="stretch"):
        reset()
        nav.go("aquarium")
    if info.get("post_id") and st.button("공유한 글 보기", width="stretch"):
        pid = info["post_id"]
        reset()
        nav.go("community", post=pid)
    if st.button("다른 생물 알아보기", width="stretch"):
        reset()
        st.rerun()


# ---------- U-02 사진 올리기 ----------
def show_upload() -> None:
    ui.page_header("생물 알아보기", "궁금한 바다 생물 사진을 올려 주세요.")
    left, right = st.columns([3, 2], gap="large")
    with right:  # 남은 횟수 · 사진 안내 (휴대폰에서는 알아보기 버튼 아래에 보여요. 버튼에 남은 횟수가 필요해서 먼저 그려요)
        left_n, limit = db.remaining(user)
        with st.container(border=True):
            st.markdown(f"**오늘 남은 횟수 {left_n} / {limit}회**")
            if not user:
                ui.muted("로그인하면 하루 20회까지 할 수 있어요.")
            ui.muted("사진은 생물 이름을 알아보는 데만 쓰여요. AI 분석을 위해 외부 AI 서비스로 전송돼요.")
        if left_n == 0:
            st.warning("오늘은 다 썼어요. 내일 다시 만나요!")
    with left:  # 올리기 → 미리 보기 → 알아보기 버튼이 한 줄로 이어지게
        file = st.file_uploader("사진 올리기", type=db.settings()["formats"], label_visibility="collapsed",
                                max_upload_size=db.settings()["max_mb"], key="identify_file",
                                help="스마트폰에서는 누르면 ‘사진 찍기 / 앨범’ 중에 고를 수 있어요.")
        st.caption(f"JPG · PNG, {db.settings()['max_mb']}MB까지 · 스마트폰에서는 누르면 사진 찍기나 앨범을 고를 수 있어요.")
        ex = None
        if file:
            with st.container(key="identify_preview"):
                st.image(file, width="stretch")
        else:
            st.markdown("**사진이 없나요? 예시로 체험해 보세요**")
            ex = st.pills("예시 사진", list(EXAMPLES), format_func=lambda k: f"{EXAMPLES[k]} {k}",
                          label_visibility="collapsed", key="identify_pick")
            if ex:
                S["identify_example"] = ex
                ui.photo(EXAMPLES[ex], tone="sand" if ex == "소라게" else "aqua", height=220, label="예시 사진")
        ready = bool(file or ex) and left_n > 0
        if st.button("이 사진으로 알아보기", type="primary", width="stretch", disabled=not ready,
                     icon=":material/search:", key="identify_go"):
            with st.spinner("바다 친구를 찾고 있어요…"):
                try:
                    S["identify_result"] = ai.analyze(None if file else ex,
                                                      image_bytes=file.getvalue() if file else None,
                                                      filename=file.name if file else "photo.jpg")
                except ai.NotSeaCreature:
                    st.warning("사진에서 바다 생물을 찾지 못했어요. 생물이 크게 보이게 다시 찍어 주세요. 횟수는 줄지 않았어요.")
                    return
                except ApiError as e:  # 횟수 초과 · 파일 형식 · 서버 오류 등 (서버가 준 안내를 그대로)
                    st.error(e.message)
                    return
            S["identify_uploaded"] = bool(file)
            S["identify_place_auto"] = "제주 · 협재 해변" if ex else ""
            S["identify_step"] = "result"
            st.rerun()
        if not ready and left_n > 0:
            st.caption("사진을 올리거나 예시를 고르면 버튼이 켜져요.")


# ---------- U-03 분석 결과 ----------
def show_result() -> None:
    r = S["identify_result"]
    ui.page_header("분석 결과", "AI가 사진을 보고 추측한 결과예요.")
    if r.get("source") == "example" and S.get("identify_uploaded"):
        st.caption("예시 모드: 올린 사진 대신 예시 결과를 보여줘요. `.env`에 GEMINI_API_KEY를 넣으면 실제로 알아봐요 (설치 가이드 3장).")
    if r["confidence"] == "low":
        st.info("AI도 헷갈려요. 아래 ‘이 생물이 아닌가요?’에서 후보를 골라 주세요.", icon=":material/help:")
    left, right = st.columns(2, gap="large")
    with left:
        ui.photo(r["emoji"], tone=r.get("tone", "aqua"), height=300)
    with right:
        ui.chips(ui.chip("AI 추측", "sea"), ui.chip(ui.CONFIDENCE[r["confidence"]]))
        st.markdown(f'<h2 class="sia-h2" style="font-size:26px;margin:.4rem 0">{r["name"]}</h2>',
                    unsafe_allow_html=True)
        ui.safety_badge(r["safety"])
        if r.get("protected"):
            st.error("해양보호생물이에요. 잡거나 가져가면 안 돼요.", icon=":material/shield:")
        st.write(r["summary"])
        st.caption("안전 정보는 AI가 추측한 참고용이에요. 위험해 보이면 만지지 말고 어른에게 알려 주세요.")
        with st.expander("사는 곳"):
            st.write(r["info"]["habitat"])
        with st.expander("먹이"):
            st.write(r["info"]["food"])
        with st.expander("재미있는 사실"):
            st.write(r["info"]["fun_fact"])
        with st.expander("이 생물이 아닌가요?", expanded=r["confidence"] == "low"):
            options = r["candidates"] + ["직접 입력", "잘 모르겠어요 (미확인으로 담기)"]
            pick = st.radio("다른 후보", options, index=None, label_visibility="collapsed")
            typed = st.text_input("생물 이름", placeholder="알고 있는 이름을 적어 주세요") if pick == "직접 입력" else ""
            if st.button("이 이름으로 바꾸기", disabled=not pick or (pick == "직접 입력" and not typed)):
                r["name"] = typed or ("미확인 생물" if pick.startswith("잘 모르겠어요") else pick)
                r["emoji"] = "❔" if r["name"] == "미확인 생물" else r["emoji"]
                st.toast("이름을 바꿨어요")
                st.rerun()

        st.space("small")
        if st.button("내 수족관에 담기", type="primary", width="stretch", icon="🐠", key="to_save") \
                and auth_gate.login_required("이 생물을 수족관에 담을 수 있어요", here="identify"):
            S["identify_step"] = "save"
            st.rerun()
        if shot == "gate" and not user:
            auth_gate.login_required("이 생물을 수족관에 담을 수 있어요", here="identify")
        with st.container(horizontal=True, gap="small"):
            if st.button("다른 사진으로 다시 하기", icon=":material/refresh:"):
                reset()
                st.rerun()
            nav.link("report", "정보가 틀렸어요", icon=":material/flag:", type="생물 정보 정정", name=r["name"])


# ---------- U-04 수족관에 담기 ----------
def show_save() -> None:
    r = S["identify_result"]
    if st.button("결과로 돌아가기", icon=":material/arrow_back:", type="tertiary"):
        S["identify_step"] = "result"
        st.rerun()
    ui.page_header("수족관에 담기", "장소와 메모는 비워 둬도 괜찮아요.")
    mine = {c["species"]["id"]: c["count"] for c in db.aquarium(user["id"])} if user else {}
    met = mine.get(r["id"], 0)
    col, _ = st.columns([3, 2])
    with col:
        with st.container(border=True):
            ui.item_row(r["emoji"], r["name"], "처음 만난 생물이에요" if not met else f"{met + 1}번째 만남이에요",
                        tone=r.get("tone", "aqua"))
        when = st.date_input("만난 날", value=date.today(), max_value=date.today(), format="YYYY.MM.DD")
        auto = S.get("identify_place_auto", "")
        places = ["선택 안 함"] + [v["name"].replace(" · ", " · ") for v in db.regions().values()]
        if auto and auto not in places:
            places.insert(1, auto)
        place = st.selectbox("만난 곳 (선택)", places, index=places.index(auto) if auto else 0)
        if auto and place == auto:
            st.caption("사진 속 위치 정보로 채웠어요. 원하지 않으면 ‘선택 안 함’으로 바꿔 주세요.")
        memo = st.text_area("메모 (선택)", placeholder="어디서, 어떻게 만났나요?", max_chars=200)

        share = st.toggle("커뮤니티에도 공유하기", key="identify_share",
                          help="켜면 ‘관찰 이야기’ 게시판에 함께 올라가요.")
        if not share:
            st.caption("켜면 ‘관찰 이야기’에 올라가요. 꺼 두면 나만 볼 수 있어요.")
        title, level, agree = "", "none", True
        if share:
            spot = place.split(" · ")[-1] if place != "선택 안 함" else "바다"
            title = st.text_input("제목", value=f"{spot}에서 만난 {r['name']}", max_chars=50)
            lv = st.radio("위치 공개", ["공개하지 않기", "지역까지만 (예: 제주)"], horizontal=True,
                          disabled=place == "선택 안 함")
            level = "region" if lv.startswith("지역") else "none"
            agree = st.checkbox("사진을 사이트에서 보여줘도 괜찮아요 (필수)",
                                help="언제든 수족관에서 ‘공유 취소’로 내릴 수 있어요.")
            if not agree:
                st.caption("사진 동의에 체크하면 ‘담고 공유하기’를 누를 수 있어요.")
        label = "담고 공유하기" if share else "담기"
        if st.button(label, type="primary", width="stretch", disabled=not agree, key="do_save"):
            try:
                info = db.add_observation(user["id"], r, str(when), "" if place == "선택 안 함" else place,
                                          memo, share, title, level)
            except ApiError as e:
                st.error(e.message or "저장하지 못했어요. 입력한 내용은 그대로 있어요. 다시 시도해 주세요.")
                return
            info["name"] = r["name"]
            S["identify_done"] = info
            st.rerun()


# ---------- 화면 그리기 ----------
if shot == "analyzing":
    show_analyzing()
elif step == "upload":
    show_upload()
elif step == "result":
    show_result()
elif step == "save":
    if not user:  # 로그인 없이 담기 화면에 오면 결과로 되돌려요
        S["identify_step"] = "result"
        st.rerun()
    show_save()

if S.get("identify_done"):
    show_done(S["identify_done"])
