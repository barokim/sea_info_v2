"""C-02 오늘의 물때 카드 (김바로 담당). 홈 오른쪽 칸(폰에서는 배너 바로 아래)에 들어가요.

    from components.tide_card import tide_card
    tide_card()                 # 보통
    tide_card(fail=True)        # 시안 캡처용: 불러오기 실패 상태

지역 기억: st.session_state["tide_region"]
    처음엔 회원의 지역 → 없으면 운영 설정(A-07)의 기본 지역.
    회원은 계정(PUT /me/region → User.region)에, 비회원은 이번 방문 동안만 기억해요.
물때 값은 서버가 Redis에 1시간 캐시해서 줘요 (GET /tide/regions · /tide/<지역>).
"""
from __future__ import annotations

import html

import streamlit as st

from services import aquarium_data as aq
from services import auth, db
from services.api import ApiError

S = st.session_state
DAY_START, DAY_END = 6 * 60, 18 * 60  # 낮 간조로 보는 시간 (06:00 ~ 18:00)


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _hhmm(minutes: int) -> str:
    minutes = max(0, min(minutes, 23 * 60 + 59))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def best_time(t: dict) -> tuple[str, str]:
    """낮 간조로 ‘관찰하기 좋은 시간’ 한 줄 설명을 만들어요. (큰 글, 보조 글)"""
    lows = [x for x in t["low"] if DAY_START <= _minutes(x) <= DAY_END]
    if not lows:
        return ("오늘 낮에는 물이 많이 빠지지 않아요.",
                "물웅덩이 관찰은 다음 간조(물 빠짐) 때 해 보세요.")
    low = lows[0]
    m = _minutes(low)
    tip = f"{_hhmm(m - 60)} ~ {_hhmm(m + 60)}에 관찰하기 좋아요."
    later_high = [h for h in t["high"] if _minutes(h) > m]
    if later_high:
        tip += f" {later_high[0]} 만조 전에는 물 밖으로 나와 주세요."
    return f"오늘 {low} 전후로 물이 가장 많이 빠져요", tip


def _default_region() -> str:
    user = auth.current_user()
    rid = (user or {}).get("region") or db.settings().get("default_region", "jeju")
    return rid if rid in db.regions() else next(iter(db.regions()))


def _pick_region() -> None:
    """지역 바꾸기 선택이 바뀌면 기억해요. 회원은 계정에도 남겨요."""
    rid = S.get("tide_pick")
    if not rid:
        return
    S["tide_region"] = rid
    if auth.current_user():
        try:
            aq.save_region(rid)
        except ApiError as e:  # 계정에 못 남겨도 이번 방문 동안은 기억해요
            st.toast(e.message)


def _row(label: str, value: str) -> None:
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center",
                      gap="small"):
        st.markdown(f'<p class="sia-muted">{html.escape(label)}</p>', unsafe_allow_html=True, width="content")
        st.markdown(f"**{value}**", width="content")


def tide_card(fail: bool = False) -> None:
    regions = db.regions()
    rid = S.setdefault("tide_region", _default_region())
    if rid not in regions:
        rid = S["tide_region"] = _default_region()

    stale = False
    try:
        if fail:
            raise ConnectionError("물때 정보를 받지 못했어요")  # 시안 캡처용
        t = dict(db.tide(rid))
        S["tide_last"] = {**t, "region": rid}
    except Exception:
        stale = True
        last = S.get("tide_last")
        if not last or last.get("region") != rid:
            last = {**regions[rid], "region": rid}  # 마지막으로 받아 둔 값
        t = last

    with st.container(border=True, gap="small"):
        st.markdown('<h2 class="sia-h2">오늘의 물때</h2>', unsafe_allow_html=True)
        with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center",
                          gap="small"):
            st.markdown(f":material/location_on: **{t['name']}**", width="content")
            with st.popover("지역 바꾸기"):
                names = list(regions)
                st.selectbox("지역", names, index=names.index(rid), key="tide_pick",
                             format_func=lambda k: regions[k]["name"], on_change=_pick_region,
                             help="이름을 입력하면 바로 찾아져요.")
                user = auth.current_user()
                st.caption("고른 지역은 내 계정에 저장돼요." if user else "고른 지역은 이번 방문 동안 기억해요.")
                st.button("내 위치로 찾기", icon=":material/my_location:", disabled=True, key="tide_gps",
                          width="stretch", help="다음 단계에 열려요.")
                st.caption("‘내 위치로 찾기’는 준비 중이에요.")

        _row("만조 (물 들어옴)", " · ".join(t["high"]))
        _row("간조 (물 빠짐)", " · ".join(t["low"]))
        _row("파고 (파도 높이)", t["wave"])

        head, tip = best_time(t)
        st.info(f"**{head}**\n\n{tip}", icon=":material/schedule:")
        if stale:
            st.caption(":material/warning: 새 정보를 불러오지 못했어요. 정보가 오래됐을 수 있어요.")
        st.caption(f"기준 {t['updated']} · 출처: {t.get('source') or '예시 데이터'}")
