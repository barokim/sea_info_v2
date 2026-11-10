"""Sea-Info Agent 화면 시작 파일 (편성훈 담당). 메뉴만 정의하고 화면은 views/에 있어요.

실행 순서 (자세한 건 docs/설치가이드.md):
  1) Redis 켜기            docker compose up -d
  2) API 서버 켜기          uvicorn backend.main:app --reload --port 8000
  3) 화면 켜기 (이 파일)     streamlit run app.py
시험용: 로컬(APP_ENV=local)에서는 주소 뒤에 ?as=member 또는 ?as=admin 을 붙이면 그 상태로 열려요.
"""
import pathlib

from dotenv import load_dotenv

load_dotenv()  # .env 의 BACKEND_URL 등을 읽어요 (아래 services 를 불러오기 전에)

import streamlit as st  # noqa: E402

from components import nav, ui  # noqa: E402
from services import auth  # noqa: E402
from services.api import ApiError  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent

st.set_page_config(page_title="Sea-Info Agent", page_icon="🌊", layout="wide",
                   initial_sidebar_state="auto")
ui.load_css()

try:
    server = auth.health()
except ApiError as e:
    st.error(e.message, icon=":material/cloud_off:")
    st.info("터미널에서 `uvicorn backend.main:app --reload --port 8000` 으로 API 서버를 먼저 켜 주세요. "
            "Redis도 켜져 있어야 해요 (`docker compose up -d`).")
    st.stop()
if not server.get("redis"):
    st.warning("Redis에 연결하지 못했어요. `docker compose up -d` 로 Redis를 켜 주세요. 일부 기능이 멈춰요.",
               icon=":material/warning:")

auth.restore_from_cookie()  # 새로 고침해도 로그인이 이어지게
dev = server.get("app_env", "local") != "production"
# 시험용: ?as=guest|member|admin (로컬에서만)
if dev and "as" in st.query_params and not st.session_state.get("_as_applied"):
    st.session_state["_as_applied"] = True
    try:
        auth.login_as(st.query_params["as"])
    except ApiError as e:
        st.warning(e.message)

user = auth.current_user()

st.logo(str(ROOT / "assets" / "logo.svg"), icon_image=str(ROOT / "assets" / "logo_icon.svg"), size="large")
page = st.navigation(nav.build(user), expanded=True)  # 메뉴를 접지 않고 모두 보여줘요

with st.sidebar:  # 로그인 상태와 관계없이 메뉴 아래에 로그인 / 로그아웃을 보여줘요
    if user:
        if st.button("로그아웃", key="sb_logout", icon=":material/logout:", width="stretch"):
            auth.logout()
            nav.go("home")
    elif st.button("로그인", key="sb_login", icon=":material/login:", width="stretch"):
        nav.go("login")

if dev:  # 시안 확인용 보기 전환 (배포 환경에서는 보이지 않아요)
    with st.sidebar:
        st.divider()
        st.caption("로컬 확인용 · 배포하면 보이지 않아요")
        labels = {"guest": "비회원", "member": "회원", "admin": "관리자"}
        now = "guest" if not user else ("admin" if user["role"] == "admin" else "member")
        picked = st.segmented_control("보기 모드", list(labels), format_func=labels.get, default=now)
        if picked and picked != now:
            auth.login_as(picked)
            st.rerun()
        m = server.get("modes", {})
        st.caption(f"로그인 {'Supabase' if m.get('auth') == 'supabase' else '로컬'} · "
                   f"메일 {'Gmail' if m.get('mail') == 'smtp' else '개발'} · "
                   f"AI {'Gemini' if m.get('ai') == 'gemini' else '예시'} · "
                   f"Jira {'연결' if m.get('jira') == 'on' else '미연결'}")

ui.top_bar(user, dev=dev)
auth.flush_cookie()
page.run()
auth.flush_cookie()  # 화면에서 로그인 · 로그아웃했다면 여기서 브라우저에 반영
