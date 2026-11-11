"""커뮤니티 · 게시판 빌더 API 모양과 검사 규칙 (pydantic, 차유진 담당).

서버가 직접 검사해요. 화면이 보낸 값은 믿지 않아요.
같은 규칙을 화면(components/fields.py)도 불러 써서, 안내 문구가 서버와 화면에서 똑같아요.
그래서 이 파일은 pydantic과 파이썬 기본 모듈만 불러와요 (streamlit · DB · FastAPI 없음).

칸별 안내 모양 (422 · 409):
    {"code": "invalid_fields", "message": "고쳐야 할 칸이 2개 있어요. ...",
     "errors": {"title": "제목이 비어 있어요. ...", "extra.depth": "0~40 사이 숫자만 ..."}}
"""
from __future__ import annotations

import math
import re
from datetime import date
from functools import partial
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, create_model, field_validator, model_validator

from backend.schemas.common import BoardOut, CommentOut, PostOut

# ---------- 고를 수 있는 값 ----------
PERM_LEVELS = ("모두", "회원", "관리자")
STATUSES = ("준비 중", "운영 중", "일시 중지", "보관")
BOARD_TYPES = ("일반형", "사진형", "질문형")
LAYOUTS = {"card": "카드형", "list": "목록형"}
SORTS = {"latest": "최신순", "likes": "공감순"}
SEARCH_FIELDS = ("제목", "내용", "생물 이름", "닉네임")
PERM_NAMES = {"list": "목록 보기", "read": "글 읽기", "write": "글쓰기", "comment": "댓글", "photo": "사진 첨부"}
REPORT_REASONS = ("스팸", "욕설", "개인정보", "기타")
SYSTEM_BOARDS = ("obs", "notice")
DEFAULT_PERM = {"list": "모두", "read": "모두", "write": "회원", "comment": "회원", "photo": "회원"}
DEFAULT_RULES = {"comments": True, "likes": True, "reports": True, "interval": 30}

Perm = Literal["모두", "회원", "관리자"]
Status = Literal["준비 중", "운영 중", "일시 중지", "보관"]
BoardType = Literal["일반형", "사진형", "질문형"]
SearchField = Literal["제목", "내용", "생물 이름", "닉네임"]
FieldType = Literal["short", "long", "number", "date", "single", "multi"]

TITLE_MAX, BODY_MAX, COMMENT_MAX = 50, 2000, 300

# ---------- 사용자 정의 항목: 공통 규칙 ----------
TYPES = {"short": "짧은 글", "long": "긴 글", "number": "숫자", "date": "날짜", "single": "단일 선택", "multi": "복수 선택"}
DEFAULT_LEN = {"short": 50, "long": 500}
KEY_RULE = re.compile(r"^[a-z][a-z0-9_]{1,29}$")
SLUG_RULE = re.compile(r"^[a-z][a-z0-9-]{1,19}$")
RESERVED_KEYS = {"title", "body", "photo", "board", "species", "place", "place_level", "extra"}  # 기본 칸과 겹치지 않게
REQUIRED_MSG = {
    "single": "꼭 골라야 하는 항목이에요. 하나를 골라 주세요.",
    "multi": "꼭 골라야 하는 항목이에요. 하나 이상 골라 주세요.",
    "date": "꼭 넣어야 하는 항목이에요. 날짜를 골라 주세요.",
    "number": "꼭 넣어야 하는 항목이에요. 숫자를 넣어 주세요.",
}


def active(fields: list[dict] | None) -> list[dict]:
    """‘사용 안 함’이 아닌 항목만, 정한 순서대로."""
    return [f for f in (fields or []) if f.get("active", True)]


def is_empty(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, (list, tuple)) and not v)


def to_date(v) -> date | None:
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def num(v):
    """정수로 쓸 수 있으면 정수로."""
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def range_hint(lo, hi) -> str:
    if lo is not None and hi is not None:
        return f"{lo}~{hi} 사이 숫자"
    if lo is not None:
        return f"{lo} 이상"
    if hi is not None:
        return f"{hi} 이하"
    return "숫자를 넣어 주세요"


def check_value(f: dict, v) -> tuple[Any, str | None]:
    """항목 하나의 값 검사. (저장할 값, 안내 문구). 안내가 있으면 저장하지 않아요. 빈 값은 (None, None)."""
    t = f.get("type")
    if is_empty(v):
        return None, (REQUIRED_MSG.get(t, "꼭 적어야 하는 항목이에요. 내용을 적어 주세요.") if f.get("required") else None)
    if t in ("short", "long"):
        if not isinstance(v, (str, int, float)) or isinstance(v, bool):
            return None, "글자로 적어 주세요."
        v = str(v).strip()
        limit = f.get("max_len") or DEFAULT_LEN[t]
        if len(v) > limit:
            return None, f"{limit}자까지 쓸 수 있어요. 지금 {len(v)}자예요. 조금 줄여 주세요."
        return v, None
    if t == "number":
        try:
            if isinstance(v, bool):
                raise ValueError
            n = float(v)
            if not math.isfinite(n):
                raise ValueError
        except (TypeError, ValueError):
            return None, "숫자만 넣을 수 있어요. 다시 넣어 주세요."
        lo, hi = f.get("min"), f.get("max")
        if (lo is not None and n < lo) or (hi is not None and n > hi):
            return None, f"{range_hint(num(lo), num(hi))}만 넣을 수 있어요. 값을 바꿔 주세요."
        return num(n), None
    if t == "date":
        lo, hi, d = to_date(f.get("min")), to_date(f.get("max")), to_date(v)
        if d is None:
            return None, "날짜를 다시 골라 주세요."
        if (lo and d < lo) or (hi and d > hi):
            span = (f"{lo:%Y.%m.%d}" if lo else "") + " ~ " + (f"{hi:%Y.%m.%d}" if hi else "")
            return None, f"{span.strip()} 사이 날짜만 고를 수 있어요."
        return d.isoformat(), None
    opts = list(f.get("options") or [])
    if t == "single":
        if not isinstance(v, str) or v not in opts:
            return None, "선택지가 바뀌었어요. 다시 골라 주세요."
        return v, None
    if t == "multi":
        if not isinstance(v, (list, tuple)) or any(not isinstance(x, str) or x not in opts for x in v):
            return None, "선택지가 바뀌었어요. 다시 골라 주세요."
        picked = list(dict.fromkeys(v))
        if f.get("max_select") and len(picked) > f["max_select"]:
            return None, f"{f['max_select']}개까지 고를 수 있어요."
        return picked, None
    return None, None  # 모르는 유형은 저장하지 않아요


def validate_values(fields: list[dict] | None, values: dict) -> dict[str, str]:
    """{항목 key: 안내}. 비어 있으면 통과 (화면에서 미리 볼 때)."""
    errs = {}
    for f in active(fields):
        _, msg = check_value(f, (values or {}).get(f["key"]))
        if msg:
            errs[f["key"]] = msg
    return errs


def _pyd_check(f: dict, v):
    clean, msg = check_value(f, v)
    if msg:
        raise ValueError(msg)
    return clean


def extra_model(fields: list[dict] | None) -> type[BaseModel]:
    """게시판의 사용 중인 항목으로 pydantic 모델을 만들어요. 모르는 key · ‘사용 안 함’ 항목 값은 버려요."""
    spec = {}
    for i, f in enumerate(active(fields)):
        spec[f"f{i}"] = (Annotated[Any, BeforeValidator(partial(_pyd_check, f))],
                         Field(default=None, alias=f["key"], validate_default=True))
    return create_model("ExtraValues", __config__=ConfigDict(extra="ignore", populate_by_name=False), **spec)


def check_extra(fields: list[dict] | None, values: dict | None) -> tuple[dict, dict[str, str]]:
    """(저장할 값, {'extra.<key>': 안내}). 빈 값은 저장하지 않아요."""
    names = {f"f{i}": f["key"] for i, f in enumerate(active(fields))}  # 빈 값 검사 오류는 속 이름(f0)으로 와요
    try:
        m = extra_model(fields).model_validate(values or {})
    except ValidationError as e:
        return {}, {f"extra.{names.get(k, k)}": v for k, v in ko_errors(e.errors(), request=False).items()}
    return m.model_dump(by_alias=True, exclude_none=True), {}


def condition_text(f: dict) -> str:
    """관리 화면용: 유형별 조건을 한 줄로."""
    t = f.get("type")
    if t in ("short", "long"):
        return f"{f.get('max_len') or DEFAULT_LEN[t]}자까지"
    if t in ("number", "date"):
        lo, hi = f.get("min"), f.get("max")
        if t == "date":
            lo = to_date(lo).strftime("%Y.%m.%d") if to_date(lo) else None
            hi = to_date(hi).strftime("%Y.%m.%d") if to_date(hi) else None
        if lo is None and hi is None:
            return "범위 없음"
        return f"{'' if lo is None else num(lo)} ~ {'' if hi is None else num(hi)}".strip()
    if t in ("single", "multi"):
        opts = f.get("options") or []
        text = " · ".join(opts) if opts else "선택지 없음"
        if t == "multi" and f.get("max_select"):
            text += f" (최대 {f['max_select']}개)"
        return text
    return ""


def field_brief(f: dict) -> str:
    return f"{f['label']} · {TYPES.get(f['type'], f['type'])} · {condition_text(f)}" + (" · 필수" if f.get("required") else "")


def validate_definition(field: dict, existing_fields: list[dict] | None) -> dict[str, str]:
    """항목 정의 검사 {속성: 안내}. existing_fields 에는 고치는 항목 자신은 빼고 넣어요."""
    errs = {}
    others = existing_fields or []
    label = (field.get("label") or "").strip()
    key = (field.get("key") or "").strip()
    t = field.get("type")
    if not label:
        errs["label"] = "항목 이름을 적어 주세요."
    elif any((o.get("label") or "").strip() == label for o in others):
        errs["label"] = "같은 이름의 항목이 이미 있어요. 다른 이름을 적어 주세요."
    if not key:
        errs["key"] = "고유 키를 적어 주세요. 예) depth"
    elif not KEY_RULE.match(key):
        errs["key"] = "영문 소문자로 시작하고, 영문 소문자 · 숫자 · _ 만 쓸 수 있어요(2~30자)."
    elif key in RESERVED_KEYS:
        errs["key"] = "제목 · 내용 같은 기본 칸이 쓰는 키예요. 다른 키를 적어 주세요."
    elif any(o.get("key") == key for o in others):
        errs["key"] = "이미 쓰고 있는 고유 키예요. 다른 키를 적어 주세요."
    if t not in TYPES:
        errs["type"] = "유형을 골라 주세요."
    elif t in ("short", "long"):
        n = field.get("max_len")
        if n is not None and n < 1:
            errs["max_len"] = "1자 이상으로 정해 주세요."
    elif t in ("number", "date"):
        lo, hi = field.get("min"), field.get("max")
        if t == "date":
            bad = [a for a in ("min", "max") if field.get(a) not in (None, "") and not to_date(field.get(a))]
            if bad:
                errs[bad[0]] = "날짜를 다시 골라 주세요."
            lo, hi = to_date(lo), to_date(hi)
        else:
            bad = [a for a in ("min", "max") if field.get(a) is not None and not isinstance(field.get(a), (int, float))]
            if bad:
                errs[bad[0]] = "숫자로 적어 주세요."
        if not errs.get("min") and not errs.get("max") and lo is not None and hi is not None and lo > hi:
            errs["min"] = "최솟값이 최댓값보다 커요. 값을 바꿔 주세요." if t == "number" \
                else "시작 날짜가 끝 날짜보다 늦어요. 날짜를 바꿔 주세요."
    elif t in ("single", "multi"):
        opts = field.get("options") or []
        if not opts:
            errs["options"] = "선택지를 하나 이상 적어 주세요."
        elif len(set(opts)) != len(opts):
            errs["options"] = "같은 선택지가 두 번 있어요. 하나만 남겨 주세요."
        elif t == "single" and len(opts) < 2:
            errs["options"] = "하나만 고르는 항목은 선택지가 2개 이상 있어야 해요."
        if t == "multi" and field.get("max_select") and opts and field["max_select"] > len(opts):
            errs["max_select"] = f"선택지가 {len(opts)}개라서 그보다 많이 고를 수 없어요."
    return errs


def _ro(word: str) -> str:
    """‘○○로 / ○○으로’ (받침이 있으면 ‘으로’, ㄹ 받침은 ‘로’)."""
    ch = word[-1] if word else ""
    if "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 not in (0, 8):
        return word + "으로"
    return word + "로"


def type_change_impact(old: dict, new: dict, used: int) -> str | None:
    """유형이나 선택지를 바꿀 때 이미 쓴 글에 생길 일을 미리 알려줘요."""
    if not used:
        return None
    ot, nt = old.get("type"), new.get("type")
    if ot != nt:
        if nt in ("short", "long"):
            return (f"이 항목을 쓴 글 {used}개가 있어요. {TYPES.get(ot, ot)} → {_ro(TYPES.get(nt, nt))} 바꾸면 "
                    "기존 값은 글자로 그대로 보여요.")
        return (f"이 항목을 쓴 글 {used}개가 있어요. {TYPES.get(ot, ot)} → {_ro(TYPES.get(nt, nt))} 바꾸면 기존 값이 새 유형에 "
                "맞지 않을 수 있어요. 기존 글에는 값이 그대로 보이고, 고칠 때 다시 입력해야 해요.")
    if nt in ("single", "multi"):
        gone = [o for o in (old.get("options") or []) if o not in (new.get("options") or [])]
        if gone:
            return (f"선택지 ‘{', '.join(gone)}’를 빼면, 이미 이 값을 고른 글에는 그대로 보이지만 "
                    "새 글에서는 고를 수 없어요.")
    if nt in ("number", "date") and (old.get("min") != new.get("min") or old.get("max") != new.get("max")):
        return f"이 항목을 쓴 글 {used}개가 있어요. 범위를 바꿔도 기존 값은 그대로 보여요."
    return None


def normalize_field(d: dict) -> dict:
    """저장 모양: 유형에 맞는 조건만 남겨요 (예전 시안 데이터와 같은 모양)."""
    t = d.get("type") or "short"
    out = {"key": (d.get("key") or "").strip(), "label": (d.get("label") or "").strip(), "type": t,
           "required": bool(d.get("required")), "active": bool(d.get("active", True))}
    if (d.get("help") or "").strip():
        out["help"] = d["help"].strip()
    if t in ("short", "long"):
        out["max_len"] = int(d.get("max_len") or DEFAULT_LEN[t])
    elif t == "number":
        for a in ("min", "max"):
            v = d.get(a)
            if v not in (None, ""):
                try:
                    out[a] = num(float(v)) if not isinstance(v, bool) else v
                except (TypeError, ValueError):
                    out[a] = v  # 검사에서 ‘숫자로 적어 주세요’
    elif t == "date":
        for a in ("min", "max"):
            v = d.get(a)
            if v not in (None, ""):
                out[a] = to_date(v).isoformat() if to_date(v) else str(v)
    else:
        out["options"] = [str(o).strip() for o in (d.get("options") or []) if str(o).strip()]
        if t == "multi" and d.get("max_select"):
            out["max_select"] = int(d["max_select"])
    return out


# ---------- 입력 검사 오류 → 한국어 안내 ----------
_KO = {
    "missing": "꼭 넣어야 하는 값이에요.",
    "string_type": "글자로 적어 주세요.",
    "string_too_long": "{max_length}자까지 쓸 수 있어요. 조금 줄여 주세요.",
    "string_too_short": "{min_length}자 이상 적어 주세요.",
    "string_pattern_mismatch": "형식이 맞지 않아요. 다시 적어 주세요.",
    "int_parsing": "숫자만 넣을 수 있어요.", "int_type": "숫자만 넣을 수 있어요.", "int_from_float": "정수만 넣을 수 있어요.",
    "float_parsing": "숫자만 넣을 수 있어요.", "float_type": "숫자만 넣을 수 있어요.",
    "bool_parsing": "켬 · 끔 값만 넣을 수 있어요.", "bool_type": "켬 · 끔 값만 넣을 수 있어요.",
    "literal_error": "고를 수 있는 값이 아니에요. {expected} 중에서 골라 주세요.",
    "greater_than_equal": "{ge} 이상으로 정해 주세요.", "greater_than": "{gt}보다 크게 정해 주세요.",
    "less_than_equal": "{le} 이하로 정해 주세요.", "less_than": "{lt}보다 작게 정해 주세요.",
    "list_type": "목록으로 보내 주세요.", "dict_type": "항목 묶음으로 보내 주세요.",
    "too_long": "{max_length}개까지 넣을 수 있어요.", "too_short": "{min_length}개 이상 넣어 주세요.",
    "date_parsing": "날짜를 다시 골라 주세요.", "date_type": "날짜를 다시 골라 주세요.",
    "date_from_datetime_parsing": "날짜를 다시 골라 주세요.",
    "json_invalid": "보낸 내용을 읽지 못했어요. 다시 시도해 주세요.",
    "model_attributes_type": "보낸 내용의 모양이 맞지 않아요.",
}


def _ko_one(err: dict) -> str:
    t = err.get("type", "")
    if t in ("value_error", "assertion_error"):
        return str(err.get("msg", "")).removeprefix("Value error, ").removeprefix("Assertion failed, ")
    tpl = _KO.get(t)
    if not tpl:
        return "입력한 값을 한 번 더 확인해 주세요."
    ctx = {k: (str(v).replace("'", "") if k == "expected" else v) for k, v in (err.get("ctx") or {}).items()}
    try:
        return tpl.format(**ctx)
    except (KeyError, IndexError):
        return "입력한 값을 한 번 더 확인해 주세요."


def ko_errors(errors: list[dict], request: bool = True) -> dict[str, str]:
    """pydantic · FastAPI 오류 목록 → {칸 이름: 한국어 안내}. 칸 이름은 'title', 'perm.write' 처럼.

    request=True 면 FastAPI가 앞에 붙이는 위치(body · query …)를 떼요. 모델을 직접 검사했으면 False.
    """
    out: dict[str, str] = {}
    for err in errors:
        loc = list(err.get("loc") or [])
        if request and loc and loc[0] in ("body", "query", "path", "header"):
            loc = loc[1:]
        parts = []
        for x in loc:
            if isinstance(x, int):
                break
            parts.append(str(x))
        out.setdefault(".".join(parts) or "_", _ko_one(err))
    return out


def field_detail(errors: dict[str, str]) -> dict:
    """HTTPException(detail=...) 로 보내는 칸별 안내 모양."""
    n = len(errors)
    msg = next(iter(errors.values())) if n == 1 else f"고쳐야 할 칸이 {n}개 있어요. 칸 아래 안내를 확인해 주세요."
    return {"code": "invalid_fields", "message": msg, "errors": errors}


# ---------- 게시글 · 댓글 · 공감 · 신고 ----------
class PostText(BaseModel):
    """제목 · 내용 검사 (추가 항목과 함께 한 번에 검사해서 안내를 모두 보여줘요)."""
    title: str
    body: str

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("제목이 비어 있어요. 무엇에 대한 글인지 적어 주세요.")
        if len(v) > TITLE_MAX:
            raise ValueError(f"제목은 {TITLE_MAX}자까지 쓸 수 있어요. 지금 {len(v)}자예요. 조금 줄여 주세요.")
        return v

    @field_validator("body")
    @classmethod
    def _body(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("내용이 비어 있어요. 2,000자까지 쓸 수 있어요.")
        if len(v) > BODY_MAX:
            raise ValueError(f"내용은 2,000자까지 쓸 수 있어요. 지금 {len(v):,}자예요. 조금 줄여 주세요.")
        return v


class PostIn(BaseModel):
    """글쓰기 (U-10). 관찰 이야기는 생물 알아보기의 공유로만 올라가요."""
    board: str = Field(max_length=20, description="게시판 고유 주소")
    title: str = Field("", max_length=500, description=f"{TITLE_MAX}자까지 (서버가 검사해요)")
    body: str = Field("", max_length=20000, description="2,000자까지 (서버가 검사해요)")
    extra: dict[str, Any] = Field(default_factory=dict, description="사용자 정의 항목 값 {key: 값}")
    species: Optional[str] = Field(None, max_length=40)
    place: str = Field("", max_length=60)
    place_level: Literal["none", "region"] = "none"
    photo_id: Optional[str] = Field(None, max_length=40, description="POST /posts/photos 로 받은 사진 번호")
    photo_consent: bool = Field(False, description="사진을 사이트에서 보여줘도 괜찮다는 동의 (사진이 있으면 필수)")


class PostPatch(BaseModel):
    """글 고치기. 보낸 칸만 바꿔요. ‘사용 안 함’ 항목의 값은 그대로 남아요."""
    title: Optional[str] = Field(None, max_length=500)
    body: Optional[str] = Field(None, max_length=20000)
    extra: Optional[dict[str, Any]] = None
    photo_id: Optional[str] = Field(None, max_length=40)
    photo_consent: bool = False


class PostView(PostOut):
    """PostOut + 화면용 몇 칸 (모양은 그대로, 칸만 더해요)."""
    edited: bool = False
    author_role: str = "user"  # 운영자 글이면 '수족관 구경하기' 대신 이름만 보여요
    author_grade: str = ""


class PostCreated(BaseModel):
    id: str


class PhotoOut(BaseModel):
    id: str


class CommentView(CommentOut):
    created_at: str
    parent_id: Optional[str] = None
    deleted: bool = False


class CommentIn(BaseModel):
    body: str = Field(max_length=5000)
    parent_id: Optional[str] = Field(None, min_length=1, max_length=40, description="답글을 달 원댓글 ID. 비우면 일반 댓글")

    @field_validator("body")
    @classmethod
    def _body(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("댓글 내용이 비어 있어요. 한 글자 이상 적어 주세요.")
        if len(v) > COMMENT_MAX:
            raise ValueError(f"댓글은 {COMMENT_MAX}자까지 쓸 수 있어요. 조금 줄여 주세요.")
        return v


class LikeOut(BaseModel):
    liked: bool
    likes: int


class LikedOut(BaseModel):
    liked: bool


class ReportIn(BaseModel):
    reason: Literal["스팸", "욕설", "개인정보", "기타"]
    detail: str = Field("", max_length=100, description="‘기타’ 설명 (선택). 지금은 신고 표에 칸이 없어 저장하지 않아요")


class ReportedOut(BaseModel):
    reported: bool


# ---------- 게시판 관리 (A-02) ----------
class PermIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    list: Perm = "모두"
    read: Perm = "모두"
    write: Perm = "회원"
    comment: Perm = "회원"
    photo: Perm = "회원"


class RulesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    comments: bool = True
    likes: bool = True
    reports: bool = True
    interval: int = Field(30, ge=0, le=600, description="연속 글쓰기 간격(초). 0이면 제한 없음")


def _period(v):
    if v in (None, "", []):
        return None
    if len(v) == 1:
        raise ValueError("끝나는 날도 골라 주세요. 기간이 없으면 비워 두세요.")
    if len(v) != 2:
        raise ValueError("시작 날짜와 끝 날짜 두 개만 골라 주세요.")
    if v[0] > v[1]:
        raise ValueError("시작 날짜가 끝 날짜보다 늦어요. 날짜를 바꿔 주세요.")
    return v


class _BoardBase(BaseModel):
    @field_validator("name", check_fields=False)
    @classmethod
    def _name(cls, v):
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("게시판 이름을 적어 주세요.")
        if len(v) > 20:
            raise ValueError("게시판 이름은 20자까지 쓸 수 있어요.")
        return v

    @field_validator("desc", "manager", check_fields=False)
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("search_fields", check_fields=False)
    @classmethod
    def _search(cls, v):
        if v is not None and not v:
            raise ValueError("검색 항목을 하나 이상 골라 주세요.")
        return list(dict.fromkeys(v)) if v is not None else v

    @field_validator("period", check_fields=False)
    @classmethod
    def _per(cls, v):
        return _period(v)


class BoardIn(_BoardBase):
    """새 게시판 만들기."""
    id: str = Field(description="고유 주소 (영문 소문자 · 숫자 · -)")
    name: str
    desc: str = Field("", max_length=80)
    type: BoardType = "일반형"
    layout: Literal["card", "list"] = "list"
    status: Status = "준비 중"
    manager: str = Field("", max_length=20)
    period: Optional[list[date]] = Field(None, description="[시작, 끝] 또는 비움")
    page_size: int = Field(20, ge=5, le=50)
    sort: Literal["latest", "likes"] = "latest"
    search_fields: list[SearchField] = Field(default_factory=lambda: ["제목", "생물 이름"])
    pin_notice: bool = True
    perm: PermIn = Field(default_factory=PermIn)
    rules: RulesIn = Field(default_factory=RulesIn)

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("고유 주소를 적어 주세요. 예) tidal")
        if not SLUG_RULE.match(v):
            raise ValueError("영문 소문자로 시작하고, 영문 소문자 · 숫자 · - 만 쓸 수 있어요(2~20자).")
        return v


class BoardPatch(_BoardBase):
    """게시판 설정 고치기. 보낸 칸만 바꿔요 (고유 주소는 바꿀 수 없어요)."""
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = None
    desc: Optional[str] = Field(None, max_length=80)
    type: Optional[BoardType] = None
    layout: Optional[Literal["card", "list"]] = None
    status: Optional[Status] = None
    manager: Optional[str] = Field(None, max_length=20)
    period: Optional[list[date]] = None
    page_size: Optional[int] = Field(None, ge=5, le=50)
    sort: Optional[Literal["latest", "likes"]] = None
    search_fields: Optional[list[SearchField]] = None
    pin_notice: Optional[bool] = None
    perm: Optional[PermIn] = None
    rules: Optional[RulesIn] = None


class OrderIn(BaseModel):
    """게시판 순서 (앞에서부터) + 함께 바꿀 상태 {게시판: 상태}. 한 번에 저장돼요."""
    ids: list[str] = Field(min_length=1)
    status: dict[str, Status] = Field(default_factory=dict)


class FieldDef(BaseModel):
    """사용자 정의 항목 하나. 조건은 유형에 맞는 것만 저장돼요.

    short · long → max_len / number → min · max (숫자) / date → min · max (YYYY-MM-DD) / single · multi → options (+ multi는 max_select)
    """
    key: str = Field(max_length=30, description="영문 소문자 · 숫자 · _ (게시판 안에서 하나뿐)")
    label: str = Field(max_length=20)
    type: FieldType = "short"
    required: bool = False
    help: str = Field("", max_length=60)
    min: Optional[float | date] = None
    max: Optional[float | date] = None
    max_len: Optional[int] = Field(None, ge=1, le=2000)
    options: list[Annotated[str, Field(max_length=30)]] = Field(default_factory=list, max_length=30)
    max_select: Optional[int] = Field(None, ge=1, le=20)
    order: Optional[int] = Field(None, ge=1, description="몇 번째에 보일지 (1부터). 비우면 맨 뒤")
    active: bool = True

    def stored(self) -> dict:
        d = self.model_dump(exclude={"order"})
        for a in ("min", "max"):
            if isinstance(d[a], date):
                d[a] = d[a].isoformat()
        return normalize_field(d)


class FieldPatch(BaseModel):
    """항목 고치기 · 사용 안 함 · 순서 바꾸기. 보낸 칸만 바꿔요."""
    model_config = ConfigDict(extra="forbid")
    key: Optional[str] = Field(None, max_length=30)
    label: Optional[str] = Field(None, max_length=20)
    type: Optional[FieldType] = None
    required: Optional[bool] = None
    help: Optional[str] = Field(None, max_length=60)
    min: Optional[float | date] = None
    max: Optional[float | date] = None
    max_len: Optional[int] = Field(None, ge=1, le=2000)
    options: Optional[list[Annotated[str, Field(max_length=30)]]] = Field(None, max_length=30)
    max_select: Optional[int] = Field(None, ge=1, le=20)
    order: Optional[int] = Field(None, ge=1)
    active: Optional[bool] = None

    @model_validator(mode="after")
    def _some(self):
        if not self.model_fields_set:
            raise ValueError("바꿀 내용을 하나 이상 보내 주세요.")
        return self


class FieldSaveOut(BaseModel):
    board: BoardOut
    impact: Optional[str] = Field(None, description="유형 · 선택지를 바꿔 이미 쓴 글에 생길 일 (있을 때만)")


class BoardUsage(BaseModel):
    posts: int
    fields: dict[str, int] = {}


class AdminLogOut(BaseModel):
    when: str
    who: str
    target: str
    action: str
    before: str = "—"
    after: str = "—"


# ---------- 변경 기록용 요약 ----------
LOG_ATTRS = {"name": "이름", "desc": "설명", "type": "유형", "manager": "담당자", "period": "운영 기간",
             "status": "상태", "layout": "목록 형태", "page_size": "한 페이지 개수", "sort": "정렬",
             "search_fields": "검색 항목", "pin_notice": "공지 고정", "rules": "운영 규칙", "perm": "권한"}


def board_summary(b: dict, attr: str) -> str:
    """변경 기록에 남길 한 줄 (게시판 dict 의 값)."""
    val = b.get(attr)
    if attr == "perm":
        p = {**DEFAULT_PERM, **(val or {})}
        return " · ".join(f"{PERM_NAMES[k]} {p[k]}" for k in PERM_NAMES)
    if attr == "rules":
        r = {**DEFAULT_RULES, **(val or {})}
        on = [n for k, n in (("comments", "댓글"), ("likes", "공감"), ("reports", "신고")) if r[k]]
        return f"{'·'.join(on) or '모두 끔'} / 간격 {r['interval']}초"
    if attr == "layout":
        return LAYOUTS.get(val, val)
    if attr == "sort":
        return SORTS.get(val, val)
    if attr == "period":
        return val or "기간 없음"
    if isinstance(val, list):
        return ", ".join(val)
    if isinstance(val, bool):
        return "켬" if val else "끔"
    return str(val if val not in (None, "") else "—")
