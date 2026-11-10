"""환경변수 설정 (강사님 기준: 키와 주소는 모두 환경변수로, 배포 사이트에서 직접 관리).

로컬에서는 프로젝트 맨 위의 .env 파일을 읽어요 (.env.example을 복사해서 만들어요).
배포할 때는 배포 사이트의 환경변수 화면에 같은 이름으로 넣어요. .env 파일은 깃에 올리지 않아요.

키가 비어 있으면 그 기능은 '로컬 대체 모드'로 돌아가요.
  - SUPABASE_* 없음  → 로그인·가입을 SQLite로 대신 (시험용 계정 제공)
  - SMTP_* 없음      → 메일을 보내지 않고 서버 로그에 코드를 찍어요
  - GEMINI_API_KEY 없음 → 예시 분석 결과
  - JIRA_* 없음      → 제보는 저장되고 Jira 단계만 '미연결'로 표시
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"  # local | production (production이면 시험용 로그인 · 개발 코드 표시를 막아요)
    database_url: str = "sqlite:///./data/sea_info.db"
    redis_url: str = "redis://localhost:6379/0"
    upload_dir: str = "./data/uploads"
    max_upload_mb: int = 10
    session_days: int = 7
    admin_emails: str = "admin@example.com"  # 쉼표로 여러 명. Supabase app_metadata.role=admin 도 관리자로 봐요
    public_site_url: str = "http://localhost:8501"

    # Gemini (생물 분석 · 뉴스 요약)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout_ms: int = 30000

    # Supabase (가입 · 로그인 · 메일 인증 · 권한만)
    supabase_url: str = ""
    supabase_anon_key: str = ""

    # Google SMTP (로컬 모드 인증 링크 · 제보 알림 메일). Supabase 모드의 인증 메일은 Supabase에 같은 Gmail을 연결해요
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""  # Gmail '앱 비밀번호' (계정 비밀번호 아님)
    mail_from: str = ""
    ops_email: str = ""  # 새 제보가 오면 알림을 받을 담당 그룹 메일

    # 물때 공공 API (선택, 김바로 routers/tide.py 의 _fetch 에서 사용)
    tide_api_key: str = ""

    # Jira (제보 → 이슈)
    jira_base_url: str = ""  # 예: https://your-team.atlassian.net
    jira_email: str = ""
    jira_api_token: str = ""
    jira_project_key: str = ""
    jira_issue_type_bug: str = "Bug"
    jira_issue_type_default: str = "Task"
    jira_webhook_secret: str = ""

    @property
    def is_local(self) -> bool:
        return self.app_env.lower() != "production"

    @property
    def supabase_on(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key)

    @property
    def smtp_on(self) -> bool:
        return bool(self.smtp_user and self.smtp_password)

    @property
    def gemini_on(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def jira_on(self) -> bool:
        return bool(self.jira_base_url and self.jira_email and self.jira_api_token and self.jira_project_key)

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
