"""화면 주소록. 화면 이동은 여기 이름(key)으로만 해요.

    nav.go("aquarium")                      # 화면 이동
    nav.go("community", post="p1")          # 상세 화면 (주소에 ?post=p1)
    nav.link("news", "바다 소식 더보기")      # 링크 모양
"""
from __future__ import annotations

import streamlit as st

# key: (파일, 메뉴 이름, 아이콘, 주소, 메뉴에 보임?)
CUSTOMER = {
    "home": ("views/home.py", "홈", ":material/home:", "home", True),
    # [BARO-SCOPE-EXTENSION] 사용자가 별도 검색 결과 화면 등록을 추가 승인했다.
    # [BARO-CHANGE-033] 홈 검색 제출로 진입하며 사이드바에는 새 메뉴를 늘리지 않는다.
    "species_search": ("views/species_search.py", "생물 이름 검색", ":material/search:", "species-search", False),
    "identify": ("views/identify.py", "생물 알아보기", ":material/photo_camera:", "identify", True),
    "aquarium": ("views/aquarium.py", "나의 수족관", ":material/water:", "aquarium", True),
    "community": ("views/community.py", "커뮤니티", ":material/forum:", "community", True),
    "playground": ("views/playground.py", "바다 놀이터", ":material/sports_esports:", "playground", True),
    "news": ("views/news.py", "바다 소식", ":material/newspaper:", "news", True),
    "write": ("views/write.py", "글쓰기", ":material/edit:", "write", False),
    "user_aquarium": ("views/user_aquarium.py", "다른 사람 수족관", ":material/water:", "user", False),
    "login": ("views/login.py", "로그인", ":material/login:", "login", False),
    "verify": ("views/verify.py", "메일 인증", ":material/mark_email_read:", "verify", False),
    "mypage": ("views/mypage.py", "내 정보", ":material/person:", "mypage", False),
}
HELP = {
    "report": ("views/report.py", "제보·건의", ":material/campaign:", "report", True),
}
ADMIN = {
    "admin_dashboard": ("views/admin/dashboard.py", "대시보드", ":material/dashboard:", "admin", True),
    "admin_boards": ("views/admin/boards.py", "게시판 관리", ":material/view_list:", "admin-boards", True),
    "admin_posts": ("views/admin/posts.py", "게시물·신고", ":material/flag:", "admin-posts", True),
    "admin_members": ("views/admin/members.py", "회원", ":material/group:", "admin-members", True),
    "admin_contents": ("views/admin/contents.py", "콘텐츠", ":material/library_books:", "admin-contents", True),
    "admin_inquiries": ("views/admin/inquiries.py", "문의", ":material/support_agent:", "admin-inquiries", True),
    "admin_settings": ("views/admin/settings.py", "운영 설정", ":material/settings:", "admin-settings", True),
}
ALL = {**CUSTOMER, **HELP, **ADMIN}


def _page(key: str, spec: tuple) -> st.Page:
    path, title, icon, url, visible = spec
    return st.Page(path, title=title, icon=icon, url_path=url, default=(key == "home"),
                   visibility="visible" if visible else "hidden")


def build(user: dict | None) -> dict:
    """st.navigation에 넣을 메뉴 묶음. 관리자 묶음은 관리자에게만 보여요."""
    pages = {
        "바다 탐험": [_page(k, v) for k, v in CUSTOMER.items()],
        "도움": [_page(k, v) for k, v in HELP.items()],
    }
    if user and user.get("role") == "admin":
        pages["관리자"] = [_page(k, v) for k, v in ADMIN.items()]
    else:
        # 관리자 화면 주소로 직접 와도 '권한 없음'을 보여줄 수 있게 숨겨서 등록
        pages["관리자"] = [st.Page(v[0], title=v[1], url_path=v[3], visibility="hidden") for v in ADMIN.values()]
    return pages


def path(key: str) -> str:
    return ALL[key][0]


def go(key: str, **params) -> None:
    """다른 화면으로 이동. params는 주소 뒤 ?key=value 로 붙어요."""
    st.switch_page(path(key), query_params=params or None)


def link(key: str, label: str | None = None, icon: str | None = None, **params) -> None:
    st.page_link(path(key), label=label or ALL[key][1], icon=icon, query_params=params or None)


def remember_here(key: str, **params) -> None:
    """로그인 뒤 돌아올 곳, 상세에서 ‘목록으로’ 돌아갈 곳을 기억해요."""
    st.session_state["back_to"] = (key, params)


def back(default: str = "home") -> None:
    key, params = st.session_state.get("back_to", (default, {}))
    go(key, **params)
