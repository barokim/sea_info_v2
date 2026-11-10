"""U-06 나의 수족관 · U-07 생물 카드 상세 (김바로 담당).

목록: aquarium            상세: aquarium?sp=<생물 id>   (미확인 생물 카드: aquarium?sp=unknown)
비회원은 흐린 예시 수족관 + [로그인하고 내 수족관 만들기]를 봐요.

시안 캡처용: ?shot=empty (빈 수족관) | edit (기록 수정 팝업) | delete (지우기 확인 팝업) | share (공유하기 팝업)
            edit · delete · share는 sp가 없으면 별불가사리(sp_star) 카드에서 열어요.
            ?sp=unknown 또는 ?shot=unknown → 미확인 생물 카드 (체험 회원에게 예시 미확인 기록을 한 번 담아요)
데이터는 FastAPI(나의 수족관 API)에 저장돼요. 쓰기가 실패하면 서버가 준 안내(e.message)를 보여줘요.
"""
from datetime import date

import streamlit as st

from components import nav, ui
from services import aquarium_data as aq
from services import auth
from services.api import ApiError

S = st.session_state
user = auth.current_user()
shot = st.query_params.get("shot")
sp_id = st.query_params.get("sp")
if shot in ("edit", "delete", "share") and not sp_id:
    sp_id = "sp_star"
legacy_unknown = sp_id == "unknown" or shot == "unknown"  # 예전 시안 주소(?sp=unknown)도 그대로 열려요
if legacy_unknown:
    sp_id = aq.UNKNOWN_ID

if S.get("aq_toast"):
    st.toast(S.pop("aq_toast"))

# ---------- 시안 캡처용 상태 만들기 ----------
if user and legacy_unknown and not S.get("_aq_unknown_demo"):
    S["_aq_unknown_demo"] = True
    try:
        aq.ensure_unknown_demo(user["id"])  # 이미 미확인 기록이 있으면 아무것도 하지 않아요
    except ApiError as e:
        st.warning(e.message, icon=":material/warning:")
if shot and S.get("_aq_shot") != shot:
    S["_aq_shot"] = shot
    S.pop("aq_dialog", None)
    if user and shot in ("edit", "delete", "share"):
        try:
            card = aq.find_card(user["id"], sp_id)
        except ApiError:
            card = None
        if card:
            recs = card["records"]
            if shot == "share":  # 아직 공유하지 않은 기록에서 열어요
                recs = [r for r in recs if not r.get("post_id")] or recs
            S["aq_dialog"] = (shot, recs[0]["id"])


def close_dialog() -> None:
    S.pop("aq_dialog", None)


def done(msg: str, go_list: bool = False, go_sp: str | None = None) -> None:
    """작업이 끝나면 팝업을 닫고 알림을 남긴 뒤 화면을 다시 그려요."""
    S["aq_toast"] = msg
    close_dialog()
    if go_list:
        nav.go("aquarium")
    elif go_sp:
        nav.go("aquarium", sp=go_sp)
    st.rerun()


def species_name(sid: str) -> str:
    return aq.species_of(sid)["name"]


# ---------- 팝업: 기록 수정 ----------
@st.dialog("관찰 기록 수정", on_dismiss=close_dialog)
def edit_dialog(rec_id: str) -> None:
    r = aq.record(rec_id)
    if not r:
        close_dialog()
        st.rerun()
    sp = aq.species_of(r["species"])
    ui.item_row(sp["emoji"], sp["name"], f"{aq.fmt_date(r['date'], short=False)}에 만난 기록", tone=sp["tone"])
    when = st.date_input("만난 날", value=date.fromisoformat(r["date"]), max_value=date.today(),
                         format="YYYY.MM.DD", key=f"aq_edit_date_{rec_id}")
    place = st.text_input("만난 곳 (선택)", value=r.get("place", ""), placeholder="예: 제주 · 협재 해변",
                          max_chars=40, key=f"aq_edit_place_{rec_id}")
    memo = st.text_area("메모 (선택)", value=r.get("memo", ""), placeholder="어디서, 어떻게 만났나요?",
                        max_chars=200, key=f"aq_edit_memo_{rec_id}")
    ids = aq.species_ids(include_unknown=sp["id"] == aq.UNKNOWN_ID)
    if sp["id"] not in ids:  # AI가 새로 알려준 생물
        ids = [sp["id"]] + ids
    move_to = st.selectbox("생물 이름 (잘못 담았다면 바꿔 주세요)", ids, index=ids.index(sp["id"]),
                           format_func=species_name, key=f"aq_edit_sp_{rec_id}")
    if move_to != sp["id"]:
        st.caption(f"저장하면 이 기록이 ‘{species_name(move_to)}’ 생물 카드로 옮겨져요.")
    if r.get("post_id"):
        st.caption("공유 중인 기록이에요. 바꾼 내용은 내 수족관에 먼저 반영돼요.")
    with st.container(horizontal=True, gap="small"):
        if st.button("저장하기", type="primary", key=f"aq_edit_save_{rec_id}", icon=":material/check:"):
            try:  # 내용 고치기와 카드 옮기기를 한 번에 저장해요
                aq.update(rec_id, place.strip(), memo.strip(), str(when),
                          species_id=move_to if move_to != sp["id"] else None)
            except ApiError as e:
                st.error(e.message or "저장하지 못했어요. 입력한 내용은 그대로 있어요. 다시 시도해 주세요.")
                return
            if move_to != sp["id"]:
                done(f"‘{species_name(move_to)}’ 카드로 옮겼어요", go_sp=move_to)
            done("관찰 기록을 고쳤어요")
        if st.button("취소", key=f"aq_edit_cancel_{rec_id}"):
            close_dialog()
            st.rerun()


# ---------- 팝업: 기록 지우기 ----------
@st.dialog("관찰 기록 지우기", on_dismiss=close_dialog)
def delete_dialog(rec_id: str) -> None:
    r = aq.record(rec_id)
    if not r:
        close_dialog()
        st.rerun()
    sp = aq.species_of(r["species"])
    st.markdown("**이 관찰 기록을 지울까요?** 지우면 되돌릴 수 없어요.")
    with st.container(border=True):
        ui.item_row(sp["emoji"], aq.fmt_date(r["date"], short=False), r.get("place") or "장소 없음", tone=sp["tone"])
        st.caption(r.get("memo") or "메모 없음")
    if r.get("post_id"):
        st.warning("공유 중인 기록이에요. 지우면 관찰 이야기에 올린 글도 함께 내려가요.", icon=":material/warning:")
    with st.container(horizontal=True, gap="small"):
        if st.button("지우기", type="primary", key=f"aq_del_ok_{rec_id}", icon=":material/delete:"):
            try:
                msg = aq.delete(rec_id)
                left = aq.find_card(user["id"], sp["id"])
            except ApiError as e:
                st.error(e.message or "지우지 못했어요. 잠시 뒤 다시 시도해 주세요.")
                return
            done(msg, go_list=not left)
        if st.button("그대로 두기", key=f"aq_del_cancel_{rec_id}"):
            close_dialog()
            st.rerun()


# ---------- 팝업: 공유하기 ----------
@st.dialog("관찰 이야기에 공유하기", on_dismiss=close_dialog)
def share_dialog(rec_id: str) -> None:
    r = aq.record(rec_id)
    if not r:
        close_dialog()
        st.rerun()
    sp = aq.species_of(r["species"])
    ui.item_row(sp["emoji"], sp["name"], f"{aq.fmt_date(r['date'], short=False)}에 만난 기록", tone=sp["tone"])
    spot = r["place"].split(" · ")[-1] if r.get("place") else "바다"
    title = st.text_input("제목", value=f"{spot}에서 만난 {sp['name']}", max_chars=50, key=f"aq_share_title_{rec_id}")
    region = r["place"].split(" · ")[0] if r.get("place") else ""
    lv = st.radio("위치 공개", ["공개하지 않기", f"지역까지만 (예: {region or '제주'})"], horizontal=True,
                  disabled=not region, key=f"aq_share_level_{rec_id}")
    agree = st.checkbox("사진을 사이트에서 보여줘도 괜찮아요 (필수)", key=f"aq_share_agree_{rec_id}",
                        help="언제든 수족관에서 ‘공유 취소’로 내릴 수 있어요.")
    st.caption("메모가 글 내용으로 올라가요. 메모가 없으면 생물 소개가 들어가요.")
    with st.container(horizontal=True, gap="small"):
        if st.button("공유하기", type="primary", icon=":material/share:", disabled=not agree,
                     key=f"aq_share_ok_{rec_id}"):
            try:
                aq.share(rec_id, title.strip(), "region" if lv.startswith("지역") else "none", consent=agree)
            except ApiError as e:
                st.error(e.message)
                return
            done("공유했어요! 관찰 이야기에 올라갔어요.")
        if st.button("취소", key=f"aq_share_cancel_{rec_id}"):
            close_dialog()
            st.rerun()


# ---------- U-06 목록 ----------
def _set_public() -> None:
    on = bool(S.get("aq_public"))
    try:
        S["aq_toast"] = aq.set_public(on)
    except ApiError as e:
        S.pop("aq_public", None)  # 바뀌지 않았으니 스위치를 서버 값으로 되돌려요
        S["aq_toast"] = e.message


def show_list() -> None:
    ui.page_header("나의 수족관", "내가 만난 바다 친구들을 모아 봐요.")
    cards = [] if shot == "empty" else aq.cards(user["id"])
    if not cards:
        ui.empty_state("🐚", "아직 만난 생물이 없어요. 첫 바다 친구를 찾아볼까요?", "생물 알아보기", "identify",
                       key="aq_empty_go")
        st.caption("생물 알아보기 결과에서 ‘내 수족관에 담기’를 누르면 여기에 생물 카드가 생겨요.")
        return

    kinds, recs, shared = aq.summary(cards)
    left, right = st.columns([3, 2], gap="medium")
    with left:
        with st.container(border=True):
            st.markdown(f"**지금까지 {kinds}종, {recs}번 만났어요**")
            with st.container(horizontal=True, gap="small"):
                st.metric("모은 생물", f"{kinds}종")
                st.metric("관찰 기록", f"{recs}번")
                st.metric("공유 중", f"{shared}개")
    with right:
        with st.container(border=True):
            on = st.toggle("다른 사람에게 내 수족관 보여주기", value=bool(user.get("aquarium_public")),
                           key="aq_public", on_change=_set_public)
            st.caption("켜도 ‘공유 중’인 기록만 보여요. 처음에는 꺼져 있어요.")
            if on:
                nav.link("user_aquarium", "다른 사람에게 보이는 모습", icon=":material/visibility:", u=user["id"])

    st.space("small")
    c1, c2 = st.columns([3, 2], gap="medium")
    q = c1.text_input("이름으로 찾기", key="aq_search", placeholder="예: 불가사리", icon=":material/search:")
    sort = c2.selectbox("정렬", ["최근 만난 순", "이름순", "많이 만난 순"], key="aq_sort")
    counts = {"전체": len(cards),
              "공유 중": sum(1 for c in cards if c["shared"]),
              "미확인": sum(1 for c in cards if c["species"]["id"] == aq.UNKNOWN_ID)}
    view = st.segmented_control("보기", list(counts), default="전체", required=True, key="aq_filter",
                                format_func=lambda v: f"{v} {counts[v]}")

    shown = [c for c in cards if q.strip() in c["species"]["name"]] if q.strip() else list(cards)
    if view == "공유 중":
        shown = [c for c in shown if c["shared"]]
    elif view == "미확인":
        shown = [c for c in shown if c["species"]["id"] == aq.UNKNOWN_ID]
    if sort == "이름순":
        shown.sort(key=lambda c: c["species"]["name"])
    elif sort == "많이 만난 순":
        shown.sort(key=lambda c: -c["count"])

    if not shown:
        ui.empty_state("🐚", "찾는 생물이 없어요. 검색어나 보기를 바꿔 보세요.")
    else:
        with st.container(horizontal=True, gap="small"):
            for c in shown:
                if aq.species_card(c, key=f"aq_open_{c['species']['id']}"):
                    nav.go("aquarium", sp=c["species"]["id"])
    st.space("small")
    if st.button("새 바다 친구 알아보기", icon=":material/photo_camera:", key="aq_more"):
        nav.go("identify")


# ---------- U-07 생물 카드 상세 ----------
def record_box(r: dict, sp: dict, unknown: bool) -> None:
    rid = r["id"]
    with st.container(border=True):
        with st.container(horizontal=True, gap="medium", vertical_alignment="top"):
            ui.photo(sp["emoji"], sp["tone"], height=84, width=84)
            with st.container(gap="small"):
                with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center",
                                  gap="small"):
                    st.markdown(f"**{aq.fmt_date(r['date'], short=False)}**", width="content")
                    if r.get("post_id"):
                        st.badge("공유 중", icon=":material/public:", color="primary")
                    else:
                        st.badge("나만 보기", icon=":material/lock:", color="gray")
                st.markdown(f":material/location_on: {r.get('place') or '장소를 적지 않았어요'}")
                if r.get("memo"):
                    st.write(r["memo"])
                else:
                    st.caption("메모가 없어요.")
        with st.container(horizontal=True, gap="small"):
            if st.button("수정", icon=":material/edit:", key=f"aq_edit_{rid}"):
                S["aq_dialog"] = ("edit", rid)
                st.rerun()
            if st.button("삭제", icon=":material/delete:", key=f"aq_del_{rid}"):
                S["aq_dialog"] = ("delete", rid)
                st.rerun()
            if unknown:
                st.button("공유하기", icon=":material/share:", key=f"aq_share_{rid}", disabled=True,
                          help="이름을 정하면 공유할 수 있어요.")
            elif r.get("post_id"):
                if st.button("공유 취소", icon=":material/visibility_off:", key=f"aq_unshare_{rid}"):
                    try:
                        aq.unshare(rid)
                    except ApiError as e:
                        st.error(e.message)
                    else:
                        done("공유를 취소했어요. 이제 나만 볼 수 있어요.")
                nav.link("community", "공유한 글 보기", icon=":material/forum:", post=r["post_id"])
            else:
                if st.button("공유하기", icon=":material/share:", key=f"aq_share_{rid}"):
                    S["aq_dialog"] = ("share", rid)
                    st.rerun()


def show_detail(card: dict, all_cards: list[dict]) -> None:
    sp = card["species"]
    unknown = sp["id"] == aq.UNKNOWN_ID
    if st.button("수족관으로", icon=":material/arrow_back:", type="tertiary", key="aq_back"):
        nav.go("aquarium")
    first = card["records"][-1]["date"]
    ui.page_header(sp["name"], f"{card['count']}번 만났어요 · 처음 만난 날 {aq.fmt_date(first, short=False)}")

    left, right = st.columns(2, gap="large")
    with left:
        ui.photo(sp["emoji"], sp["tone"], height=230, label="대표 사진")
    with right:
        ui.chips(ui.chip("생물 카드", "sea"), ui.chip(f"{card['count']}번 만남"),
                 ui.chip(f"마지막 {aq.fmt_date(card['last'], short=False)}"))
        if unknown:
            st.info("아직 이름을 모르는 생물이에요. 이름을 정하면 그 생물 카드로 옮겨져요.", icon=":material/help:")
            ids = aq.species_ids()
            pick = st.selectbox("이름 정하기", ids, index=None, placeholder="생물 이름을 골라 주세요",
                                format_func=species_name, key="aq_name_pick")
            if st.button("이 이름으로 정하기", type="primary", disabled=not pick, key="aq_name_save"):
                try:
                    for r in list(card["records"]):
                        aq.move(r["id"], pick)
                except ApiError as e:
                    st.error(e.message)
                else:
                    done(f"‘{species_name(pick)}’ 카드로 옮겼어요", go_sp=pick)
            nav.link("write", "이름을 모르겠다면 궁금해요에 물어보기", icon=":material/forum:", board="qna")
        else:
            ui.safety_badge(sp["safety"], with_reason=False)
            st.markdown(f"**안전** · {sp['safety']['reason']}")
            if sp.get("protected"):
                st.error("해양보호생물이에요. 잡거나 가져가면 안 돼요.", icon=":material/shield:")
            st.write(sp["summary"])
            st.markdown(f"**사는 곳** · {sp['info']['habitat']}  \n**먹이** · {sp['info']['food']}  \n"
                        f"**재미있는 사실** · {sp['info']['fun_fact']}")
            st.caption("안전 정보는 AI가 추측한 참고용이에요.")
            nav.link("report", "정보가 틀렸어요", icon=":material/flag:", type="생물 정보 정정", name=sp["name"])

    st.space("small")
    ui.section(f"관찰 기록 {card['count']}개 · 최신순")
    for r in card["records"]:
        record_box(r, sp, unknown)

    st.space("small")
    idx = next(i for i, c in enumerate(all_cards) if c["species"]["id"] == sp["id"])
    prev_c = all_cards[idx - 1] if idx > 0 else None
    next_c = all_cards[idx + 1] if idx + 1 < len(all_cards) else None
    c1, c2 = st.columns(2, wrap=False)
    with c1:
        if prev_c and st.button(f"이전 · {prev_c['species']['name']}", icon=":material/chevron_left:",
                                key="aq_prev", width="stretch"):
            nav.go("aquarium", sp=prev_c["species"]["id"])
    with c2:
        if next_c and st.button(f"다음 · {next_c['species']['name']}", icon=":material/chevron_right:",
                                icon_position="right", key="aq_next", width="stretch"):
            nav.go("aquarium", sp=next_c["species"]["id"])


# ---------- 비회원: 흐린 예시 수족관 ----------
def show_guest() -> None:
    ui.page_header("나의 수족관", "내가 만난 바다 친구들을 모아 보는 곳이에요.")
    with st.container(border=True, horizontal_alignment="center"):
        st.markdown('<div class="sia-empty"><div class="ic">🐠</div>'
                    '<p>로그인하면 알아본 생물을 담아 나만의 수족관을 만들 수 있어요.</p></div>',
                    unsafe_allow_html=True)
        if st.button("로그인하고 내 수족관 만들기", type="primary", icon=":material/login:", key="aq_guest_login"):
            nav.remember_here("aquarium")
            S["after_login"] = S.get("back_to")
            nav.go("login")
    st.space("small")
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        st.markdown('<h2 class="sia-h2">이런 모습이 돼요</h2>', unsafe_allow_html=True, width="content")
        ui.chips(ui.chip("예시 수족관", "demo"))
    tiles = []
    for c in aq.example_cards():
        s = c["species"]
        chip = ui.chip("공유 중", "sea") if c["shared"] else ui.chip("나만 보기")
        tiles.append(f'<div style="width:{aq.CARD_W}px">{ui.photo_html(s["emoji"], s["tone"], 104)}'
                     f'<p style="margin:.5rem 0 0"><b>{s["name"]}</b></p>'
                     f'<p class="sia-muted">{c["count"]}번 만남 · {aq.fmt_date(c["last"])}</p>'
                     f'<div class="sia-chips" style="margin-top:.3rem">{chip}</div></div>')
    st.markdown('<div aria-hidden="true" style="display:flex;flex-wrap:wrap;gap:16px;opacity:.45;'
                f'filter:grayscale(.35);pointer-events:none">{"".join(tiles)}</div>', unsafe_allow_html=True)


# ---------- 화면 그리기 ----------
try:
    if not user:
        show_guest()
    elif sp_id:
        all_cards = aq.cards(user["id"])
        card = next((c for c in all_cards if c["species"]["id"] == sp_id), None)
        if card:
            show_detail(card, all_cards)
        else:
            ui.page_header("생물 카드", "내 수족관에 없는 생물이에요.")
            st.warning("이 생물 카드를 찾지 못했어요. 수족관에서 다시 골라 주세요.", icon=":material/search_off:")
            if st.button("수족관으로", icon=":material/arrow_back:", key="aq_missing_back"):
                nav.go("aquarium")
    else:
        show_list()
except ApiError as e:
    st.error(e.message, icon=":material/cloud_off:")
    st.stop()

dlg = S.get("aq_dialog")
if user and dlg:
    kind, rid = dlg
    if aq.record(rid) is None:
        close_dialog()
    elif kind == "edit":
        edit_dialog(rid)
    elif kind == "delete":
        delete_dialog(rid)
    elif kind == "share":
        share_dialog(rid)
