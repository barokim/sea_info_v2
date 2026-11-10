"""U-09 게시글 상세 진입점 (차유진 담당).

사이드 메뉴의 U-08 목록과 경로를 분리하고 기존 커뮤니티 화면 코드를 함께 써요.
"""
from pathlib import Path
from runpy import run_path

run_path(str(Path(__file__).with_name("community.py")), init_globals={"_COMMUNITY_DETAIL": True})
