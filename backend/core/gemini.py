"""Gemini 연동 (편성훈). 키는 환경변수 GEMINI_API_KEY 에서만 읽어요."""
from __future__ import annotations

import hashlib
import io
import json
from typing import Literal

from pydantic import BaseModel, Field

from backend.config import get_settings


class NotSeaCreature(Exception):
    """사진에서 바다 생물을 찾지 못했어요."""


class _Safety(BaseModel):
    level: Literal["safe", "caution", "danger"]
    reason: str = Field(description="해요체 한 문장. 예: 집게에 물릴 수 있어요")


class _Info(BaseModel):
    habitat: str
    food: str
    fun_fact: str


class GeminiAnswer(BaseModel):
    is_sea_creature: bool = Field(description="사진에 바다 생물이 보이면 true")
    name: str = Field(description="한국어 이름(국명). 모르면 '미확인 생물'")
    emoji: str = Field(description="생물과 가장 비슷한 이모지 1개")
    confidence: Literal["high", "medium", "low"]
    safety: _Safety
    protected: bool = Field(description="한국 해양보호생물로 지정된 것이 확실할 때만 true")
    summary: str = Field(description="초등학생도 이해하는 해요체 한 문장 소개")
    info: _Info
    candidates: list[str] = Field(description="헷갈릴 수 있는 다른 후보 이름 0~3개")


SYSTEM = (
    "너는 한국 바닷가(갯벌, 바위 해변, 해수욕장)에서 찍은 사진 속 해양 생물을 알려주는 다정한 해설사야. "
    "부모와 초등학생이 읽으니 모든 문장은 짧은 해요체로 써. "
    "확실하지 않으면 confidence를 low로 하고 candidates에 후보를 넣어. 지어내지 마. "
    "안전 정보는 모르면 caution으로 하고 '만지지 말고 눈으로만 봐 주세요'처럼 조심하는 쪽으로 써. "
    "사진에 바다 생물이 없으면 is_sea_creature를 false로 해."
)


def shrink(image_bytes: bytes, max_side: int = 1280) -> bytes:
    from PIL import Image

    im = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    im.thumbnail((max_side, max_side))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=85)
    return out.getvalue()


def _client():
    from google import genai
    from google.genai import types

    s = get_settings()
    return genai.Client(api_key=s.gemini_api_key, http_options=types.HttpOptions(timeout=s.gemini_timeout_ms))


def analyze(image_bytes: bytes) -> dict:
    """사진 → GeminiAnswer(dict). 바다 생물이 없으면 NotSeaCreature."""
    from google.genai import types

    resp = _client().models.generate_content(
        model=get_settings().gemini_model,
        contents=[types.Part.from_bytes(data=shrink(image_bytes), mime_type="image/jpeg"),
                  "이 사진 속 바다 생물이 무엇인지 알려 주세요."],
        config=types.GenerateContentConfig(system_instruction=SYSTEM, temperature=0.2,
                                           response_mime_type="application/json", response_schema=GeminiAnswer),
    )
    ans = resp.parsed if isinstance(resp.parsed, GeminiAnswer) else GeminiAnswer.model_validate(json.loads(resp.text))
    if not ans.is_sea_creature:
        raise NotSeaCreature()
    return ans.model_dump()


def summarize(text: str) -> str:
    """바다 소식 요약. 키가 없거나 실패하면 앞부분을 잘라 써요."""
    if get_settings().gemini_on and len(text) > 120:
        try:
            resp = _client().models.generate_content(
                model=get_settings().gemini_model,
                contents="다음 해양 소식을 초등학생 부모가 읽기 쉽게 해요체 2~3문장으로 요약해 주세요. "
                         f"없는 내용은 쓰지 마세요.\n\n{text}")
            return resp.text.strip()
        except Exception:
            pass
    return text[:120] + ("…" if len(text) > 120 else "")


def new_species_id(name: str) -> str:
    return "ai_" + hashlib.md5(name.encode()).hexdigest()[:8]
