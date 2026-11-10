"""공통 UI (편성훈 담당). 색 · 글꼴 · 크기는 여기와 config.toml에서만 정해요.

화면 파일에서는 이 함수들만 불러 쓰세요.
    ui.page_header("나의 수족관", "내가 만난 바다 친구들이에요.")
    ui.photo("🦀", tone="sand")
    ui.safety_badge(result["safety"])
    ui.empty_state("🐚", "아직 만난 생물이 없어요.", "생물 알아보기", "identify")
"""
from __future__ import annotations

import html
import os
import pathlib

import streamlit as st

from components import nav

ROOT = pathlib.Path(__file__).resolve().parent.parent
STAGE = os.environ.get("SEA_STAGE", "2")  # "1" 와이어프레임 시안, "2" 디자인 시안

SAFETY = {
    "safe": ("괜찮아요", "green", ":material/check_circle:"),
    "caution": ("조심해요", "orange", ":material/warning:"),
    "danger": ("만지지 마세요", "red", ":material/dangerous:"),
}
CONFIDENCE = {"high": "확신 높음", "medium": "확신 보통", "low": "확신 낮음"}
TONES = ("aqua", "sand", "coral", "violet", "navy")


def load_css() -> None:
    css = (ROOT / "assets" / "style.css").read_text(encoding="utf-8")
    if STAGE == "1":
        css += (ROOT / "assets" / "wire.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def page_header(title: str, desc: str | None = None) -> None:
    body = f'<h1 class="sia-title">{html.escape(title)}</h1>'
    if desc:
        body += f'<p class="sia-desc">{html.escape(desc)}</p>'
    st.markdown(f'<div class="sia-head">{body}</div>', unsafe_allow_html=True)


def section(title: str, more_label: str | None = None, target: str | None = None, **params) -> None:
    """영역 제목 + (선택) 오른쪽 ‘더보기’ 링크."""
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        st.markdown(f'<h2 class="sia-h2">{html.escape(title)}</h2>', unsafe_allow_html=True)
        if more_label and target:
            nav.link(target, more_label, icon=":material/arrow_forward:", **params)


def photo_html(emoji: str, tone: str = "aqua", height: int = 160, label: str | None = None,
               width: int | None = None) -> str:
    tone = tone if tone in TONES else "aqua"
    size = max(24, int(height * 0.38))
    cap = f'<em class="sia-photo-cap">{html.escape(label)}</em>' if label else ""
    w = f"width:{width}px;flex:none;" if width else ""
    return (f'<div class="sia-photo t-{tone}" style="height:{height}px;{w}">'
            f'<span style="font-size:{size}px">{emoji}</span>{cap}</div>')


def photo(emoji: str, tone: str = "aqua", height: int = 160, label: str | None = None,
          width: int | None = None) -> None:
    """사진 자리 (시안 단계에서는 이모지 타일로 대신해요). width를 주면 그 폭으로 고정."""
    st.markdown(photo_html(emoji, tone, height, label, width), unsafe_allow_html=True)


def item_row(emoji: str, title: str, sub: str = "", tone: str = "aqua", size: int = 56) -> None:
    """작은 사진 + 제목 + 보조 글 한 줄 (목록 · 요약 카드용)."""
    sub_html = f'<span class="sia-muted">{html.escape(sub)}</span>' if sub else ""
    st.markdown(f'<div class="sia-item">{photo_html(emoji, tone, size, width=size)}'
                f'<div><b>{html.escape(title)}</b><br>{sub_html}</div></div>', unsafe_allow_html=True)


def chip(text: str, kind: str = "") -> str:
    """작은 꼬리표 HTML (여러 개를 이어 붙여 st.markdown으로 출력)."""
    return f'<span class="sia-chip {kind}">{html.escape(text)}</span>'


def chips(*items: str) -> None:
    st.markdown('<div class="sia-chips">' + "".join(items) + "</div>", unsafe_allow_html=True)


def safety_badge(safety: dict, with_reason: bool = True) -> None:
    label, color, icon = SAFETY[safety["level"]]
    st.badge(f"{label} · {safety['reason']}" if with_reason else label, icon=icon, color=color)


def empty_state(icon: str, text: str, button: str | None = None, target: str | None = None,
                key: str | None = None) -> None:
    with st.container(border=True, horizontal_alignment="center"):
        st.markdown(f'<div class="sia-empty"><div class="ic">{icon}</div><p>{html.escape(text)}</p></div>',
                    unsafe_allow_html=True)
        if button and target and st.button(button, type="primary", key=key or f"empty_{target}"):
            nav.go(target)


def muted(text: str) -> None:
    st.markdown(f'<div class="sia-muted">{html.escape(text)}</div>', unsafe_allow_html=True)


def top_bar(user: dict | None, dev: bool = False) -> None:
    """모든 화면 맨 위: 왼쪽 로고, 오른쪽 로그인 / 내 정보."""
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center",
                      key="sia_topbar"):
        st.page_link(nav.path("home"), label="Sea-Info Agent", icon="🌊")
        with st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center",
                          width="content", gap="small"):
            if dev:
                st.markdown(chip("로컬 실행 중", "demo"), unsafe_allow_html=True)
            if user:
                if st.button(f"{user['character']} {user['nickname']}", key="tb_me", type="tertiary"):
                    nav.go("mypage")
            elif st.button("로그인", key="tb_login", icon=":material/login:"):
                nav.go("login")
