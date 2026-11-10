"""모든 화면을 비회원 · 회원 · 관리자로 한 번씩 열어 보고 오류가 있는지 알려줘요.

    python tools/smoke_test.py              # 전체 화면
    python tools/smoke_test.py home aquarium # 고른 화면만 (키 이름은 components/nav.py)

마지막 줄이 `문제 0건` 이면 통과예요. 깃에 올리기 전에 한 번씩 돌려 주세요.
"""
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
import httpx  # noqa: E402

from components import nav  # noqa: E402

_base = os.environ.get("BACKEND_URL", "http://localhost:8000")
try:
    h = httpx.get(f"{_base}/health", timeout=5).json()
    print(f"API 서버 {_base} · Redis {'켜짐' if h.get('redis') else '꺼짐'} · 모드 {h.get('modes')}")
except Exception:
    print(f"✕ API 서버({_base})에 연결하지 못했어요. 먼저 `uvicorn backend.main:app --port 8000` 으로 켜 주세요.")
    sys.exit(2)

targets = sys.argv[1:] or list(nav.ALL)
problems = 0
for key in targets:
    for who in ("guest", "member", "admin"):
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
        at.query_params["as"] = who
        try:
            at.run()                       # 첫 실행으로 로그인 상태를 만들고
            at.switch_page(nav.path(key))   # 대상 화면으로 옮겨서
            at.run()                       # 다시 실행
        except Exception as e:  # 시간 초과 등
            problems += 1
            print(f"✕ {key} ({who}) 실행 실패: {e}")
            continue
        if at.exception:
            problems += 1
            for x in at.exception:
                print(f"✕ {key} ({who}) 오류: {str(x.value)[:300]}")
        else:
            print(f"✓ {key} ({who})")
print(f"\n문제 {problems}건")
sys.exit(1 if problems else 0)
