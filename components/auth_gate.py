"""비회원 · 관리자 막기 (이종민 담당, 시안 뼈대는 편성훈).

    if st.button("공감") and auth_gate.login_required("공감할 수 있어요"):
        ...                      # 회원일 때만 여기로 와요

    auth_gate.admin_only()       # 관리자 화면 맨 위에 한 줄
"""
from __future__ import annotations

from urllib.parse import urlparse

import streamlit as st

from components import nav
from services import auth


def _here_now() -> tuple[str, dict] | None:
    """지금 보고 있는 화면의 (key, 주소 뒤 값). 주소를 알 수 없으면 None."""
    try:
        path = urlparse(st.context.url).path.strip("/")
    except Exception:  # noqa: BLE001 - 시험 환경 등에서 주소를 못 읽을 때
        return None
    for key, spec in nav.ALL.items():
        if spec[3] == path:
            return key, {k: v for k, v in st.query_params.items() if k != "as"}
    return None


def login_required(can_do: str, here: str | None = None, **params) -> bool:
    """회원이면 True. 비회원이면 로그인 안내 팝업(C-03)을 띄우고 False.

    can_do: “로그인하면 ○○” 의 ○○ 부분. 예) "이 생물을 수족관에 담을 수 있어요"
    here:   로그인 뒤 돌아올 화면 key (없으면 지금 화면)
    """
    if auth.current_user():
        return True

    @st.dialog("로그인이 필요해요")
    def _dialog():
        st.markdown(f"로그인하면 **{can_do}**")
        st.caption("지금 하던 내용은 그대로 남아요.")
        if st.button("로그인 / 회원가입", type="primary", width="stretch", key="gate_login"):
            if here:
                nav.remember_here(here, **params)
            elif _here_now():  # here를 안 줬으면 지금 화면으로 돌아와요
                key, qp = _here_now()
                nav.remember_here(key, **qp)
            st.session_state["after_login"] = st.session_state.get("back_to")
            nav.go("login")
        if st.button("나중에 할게요", width="stretch", key="gate_later"):
            st.rerun()

    _dialog()
    return False


def admin_only() -> dict:
    """관리자가 아니면 안내하고 화면을 멈춰요. 관리자면 user를 돌려줘요."""
    user = auth.current_user()
    if not user or user.get("role") != "admin":
        st.warning("접근 권한이 없어요. 관리자 계정으로 로그인해 주세요.", icon=":material/lock:")
        if st.button("홈으로", type="primary"):
            nav.go("home")
        st.stop()
    return user
