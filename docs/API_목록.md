# Sea-Info Agent API 목록

서버를 켠 뒤 `http://localhost:8000/docs` 에서 각 API를 눌러 직접 시험해 볼 수 있어요. 이 파일은 `python tools/make_api_doc.py`로 다시 만들어요.

전체 105개 · 로그인이 필요한 API는 `Authorization: Bearer <토큰>` 머리글을 보내요 (화면은 `services/api.py`가 알아서 붙여요).

## 공통 · 담당 편성훈

| 방법 | 주소 | 설명 |
|---|---|---|
| `GET` | `/health` | 서버 상태와 연동 모드 |
| `GET` | `/settings/public` | 화면에 필요한 운영 설정 |
| `GET` | `/species` | 생물 목록 |
| `GET` | `/species/{species_id}` | 생물 하나 |
| `GET` | `/users/{user_id}` | 회원 공개 정보 (닉네임 · 캐릭터) |

## 생물 알아보기 · 담당 편성훈

| 방법 | 주소 | 설명 |
|---|---|---|
| `POST` | `/drafts` | 로그인 전 분석 결과 30분 보관 |
| `GET` | `/drafts/{draft_id}` | 보관한 분석 결과 되살리기 |
| `POST` | `/identify` | 사진으로 생물 알아보기 |
| `POST` | `/identify/save` | 수족관에 담기 (+ 선택 공유를 한 번에) |
| `GET` | `/usage` | 오늘 남은 알아보기 횟수 |

## 로그인 · 담당 이종민

| 방법 | 주소 | 설명 |
|---|---|---|
| `POST` | `/auth/dev-login` | 시험용 로그인 (APP_ENV=local 에서만) |
| `POST` | `/auth/login` | 이메일 · 비밀번호 로그인 (메일 인증을 마친 계정) |
| `POST` | `/auth/logout` | 로그아웃 |
| `DELETE` | `/auth/me` | 회원 탈퇴 (수족관 기록은 지우고, 글 · 댓글은 ‘탈퇴한 회원’으로 남겨요) |
| `GET` | `/auth/me` | 내 정보 |
| `PATCH` | `/auth/me` | 프로필 바꾸기 (닉네임 · 캐릭터 · 수족관 공개 · 지역) |
| `POST` | `/auth/password/change` | 비밀번호 바꾸기 (로그인한 상태 · 로컬 모드) |
| `POST` | `/auth/password/reset` | 비밀번호 찾기 → 재설정 링크 메일 |
| `POST` | `/auth/password/reset/confirm` | 재설정 링크를 누른 뒤 새 비밀번호 저장 |
| `POST` | `/auth/resend` | 가입 인증 메일 다시 보내기 |
| `POST` | `/auth/signup` | 가입 ① 이메일 · 비밀번호 · 약관 → 인증 링크 메일 |
| `POST` | `/auth/verify-link` | 가입 ② 메일 속 링크 확인 (가입 인증 → 바로 로그인 · 비밀번호 재설정 → reset_id) |

## 내 정보 · 담당 이종민

| 방법 | 주소 | 설명 |
|---|---|---|
| `GET` | `/me/comments` | 내가 남긴 댓글 (어느 글인지 함께) |
| `GET` | `/me/posts` | 내가 쓴 글 (운영자가 숨긴 글 포함) |

## 관리자 운영 · 담당 이종민

| 방법 | 주소 | 설명 |
|---|---|---|
| `GET` | `/admin/dashboard` | 오늘 숫자 5개 · 오늘 할 일 · 최근 조치 기록 |
| `GET` | `/admin/logs` | 조치 기록 (screen=게시물,신고 처럼 쉼표로 여러 개) |
| `GET` | `/admin/members` | 회원 목록 (닉네임 · 이메일 검색 · 상태) |
| `GET` | `/admin/members/{user_id}` | 회원 한 명 |
| `POST` | `/admin/members/{user_id}/suspend` | 이용 정지 (기간 · 사유) |
| `POST` | `/admin/members/{user_id}/unsuspend` | 이용 정지 풀기 |
| `GET` | `/admin/posts` | 게시물 목록 (숨긴 글 포함 · 검색 · 게시판 · 상태) |
| `DELETE` | `/admin/posts/{post_id}` | 글 지우기 (댓글 · 대기 중인 신고도 함께 정리) |
| `POST` | `/admin/posts/{post_id}/hide` | 글 숨기기 (대기 중인 신고도 ‘숨김’으로 처리) |
| `POST` | `/admin/posts/{post_id}/restore` | 숨긴 글 다시 보이게 |
| `GET` | `/admin/reports` | 신고 목록 (글마다 묶음 · 대기가 먼저) |
| `POST` | `/admin/reports/{post_id}/resolve` | 신고 처리: 숨기기 또는 문제없음 |
| `GET` | `/admin/settings` | 운영 설정 전체 (금칙어 포함) |
| `PUT` | `/admin/settings` | 운영 설정 저장 (바뀐 항목마다 변경 기록) |

## 나의 수족관 · 담당 김바로

| 방법 | 주소 | 설명 |
|---|---|---|
| `GET` | `/aquariums/public` | 구경할 수 있는 수족관 목록 |
| `GET` | `/me/aquarium` | 나의 수족관 (생물별로 묶음) |
| `PUT` | `/me/aquarium/public` | 내 수족관 공개 · 비공개 |
| `GET` | `/me/observations` | 내 관찰 기록 |
| `DELETE` | `/me/observations/{obs_id}` | 관찰 기록 지우기 (공유한 글도 함께 내려요) |
| `PATCH` | `/me/observations/{obs_id}` | 관찰 기록 고치기 · 다른 생물 카드로 옮기기 |
| `POST` | `/me/observations/{obs_id}/share` | 관찰 기록을 ‘관찰 이야기’에 공유하기 |
| `POST` | `/me/observations/{obs_id}/unshare` | 공유 취소 (기록은 ‘나만 보기’로 남아요) |
| `GET` | `/users/{user_id}/aquarium` | 다른 사람 수족관 (공유 중인 기록만) |

## 물때 · 담당 김바로

| 방법 | 주소 | 설명 |
|---|---|---|
| `PUT` | `/me/region` | 물때 카드에서 고른 지역을 내 계정에 기억 |
| `GET` | `/tide/regions` | 물때 지역 전체 |
| `GET` | `/tide/{region_id}` | 지역 하나의 오늘 물때 |

## 제보·건의 · 담당 김바로

| 방법 | 주소 | 설명 |
|---|---|---|
| `GET` | `/admin/inquiries` | 문의 목록 (관리자) |
| `PATCH` | `/admin/inquiries/{rid}` | 답변 · 상태 저장 (완료 + 답변이면 결과 메일) |
| `POST` | `/admin/inquiries/{rid}/jira/retry` | Jira 다시 보내기 (이슈가 없을 때만) |
| `POST` | `/admin/inquiries/{rid}/jira/sync` | Jira 상태 가져오기 (끝났으면 완료로) |
| `POST` | `/inquiries` | 제보·건의 보내기 (저장 → Jira → 담당 그룹 메일) |
| `POST` | `/inquiries/lookup/send` | 비회원 처리 확인 ① 메일로 6자리 코드 받기 |
| `POST` | `/inquiries/lookup/verify` | 비회원 처리 확인 ② 코드 확인 → 처리 상황 |
| `GET` | `/me/inquiries` | 내 제보·건의 (회원) |
| `POST` | `/webhooks/jira` | Jira 웹훅 (이슈가 끝나면 문의를 완료로) |

## 커뮤니티 · 담당 차유진

| 방법 | 주소 | 설명 |
|---|---|---|
| `GET` | `/boards` | 게시판 목록 (all=true면 운영 중이 아닌 것도) |
| `GET` | `/boards/{board_id}` | 게시판 하나 |
| `DELETE` | `/comments/{comment_id}` | 댓글 지우기 (쓴 사람 · 관리자) |
| `GET` | `/posts` | 게시글 목록 (board를 주면 그 게시판의 검색 항목 · 공지 고정 · 목록 권한을 따라요) |
| `POST` | `/posts` | 글쓰기 (관찰 이야기는 생물 알아보기의 공유로만) |
| `POST` | `/posts/photos` | 글에 붙일 사진 올리기 (1시간 안에 글에 붙여요) |
| `GET` | `/posts/recent` | 최근 관찰 이야기 (홈) |
| `DELETE` | `/posts/{post_id}` | 글 지우기 (글쓴이 · 관리자). 관찰 이야기 글이면 관찰 기록은 남기고 ‘나만 보기’로 |
| `GET` | `/posts/{post_id}` | 게시글 하나 (닫힌 게시판 · 읽기 권한은 관리자 · 글쓴이 말고는 막아요) |
| `PATCH` | `/posts/{post_id}` | 글 고치기 (글쓴이 · 관리자) |
| `GET` | `/posts/{post_id}/comments` | 댓글 목록 |
| `POST` | `/posts/{post_id}/comments` | 댓글 달기 |
| `GET` | `/posts/{post_id}/like` | 내가 공감했는지 |
| `POST` | `/posts/{post_id}/like` | 공감하기 · 다시 누르면 취소 (한 사람 한 번) |
| `GET` | `/posts/{post_id}/report` | 내가 신고했는지 |
| `POST` | `/posts/{post_id}/report` | 신고하기 (한 글에 한 번). 쌓인 신고가 운영 설정 횟수 이상이면 자동으로 숨겨요 |

## 게시판 관리 · 담당 차유진

| 방법 | 주소 | 설명 |
|---|---|---|
| `POST` | `/admin/boards` | 새 게시판 만들기 |
| `GET` | `/admin/boards/logs` | 게시판 관리 변경 기록 (최근 순) |
| `PUT` | `/admin/boards/order` | 게시판 순서 (+ 상태) 한 번에 저장 |
| `GET` | `/admin/boards/stats` | 게시판별 글 수와 항목별 사용 글 수 |
| `DELETE` | `/admin/boards/{board_id}` | 게시판 지우기 (기본 게시판 · 글이 있는 게시판은 못 지워요) |
| `PATCH` | `/admin/boards/{board_id}` | 게시판 설정 고치기 (보낸 칸만) |
| `POST` | `/admin/boards/{board_id}/fields` | 항목 추가 |
| `DELETE` | `/admin/boards/{board_id}/fields/{key}` | 항목 지우기 (아직 어떤 글에도 쓰이지 않은 항목만) |
| `PATCH` | `/admin/boards/{board_id}/fields/{key}` | 항목 고치기 · 사용 안 함/다시 사용(active) · 순서(order). 글에 쓰인 항목은 지우지 않고 사용 안 함으로 |

## 바다 놀이터 · 담당 이정민

| 방법 | 주소 | 설명 |
|---|---|---|
| `GET` | `/games/best` | 내 최고 점수 (기록이 없으면 null) |
| `GET` | `/games/quiz` | 퀴즈 문제 n개 (사용 중인 문제에서 무작위) |
| `POST` | `/games/scores` | 점수 기록 (회원만 · 끝까지 했을 때) |
| `GET` | `/games/top` | 게임별 Top 5 [닉네임, 점수, 날짜] |

## 바다 소식 · 담당 이정민

| 방법 | 주소 | 설명 |
|---|---|---|
| `GET` | `/news` | 공개된 바다 소식 |
| `GET` | `/news/last-run` | 마지막으로 새 소식을 모은 때 (없으면 null) |
| `GET` | `/news/latest` | 최신 소식 n개 |
| `GET` | `/news/top` | 많이 읽은 소식 n개 (최근 30일 · 1시간마다 순서 갱신) |
| `GET` | `/news/{news_id}` | 소식 하나 (숨긴 소식은 관리자만) |
| `POST` | `/news/{news_id}/view` | 상세를 열면 조회수 +1 (같은 사람은 24시간에 한 번) |

## 관리자 · 콘텐츠 · 담당 이정민

| 방법 | 주소 | 설명 |
|---|---|---|
| `GET` | `/admin/news` | 모든 소식 (숨긴 소식 포함, 최신순) |
| `POST` | `/admin/news` | 소식 직접 등록 (바로 공개) |
| `POST` | `/admin/news/collect` | 지금 수집하기 (출처 이름을 주면 그 출처만 다시) |
| `GET` | `/admin/news/runs` | 수집 기록 (최신순) |
| `GET` | `/admin/news/sources` | 수집 출처 목록 |
| `PUT` | `/admin/news/sources` | 수집 출처 한 번에 저장 (목록에 없는 출처는 지워요) |
| `PATCH` | `/admin/news/{news_id}` | 소식 고치기 · 숨기기 · 다시 공개 |
| `POST` | `/admin/news/{news_id}/resummarize` | 원문으로 AI 다시 요약 |
| `GET` | `/admin/quiz` | 퀴즈 문제 모두 (쉬는 문제 포함) |
| `POST` | `/admin/quiz` | 새 문제 추가 (보기 3~4개) |
| `PATCH` | `/admin/quiz/{quiz_id}` | 문제 고치기 · 사용 여부 바꾸기 |
