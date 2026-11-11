"""U-10 글쓰기 (차유진 담당).

?board=<게시판> 이 기본 게시판이 되고, ?edit=<글 번호> 면 그 글을 고쳐요.
고른 게시판의 사용자 정의 항목(A-02에서 만든 것)을 fields.render 로 순서대로 보여줘요.
관찰 이야기는 생물 알아보기의 ‘공유하기’로만 올라가서 여기서는 고를 수 없어요.

저장할 때 서버가 다시 검사해요(권한 · 금칙어 · 연속 글쓰기 간격 · 추가 항목). 서버 안내는 그 칸 아래에 보여줘요.

시안 캡처용: ?shot=dive (다이빙 기록 · 추가 항목 2개) | errors (빠진 칸 안내, 서버 검사 결과) | cancel (그만두기 확인 팝업)
           ?edit=<글 번호> (글 고치기, 예: ?edit=p1&as=member · ?edit=p11&as=admin)
"""
import streamlit as st

from components import fields, nav, ui
from services import auth, db
from services import community_data as cd
from services.api import ApiError

S = st.session_state
user = auth.current_user()
FP = "write_f"  # 사용자 정의 항목 위젯 key 앞부분
TEXT_KEYS = ("write_title", "write_body", "write_consent", "write_photo_id")

# 콜백에서 저장을 마쳤으면 새 글로 이동
if S.get("write_new_post"):
    nav.go("community", post=S.pop("write_new_post"))
if S.get("write_cancel_go"):
    nav.go("community", **S.pop("write_cancel_go"))

edit_id = st.query_params.get("edit")
qp_board = st.query_params.get("board")


def photo_key() -> str:
    return f"write_photo_{S.get('_write_photo_version', 0)}"


def selected_photo():
    return S.get(photo_key())


def reset() -> None:
    # 업로더는 값을 직접 비울 수 없어 새 key로 다시 만들어요.
    S["_write_photo_version"] = S.get("_write_photo_version", 0) + 1
    for k in TEXT_KEYS + ("write_errors", "write_cancel"):
        S.pop(k, None)
    for b in db.boards(active_only=False):
        fields.clear(b.get("fields"), FP)


# ---------- 시안 캡처용 상태 만들기 ----------
shot = st.query_params.get("shot")
if shot in ("dive", "errors", "cancel") and S.get("_write_shot") != shot:
    S["_write_shot"] = shot
    reset()
    S["write_board"] = S["_write_qp"] = "dive"
    if shot in ("dive", "cancel"):
        S["write_cancel"] = shot == "cancel"
        S["write_title"] = "섶섬 앞바다 스노클링 기록"
        S["write_body"] = ("물이 맑아서 바닥까지 잘 보였어요.\n"
                           "바위 틈에 보라성게가 모여 있어서 손대지 않고 눈으로만 봤어요.")
        S[f"{FP}_depth"] = 5
        S[f"{FP}_gear"] = "스노클링"
    else:
        S["write_title"] = "문섬 포인트에서 만난 군소"
        S["_write_shot_errors"] = True


# ---------- 저장 (올리기 버튼 콜백) ----------
def check(b: dict) -> dict:
    """화면에서 먼저 보는 검사 (사진 동의가 빠졌을 때만 써요. 서버와 같은 규칙)."""
    title = (S.get("write_title") or "").strip()
    body = (S.get("write_body") or "").strip()
    errs = {}
    if not title:
        errs["title"] = "제목이 비어 있어요. 무엇에 대한 글인지 적어 주세요."
    if not body:
        errs["body"] = "내용이 비어 있어요. 2,000자까지 쓸 수 있어요."
    errs.update(fields.validate(b.get("fields"), fields.read(b.get("fields"), FP)))
    if selected_photo() and not S.get("write_consent"):
        errs["photo"] = "사진을 올리려면 바로 위 동의에 체크해 주세요."
    return errs


def photo_id() -> str | None:
    """고른 사진을 서버에 맡겨요. 같은 사진이면 다시 올리지 않아요."""
    photo = selected_photo()
    if not photo:
        return None
    done = S.get("write_photo_id")
    if done and done[0] == photo.file_id:
        return done[1]
    pid = cd.upload_photo(photo)
    S["write_photo_id"] = (photo.file_id, pid)
    return pid


def submit(bid: str, pid: str | None) -> None:
    b = db.board(bid)
    if selected_photo() and not S.get("write_consent"):  # 동의 없는 사진은 서버에 보내지 않아요
        S["write_errors"] = check(b)
        return
    title, body = S.get("write_title") or "", S.get("write_body") or ""
    extra = fields.to_store(b.get("fields"), fields.read(b.get("fields"), FP))
    for attempt in range(2):
        try:
            ph = photo_id()
            if pid:
                cd.update_post(pid, title, body, extra, ph, bool(S.get("write_consent")))
                S["community_toast"] = "고친 내용을 저장했어요"
            else:
                pid = cd.create_post(bid, title, body, extra, ph, bool(S.get("write_consent")))
                S["community_toast"] = "글을 올렸어요"
            break
        except cd.Problem as e:
            if e.code == "photo_expired":
                S.pop("write_photo_id", None)
                if attempt == 0 and selected_photo():
                    # 서버가 저장 전에 만료를 확인했을 때만, 고른 사진을 한 번 다시 올려요.
                    continue
            S["write_errors"] = cd.write_errors(e)
            return
        except ApiError as e:
            S["write_errors"] = {"_other": e.message}
            return
    reset()
    S["write_new_post"] = pid


def server_errors(bid: str) -> dict:
    """시안 캡처용: 지금 칸 값으로 서버 검사 결과를 받아요 (빈 칸이 있어 저장되지 않아요)."""
    b = db.board(bid)
    try:
        cd.create_post(bid, S.get("write_title") or "", S.get("write_body") or "",
                       fields.to_store(b.get("fields"), fields.read(b.get("fields"), FP)))
    except cd.Problem as e:
        return cd.write_errors(e)
    except ApiError as e:
        return {"_other": e.message}
    return {}


def ask_cancel(bid: str, pid: str | None) -> None:
    typed = any((S.get(k) or "") for k in ("write_title", "write_body")) or selected_photo()
    if typed:
        S["write_cancel"] = True
    else:  # 쓴 게 없으면 묻지 않고 돌아가요
        reset()
        S["write_cancel_go"] = {"post": pid} if pid else {"board": bid}


@st.dialog("글쓰기를 그만둘까요?", on_dismiss=lambda: S.pop("write_cancel", None))
def cancel_dialog(bid: str, pid: str | None) -> None:
    st.markdown("쓰던 내용이 사라져요. 그래도 그만둘까요?")
    with st.container(horizontal=True, gap="small"):
        if st.button("그만두고 목록으로", type="primary", key="write_cancel_ok"):
            reset()
            if pid:
                nav.go("community", post=pid)
            nav.go("community", board=bid)
        if st.button("계속 쓰기", key="write_cancel_back"):
            S.pop("write_cancel", None)
            st.rerun()


def tips(b: dict) -> None:
    with st.container(border=True):
        st.markdown("**이렇게 쓰면 좋아요**")
        st.markdown("- 제목에 무엇을, 어디서 봤는지 짧게 적어요.\n"
                    "- 사람 얼굴이나 차 번호판이 사진에 나오지 않게 해 주세요.\n"
                    "- 사는 곳은 지역까지만 적어요. 자세한 주소는 쓰지 않아요.\n"
                    "- 생물을 만났다면 사진만 찍고 제자리에 두어요.")
        if b["type"] == "질문형":
            ui.muted("궁금해요 게시판은 날짜와 지역을 함께 적으면 답이 빨리 달려요.")
    with st.container(border=True):
        st.markdown("**관찰 이야기를 올리고 싶나요?**")
        ui.muted("생물 사진은 ‘생물 알아보기’에서 이름을 알아본 뒤 수족관에 담으면서 공유할 수 있어요.")
        nav.link("identify", "생물 알아보기", icon=":material/photo_camera:")


# ---------- 화면 그리기 ----------
if not user:
    ui.page_header("글쓰기", "궁금해요 · 자유 수다 같은 게시판에 글을 남겨요.")
    ui.empty_state("🐚", "로그인하면 글을 쓸 수 있어요. 로그인 뒤 이 화면으로 다시 돌아와요.")
    if st.button("로그인 / 회원가입", type="primary", icon=":material/login:", key="write_login"):
        nav.remember_here("write", **({"board": qp_board} if qp_board else {}))
        S["after_login"] = S.get("back_to")
        nav.go("login")
    st.stop()

post = cd.get_post(edit_id)[0] if edit_id else None
if edit_id:
    if not post or not (post["user"] == user["id"] or cd.is_admin(user)):
        ui.page_header("글 고치기")
        ui.empty_state("🐚", "고칠 수 없는 글이에요. 내가 쓴 글만 고칠 수 있어요.")
        nav.link("community", "커뮤니티로 가기", icon=":material/arrow_back:")
        st.stop()
    board = db.board(post["board"])
    if S.get("_write_edit_loaded") != edit_id:  # 처음 열 때 원래 내용을 채워요
        S["_write_edit_loaded"] = edit_id
        reset()
        S["write_title"], S["write_body"] = post["title"], post.get("body", "")
        for f in fields.active(board.get("fields")):
            v = (post.get("extra") or {}).get(f["key"])
            if fields.is_empty(v) or fields.validate([{**f, "required": False}], {f["key"]: v}):
                continue
            S[f"{FP}_{f['key']}"] = fields._date(v) if f["type"] == "date" else v
    ui.page_header("글 고치기", "고친 내용은 저장하면 바로 보여요.")
else:
    if S.pop("_write_edit_loaded", None) is not None:
        reset()
    options = cd.writable_boards(user)
    ids = [b["id"] for b in options]
    ui.page_header("글쓰기", "궁금한 것, 나누고 싶은 바다 이야기를 남겨요.")
    if qp_board and qp_board != S.get("_write_qp"):
        S["_write_qp"] = qp_board
        if qp_board in ids:
            S["write_board"] = qp_board
    if qp_board == "obs":
        st.info("관찰 이야기는 ‘생물 알아보기’에서 수족관에 담으면서 공유해요. 다른 게시판을 골라 주세요.",
                icon=":material/info:")
    if not ids:
        ui.empty_state("🐚", "지금 글을 쓸 수 있는 게시판이 없어요.", "커뮤니티로 가기", "community", key="write_none")
        st.stop()
    if S.get("write_board") not in ids:
        S["write_board"] = ids[0]
    board = None

errs = S.get("write_errors") or {}
if S.pop("_write_shot_errors", False):
    errs = S["write_errors"] = server_errors("dive")

left, right = st.columns([3, 2], gap="large")
with left:
    if post:
        ui.chips(ui.chip(f"게시판 · {board['name']}"))
    else:
        st.selectbox("게시판", ids, format_func=lambda i: db.board(i)["name"], key="write_board",
                     on_change=lambda: S.pop("write_errors", None))
        board = db.board(S["write_board"])
    extra_n = len(fields.active(board.get("fields")))
    st.caption(board.get("desc", ""))

    with st.form("write_form"):
        st.text_input("제목 *", max_chars=50, key="write_title", placeholder="무엇에 대한 글인가요?")
        fields.error_text(errs.get("title"))
        st.text_area("내용 *", max_chars=2000, height=180, key="write_body",
                     placeholder="본 것, 궁금한 것, 나누고 싶은 이야기를 적어 주세요.")
        fields.error_text(errs.get("body"))
        if extra_n:
            st.markdown(f"**{board['name']} 추가 항목**")
            fields.render(board.get("fields"), FP, errors=errs)
        if cd.can(user, board["perm"]["photo"]):
            st.file_uploader("사진 1장 (선택)", type=db.settings()["formats"], key=photo_key(),
                             max_upload_size=int(db.settings()["max_mb"]),
                             help=f"JPG · PNG, {db.settings()['max_mb']}MB까지. 스마트폰에서는 사진 찍기나 앨범을 고를 수 있어요.")
            st.checkbox("사진을 사이트에서 보여줘도 괜찮아요 (사진을 올릴 때 필수)", key="write_consent",
                        help="올린 사진은 글을 지우면 함께 지워져요.")
            fields.error_text(errs.get("photo"))
        n_err = len([k for k in errs if not k.startswith("_")])
        if n_err:
            st.error(f"고쳐야 할 칸이 {n_err}개 있어요. 칸 아래 안내를 확인해 주세요. 입력한 내용은 그대로 있어요.",
                     icon=":material/error:")
        if errs.get("_wait"):
            st.warning(errs["_wait"], icon=":material/schedule:")
        if errs.get("_other"):
            st.error(errs["_other"], icon=":material/error:")
        with st.container(horizontal=True, gap="small"):
            st.form_submit_button("고친 내용 저장하기" if post else "올리기", type="primary", icon=":material/send:",
                                  on_click=submit, args=(board["id"], edit_id))
            st.form_submit_button("취소", on_click=ask_cancel, args=(board["id"], edit_id))
with right:
    tips(board)

if S.get("write_cancel"):
    cancel_dialog(board["id"], edit_id)
