"""U-15 바다 소식 (이정민 담당).

담당 로컬 미리보기에서는 매일 한국 시간 오전 6시에 허용된 정책브리핑 글을 확인해 원문 일부를 등록해요.
관리자는 A-05 콘텐츠 관리에서 숨기기 · 고치기 · 다시 요약을 해요. 소식은 모두 FastAPI 서버(SQLite)에서 와요.
조회수는 상세를 열 때 서버(Redis)가 세요. 같은 사람의 같은 소식은 24시간에 한 번만 올라가요.

상세 팝업은 주소로도 열려요: news?item=n1 (홈에서 오면 news?n=n1)
전체 뉴스 관리 새 창: news?view=all
시안 캡처용: 주소에 ?shot=detail|empty
"""
import html
import re

import streamlit as st

from components import ui
from services import db, news_data
from services.api import ApiError

S = st.session_state

PAGE_SIZE = 5          # 메인 최신 소식 한 페이지당 기사 수
MAX_PAGES = 5          # 메인 최신 소식 최대 노출 페이지 수 (5개 × 5페이지 = 최대 25개)
ALL_PAGE_SIZE = 10     # 최신뉴스 전체보기 한 페이지당 기사 수 (10개씩 묶음)
TOP_LIMIT = 5          # 많이 읽은 소식 노출 개수

BIO_KEYWORDS = (
    "생물", "고래", "돌고래", "상괭이", "바다거북", "물범", "물개", "어류", "물고기",
    "해파리", "산호", "해조", "미역", "다시마", "잘피", "원생생물", "미생물", "플랑크톤",
    "신종", "미기록종", "멸종위기", "해양보호생물", "생태", "서식", "방류", "구조",
    "국립수산과학원", "국립해양생물자원관", "MABIK", "NIFS",
)


def _date_sort_key(item: dict) -> tuple:
    """발행 날짜(YYYY-MM-DD 또는 YYYY.MM.DD) 내림차순 정렬을 위한 키 생성."""
    raw_date = str(item.get("date", ""))
    nums = re.findall(r"\d+", raw_date)
    d_str = "".join(nums[:3]) if len(nums) >= 3 else "00000000"
    raw_id = str(item.get("id", ""))
    id_num = int(re.sub(r"\D", "", raw_id)) if re.sub(r"\D", "", raw_id) else 0
    return (d_str, id_num)


def _open(nid: str) -> None:
    S["news_open"] = nid
    news_data.count_view(nid)
    db.clear_cache()


def _close() -> None:
    S.pop("news_open", None)
    for k in ("item", "n"):
        if k in st.query_params:
            del st.query_params[k]


def _set_page(p: int) -> None:
    S["news_page"] = p


def _set_all_page(p: int) -> None:
    S["news_all_page"] = p


def _meta(item: dict) -> str:
    return f"{item['source']} · {news_data.date_label(item['date'])} · 조회 {item['views']:,}"


def _clamp(text: str, lines: int = 2) -> str:
    return (f'<p style="display:-webkit-box;-webkit-line-clamp:{lines};-webkit-box-orient:vertical;'
            f'overflow:hidden;margin:.15rem 0 .35rem;line-height:1.6">{html.escape(text)}</p>')


def _category(item: dict) -> str:
    """기사의 제목·요약·출처를 바탕으로 '해양생물' 또는 '해양환경' 분야를 판별한다."""
    text = f"{item.get('title', '')} {item.get('summary', '')} {item.get('source', '')}"
    if any(k in text for k in BIO_KEYWORDS):
        return "해양생물"
    return "해양환경"


def _tag(item: dict) -> str:
    # 1. AI 요약된 글이면 무조건 파란색 [AI 요약] 칩 노출!
    if item.get("ai"):
        return ui.chip("AI 요약", "sea")
    # 2. 수동 등록/요약 글
    if item.get("id", "").startswith("n_ko_") or "수동" in item.get("source", ""):
        return ui.chip("수동 요약")
    # 3. 저작권 보호를 위한 원문 발췌 글
    return ui.chip("원문 발췌")


def _cat_chip(item: dict) -> str:
    cat = _category(item)
    return ui.chip(cat, "sea" if cat == "해양생물" else "sand")


def _is_example(item: dict) -> bool:
    """초기 시연용 기사를 실제로 수집한 소식과 구분한다."""
    return item.get("url", "").startswith(("https://example.com/", "http://example.com/")) or item.get("source", "").startswith("예시 ")


def _build_top_rows(rows: list[dict], api_top: list[dict], limit: int = TOP_LIMIT) -> list[dict]:
    """많이 읽은 소식 목록을 구성한다."""
    valid_top = [item for item in api_top if not _is_example(item)]
    seen_ids = {item["id"] for item in valid_top}
    if len(valid_top) < limit:
        fallback = sorted(
            (r for r in rows if r["id"] not in seen_ids),
            key=lambda x: (x.get("views", 0), _date_sort_key(x)),
            reverse=True,
        )
        valid_top.extend(fallback[: limit - len(valid_top)])
    return valid_top[:limit]


# ---------- 상세 팝업 ----------
@st.dialog("바다 소식", width="medium", on_dismiss=_close)
def detail(nid: str) -> None:
    try:
        item = news_data.get(nid)
    except ApiError as e:
        st.error(e.message, icon=":material/error:")
        return
    if not item or not item["public"] or _is_example(item):
        st.warning("지금은 볼 수 없는 소식이에요. 목록에서 다른 소식을 골라 주세요.")
        return

    ui.chips(_tag(item), _cat_chip(item), ui.chip(item["source"]))
    st.markdown(f'<h2 class="sia-h2" style="margin:.6rem 0 .25rem">{html.escape(item["title"])}</h2>',
                unsafe_allow_html=True)
    ui.muted(_meta(item))
    st.space("small")

    # 요약 본문 표시
    st.write(item["summary"])
    st.space("small")

    # 저작권 및 출처 형태에 맞춘 깔끔한 안내
    is_public_agency = any(k in item.get("source", "") for k in ("정책브리핑", "국립수산과학원", "국립해양생물자원관", "해양수산부"))

    if item.get("ai"):
        st.info("AI가 작성한 핵심 요약본이에요. 상세한 내용은 아래 원문에서 확인해 주세요.", icon=":material/smart_toy:")
    elif is_public_agency:
        st.info("공공기관의 공공누리 제1유형 출처 표시 기준에 따라 핵심 내용을 발췌하여 제공합니다.", icon=":material/verified:")
    else:
        st.info("본 소식은 저작권 보호를 위해 원문 일부를 발췌하여 제공합니다. 기사 전문은 아래 [원문 보기]를 통해 원본 사이트에서 확인해 주세요.",
                icon=":material/copyright:")

    st.markdown(f"**출처** · {item['source']}")
    st.link_button("원문 보기", item["url"], type="primary", width="stretch", icon=":material/open_in_new:")
    st.caption("원문은 해당 매체 공식 사이트의 새 창에서 열려요.")


# ---------- 전체 뉴스 보기 화면 (새 창 ?view=all) ----------
def _render_all_news_view(rows: list[dict]) -> None:
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        ui.page_header("최신뉴스 전체보기", "수집된 모든 해양환경 · 해양생물 소식을 검색하고 한눈에 살펴봐요.")
        if st.button("기본 화면으로", type="secondary", icon=":material/arrow_back:"):
            if "view" in st.query_params:
                del st.query_params["view"]
            st.rerun()

    # 상단 검색바 + 카테고리 필터 탭
    search_col, filter_col = st.columns([3, 2], gap="medium", vertical_alignment="bottom")
    with search_col:
        keyword = st.text_input(
            "키워드 검색",
            value=S.get("news_all_q", ""),
            placeholder="검색어를 입력해 주세요 (제목, 요약, 출처)",
            icon=":material/search:",
            label_visibility="collapsed",
            key="news_all_search_input",
        )
        if keyword != S.get("news_all_q", ""):
            S["news_all_q"] = keyword
            S["news_all_page"] = 1

    with filter_col:
        selected_cat = st.segmented_control(
            "분야 필터",
            options=["전체", "해양환경", "해양생물"],
            default=S.get("news_all_cat", "전체"),
            label_visibility="collapsed",
            key="news_all_cat_control",
        )
        if not selected_cat:
            selected_cat = "전체"
        if selected_cat != S.get("news_all_cat", "전체"):
            S["news_all_cat"] = selected_cat
            S["news_all_page"] = 1

    st.space("small")

    # 발행 날짜 내림차순(최신순) 정렬
    all_latest = sorted(rows, key=_date_sort_key, reverse=True)
    newest_date = all_latest[0]["date"] if all_latest else ""

    q_lower = (keyword or "").strip().lower()
    filtered = []
    for item in all_latest:
        cat = _category(item)
        if selected_cat != "전체" and cat != selected_cat:
            continue
        if q_lower:
            searchable = f"{item.get('title', '')} {item.get('summary', '')} {item.get('source', '')} {cat}".lower()
            if q_lower not in searchable:
                continue
        filtered.append(item)

    # 10개씩 묶어서 페이지네이션
    total_items = len(filtered)
    total_pages = max(1, (total_items + ALL_PAGE_SIZE - 1) // ALL_PAGE_SIZE)
    current_page = min(max(1, S.get("news_all_page", 1)), total_pages)
    S["news_all_page"] = current_page

    ui.muted(f"총 {total_items:,}건의 소식이 있어요. (페이지 {current_page} / {total_pages})")
    st.space("small")

    if not filtered:
        ui.empty_state("🔍", "검색 조건에 맞는 소식이 없어요. 다른 키워드나 카테고리를 선택해 보세요.")
        return

    start_idx = (current_page - 1) * ALL_PAGE_SIZE
    page_items = filtered[start_idx : start_idx + ALL_PAGE_SIZE]

    for item in page_items:
        with st.container(border=True, gap="small"):
            tags = [_tag(item), _cat_chip(item)] + ([ui.chip("새 소식", "coral")] if item["date"] == newest_date else [])
            ui.chips(*tags)
            st.markdown(f'<h3 class="sia-h2" style="font-size:17px;margin:.2rem 0 0">'
                        f'{html.escape(item["title"])}</h3>', unsafe_allow_html=True)
            st.markdown(_clamp(item["summary"]), unsafe_allow_html=True)
            with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
                ui.muted(_meta(item))
                st.button("요약 보기", key=f"news_all_item_{item['id']}", type="tertiary",
                          icon=":material/chevron_right:", icon_position="right",
                          on_click=_open, args=(item["id"],))

    if total_pages > 1:
        st.space("small")
        with st.container(horizontal=True, horizontal_alignment="center", vertical_alignment="center", gap="small"):
            st.button(
                "이전",
                key="news_all_prev",
                type="tertiary",
                icon=":material/chevron_left:",
                disabled=(current_page <= 1),
                on_click=_set_all_page,
                args=(current_page - 1,),
            )
            p_start = max(1, current_page - 3)
            p_end = min(total_pages, p_start + 6)
            p_start = max(1, p_end - 6)
            for p in range(p_start, p_end + 1):
                st.button(
                    str(p),
                    key=f"news_all_p_{p}",
                    type="primary" if p == current_page else "secondary",
                    on_click=_set_all_page,
                    args=(p,),
                )
            st.button(
                "다음",
                key="news_all_next",
                type="tertiary",
                icon=":material/chevron_right:",
                icon_position="right",
                disabled=(current_page >= total_pages),
                on_click=_set_all_page,
                args=(current_page + 1,),
            )


# ---------- 주소 · 시안 상태 ----------
shot = st.query_params.get("shot")
if shot and S.get("news_shot") != shot:
    S["news_shot"] = shot
    _close()
    first = db.top_news(1) if shot == "detail" else []
    if first:
        _open(first[0]["id"])

item_q = st.query_params.get("item") or st.query_params.get("n")
if item_q and S.get("news_item_applied") != item_q:
    S["news_item_applied"] = item_q
    _open(item_q)

try:
    rows = [] if shot == "empty" else [item for item in db.news() if not _is_example(item)]
    raw_top = db.top_news(TOP_LIMIT) if rows else []
    top_rows = _build_top_rows(rows, raw_top, TOP_LIMIT) if rows else []
except ApiError as e:
    st.error(e.message, icon=":material/error:")
    st.stop()

# ---------- 새 창 전체보기 모드 (?view=all) ----------
if st.query_params.get("view") == "all" and shot != "empty":
    if not rows:
        ui.page_header("최신뉴스 전체보기", "수집된 모든 해양환경 · 해양생물 소식을 검색하고 한눈에 살펴봐요.")
        ui.empty_state("🐚", "공개할 수 있는 실제 소식이 아직 없어요.")
    else:
        _render_all_news_view(rows)
    if S.get("news_open"):
        detail(S["news_open"])
    st.stop()

# ---------- 기본 화면 ----------
with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
    ui.page_header("바다 소식", "이용 조건이 확인된 바다 소식을 모아 원문으로 연결해요.")
    st.link_button("소식 검색", "?view=all", type="secondary", icon=":material/search:")

st.info("정책브리핑 해양수산부 보도자료와 국립수산과학원 해양생물 글은 게시물별 공공누리 제1유형을 확인한 뒤 등록합니다. 다른 유형·미표시 글과 예시 기사는 제외합니다.")
st.space("small")

if not rows:
    ui.empty_state("🐚", "공개할 수 있는 실제 소식이 아직 없어요. 출처별 이용 조건을 확인하고 있습니다.")
else:
    top_col, new_col = st.columns([2, 3], gap="large")
    with top_col:
        ui.section("많이 읽은 소식")
        ui.muted("최근 30일 조회수 기준이에요. (조회수가 부족하면 임의의 소식을 보여줘요)")
        with st.container(border=True, gap="small"):
            for rank, item in enumerate(top_rows, 1):
                with st.container(horizontal=True, vertical_alignment="top", gap="small", wrap=False):
                    st.markdown(f'<h3 class="sia-h2" style="width:1.4rem;padding-top:.55rem">{rank}</h3>',
                                unsafe_allow_html=True, width="content")
                    with st.container(gap=None):
                        st.button(item["title"], key=f"news_top_{item['id']}", type="tertiary", wrap=True,
                                  on_click=_open, args=(item["id"],))
                        ui.muted(f"{item['source']} · 조회 {item['views']:,}")

    with new_col:
        with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
            ui.section("최신 소식")
            st.link_button(
                "최신뉴스 전체보기",
                "?view=all",
                type="secondary",
                icon=":material/open_in_new:",
            )

        latest = sorted(rows, key=_date_sort_key, reverse=True)
        newest = latest[0]["date"] if latest else ""

        capped_latest = latest[: PAGE_SIZE * MAX_PAGES]
        total_pages = max(1, min(MAX_PAGES, (len(capped_latest) + PAGE_SIZE - 1) // PAGE_SIZE))
        current_page = min(max(1, S.get("news_page", 1)), total_pages)
        S["news_page"] = current_page

        start_idx = (current_page - 1) * PAGE_SIZE
        page_items = capped_latest[start_idx : start_idx + PAGE_SIZE]

        for item in page_items:
            with st.container(border=True, gap="small"):
                tags = [_tag(item), _cat_chip(item)] + ([ui.chip("새 소식", "coral")] if item["date"] == newest else [])
                ui.chips(*tags)
                st.markdown(f'<h3 class="sia-h2" style="font-size:17px;margin:.2rem 0 0">'
                            f'{html.escape(item["title"])}</h3>', unsafe_allow_html=True)
                st.markdown(_clamp(item["summary"]), unsafe_allow_html=True)
                with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
                    ui.muted(_meta(item))
                    st.button("요약 보기", key=f"news_new_{item['id']}", type="tertiary",
                              icon=":material/chevron_right:", icon_position="right",
                              on_click=_open, args=(item["id"],))

        with st.container(horizontal=True, horizontal_alignment="center", vertical_alignment="center", gap="small"):
            st.button(
                "이전",
                key="news_page_prev",
                type="tertiary",
                icon=":material/chevron_left:",
                disabled=(current_page <= 1),
                on_click=_set_page,
                args=(current_page - 1,),
            )
            for p in range(1, total_pages + 1):
                st.button(
                    str(p),
                    key=f"news_page_btn_{p}",
                    type="primary" if p == current_page else "secondary",
                    on_click=_set_page,
                    args=(p,),
                )
            st.button(
                "다음",
                key="news_page_next",
                type="tertiary",
                icon=":material/chevron_right:",
                icon_position="right",
                disabled=(current_page >= total_pages),
                on_click=_set_page,
                args=(current_page + 1,),
            )

st.space("medium")
st.caption("담당 PC의 로컬 미리보기는 매일 오전 6시에 예약 수집합니다. 배포 서버의 예약 작업은 별도 등록이 필요합니다.")

if S.get("news_open"):
    detail(S["news_open"])