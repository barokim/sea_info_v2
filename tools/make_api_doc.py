"""docs/API_목록.md 를 서버의 OpenAPI에서 다시 만들어요. (API를 바꾼 뒤 실행)

    python tools/make_api_doc.py      # API 서버가 켜져 있어야 해요
"""
import collections
import os
import pathlib

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = os.environ.get("BACKEND_URL", "http://localhost:8000")
OWNER = {"공통": "편성훈", "생물 알아보기": "편성훈", "로그인": "이종민", "내 정보": "이종민", "관리자 운영": "이종민",
         "나의 수족관": "김바로", "물때": "김바로", "제보·건의": "김바로", "커뮤니티": "차유진", "게시판 관리": "차유진",
         "바다 놀이터": "이정민", "바다 소식": "이정민", "관리자 · 콘텐츠": "이정민"}
ORDER = list(OWNER)



def main() -> None:
    spec = httpx.get(f"{BASE}/openapi.json", timeout=10).json()
    groups = collections.defaultdict(list)
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            tag = (op.get("tags") or ["기타"])[0]
            groups[tag].append((path, method.upper(), op.get("summary", "")))
    lines = ["# Sea-Info Agent API 목록", "",
             f"서버를 켠 뒤 `{BASE}/docs` 에서 각 API를 눌러 직접 시험해 볼 수 있어요. 이 파일은 `python tools/make_api_doc.py`로 다시 만들어요.", "",
             f"전체 {sum(len(v) for v in groups.values())}개 · 로그인이 필요한 API는 `Authorization: Bearer <토큰>` 머리글을 보내요 (화면은 `services/api.py`가 알아서 붙여요).", ""]
    for tag in ORDER + sorted(set(groups) - set(ORDER)):
        if tag not in groups:
            continue
        lines += [f"## {tag} · 담당 {OWNER.get(tag, '-')}", "", "| 방법 | 주소 | 설명 |", "|---|---|---|"]
        for path, method, summary in sorted(groups[tag], key=lambda x: (x[0], x[1])):
            lines.append(f"| `{method}` | `{path}` | {summary} |")
        lines.append("")
    (ROOT / "docs" / "API_목록.md").write_text("\n".join(lines), encoding="utf-8")
    print("docs/API_목록.md 를 만들었어요.")


if __name__ == "__main__":
    main()
