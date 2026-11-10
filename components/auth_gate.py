"""비회원 · 관리자 막기 (이종민 담당, 시안 뼈대는 편성훈).

    if st.button("공감") and auth_gate.login_required("공감할 수 있어요"):
        ...                      # 회원일 때만 여기로 와요

    auth_gate.admin_only()       # 관리자 화면 맨 위에 한 줄
"""
from __future__ import annotations

import streamlit as st

from components import nav
from services import auth


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
