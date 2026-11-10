"""나의 수족관 · 다른 사람 수족관 · 물때 지역 도우미 (김바로 담당). 이제 FastAPI 서버를 불러요.

화면 파일(views/aquarium.py, views/user_aquarium.py, views/home.py, components/tide_card.py)이 같이 써요.

    cards(uid)                     # 생물 카드 목록 (미확인 카드 포함) ← GET /me/aquarium
    update · move · delete · share · unshare   # 기록 고치기 · 옮기기 · 지우기 · 공유 (실패하면 ApiError)
    set_public(on)                 # 수족관 공개 설정
    public_aquariums() / public_view(uid)      # U-11
    species_card(card, key)        # 카드 하나 그리기 (U-06 · U-11 공용)

미확인 생물: 서버의 진짜 생물 행 'sp_unknown'(❔)이에요. 이름을 정하면 그 생물 카드로 옮겨요(move).
쓰기 함수는 성공하면 db.clear_cache() 를 불러요. 화면은 그다음 st.rerun() 만 하면 돼요.
"""
from __future__ import annotations

import streamlit as st

from components import ui
from services import api, db
from services.api import ApiError

__all__ = ["ApiError"]

S = st.session_state
CARD_W = 165  # 폰(390px)에서 2개, PC에서 4~5개가 한 줄에 들어가는 폭
UNKNOWN_ID = "sp_unknown"
# 서버의 ‘미확인 생물’ 행을 아직 못 받았을 때 화면에 쓸 모양 (서버 값과 같아요)
UNKNOWN = {"id": UNKNOWN_ID, "name": "미확인 생물", "emoji": "❔", "tone": "navy", "confidence": "low",
           "safety": {"level": "caution", "reason": "어떤 생물인지 모를 때는 만지지 말고 눈으로만 봐요."},
           "protected": False, "summary": "아직 이름을 정하지 않은 생물이에요.",
           "info": {"habitat": "", "food": "", "fun_fact": ""}, "candidates": []}


# ---------- 날짜 ----------
def fmt_date(d: str, short: bool = True) -> str:
    """'2026-11-01' → '11.01' (짧게) / '2026.11.01' (길게)."""
    try:
        y, m, dd = d.split("-")
    except ValueError:
        return d
    return f"{m}.{dd}" if short else f"{y}.{m}.{dd}"


# ---------- 내 수족관 (조회) ----------
def cards(uid: str | None = None) -> list[dict]:
    """생물 카드 목록 (최근 만난 순). 미확인 기록은 ‘미확인 생물’ 카드로 묶여 와요."""
    rows = db._cached("aq:cards", lambda: api.get("/me/aquarium"), ttl=15)
    return [c for c in rows if c.get("species")]


def find_card(uid: str | None, sp_id: str) -> dict | None:
    return next((c for c in cards(uid) if c["species"]["id"] == sp_id), None)


def summary(card_list: list[dict]) -> tuple[int, int, int]:
    """(생물 종 수, 관찰 기록 수, 공유 중인 기록 수) — 미확인은 종 수에서 빼요."""
    kinds = sum(1 for c in card_list if c["species"]["id"] != UNKNOWN_ID)
    recs = sum(c["count"] for c in card_list)
    shared = sum(1 for c in card_list for r in c["records"] if r.get("post_id"))
    return kinds, recs, shared


def record(rec_id: str) -> dict | None:
    return next((r for c in cards() for r in c["records"] if r["id"] == rec_id), None)


def species_ids(include_unknown: bool = False) -> list[str]:
    """이름 고르기 목록. 미확인 생물은 기본으로 빼요."""
    ids = [s["id"] for s in db.all_species() if s["id"] != UNKNOWN_ID]
    return [UNKNOWN_ID] + ids if include_unknown else ids


def species_of(sid: str) -> dict:
    return db.species(sid) or UNKNOWN


# ---------- 내 수족관 (쓰기: 실패하면 ApiError) ----------
def _done(out):
    db.clear_cache()
    return out


def update(rec_id: str, place: str, memo: str, when: str, species_id: str | None = None) -> dict:
    """기록 고치기. species_id를 주면 그 생물 카드로 함께 옮겨요 (한 번에 저장)."""
    body = {"place": place, "memo": memo, "date": when}
    if species_id:
        body["species_id"] = species_id
    return _done(api.patch(f"/me/observations/{rec_id}", json=body))


def move(rec_id: str, species_id: str) -> dict:
    """이름 정하기 · 다른 생물 카드로 옮기기."""
    return _done(api.patch(f"/me/observations/{rec_id}", json={"species_id": species_id}))


def delete(rec_id: str) -> str:
    """기록을 지워요. 공유 중이었다면 관찰 이야기에 올린 글도 함께 내려가요. 안내 문구를 돌려줘요."""
    return _done(api.delete(f"/me/observations/{rec_id}"))["message"]


def share(rec_id: str, title: str, place_level: str = "none", consent: bool = False) -> str:
    """기록을 ‘관찰 이야기’에 공유해요. 새 글 id를 돌려줘요."""
    out = api.post(f"/me/observations/{rec_id}/share",
                   json={"title": title, "place_level": place_level, "consent": consent})
    return _done(out)["post_id"]


def unshare(rec_id: str) -> None:
    """공유 취소: 글과 사진이 다른 사람에게 바로 안 보여요. 기록은 ‘나만 보기’로 남아요."""
    _done(api.post(f"/me/observations/{rec_id}/unshare"))


def set_public(on: bool) -> str:
    out = api.put("/me/aquarium/public", json={"public": on})
    if S.get("user"):
        S["user"]["aquarium_public"] = out["public"]
    return _done(out)["message"]


# ---------- 비회원 예시 수족관 ----------
def example_cards() -> list[dict]:
    sample = [("sp_hermit", 3, "2026-11-02"), ("sp_star", 2, "2026-10-28"), ("sp_moon", 1, "2026-10-20"),
              ("sp_seahare", 2, "2026-10-11"), ("sp_anemone", 1, "2026-09-30")]
    out = []
    for sid, n, last in sample:
        sp = db.species(sid)
        if sp:
            out.append({"species": sp, "records": [], "count": n, "last": last, "shared": n > 1})
    return out


# ---------- 다른 사람 수족관 (U-11) ----------
def public_aquariums() -> list[dict]:
    """구경할 수 있는 수족관: [{owner: {id, nickname, character, grade}, species_count, record_count}]"""
    return db._cached("aq:public", lambda: api.get("/aquariums/public"), ttl=30)


def public_view(uid: str) -> dict:
    """{owner, cards, species_count, record_count}. 비공개면 ApiError(403, code='private'), 없으면 404."""
    return api.get(f"/users/{uid}/aquarium")


# ---------- 물때 지역 기억 (C-02) ----------
def save_region(rid: str) -> None:
    """회원이 고른 물때 지역을 계정에 남겨요. 실패해도 이번 방문 동안은 기억해요."""
    out = api.put("/me/region", json={"region": rid})
    if S.get("user"):
        S["user"]["region"] = out["region"]


# ---------- 카드 그리기 (U-06 · U-11 공용) ----------
def species_card(card: dict, key: str, button: str = "열기", sub: str | None = None,
                 show_status: bool = True) -> bool:
    """폭이 고정된 생물 카드. 버튼을 누르면 True."""
    sp = card["species"]
    with st.container(border=True, width=CARD_W, gap="small"):
        ui.photo(sp["emoji"], sp.get("tone", "aqua"), height=104)
        st.markdown(f"**{sp['name']}**")
        ui.muted(sub or f"{card['count']}번 만남 · {fmt_date(card['last'])}")
        if show_status:
            if sp["id"] == UNKNOWN_ID:
                ui.chips(ui.chip("미확인", "warn"))
            elif card.get("shared"):
                ui.chips(ui.chip("공유 중", "sea"))
            else:
                ui.chips(ui.chip("나만 보기"))
        return st.button(button, key=key, width="stretch")
