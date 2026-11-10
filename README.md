# Sea-Info Agent

사진 한 장으로 바다 생물을 알아보고(생물 알아보기), 모으고(나의 수족관), 나누는(커뮤니티) 반응형 웹이에요.
화면은 Streamlit, 데이터는 FastAPI 서버(SQLite + Redis)를 거쳐요. 키를 넣지 않아도 **로컬 대체 모드**로 모든 화면이 돌아가고,
`.env`에 Supabase · Gmail · Gemini · Jira 키를 넣으면 그 기능이 실제 서비스로 바뀌어요. 처음 켤 때 `mock/`의 예시 데이터가 들어가요.

## 실행

**가장 빠른 방법:** Windows는 `start.bat` 더블클릭, Mac · Linux는 `./start.sh`.
설치 → Redis(Docker) → API 서버 → 화면까지 한 번에 켜고 브라우저가 열려요. 끄기는 `stop`, 오류 검사는 `check`.

- 준비물: Python 3.10 이상, Docker Desktop
- 키는 `.env`에 넣어요 (`.env.example`을 복사). 비워 두면 로컬 대체 모드로 돌아가요.
- 로컬 시험 계정: `explorer@example.com` / `sea12345` (회원), `admin@example.com` / `admin12345` (관리자)
- 자세한 설치 · 키 발급 · 배포 · 문제 해결: **[docs/설치가이드.md](docs/설치가이드.md)**
- API 문서: 서버를 켠 뒤 `http://localhost:8000/docs`

## 기술 구성 (강사님 기준)

| 항목 | 쓰는 것 |
|---|---|
| 화면 | Streamlit |
| API 서버 | FastAPI + pydantic 타입 검사 |
| 앱 데이터 | SQLite 파일 (`data/sea_info.db`) |
| 빠른 값 | Redis (Docker): 세션 · 1회용 인증 링크 값 · 하루 분석 횟수 · 랭킹 · 조회수 |
| 가입 · 로그인 · 메일 인증(링크) · 권한 | Supabase (키가 없으면 SQLite로 대체) |
| 인증 메일 · 알림 메일 | Google SMTP (Supabase SMTP 설정에도 같은 Gmail 연결) |
| 제보 연동 | Jira |
| 생물 분석 | Gemini |
| 키 관리 | 환경변수 (`.env` / 배포 사이트 설정) |

## 폴더와 담당

화면을 만든 사람이 그 화면의 API(FastAPI 라우터)도 맡아요.

| 담당 | 백엔드 (`backend/`) | 화면 (Streamlit) |
|---|---|---|
| 편성훈 (리드 · 전체 흐름) | `main.py · config.py · db.py · models.py · core/` · `routers/core.py · identify.py` | `app.py` · `components/ui.py · nav.py` · `services/api.py · db.py · ai.py` · `views/identify.py` · 실행 스크립트 |
| 이종민 | `routers/auth.py · admin.py` · `auth_provider.py` | `views/login.py · mypage.py · admin/dashboard.py · posts.py · settings.py · members.py` · `services/auth.py · admin_data.py` · `components/auth_gate.py` |
| 김바로 | `routers/aquarium.py · tide.py · inquiries.py` | `views/home.py · aquarium.py · user_aquarium.py · report.py · admin/inquiries.py` · `services/aquarium_data.py · inquiry_data.py` · `components/tide_card.py` |
| 차유진 | `routers/community.py · admin_boards.py` | `views/community.py · write.py · admin/boards.py` · `services/community_data.py` · `components/fields.py` |
| 이정민 | `routers/games.py · news.py · admin_contents.py` · `news_collector.py` | `views/playground.py · news.py · admin/contents.py` · `services/news_data.py · games_data.py` · `jobs/collect_news.py` |

pydantic 모델은 `backend/schemas/`에 담당자별 파일로 있어요. API 전체 목록은 [docs/API_목록.md](docs/API_목록.md).

## 작업 규칙 (요약)

1. 내 파일만 고쳐요. 공통 파일(편성훈 칸)은 편성훈 님에게 요청해요.
2. API는 요청 · 응답을 pydantic 모델로 정의하고, 권한은 서버에서 확인해요(`require_user` · `require_admin`).
3. 화면은 `services/` 함수만 불러요. 실패하면 `ApiError.message`를 보여줘요.
4. 오류 문구 · 화면 문구는 기능정의서 7장(말투 · 용어 사전)을 따라요.
5. 키는 `.env`에만. 코드 · 깃 · 채팅에 올리지 않아요.
6. 올리기 전에 `check` 스크립트 마지막 줄이 `문제 0건`인지 확인해요.
7. 폭 375px(폰)과 PC에서 한 번씩 확인해요.

## 문서

- [docs/설치가이드.md](docs/설치가이드.md): 설치 · 실행 · 키 발급 · 배포 · 문제 해결
- [docs/API_목록.md](docs/API_목록.md): 담당자별 API 107개
- [docs/작업정리.md](docs/작업정리.md): 지금까지 한 일 · 결정 사항 · 남은 일
