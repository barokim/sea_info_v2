"""앱과 같은 DATABASE_URL로 국내 바다 소식을 수집하는 팀 전달용 진입점.

실행: python jobs/collect_korea.py
시험: python jobs/collect_korea.py --dry-run --max-items 2
매일 06:00 예약 명령도 이 파일을 실행한다.
"""
from __future__ import annotations

from collect_korea_preview import main


if __name__ == "__main__":
    raise SystemExit(main())
