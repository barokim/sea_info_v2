"""U-01 홈 (김바로 담당).

배치 · PC: 왼쪽 넓은 칸(배너 → 최근 관찰 → 수족관 · 놀이터), 오른쪽 좁은 칸(물때 → 소식)
      폰: 배너 → 물때 → 최근 관찰 → 수족관 → 놀이터 → 소식
그래서 [배너 | 물때] 한 줄, [나머지 | 소식] 한 줄로 나눠 그려요. 폰에서는 칸이 위아래로 쌓여요.
영역마다 try/except로 감싸서 한 영역이 실패해도 나머지는 보여요.

시안 캡처용: ?shot=tide_error (물때 불러오기 실패) | empty (최근 관찰 · 소식이 비었을 때)
데이터는 모두 FastAPI에서 받아요 (최근 글 · 소식 · 수족관 · 놀이터 랭킹 · 물때).
"""
import streamlit as st

from components import nav, ui
from components.tide_card import tide_card
from services import aquarium_data as aq
from services import auth, db

S = st.session_state
user = auth.current_user()
shot = st.query_params.get("shot")
CARD_W = 164  # 최근 관찰 카드: 폰(358px) 2개, PC 왼쪽 칸(531px) 3개씩


def area(draw, *args) -> None:
    """영역 하나 그리기. 실패하면 그 자리에만 안내를 보여요."""
    try:
        draw(*args)
    except Exception:
        st.warning("이 영역을 불러오지 못했어요. 잠시 뒤 새로고침해 주세요.", icon=":material/error:")


# ---------- 메인 배너 ----------
def hero() -> None:
    # [BARO-CHANGE-001] 횟수 조회 실패를 배너와 분리해 식별 진입을 유지한다.
    # 조회하지 못한 횟수를 정상 값으로 대체하지 않는다.
    try:
        left_n, limit = db.remaining(user)
        note = f"오늘 남은 횟수 {left_n} / {limit}회" if user else f"로그인 없이 오늘 {limit}번 무료"
    except Exception:
        note = "오늘 이용 가능 횟수를 확인하지 못했어요."
    with st.container(key="home_hero", gap="medium"):  # 배너 안에 버튼까지 함께 (버튼이 배너에 붙어 보이지 않게)
        st.markdown('<div class="eyebrow">DISCOVER THE OCEAN</div><h2>이 생물, 이름이 뭘까요?</h2>'
                    '<p>바닷가에서 만난 생물을 찍어 올리면 AI가 이름과 안전 정보를 알려 줘요.</p>',
                    unsafe_allow_html=True)
        with st.container(horizontal=True, vertical_alignment="center", gap="medium"):
            if st.button("사진으로 알아보기", type="primary", icon=":material/photo_camera:", key="home_identify"):
                nav.go("identify")
            # [BARO-CHANGE-031] 홈에는 작은 이름 검색창만 배치하고 제출 후 전용 결과 화면으로 이동한다.
            # 입력할 때마다 외부 API를 호출하지 않고 Enter 또는 검색 버튼으로만 제출한다.
            with st.form("home_species_search", border=False, width=280):
                with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                    name = st.text_input("생물 이름으로 검색", max_chars=100, label_visibility="collapsed",
                                         placeholder="생물 이름으로 검색", key="home_species_name")
                    search = st.form_submit_button("검색", icon=":material/search:")
                if search:
                    term = " ".join((name or "").split())
                    if term:
                        nav.go("species_search", q=term)
                    else:
                        st.warning("검색할 생물 이름을 적어 주세요.")
        st.markdown(f'<span class="sia-hero-chip">{note}</span>', unsafe_allow_html=True)
    st.markdown('<div class="sia-steps">'
                '<div class="step"><span class="n">1</span>사진 올리기</div><span class="arr">›</span>'
                '<div class="step"><span class="n">2</span>AI가 알아보기</div><span class="arr">›</span>'
                '<div class="step"><span class="n">3</span>수족관에 담기</div></div>', unsafe_allow_html=True)
    with st.container(key="home_try", gap="small"):
        ui.muted("사진이 없나요? 예시 사진으로 먼저 해 보세요.")
        with st.container(horizontal=True, gap="small"):
            for name, emoji in (("소라게", "🦀"), ("불가사리", "⭐"), ("해파리", "🪼")):
                if st.button(f"{emoji} {name}", key=f"home_try_{name}"):
                    S["identify_pick"] = name  # 생물 알아보기 화면의 예시 사진 고르기에 미리 넣어 둬요
                    nav.go("identify")


# ---------- 최근 관찰 이야기 ----------
def recent_posts() -> None:
    ui.section("최근 관찰 이야기", "더보기", "community", board="obs")
    rows = [] if shot == "empty" else db.recent_posts(6)
    if not rows:
        ui.empty_state("🐚", "아직 공유된 관찰 이야기가 없어요. 첫 이야기를 들려줄까요?",
                       "생물 알아보기", "identify", key="home_recent_empty")
        return
    with st.container(horizontal=True, gap="small", horizontal_alignment="distribute"):
        for p in rows:
            # [BARO-CHANGE-002] 카드 보조 정보 조회 실패를 개별 카드 안에서 처리한다.
            # 게시글 본문은 기존 공개 API 응답만 사용하며 다른 자료로 복원하지 않는다.
            try:
                sp = db.species(p.get("species") or "") or aq.UNKNOWN
            except Exception:
                sp = aq.UNKNOWN
            try:
                nickname = db.user(p["user"])["nickname"]
            except Exception:
                nickname = "작성자 정보 확인 불가"
            with st.container(border=True, width=CARD_W, gap="small"):
                ui.photo(sp["emoji"], sp.get("tone", "aqua"), height=104, label=sp["name"])
                st.markdown(f"**{p['title']}**")
                ui.muted(f"{nickname} · {p['created']}")
                with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center",
                                  gap="small"):
                    ui.chips(ui.chip(f"♥ {p['likes']}", "coral"))
                    nav.link("community", "보기", post=p["id"])


# ---------- 나의 수족관 미리보기 ----------
def aquarium_preview() -> None:
    ui.section("나의 수족관", "수족관 보기" if user else None, "aquarium" if user else None)
    with st.container(border=True):
        if not user:
            st.markdown("**첫 바다 친구를 모아 보세요**")
            ui.muted("알아본 생물을 담으면 나만의 수족관이 생겨요. 이렇게 모여요.")
            with st.container(horizontal=True, gap="small"):
                for c in aq.example_cards()[:4]:
                    ui.photo(c["species"]["emoji"], c["species"]["tone"], height=64, width=64)
            if st.button("로그인하고 내 수족관 만들기", icon=":material/login:", key="home_aq_login"):
                nav.remember_here("aquarium")
                S["after_login"] = S.get("back_to")
                nav.go("login")
            return
        cards = aq.cards(user["id"])
        if not cards:
            ui.muted("아직 만난 생물이 없어요. 첫 바다 친구를 찾아볼까요?")
            if st.button("생물 알아보기", key="home_aq_first", icon=":material/photo_camera:"):
                nav.go("identify")
            return
        kinds, recs, _ = aq.summary(cards)
        with st.container(horizontal=True, gap="small"):
            st.metric("모은 생물", f"{kinds}종")
            st.metric("관찰 기록", f"{recs}번")
        ui.muted("최근에 만난 친구")
        for col, c in zip(st.columns(3, gap="small"), cards[:3]):
            sp = c["species"]
            with col:
                ui.item_row(sp["emoji"], sp["name"], f"{aq.fmt_date(c['last'])} 만남", tone=sp["tone"], size=48)
                nav.link("aquarium", "카드 열기", icon=":material/arrow_forward:", sp=sp["id"])


# ---------- 바다 놀이터 ----------
def playground() -> None:
    ui.section("바다 놀이터", "놀이터 가기", "playground")
    from services import games_data  # 놀이터 랭킹 창구 (이정민 담당). 실패하면 이 칸만 안내가 떠요

    quiz_top = games_data.top_scores("quiz")
    puzzle_top = games_data.top_scores("puzzle")
    with st.container(horizontal=True, gap="small"):
        with st.container(border=True, width=250):
            ui.item_row("🦀", "바다 생물 퀴즈", f"5문제 · 최고 {quiz_top[0][1]}점" if quiz_top else "5문제",
                        tone="sand")
            nav.link("playground", "퀴즈 풀러 가기", icon=":material/sports_esports:")
        with st.container(border=True, width=250):
            ui.item_row("⭐", "바다 친구 퍼즐", f"그림 맞추기 · 최고 {puzzle_top[0][1]}점" if puzzle_top else "그림 맞추기",
                        tone="coral")
            nav.link("playground", "퍼즐 맞추러 가기", icon=":material/extension:")


# ---------- 바다 소식 ----------
def news() -> None:
    ui.section("바다 소식", "더보기", "news")
    rows = [] if shot == "empty" else db.latest_news(3)
    if not rows:
        ui.empty_state("🐠", "아직 새 소식이 없어요. 곧 바다 소식을 모아 올게요.")
        return
    with st.container(border=True):
        for i, n in enumerate(rows):
            if i:
                st.divider()
            st.markdown(f"**{n['title']}**")
            with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center",
                              gap="small"):
                ui.muted(f"{n['source']} · {aq.fmt_date(n['date'])}")
                nav.link("news", "읽기", n=n["id"])


# ---------- 화면 그리기 ----------
if user:
    ui.page_header(f"{user['nickname']}님, 반가워요", "오늘은 어떤 바다 친구를 만날까요?")
else:
    ui.page_header("반가워요!", "사진 한 장으로 바다 생물의 이름을 알아봐요.")

top_l, top_r = st.columns([3, 2], gap="medium")
with top_l:
    area(hero)
with top_r:
    area(tide_card, shot == "tide_error")

st.space("small")
bot_l, bot_r = st.columns([3, 2], gap="medium")
with bot_l:
    area(recent_posts)
    st.space("small")
    area(aquarium_preview)
    st.space("small")
    area(playground)
with bot_r:
    area(news)
