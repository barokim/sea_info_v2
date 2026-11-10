"""A-01 관리자 대시보드 (이종민 담당).

오늘 숫자 5개 · 오늘 할 일(대기 중인 신고 · 문의) · 최근 7일 추이 · 최근 조치 기록.
데이터: GET /admin/dashboard (SQLite 집계 + Redis 오늘 알아보기 횟수)
"""
from datetime import date

import pandas as pd
import streamlit as st

from components import auth_gate, nav, ui
from services import admin_data
from services.api import ApiError

me = auth_gate.admin_only()

try:
    d = admin_data.dashboard()
except ApiError as e:
    ui.page_header("대시보드", "오늘 처리할 일을 한눈에 봐요.")
    st.error(e.message, icon=":material/cloud_off:")
    st.stop()

today = date.fromisoformat(d["date"])
reports = d["reports"]
inquiries = d["inquiries"]


def series(m: dict) -> list[int]:
    return [x["value"] for x in m["trend"]]


ui.page_header("대시보드", "오늘 처리할 일을 한눈에 봐요.")
ui.chips(ui.chip(f"{today:%Y-%m-%d} 기준", ""), ui.chip("실제 데이터", "ok"),
         ui.chip(f"처리할 일 {len(reports) + len(inquiries)}건", "warn" if reports or inquiries else "ok"))
st.space("small")

# ---------- 오늘 숫자 ----------
cols = st.columns(5, gap="small")
for col, (key, label, unit, inverse) in zip(cols, [("signups", "신규 가입", "명", False),
                                                    ("identifies", "알아보기 횟수", "회", False),
                                                    ("new_posts", "새 글", "개", False)]):
    m = d[key]
    with col:
        st.metric(label, f"{m['today']:,}{unit}", delta=m["today"] - m["yesterday"], delta_description="어제보다",
                  border=True, chart_data=series(m))
with cols[3]:
    m = d["pending_reports"]
    new_today = series(m)[-1]
    st.metric("대기 중인 신고", f"{m['today']}건", delta=new_today, delta_description="오늘 들어옴",
              delta_color="inverse", border=True, chart_data=series(m),
              help=f"글마다 묶어서 세요. 같은 글에 신고가 {d['report_hide']}번 쌓이면 자동으로 숨겨져요.")
with cols[4]:
    m = d["pending_inquiries"]
    st.metric("대기 중인 문의", f"{m['today']}건", delta=series(m)[-1], delta_description="오늘 들어옴",
              delta_color="inverse", border=True, chart_data=series(m), help="‘완료’가 아닌 제보·건의예요.")

st.space("small")
left, right = st.columns([3, 2], gap="large")

# ---------- 오늘 할 일 ----------
with left:
    ui.section("오늘 할 일")
    if not reports and not inquiries:
        ui.empty_state("🐚", "오늘 처리할 신고와 문의가 없어요.")
    for r in reports:
        with st.container(border=True):
            ui.chips(ui.chip("신고", "danger"), ui.chip(r.get("reason", "")), ui.chip(f"{r.get('count', 1)}회", "warn"),
                     ui.chip(r.get("date", "")), ui.chip("✕ 숨김", "danger") if r.get("hidden") else "")
            with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
                emoji, tone = admin_data.post_look(r)
                admin_data.item_row(emoji, r["title"], f"{r['board']} · {r['author']}" if not r.get("deleted") else
                                    "이미 지워진 글", tone=tone, size=48)
                nav.link("admin_posts", "신고 처리하기", icon=":material/arrow_forward:", post=r["post"])
    for r in inquiries:
        with st.container(border=True):
            ui.chips(ui.chip("문의", "sea"), ui.chip(r.get("type", "")),
                     ui.chip(r.get("status", ""), "warn" if r.get("status") == "처리 중" else ""), ui.chip(r.get("date", "")))
            with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
                admin_data.text_row(r["title"], f"{r['who']} · {r['id']}")
                nav.link("admin_inquiries", "답변하기", icon=":material/arrow_forward:")

# ---------- 추이 · 바로가기 ----------
with right:
    ui.section("최근 7일 알아보기 횟수")
    ident = d["identifies"]["trend"]
    with st.container(border=True):
        ui.chips(ui.chip("2차 미리보기", "demo"), ui.chip("단위: 회"))
        total = sum(x["value"] for x in ident)
        if total:
            st.line_chart(pd.DataFrame({"날짜": [int(x["date"][-2:]) for x in ident],
                                        "알아보기 횟수": [x["value"] for x in ident]}),
                          x="날짜", y="알아보기 횟수", x_label=f"날짜 ({today.month}월)", y_label="회", height=220)
            admin_data.muted(f"이번 주 합계 {total:,}회 · 하루 평균 {total // 7}회 · 지난 날짜는 대시보드를 연 때까지 센 값이에요")
        else:
            admin_data.muted("최근 7일 동안 센 알아보기 횟수가 아직 없어요. 사진으로 알아보면 여기에 하루씩 쌓여요.")
    st.space("small")
    ui.section("바로가기")
    with st.container(border=True):
        for key in ("admin_posts", "admin_inquiries", "admin_boards", "admin_contents", "admin_settings"):
            nav.link(key, icon=nav.ALL[key][2])

# ---------- 최근 조치 기록 ----------
st.space("small")
ui.section("최근 조치 기록", "전체 보기", "admin_posts")
rows = admin_data.log_rows(rows=d["logs"])
if rows:
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
else:
    admin_data.muted("아직 조치 기록이 없어요.")
