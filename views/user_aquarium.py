"""U-11 다른 사람 수족관 (김바로 담당 · 2차 기능을 시안으로 미리 만들어요).

주소: user?u=<회원 id>   예) user?u=u_2 (공개)  ·  user?u=u_4 (비공개)
‘공유 중’ 기록이 있는 생물만 카드로 보여요. 카드를 누르면 공유 기록 팝업 (위치는 공개한 경우만).
u가 없으면 구경할 수 있는 수족관 목록을 보여줘요.

시안 캡처용: ?shot=records (첫 생물 카드의 공유 기록 팝업)
데이터: GET /aquariums/public (목록) · GET /users/<id>/aquarium (공개면 카드, 비공개면 403 안내, 없으면 404).
"""
import streamlit as st

from components import nav, ui
from services import aquarium_data as aq
from services import auth, db
from services.api import ApiError

S = st.session_state
me = auth.current_user()
uid = st.query_params.get("u")
shot = st.query_params.get("shot")


def close_dialog() -> None:
    S.pop("ua_dialog", None)


def public_users() -> list[dict]:
    """[{owner: {id, nickname, character, grade}, species_count, record_count}] — 못 불러오면 빈 목록."""
    try:
        return aq.public_aquariums()
    except ApiError:
        return []


def other_aquariums(skip: str | None = None) -> None:
    rows = [x for x in public_users() if x["owner"]["id"] != skip]
    if not rows:
        return
    ui.section("다른 수족관 구경하기")
    with st.container(horizontal=True, gap="small"):
        for x in rows:
            o = x["owner"]
            if st.button(f"{o['character']} {o['nickname']} · {x['species_count']}종", key=f"ua_go_{o['id']}"):
                nav.go("user_aquarium", u=o["id"])


@st.dialog("공유한 관찰 기록", width="medium", on_dismiss=close_dialog)
def records_dialog(card: dict, owner: dict) -> None:
    sp = card["species"]
    ui.item_row(sp["emoji"], sp["name"], f"{owner['nickname']}님이 공유한 기록 {card['count']}개", tone=sp["tone"])
    ui.safety_badge(sp["safety"], with_reason=False)
    for r in card["records"]:
        with st.container(border=True):
            st.markdown(f"**{r['title']}**")
            ui.chips(ui.chip(r["when"]), ui.chip(r["place"] or "위치 비공개"), ui.chip(f"♥ {r['likes']}", "coral"))
            if r.get("memo"):
                st.write(r["memo"])
            if r.get("post_id"):
                nav.link("community", "관찰 이야기에서 보기", icon=":material/forum:", post=r["post_id"])
    st.caption("위치는 올린 사람이 공개한 경우에만 보여요.")
    if st.button("닫기", width="stretch", key="ua_close"):
        close_dialog()
        st.rerun()


# ---------- u 없이 왔을 때: 구경할 수 있는 수족관 ----------
if not uid:
    ui.page_header("다른 사람 수족관", "다른 회원이 공개한 수족관을 구경해요.")
    rows = public_users()
    if not rows:
        ui.empty_state("🐚", "아직 공개된 수족관이 없어요. 내 수족관을 공개하면 여기에 보여요.")
    with st.container(horizontal=True, gap="small"):
        for x in rows:
            u = x["owner"]
            with st.container(border=True, width=aq.CARD_W, gap="small"):
                ui.photo(u["character"], "aqua", height=96)
                st.markdown(f"**{u['nickname']}**")
                ui.muted(f"공유한 생물 {x['species_count']}종")
                if st.button("구경하기", key=f"ua_pick_{u['id']}", width="stretch"):
                    nav.go("user_aquarium", u=u["id"])
    st.stop()

private_msg = ""
try:
    view = aq.public_view(uid)
    owner, cards, public = view["owner"], view["cards"], True
except ApiError as e:
    if e.status == 403:  # 비공개 수족관: 닉네임 · 캐릭터만 보여줘요
        owner, cards, public, private_msg = db.user(uid), [], False, e.message
    elif e.status == 404:
        ui.page_header("다른 사람 수족관")
        st.warning(e.message, icon=":material/search_off:")
        other_aquariums()
        st.stop()
    else:
        ui.page_header("다른 사람 수족관")
        st.error(e.message, icon=":material/cloud_off:")
        st.stop()

mine = bool(me and me["id"] == uid)

# 시안 캡처용: 공유 기록 팝업
if shot == "records" and S.get("_ua_shot") != f"{uid}:{shot}" and cards:
    S["_ua_shot"] = f"{uid}:{shot}"
    S["ua_dialog"] = cards[0]["species"]["id"]

ui.page_header(f"{owner['nickname']}님의 수족관", "공개한 수족관을 구경해요. ‘공유 중’인 기록만 보여요.")
if mine:
    st.info("다른 사람에게는 내 수족관이 이렇게 보여요.", icon=":material/visibility:")

with st.container(border=True):
    with st.container(horizontal=True, vertical_alignment="center", gap="medium"):
        ui.photo(owner["character"], "aqua", height=72, width=72)
        with st.container(gap="small"):
            st.markdown(f"**{owner['nickname']}**")
            if public:
                recs = sum(c["count"] for c in cards)
                ui.chips(ui.chip(f"공유한 생물 {len(cards)}종", "sea"), ui.chip(f"공유 기록 {recs}개"),
                         ui.chip(owner.get("grade") or "바다 친구"))
            else:
                ui.chips(ui.chip("비공개 수족관"))
            st.caption("생물 카드를 누르면 공유한 기록을 볼 수 있어요." if public else "공유한 기록을 볼 수 없어요.")

if not public:
    st.info(private_msg or "비공개 수족관이에요. 이 회원이 수족관을 공개하면 구경할 수 있어요.", icon=":material/lock:")
    if mine:
        nav.link("aquarium", "내 수족관에서 공개 설정 바꾸기", icon=":material/settings:")
    st.space("small")
    other_aquariums(skip=uid)
    st.stop()

st.space("small")
ui.section("공개한 생물")
if not cards:
    ui.empty_state("🐚", "아직 공유한 기록이 없어요. 공유한 기록이 생기면 여기에 보여요.")
else:
    with st.container(horizontal=True, gap="small"):
        for c in cards:
            if aq.species_card(c, key=f"ua_open_{c['species']['id']}", button="기록 보기",
                               sub=f"{c['count']}개 공유 · {c['last']}", show_status=False):
                S["ua_dialog"] = c["species"]["id"]
                st.rerun()

st.space("small")
other_aquariums(skip=uid)

open_sp = S.get("ua_dialog")
if open_sp:
    card = next((c for c in cards if c["species"]["id"] == open_sp), None)
    if card:
        records_dialog(card, owner)
    else:
        close_dialog()
