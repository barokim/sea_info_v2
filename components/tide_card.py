"""C-02 오늘의 물때 카드 (김바로 담당). 홈 오른쪽 칸(폰에서는 배너 바로 아래)에 들어가요.

    from components.tide_card import tide_card
    tide_card()                 # 보통
    tide_card(fail=True)        # 시안 캡처용: 불러오기 실패 상태

지역 기억: st.session_state["tide_region"]
    처음엔 회원의 지역 → 없으면 운영 설정(A-07)의 기본 지역.
    회원은 계정(PUT /me/region → User.region)에, 비회원은 이번 방문 동안만 기억해요.
지역 목록은 자료 조회와 분리하고, 지역별 물때는 서버가 Redis에 1시간 캐시해요.
"""
from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone

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


def _default_region(regions: dict) -> str:
    user = auth.current_user()
    rid = (user or {}).get("region")
    if rid not in regions:
        try:
            rid = db.settings().get("default_region", "jeju")
        except Exception:
            rid = None
    return rid if rid in regions else next(iter(regions))


def _data_notice(t: dict) -> str:
    """자료 시각과 예시 여부를 알린다. 갱신 시각을 예보 대상 날짜로 간주하지 않는다."""
    source = t.get("source") or "출처 미확인"
    if "예시" in source:
        return "예시 데이터예요. 실제 관측·예보나 오늘의 관찰 시간 안내로 사용할 수 없어요."
    # [BARO-SCOPE-EXTENSION] 주요 5개 파일 밖의 승인된 연관 수정.
    # 변경 이유: tide.py의 공식 예보 대상 날짜·지점을 실제 관측과 구분해 표시한다.
    # [BARO-CHANGE-012] 갱신시각 대신 명시적인 예보 대상 날짜로 오늘 자료인지 판단한다.
    if t.get("data_kind") == "forecast" and t.get("target_date"):
        today = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
        if t["target_date"] != today:
            return f"{t['target_date']} 대상 예보예요. 오늘의 물때로 사용할 수 없어요."
        return "오늘의 고·저조 예보예요. 실제 관측값이 아니며 현장 안전이나 관찰 가능 시간을 보장하지 않아요."
    try:
        stamp = datetime.fromisoformat(t.get("updated", ""))
        kst = timezone(timedelta(hours=9))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=kst)
        today = datetime.now(kst).date()
        if stamp.astimezone(kst).date() < today:
            return "이전 날짜의 자료예요. 오늘의 물때로 사용할 수 없어요."
        if stamp.astimezone(kst).date() > today:
            return "자료 시각이 현재 날짜보다 미래예요. 최신 여부를 확인할 수 없어요."
    except (ValueError, TypeError):
        return "자료 날짜를 확인할 수 없어 최신 여부를 알 수 없어요."
    return "자료 시각은 오늘이지만 관측·예보 구분과 대상 날짜가 제공되지 않아 오늘의 물때인지 확인할 수 없어요."


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
    try:
        regions = db.regions()
    except Exception:
        with st.container(border=True):
            st.markdown("**물때 정보**")
            st.warning("지역 목록을 불러오지 못했어요. 잠시 뒤 다시 시도해 주세요.")
        return
    if not regions:
        with st.container(border=True):
            st.markdown("**물때 정보**")
            st.info("선택할 수 있는 물때 지역이 없어요.")
        return
    rid = S.get("tide_region")
    # [BARO-CHANGE-013] 계정이 바뀌면 이전 사용자의 선택·이전 자료를 재사용하지 않는다.
    owner = (auth.current_user() or {}).get("id") or "guest"
    if S.get("tide_owner") != owner:
        for key in ("tide_region", "tide_pick", "tide_last"):
            S.pop(key, None)
        S["tide_owner"] = owner
        rid = None
    if rid not in regions:
        rid = S["tide_region"] = _default_region(regions)

    stale = False
    try:
        if fail:
            raise ConnectionError("물때 정보를 받지 못했어요")  # 시안 캡처용
        t = dict(db.tide(rid))
        S["tide_last"] = {**t, "region": rid}
    except Exception:
        stale = True
        last = S.get("tide_last")
        if not isinstance(last, dict) or last.get("region") != rid:
            # [BARO-CHANGE-014] 자료가 없어도 지역 선택 UI는 남겨 다른 지역을 고를 수 있게 한다.
            t = {**regions[rid], "available": False}
        else:
            t = last

    with st.container(border=True, gap="small"):
        st.markdown('<h2 class="sia-h2">물때 정보</h2>', unsafe_allow_html=True)
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

        if not t.get("available", True):
            st.warning("선택한 지역의 물때를 불러오지 못했어요. 다른 지역을 고르거나 잠시 뒤 다시 시도해 주세요.")
            return
        if t.get("station_name"):
            st.caption(f"예보 지점: {t['station_name']} ({t.get('station_id', '')}) · 대상 날짜: {t.get('target_date', '미확인')}")
            st.caption("선택 지역의 대표 예보지점 자료예요. 해당 해변과 위치가 다를 수 있어요.")
        _row("만조 (물 들어옴)", " · ".join(t["high"]) or "예보 시각 없음")
        _row("간조 (물 빠짐)", " · ".join(t["low"]) or "예보 시각 없음")
        _row("파고 (파도 높이)", t["wave"])

        # [BARO-CHANGE-050] 예보와 별도 블록으로 dtRecent 실측값·관측 지점·자료 시각을 표시한다.
        st.markdown("**현재 관측값**")
        observation_status = t.get("observation_status", "not_configured")
        if observation_status in ("ok", "stale"):
            level = t.get("observation_level_cm")
            temperature = t.get("observation_water_temp_c")
            _row("현재 조위", f"{level:g} cm" if isinstance(level, (int, float)) else "자료 없음")
            _row("현재 수온", f"{temperature:g} °C" if isinstance(temperature, (int, float)) else "자료 없음")
            st.caption(f"관측소: {t.get('observation_station_name') or '미확인'} "
                       f"({t.get('observation_station_id') or '코드 미확인'}) · "
                       f"관측 시각: {t.get('observation_time') or '미확인'} · "
                       f"출처: {t.get('observation_source') or '미확인'}")
            if observation_status == "stale":
                st.warning(t.get("observation_message") or "관측 시각을 확인해 주세요.")
        else:
            st.caption(t.get("observation_message") or "현재 관측 자료를 표시할 수 없어요.")

        st.info(_data_notice(t), icon=":material/info:")
        if stale:
            st.warning("재조회에 실패해 같은 지역에서 마지막으로 받은 자료를 표시해요. 최신 자료가 아니에요.")
        label = "수집 시각" if t.get("data_kind") == "forecast" else "자료 시각"
        st.caption(f"{label} {t.get('updated') or '미확인'} · 출처: {t.get('source') or '미확인'}")
