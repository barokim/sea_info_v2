"""사용자 정의 항목 (차유진 담당). 게시판마다 붙이는 입력 칸을 그리고 검사해요.

관리자가 A-02에서 정한 board["fields"] 를 글쓰기(U-10) · 상세(U-09) · 관리(A-02)가 함께 써요.

    values = fields.render(board["fields"], "write_f", errors=errs)   # 입력 칸 그리기
    errs = fields.validate(board["fields"], values)                   # {key: 안내 문구}
    fields.show(board["fields"], post.get("extra"))                   # 상세: ‘항목 이름: 값’
    errs = fields.validate_definition(new_field, other_fields)        # 관리자 팝업 저장 검사

항목 정의 모양
    {"key": "depth", "label": "관찰 수심(m)", "type": "number", "required": False,
     "min": 0, "max": 40, "help": "모르면 비워 두세요", "active": True}
    유형별 조건: short · long → "max_len" / number → "min" · "max" / date → "min" · "max" (YYYY-MM-DD)
               single · multi → "options" (multi는 "max_select" 선택)

    검사 규칙(validate · validate_definition · type_change_impact · condition_text)은 서버와 같은 코드예요
    (backend/schemas/community.py). 서버도 글을 받을 때 같은 규칙으로 다시 검사해요 — 화면 검사는 미리 보기용이에요.
"""
from __future__ import annotations

import html
import re
from datetime import date

import streamlit as st

from backend.schemas import community as rules

TYPES = rules.TYPES
TYPE_HINT = {
    "short": "한 줄로 적는 칸이에요. 예) 관찰한 포인트 이름",
    "long": "여러 줄로 적는 칸이에요. 예) 준비물, 느낀 점",
    "number": "숫자만 넣는 칸이에요. 예) 수심, 수온",
    "date": "날짜를 고르는 칸이에요. 예) 관찰한 날",
    "single": "여러 선택지 중 하나만 골라요. 4개 이하면 동그라미 버튼으로 보여요.",
    "multi": "여러 선택지 중 여러 개를 골라요. 예) 함께 본 생물",
}
DEFAULT_LEN = rules.DEFAULT_LEN
KEY_RULE = rules.KEY_RULE

# ---------- 작은 도우미 (서버와 같은 규칙) ----------
active = rules.active
is_empty = rules.is_empty
_date = rules.to_date
_num = rules.num


def label_of(f: dict) -> str:
    return f["label"] + (" *" if f.get("required") else " (선택)")


def error_text(msg: str | None) -> None:
    """입력 칸 바로 아래에 붙는 빨간 안내 한 줄."""
    if msg:
        st.markdown(f":red[:material/error: {msg}]")


def condition_text(f: dict) -> str:
    """관리 화면용: 유형별 조건을 한 줄로."""
    return rules.condition_text(f)


def format_value(f: dict, v) -> str:
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v)
    if f.get("type") == "date" and _date(v):
        return _date(v).strftime("%Y.%m.%d")
    return str(_num(v))


# ---------- 입력 칸 그리기 ----------
def render(fields: list[dict] | None, key_prefix: str, values: dict | None = None,
           errors: dict | None = None, disabled: bool = False) -> dict:
    """사용 중인 항목을 순서대로 그리고 {key: 값}을 돌려줘요.

    values: 처음 채워 둘 값 (글 고치기). errors: {key: 안내} 를 주면 그 칸 아래에 보여요.
    """
    values, errors = values or {}, errors or {}
    out = {}
    for f in active(fields):
        k, t = f["key"], f.get("type", "short")
        wkey = f"{key_prefix}_{k}"
        label, helptext = label_of(f), f.get("help") or None
        cur = values.get(k)
        if t == "short":
            out[k] = st.text_input(label, value=cur or "", max_chars=f.get("max_len") or DEFAULT_LEN[t],
                                   help=helptext, key=wkey, disabled=disabled)
        elif t == "long":
            out[k] = st.text_area(label, value=cur or "", max_chars=f.get("max_len") or DEFAULT_LEN[t],
                                  help=helptext, key=wkey, disabled=disabled, height=110)
        elif t == "number":
            lo, hi = f.get("min"), f.get("max")
            is_float = any(isinstance(x, float) and not x.is_integer() for x in (lo, hi, cur))
            cast = float if is_float else int
            lo = None if lo is None else cast(lo)
            hi = None if hi is None else cast(hi)
            val = None if cur is None else cast(cur)
            if val is not None and ((lo is not None and val < lo) or (hi is not None and val > hi)):
                val = None  # 범위가 바뀌어 들어갈 수 없는 옛 값은 비워서 보여줘요
            out[k] = st.number_input(label, min_value=lo, max_value=hi, value=val,
                                     step=0.1 if is_float else 1, help=helptext, key=wkey,
                                     placeholder=_range_hint(lo, hi), disabled=disabled)
        elif t == "date":
            lo, hi = _date(f.get("min")), _date(f.get("max"))
            val = _date(cur)
            if val and ((lo and val < lo) or (hi and val > hi)):
                val = None
            out[k] = st.date_input(label, value=val, min_value=lo, max_value=hi, format="YYYY.MM.DD",
                                   help=helptext, key=wkey, disabled=disabled)
        elif t == "single":
            opts = list(f.get("options") or [])
            idx = opts.index(cur) if cur in opts else None
            if len(opts) <= 4:
                out[k] = st.radio(label, opts, index=idx, horizontal=True, help=helptext, key=wkey,
                                  disabled=disabled)
            else:
                out[k] = st.selectbox(label, opts, index=idx, placeholder="하나를 골라 주세요",
                                      help=helptext, key=wkey, disabled=disabled)
        elif t == "multi":
            opts = list(f.get("options") or [])
            default = [x for x in (cur or []) if x in opts]
            out[k] = st.multiselect(label, opts, default=default, placeholder="골라 주세요 (여러 개 가능)",
                                    max_selections=f.get("max_select") or None, help=helptext, key=wkey,
                                    disabled=disabled)
        error_text(errors.get(k))
    return out


def read(fields: list[dict] | None, key_prefix: str) -> dict:
    """콜백 안에서 쓰기: 위젯에 들어 있는 값을 session_state에서 읽어요."""
    return {f["key"]: st.session_state.get(f"{key_prefix}_{f['key']}") for f in active(fields)}


def clear(fields: list[dict] | None, key_prefix: str) -> None:
    for f in fields or []:
        st.session_state.pop(f"{key_prefix}_{f['key']}", None)


def _range_hint(lo, hi) -> str:
    return rules.range_hint(lo, hi)


# ---------- 값 검사 (글쓰기) ----------
def validate(fields: list[dict] | None, values: dict) -> dict:
    """{key: 안내 문구}. 비어 있으면 통과. (서버도 글을 받을 때 같은 규칙으로 검사해요)"""
    return rules.validate_values(fields, values)


def to_store(fields: list[dict] | None, values: dict) -> dict:
    """저장용 값: 빈 값은 빼고, 날짜는 YYYY-MM-DD 글자로."""
    out = {}
    for f in active(fields):
        v = values.get(f["key"])
        if is_empty(v):
            continue
        out[f["key"]] = v.isoformat() if isinstance(v, date) else _num(v)
    return out


# ---------- 상세 보기 ----------
def show(fields: list[dict] | None, extra: dict | None) -> None:
    """‘항목 이름: 값’ 줄로 보여줘요. 비어 있는 항목은 숨겨요.

    ‘사용 안 함’이 된 항목도 이미 쓴 글에서는 그대로 보여요(기존 글 보호).
    """
    extra = extra or {}
    rows = [(f, extra.get(f["key"])) for f in (fields or []) if not is_empty(extra.get(f["key"]))]
    if not rows:
        return
    lines = "<br>".join(f"<b>{html.escape(f['label'])}</b>: {html.escape(format_value(f, v))}" for f, v in rows)
    with st.container(border=True):
        st.markdown(f"<div style='line-height:1.9;padding-bottom:4px'>{lines}</div>", unsafe_allow_html=True)


# ---------- 항목 정의 검사 (관리자) ----------
def parse_options(text: str) -> list[str]:
    """선택지 입력칸(한 줄에 하나 또는 쉼표)을 목록으로."""
    parts = re.split(r"[\n,]", text or "")
    return [p.strip() for p in parts if p.strip()]


def validate_definition(field: dict, existing_fields: list[dict] | None) -> dict:
    """{속성: 안내}. existing_fields 에는 고치는 항목 자신은 빼고 넣어 주세요. (서버도 같은 규칙으로 검사해요)"""
    return rules.validate_definition(field, existing_fields)


def type_change_impact(old: dict, new: dict, used: int) -> str | None:
    """유형이나 선택지를 바꿀 때 이미 쓴 글에 생길 일을 미리 알려줘요."""
    return rules.type_change_impact(old, new, used)
