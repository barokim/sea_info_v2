"""U-12 바다 놀이터 · U-13 퀴즈 팝업 · U-14 퍼즐 팝업 (이정민 담당).

게임은 팝업(st.dialog) 안에서 끝까지 진행해요. 진행 상황은 session_state에만 있어요.
    playground_open    : "quiz" | "puzzle" | None  (어느 팝업이 열려 있는지)
    playground_quiz    : 뽑은 5문제, 지금 문제 번호, 고른 답, 맞힌 개수 …
    playground_puzzle  : 정답 순서, 지금 배치, 처음 배치, 이동 횟수, 처음 누른 조각 …
문제 · 점수 · Top 5는 FastAPI 서버에서 와요 (services/games_data.py). 비회원도 게임은 마음껏 할 수 있어요.
점수는 회원이 끝까지 했을 때만 서버에 저장돼 Top 5(Redis)와 내 최고 점수(SQLite)에 들어가요.
중간에 닫으면 아무것도 남지 않아요.

시안 캡처용: 주소에 ?shot=quiz|quiz_answered|quiz_result|puzzle
"""
import random

import streamlit as st

from components import nav, ui
from services import auth, db, games_data
from services.api import ApiError

S = st.session_state
user = auth.current_user()

QUIZ_N = 5
LEVELS = {"easy": "쉬움 2×2", "normal": "보통 3×3"}
# 퍼즐 조각: 수족관 생물 이모지 (쉬움은 4종, 보통은 8종 + 소라 껍데기)
EASY_IDS = ["sp_hermit", "sp_star", "sp_moon", "sp_blue"]
CIRCLED = "①②③④"
# 퍼즐 조각 버튼: (폭 px, 이모지 크기). 폰(390px)에서도 3칸이 한 줄에 들어가요.
TILE = {2: (120, "Huge"), 3: (92, "huge")}


def _tiles(level: str) -> list[str]:
    if level == "easy":
        return [db.species(i)["emoji"] for i in EASY_IDS]
    return [s["emoji"] for s in db.all_species()][:8] + ["🐚"]


def _my_best(game: str) -> int | None:
    if not user:
        return None
    try:
        return games_data.best(game)
    except ApiError:
        return None


def _save(game: str, g: dict) -> None:
    """회원이 끝까지 한 판만 저장해요. 실패하면 결과 화면에 안내를 보여요."""
    try:
        g["rank"] = games_data.submit(game, g["score"])["rank"]
    except ApiError as e:
        g["save_error"] = e.message


def _close() -> None:
    S["playground_open"] = None
    S.pop("playground_quiz", None)
    S.pop("playground_puzzle", None)


def _go_login() -> None:
    _close()
    nav.remember_here("playground")
    nav.go("login")


# ---------- 퀴즈 ----------
def start_quiz(fixed: bool = False) -> None:
    error = None
    try:  # 사용 중인 문제 중 5개를 서버가 무작위로 골라 줘요 (시안 캡처는 늘 같은 문제로)
        qs = games_data.quiz(QUIZ_N, shuffle=not fixed)
    except ApiError as e:
        qs, error = [], e.message
    S["playground_quiz"] = {"qs": qs, "i": 0, "picked": None, "correct": 0, "error": error,
                            "marks": [], "done": False, "score": 0, "rank": None}
    S["playground_open"] = "quiz"


def _quiz_pick(j: int) -> None:
    g = S["playground_quiz"]
    if g["picked"] is not None:
        return
    g["picked"] = j
    right = j == g["qs"][g["i"]]["answer"]
    g["correct"] += int(right)
    g["marks"].append(right)


def _quiz_next() -> None:
    g = S["playground_quiz"]
    if g["i"] + 1 < len(g["qs"]):
        g["i"] += 1
        g["picked"] = None
        return
    g["done"] = True
    g["score"] = 20 * g["correct"]
    if user:  # 회원이 끝까지 풀었을 때만 기록
        _save("quiz", g)


def _quiz_dismiss() -> None:
    g = S.get("playground_quiz")
    if g and not g["done"]:
        S["playground_toast"] = "중간에 닫아서 이번 퀴즈는 기록되지 않았어요."
    _close()


def _rank_note(g: dict) -> None:
    rank = g["rank"]
    if user and g.get("save_error"):
        st.error(g["save_error"], icon=":material/error:")
    elif user:
        if rank:
            st.success(f"Top 5에 들었어요! 지금 **{rank}위**예요.", icon=":material/emoji_events:")
        else:
            st.info("이번엔 Top 5에 들지 못했어요. 한 번 더 도전해 볼까요?", icon=":material/emoji_events:")
    else:
        st.info("로그인하면 점수가 랭킹에 올라가요. 이번 점수는 기록되지 않았어요.", icon=":material/login:")
        if st.button("로그인하러 가기", type="tertiary", icon=":material/arrow_forward:", key="playground_to_login"):
            _go_login()


@st.dialog("바다 퀴즈", width="medium", on_dismiss=_quiz_dismiss)
def quiz_dialog() -> None:
    g = S.get("playground_quiz")
    if not g:
        return
    if g.get("error"):
        st.error(g["error"], icon=":material/error:")
        return
    if not g["qs"]:
        st.info("아직 준비된 문제가 없어요. 조금 뒤에 다시 와 주세요.")
        return
    n = len(g["qs"])

    if g["done"]:  # 결과
        good = g["correct"] >= 3
        st.markdown(f'<div class="sia-celebrate"><div class="big">{"🎉" if good else "🐚"}</div>'
                    f'<h3>{g["score"]}점</h3><p>{n}문제 중 <b>{g["correct"]}개</b> 맞혔어요.</p></div>',
                    unsafe_allow_html=True)
        st.space("small")
        ui.chips(*[ui.chip(f"{k}번 {'✓ 정답' if m else '✕ 오답'}", "ok" if m else "danger")
                   for k, m in enumerate(g["marks"], 1)])
        st.space("small")
        _rank_note(g)
        with st.container(horizontal=True, gap="small"):
            st.button("다시 하기", type="primary", width="stretch", icon=":material/replay:",
                      key="playground_quiz_again", on_click=start_quiz)
            if st.button("닫기", width="stretch", key="playground_quiz_close"):
                _close()
                st.rerun()
        return

    i, q, picked = g["i"], g["qs"][g["i"]], g["picked"]
    answered = picked is not None
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        st.markdown(f"**{i + 1} / {n}**")
        st.markdown(ui.chip(f"맞힌 개수 {g['correct']}", "ok"), unsafe_allow_html=True)
    st.progress((i + 1) / n)
    st.markdown(f'<h2 class="sia-h2" style="margin:.5rem 0 .75rem">Q{i + 1}. {q["q"]}</h2>',
                unsafe_allow_html=True)

    for j, opt in enumerate(q["options"]):
        label = f"{CIRCLED[j]} {opt}"
        if not answered:
            st.button(label, key=f"playground_q{i}_o{j}", width="stretch", on_click=_quiz_pick, args=(j,))
        elif j == q["answer"]:
            st.button(label, key=f"playground_q{i}_o{j}", width="stretch", type="primary",
                      icon=":material/check_circle:")
        else:
            st.button(label, key=f"playground_q{i}_o{j}", width="stretch", disabled=True,
                      icon=":material/cancel:" if j == picked else None)

    if answered:
        if picked == q["answer"]:
            st.success(f"**정답이에요!**  \n{q['explain']}", icon=":material/check_circle:")
        else:
            st.warning(f"**아쉬워요, 오답이에요.** 정답은 ‘{q['options'][q['answer']]}’예요.  \n{q['explain']}",
                       icon=":material/lightbulb:")
        last = i + 1 == n
        st.button("결과 보기" if last else "다음 문제", type="primary", width="stretch",
                  icon=":material/flag:" if last else ":material/arrow_forward:",
                  key=f"playground_next_{i}", on_click=_quiz_next)
    st.caption("지금 닫으면 기록되지 않아요. 끝까지 풀어야 점수가 남아요.")


# ---------- 퍼즐 ----------
def _min_swaps(board: list[str], target: list[str]) -> int:
    """정답 순서로 돌리는 데 필요한 가장 적은 자리 바꿈 수 (조각 수 − 순환 수)."""
    pos = {t: k for k, t in enumerate(target)}
    perm = [pos[t] for t in board]
    seen, cycles = set(), 0
    for k in range(len(perm)):
        if k not in seen:
            cycles += 1
            while k not in seen:
                seen.add(k)
                k = perm[k]
    return len(perm) - cycles


def start_puzzle(level: str | None = None, rng: random.Random | None = None) -> None:
    level = level or S.get("playground_level") or "easy"
    S["playground_level"] = level
    target = _tiles(level)
    rng = rng or random.Random()
    need = 2 if level == "easy" else 5
    board = target[:]
    while _min_swaps(board, target) < need:
        rng.shuffle(board)
    S["playground_puzzle"] = {"level": level, "n": 2 if level == "easy" else 3, "target": target,
                              "start": board[:], "board": board[:], "moves": 0, "pick": None,
                              "min": _min_swaps(board, target), "done": False, "score": 0, "rank": None}
    S["playground_open"] = "puzzle"


def _puzzle_level() -> None:
    start_puzzle(S["playground_level"])


def _puzzle_restart() -> None:
    g = S["playground_puzzle"]
    g.update(board=g["start"][:], moves=0, pick=None, done=False, score=0, rank=None)


def _puzzle_tap(k: int) -> None:
    g = S["playground_puzzle"]
    if g["done"]:
        return
    if g["pick"] is None:
        g["pick"] = k
        return
    if g["pick"] == k:  # 같은 조각을 다시 누르면 선택 취소
        g["pick"] = None
        return
    b = g["board"]
    b[g["pick"]], b[k] = b[k], b[g["pick"]]
    g["moves"] += 1
    g["pick"] = None
    if b == g["target"]:
        g["done"] = True
        g["score"] = max(10, 100 - 5 * (g["moves"] - g["min"]))
        if user:
            _save("puzzle", g)


def _puzzle_dismiss() -> None:
    g = S.get("playground_puzzle")
    if g and not g["done"]:
        S["playground_toast"] = "중간에 닫아서 이번 퍼즐은 기록되지 않았어요."
    _close()


def _goal_html(target: list[str], n: int) -> str:
    size = 40 if n == 2 else 34
    cells = "".join(ui.photo_html(t, "aqua", size, width=size) for t in target)
    return (f'<div style="display:grid;grid-template-columns:repeat({n},{size}px);gap:4px;'
            f'justify-content:start">{cells}</div>')


@st.dialog("바다 퍼즐", width="medium", on_dismiss=_puzzle_dismiss)
def puzzle_dialog() -> None:
    g = S.get("playground_puzzle")
    if not g:
        return
    st.segmented_control("난이도", list(LEVELS), format_func=LEVELS.get, key="playground_level",
                         required=True, on_change=_puzzle_level, label_visibility="collapsed")
    n, b, target = g["n"], g["board"], g["target"]

    if g["done"]:
        st.markdown(f'<div class="sia-celebrate"><div class="big">🎉</div><h3>완성했어요! {g["score"]}점</h3>'
                    f'<p><b>{g["moves"]}번</b> 만에 맞혔어요. (가장 적게는 {g["min"]}번)</p></div>',
                    unsafe_allow_html=True)
        st.space("small")
        _rank_note(g)
        with st.container(horizontal=True, gap="small"):
            st.button("다시 하기", type="primary", icon=":material/shuffle:", key="playground_pz_again",
                      on_click=start_puzzle, args=(g["level"],))
            st.button("처음부터", icon=":material/restart_alt:", key="playground_pz_restart_done",
                      on_click=_puzzle_restart)
            if st.button("닫기", key="playground_pz_close"):
                _close()
                st.rerun()
        return

    placed = sum(1 for x, t in zip(b, target) if x == t)
    with st.container(horizontal=True, gap="medium", vertical_alignment="center"):
        st.markdown(_goal_html(target, n), unsafe_allow_html=True)
        with st.container(width="stretch", gap="small"):
            st.markdown("**완성 모습**")
            ui.muted("왼쪽과 같은 순서로 맞춰 보세요.")
            ui.chips(ui.chip(f"이동 {g['moves']}번", "sea"), ui.chip(f"제자리 {placed} / {n * n}", "ok"))
    st.space("small")
    tile_w, size = TILE[n]
    for r in range(n):
        with st.container(horizontal=True, gap="small", wrap=False):
            for c in range(n):
                k = r * n + c
                # 버튼 글씨 크기는 못 바꿔서, 이모지를 LaTeX 크게(\huge) 글자로 넣어 조각처럼 보이게 해요
                st.button(f"$\\{size}\\text{{{b[k]}}}$", key=f"playground_tile_{k}", width=tile_w,
                          type="primary" if g["pick"] == k else "secondary",
                          on_click=_puzzle_tap, args=(k,))
    if g["pick"] is None:
        st.caption("조각 두 개를 차례로 누르면 자리가 바뀌어요. 적게 움직일수록 점수가 높아요.")
    else:
        st.caption(f"{b[g['pick']]} 조각을 골랐어요. 바꿀 조각을 하나 더 눌러 주세요.")
    st.button("처음부터", icon=":material/restart_alt:", key="playground_pz_restart", on_click=_puzzle_restart)
    st.caption("지금 닫으면 기록되지 않아요.")


# ---------- 시안 캡처용 상태 만들기 ----------
shot = st.query_params.get("shot")
if shot and S.get("playground_shot") != shot:
    S["playground_shot"] = shot
    _close()
    if shot in ("quiz", "quiz_answered", "quiz_result"):
        start_quiz(fixed=True)
        if shot == "quiz_answered":
            _quiz_pick(S["playground_quiz"]["qs"][0]["answer"])
        if shot == "quiz_result":  # 5문제 중 4개 맞힘 (3번만 오답)
            for k, q in enumerate(S["playground_quiz"]["qs"]):
                _quiz_pick(q["answer"] if k != 2 else (q["answer"] + 1) % len(q["options"]))
                _quiz_next()
    elif shot == "puzzle":  # 보통 3×3, 두 번 움직이고 한 조각을 고른 상태
        start_puzzle("normal", rng=random.Random(11))
        g = S["playground_puzzle"]
        for _ in range(2):
            p = next(k for k, (x, t) in enumerate(zip(g["board"], g["target"])) if x != t)
            _puzzle_tap(p)
            _puzzle_tap(g["board"].index(g["target"][p]))
        g["pick"] = next(k for k, (x, t) in enumerate(zip(g["board"], g["target"])) if x != t)

toast = S.pop("playground_toast", None)
if toast:
    st.toast(toast, icon=":material/info:")


# ---------- U-12 바다 놀이터 ----------
GAMES = {
    "quiz": {"title": "바다 퀴즈", "emoji": "🐙", "tone": "navy", "start": start_quiz,
             "desc": "바다 생물 문제 5개를 풀어요. 답을 고르면 바로 해설이 나와요. 맞힐수록 점수가 올라가요.",
             "chips": ["5문제", "한 문제 20점", "약 2분"]},
    "puzzle": {"title": "바다 퍼즐", "emoji": "⭐", "tone": "coral", "start": start_puzzle,
               "desc": "섞인 생물 조각을 두 개씩 바꿔 완성 모습대로 맞춰요. 쉬움과 보통 중에 골라요.",
               "chips": ["쉬움 2×2", "보통 3×3", "적게 움직일수록 높은 점수"]},
}

ui.page_header("바다 놀이터", "퀴즈와 퍼즐로 바다 친구들의 생김새와 습성을 알아가요.")
if not user:
    st.info("로그인하면 점수가 랭킹에 올라가요. 비회원도 마음껏 해 볼 수 있어요.", icon=":material/emoji_events:")

cols = st.columns(2, gap="large")
for col, (game, info) in zip(cols, GAMES.items()):
    with col:
        with st.container(border=True):
            ui.photo(info["emoji"], tone=info["tone"], height=150)
            st.markdown(f'<h3 class="sia-h2" style="font-size:18px;margin:.5rem 0 .25rem">{info["title"]}</h3>',
                        unsafe_allow_html=True)
            st.write(info["desc"])
            ui.chips(*[ui.chip(c) for c in info["chips"]])
            st.space("small")
            best = _my_best(game)
            if user:
                st.markdown(f"내 최고 점수 **{best}점**" if best is not None else "내 최고 점수 · 아직 기록이 없어요")
            else:
                ui.muted("로그인하면 내 최고 점수가 남아요.")
            st.button("시작하기", type="primary", width="stretch", icon=":material/play_arrow:",
                      key=f"playground_start_{game}", on_click=info["start"])

        st.space("small")
        ui.section(f"{info['title']} Top 5")
        try:
            rows = games_data.top_scores(game)
        except ApiError as e:
            st.warning(e.message, icon=":material/error:")
            continue
        if rows:
            me = user["nickname"] if user else None
            st.dataframe(
                [{"순위": f"{k}위", "닉네임": nick + (" (나)" if nick == me else ""), "점수": score, "날짜": when}
                 for k, (nick, score, when) in enumerate(rows, 1)],
                hide_index=True, width="stretch",
                column_config={"순위": st.column_config.TextColumn(width="small"),
                               "점수": st.column_config.NumberColumn(format="%d점", width="small")},
                key=f"playground_top_{game}")
            ui.muted("점수가 같으면 먼저 달성한 사람이 위예요.")
        else:
            ui.empty_state("🐚", "아직 기록이 없어요. 첫 번째 주인공이 되어 볼까요?")


# ---------- 더 해 보기: 점수 없이 즐기는 게임 (이종민 추가) ----------
# 우리가 만든 게임 HTML은 static/games/ 에 있고, 서버가 /app/static/games/ 로 같이 내보내요 (.streamlit/config.toml 의 enableStaticServing).
# 점수와 Top 5는 없어요. 누르면 새 창에서 열려요.
EXTRA_GAMES = [
    {"title": "집게돌이 갯벌 대결", "emoji": "🦀", "desc": "상대 집게보다 먼저 조개를 주워 바구니에 넣어요. 밀물이 오기 전에 돌아와야 해요.",
     "chips": ["5판", "컴퓨터와 대결"], "url": "/app/static/games/crab-tide.html"},
    {"title": "복어 빵빵이 대결", "emoji": "🐡", "desc": "상대보다 먼저 복어를 터뜨려요. 간지럼으로 둘 다 부풀게 할 수도 있어요.",
     "chips": ["5판", "컴퓨터와 대결"], "url": "/app/static/games/puffer-duel.html"},
    {"title": "물방울 결투", "emoji": "🫧", "desc": "문어가 물방울을 쏘아 복어를 맞혀요. 큰 물방울은 세지만 느려요.",
     "chips": ["5판", "컴퓨터와 대결"], "url": "/app/static/games/bubble-duel.html"},
    {"title": "바닷속 초성 탐험대", "emoji": "🔤", "desc": "초성만 보고 해양생물과 바다 용어를 맞혀요. 목숨 10개로 10단계에 도전해요.",
     "chips": ["10단계", "목숨 10개"], "url": "/app/static/games/chosung-quiz.html"},
    {"title": "누구게? 바닷속 확대경", "emoji": "🔍", "desc": "확대된 사진을 보고 어떤 바다 생물인지 맞혀요. 정답 뒤에 바다 상식도 알려 줘요.",
     "chips": ["퀴즈", "새 창에서 열림"], "url": "/app/static/games/magnifier.html"},
    {"title": "나의 바다 성향 찾기", "emoji": "🧭", "desc": "여섯 가지 질문으로 나와 어울리는 바다 성향을 알아봐요. 재미로 하는 테스트예요.",
     "chips": ["테스트", "새 창에서 열림"], "url": "/app/static/games/personality.html"},
]

st.space("medium")
ui.section("더 해 보기")
ui.muted("점수는 남지 않아요. 누르면 새 창에서 열려요.")
for row in range(0, len(EXTRA_GAMES), 2):
    cols2 = st.columns(2, gap="large")
    for col, g in zip(cols2, EXTRA_GAMES[row:row + 2]):
        with col:
            with st.container(border=True):
                st.markdown(f'<h3 class="sia-h2" style="font-size:18px;margin:0 0 .25rem">{g["emoji"]} {g["title"]}</h3>',
                            unsafe_allow_html=True)
                st.write(g["desc"])
                ui.chips(*[ui.chip(c) for c in g["chips"]])
                st.space("small")
                st.link_button("열기", g["url"], width="stretch", icon=":material/open_in_new:")

# ---------- 팝업 열기 (한 번에 하나만) ----------
if S.get("playground_open") == "quiz":
    quiz_dialog()
elif S.get("playground_open") == "puzzle":
    puzzle_dialog()
