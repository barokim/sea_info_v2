"""U-15 바다 소식 (이정민 담당).

매일 한국 시간 오전 6시에 jobs/collect_news.py가 소식을 모으고 AI가 두세 문장으로 요약해 자동 공개해요.
관리자는 A-05 콘텐츠 관리에서 숨기기 · 고치기 · 다시 요약을 해요. 소식은 모두 FastAPI 서버(SQLite)에서 와요.
조회수는 상세를 열 때 서버(Redis)가 세요. 같은 사람의 같은 소식은 24시간에 한 번만 올라가요.

상세 팝업은 주소로도 열려요: news?item=n1 (홈에서 오면 news?n=n1)
시안 캡처용: 주소에 ?shot=detail|empty
"""
import html

import streamlit as st

from components import ui
from services import db, news_data
from services.api import ApiError

S = st.session_state


def _open(nid: str) -> None:
    S["news_open"] = nid
    news_data.count_view(nid)  # 서버가 24시간에 한 번만 세요 (실패해도 상세는 열려요)


def _close() -> None:
    S.pop("news_open", None)
    for k in ("item", "n"):
        if k in st.query_params:
            del st.query_params[k]


def _meta(item: dict) -> str:
    return f"{item['source']} · {news_data.date_label(item['date'])} · 조회 {item['views']:,}"


def _clamp(text: str, lines: int = 2) -> str:
    return (f'<p style="display:-webkit-box;-webkit-line-clamp:{lines};-webkit-box-orient:vertical;'
            f'overflow:hidden;margin:.15rem 0 .35rem;line-height:1.6">{html.escape(text)}</p>')


def _tag(item: dict) -> str:
    return ui.chip("AI 요약", "sea") if item.get("ai") else ui.chip("운영자 등록")


# ---------- 상세 팝업 ----------
@st.dialog("바다 소식", width="medium", on_dismiss=_close)
def detail(nid: str) -> None:
    try:
        item = news_data.get(nid)
    except ApiError as e:
        st.error(e.message, icon=":material/error:")
        return
    if not item or not item["public"]:
        st.warning("지금은 볼 수 없는 소식이에요. 목록에서 다른 소식을 골라 주세요.")
        return
    ui.chips(_tag(item), ui.chip(item["source"]))
    st.markdown(f'<h2 class="sia-h2" style="margin:.6rem 0 .25rem">{html.escape(item["title"])}</h2>',
                unsafe_allow_html=True)
    ui.muted(_meta(item))
    st.space("small")
    st.write(item["summary"])
    if item.get("ai"):
        st.info("AI가 요약한 내용이에요. 정확한 내용은 원문에서 확인해 주세요.", icon=":material/smart_toy:")
    else:
        st.info("운영자가 직접 정리한 소식이에요. 자세한 내용은 원문에서 확인해 주세요.", icon=":material/edit_note:")
    st.markdown(f"**출처** · {item['source']}")
    st.link_button("원문 보기", item["url"], type="primary", width="stretch", icon=":material/open_in_new:")
    st.caption("원문은 새 창에서 열려요.")


# ---------- 주소 · 시안 상태 ----------
shot = st.query_params.get("shot")
if shot and S.get("news_shot") != shot:
    S["news_shot"] = shot
    _close()
    first = db.top_news(1) if shot == "detail" else []
    if first:
        _open(first[0]["id"])

item_q = st.query_params.get("item") or st.query_params.get("n")  # 홈의 [읽기]는 ?n=n1 로 와요
if item_q and S.get("news_item_applied") != item_q:
    S["news_item_applied"] = item_q
    _open(item_q)

# ---------- 화면 ----------
ui.page_header("바다 소식", "믿을 만한 곳의 바다 소식을 AI가 짧게 요약했어요. 원문으로 이어서 읽을 수 있어요.")
try:
    run = news_data.last_run()
except ApiError:
    run = None  # 수집 시각을 못 불러와도 소식 목록은 보여요
if run:
    ui.chips(ui.chip("AI 요약", "sea"), ui.chip(f"{news_data.date_label(run['date'])}에 새로 모았어요"))
st.space("small")

try:
    rows = [] if shot == "empty" else db.news()
    top_rows = db.top_news(5) if rows else []
except ApiError as e:
    st.error(e.message, icon=":material/error:")
    st.stop()
if not rows:
    ui.empty_state("🐚", "아직 모인 소식이 없어요. 내일 오전 6시에 새 소식을 모아 올게요.")
else:
    top_col, new_col = st.columns([2, 3], gap="large")
    with top_col:
        ui.section("많이 읽은 소식")
        ui.muted("최근 30일 조회수 기준이에요.")
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
        ui.section("최신 소식")
        latest = sorted(rows, key=lambda x: x["date"], reverse=True)
        newest = latest[0]["date"]
        for item in latest:
            with st.container(border=True, gap="small"):
                tags = [_tag(item)] + ([ui.chip("새 소식", "coral")] if item["date"] == newest else [])
                ui.chips(*tags)
                st.markdown(f'<h3 class="sia-h2" style="font-size:17px;margin:.2rem 0 0">'
                            f'{html.escape(item["title"])}</h3>', unsafe_allow_html=True)
                st.markdown(_clamp(item["summary"]), unsafe_allow_html=True)
                with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
                    ui.muted(_meta(item))
                    st.button("요약 보기", key=f"news_new_{item['id']}", type="tertiary",
                              icon=":material/chevron_right:", icon_position="right",
                              on_click=_open, args=(item["id"],))

st.space("medium")
st.caption("매일 오전 6시에 모아 AI가 요약해요 · 예시 데이터")

if S.get("news_open"):
    detail(S["news_open"])
