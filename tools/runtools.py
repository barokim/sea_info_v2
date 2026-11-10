"""실행 스크립트(start/stop/check)가 쓰는 작은 도우미. 직접 실행할 일은 거의 없어요.

    python tools/runtools.py need-install      # 설치가 필요하면 종료 코드 1
    python tools/runtools.py mark-installed
    python tools/runtools.py wait-redis 20     # Redis가 켜질 때까지 최대 20초
    python tools/runtools.py wait-api 40       # API 서버가 켜질 때까지 최대 40초
    python tools/runtools.py redis-ping
"""
import hashlib
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
STAMP = ROOT / ".venv" / ".req_hash"


def _env():
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass


def req_hash() -> str:
    return hashlib.md5((ROOT / "requirements.txt").read_bytes()).hexdigest()


def redis_ok() -> bool:
    _env()
    try:
        import redis
        return bool(redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                                         socket_connect_timeout=1).ping())
    except Exception:
        return False


def api_url() -> str:
    _env()
    port = os.environ.get("API_PORT")
    return f"http://localhost:{port}" if port else os.environ.get("BACKEND_URL", "http://localhost:8000")


def api_health():
    import httpx
    try:
        r = httpx.get(f"{api_url()}/health", timeout=2)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    if cmd == "need-install":
        return 0 if STAMP.exists() and STAMP.read_text().strip() == req_hash() else 1
    if cmd == "mark-installed":
        STAMP.write_text(req_hash())
        return 0
    if cmd == "redis-ping":
        return 0 if redis_ok() else 1
    if cmd == "wait-redis":
        for _ in range(n):
            if redis_ok():
                print("  ✓ Redis 준비 완료")
                return 0
            time.sleep(1)
        print("  ✕ Redis가 켜지지 않았어요. Docker Desktop이 실행 중인지 확인하고 `docker compose logs redis` 를 봐 주세요.")
        return 1
    if cmd == "wait-api":
        for _ in range(n):
            h = api_health()
            if h:
                m = h["modes"]
                print(f"  ✓ API 서버 준비 완료 ({api_url()}/docs)")
                print(f"    로그인: {'Supabase' if m['auth'] == 'supabase' else '로컬 대체 (시험 계정 explorer@example.com / sea12345)'}")
                print(f"    메일: {'Google SMTP' if m['mail'] == 'smtp' else '개발 모드 (인증 링크가 화면과 logs/api.log에 보여요)'}")
                print(f"    AI: {'Gemini' if m['ai'] == 'gemini' else '예시 결과 (.env에 GEMINI_API_KEY를 넣으면 실제 분석)'}")
                print(f"    Jira: {'연결' if m['jira'] == 'on' else '미연결 (제보는 저장돼요)'}")
                if not h.get("redis"):
                    print("    ⚠ API 서버가 Redis에 연결하지 못했어요. REDIS_URL을 확인해 주세요.")
                return 0
            time.sleep(1)
        print("  ✕ API 서버가 켜지지 않았어요. logs/api.log 의 마지막 줄을 확인해 주세요.")
        log = ROOT / "logs" / "api.log"
        if log.exists():
            print("".join(log.read_text(encoding="utf-8", errors="replace").splitlines(True)[-15:]))
        return 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
