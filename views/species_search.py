"""홈의 작은 검색창에서 진입하는 생물 이름 검색 결과·상세 화면."""
import streamlit as st

from components import nav, ui
from services import species_search_data as species
from services.api import ApiError

# [BARO-SCOPE-EXTENSION] 사용자가 별도 결과 화면 생성을 추가 승인했다.
# [BARO-CHANGE-041] 결과와 상세는 이 화면에서만 조회하며 홈에는 검색 결과를 쌓지 않는다.
SOURCES = species.SOURCES
query = " ".join(st.query_params.get("q", "").split())
provider = st.query_params.get("source", "")
record_id = st.query_params.get("record", "")
try:
    page = int(st.query_params.get("page", "1"))
except (TypeError, ValueError):
    page = 1
page = max(1, min(page, 100))


def search_box() -> None:
    with st.form("species_search_form", border=False):
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            term = st.text_input("생물 이름", value=query[:100], max_chars=100,
                                 placeholder="국명 또는 학명으로 검색", label_visibility="collapsed",
                                 key=f"species_search_query_{query[:100]}")
            submitted = st.form_submit_button("검색", icon=":material/search:", type="primary")
        if submitted:
            name = " ".join((term or "").split())
            if name:
                nav.go("species_search", q=name)
            else:
                st.warning("검색할 생물 이름을 적어 주세요.")


def record_box(item: dict, linked: bool = False) -> None:
    # [BARO-CHANGE-042] 출처·종 식별자·동의어 정보를 구별하고 외부 본문은 HTML 없이 일반 텍스트로 표시한다.
    with st.container(border=True, gap="small"):
        st.subheader(item.get("name") or item["scientific_name"])
        st.text(item["scientific_name"])
        st.caption(f"{SOURCES[item['provider']]} · 종 식별자 {item['id']}")
        if item.get("taxon_status"):
            st.text(f"이름 상태: {item['taxon_status']}")
        if item.get("accepted_name"):
            st.text(f"현재 정명: {item['accepted_name']}")
        if item.get("accepted_id"):
            st.caption(f"현재 정명의 WoRMS AphiaID: {item['accepted_id']}")
        if item.get("rank"):
            st.text(f"분류 단계: {item['rank']}")
        if item.get("marine") is not None:
            st.text("해양 서식 기록: 있음" if item["marine"] else "해양 서식 기록: 없음")
        if item.get("classification"):
            st.markdown("**분류 정보**")
            st.text(" → ".join(f"{rank}: {name}" for rank, name in item["classification"].items()))
        for title, body in item.get("sections", {}).items():
            st.markdown(f"**{title}**")
            st.text(body)
        if item["provider"] == "mbris" and not item.get("sections"):
            st.caption("이 종의 개요·생태·분포 설명은 제공되지 않았어요.")
        st.link_button(f"{SOURCES[item['provider']]} 출처 보기", item["source_url"], icon=":material/open_in_new:")
        if item.get("citation"):
            st.caption(item["citation"])


def show_detail() -> None:
    if provider not in SOURCES or not record_id.isascii() or not record_id.isdigit() or len(record_id) > 20:
        st.warning("검색 결과에서 생물을 다시 선택해 주세요.")
        return
    try:
        with st.spinner("두 출처의 종 정보를 확인하고 있어요…"):
            result = species.detail(provider, record_id)
    except ApiError as exc:
        st.error(exc.message)
        if st.button("상세 다시 불러오기", icon=":material/refresh:"):
            st.rerun()
        return
    st.caption(f"조회 시각 {result['fetched_at']}")
    if result["link_status"] == "matched":
        st.success(result["link_message"])
    elif result["link_status"] in ("unavailable", "not_configured"):
        st.warning(result["link_message"])
    else:
        st.info(result["link_message"])
    record_box(result["record"])
    if result.get("linked_records"):
        st.subheader("연결된 출처 정보" if result["link_status"] == "matched" else "동일 종 여부를 확인할 후보")
        for item in result["linked_records"]:
            record_box(item, linked=True)
    if result["link_status"] in ("unavailable", "not_configured"):
        if st.button("다른 출처 연결 다시 확인", icon=":material/refresh:"):
            st.rerun()


def show_results() -> None:
    if not query:
        st.info("찾고 싶은 생물의 국명이나 학명을 입력해 주세요.")
        return
    if len(query) > 100:
        st.warning("생물 이름은 100자 안으로 입력해 주세요.")
        return
    try:
        with st.spinner("공식 생물 정보를 검색하고 있어요…"):
            result = species.search(query, page)
    except ApiError as exc:
        st.error(exc.message)
        if st.button("검색 다시 시도", icon=":material/refresh:"):
            st.rerun()
        return
    st.caption(f"조회 시각 {result['fetched_at']} · {page}페이지")
    st.caption("국명 검색은 국립해양생물자원관을 먼저 확인해 보세요. WoRMS의 국명 수록 범위는 다를 수 있어요.")
    for tab, source in zip(st.tabs([SOURCES[s["provider"]] for s in result["sources"]]), result["sources"]):
        with tab:
            if source["status"] in ("error", "not_configured"):
                st.warning(source["message"])
                if st.button("이 출처 다시 조회", key=f"species_retry_{source['provider']}", icon=":material/refresh:"):
                    st.rerun()
                continue
            if source["status"] == "empty":
                st.info("이 페이지에 검색된 생물이 없어요. 이름을 바꾸거나 이전 페이지를 확인해 주세요.")
                continue
            if source.get("total") is not None:
                st.caption(f"검색 결과 {source['total']:,}건")
            for item in source["items"]:
                with st.container(border=True, gap="small"):
                    st.markdown(f"**{item.get('name') or item['scientific_name']}**")
                    st.text(item["scientific_name"])
                    st.caption(f"{SOURCES[item['provider']]} · {item.get('taxon_status') or '이름 상태 미제공'}")
                    if st.button("정보 보기", key=f"species_open_{item['provider']}_{item['id']}", icon=":material/arrow_forward:"):
                        nav.go("species_search", q=query, page=page, source=item["provider"], record=item["id"])
    with st.container(horizontal=True, gap="small"):
        if page > 1 and st.button("이전", icon=":material/chevron_left:"):
            nav.go("species_search", q=query, page=page - 1)
        if page < 100 and any(s["has_more"] for s in result["sources"]) and st.button("다음", icon=":material/chevron_right:"):
            nav.go("species_search", q=query, page=page + 1)


ui.page_header("생물 이름 검색", "이름으로 찾고, 국립해양생물자원관과 WoRMS의 정보를 함께 확인해요.")
nav.link("home", "홈으로", icon=":material/home:")
search_box()
if provider or record_id:
    nav.link("species_search", "검색 결과로", q=query, page=page, icon=":material/arrow_back:")
    show_detail()
else:
    show_results()
