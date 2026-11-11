"""기사별 이용 조건을 재확인한 정책브리핑 텍스트의 AI 요약."""
from __future__ import annotations

import os

from google import genai
from google.genai import types

from backend.config import get_settings


def summarize_licensed(text: str) -> str:
    settings = get_settings()
    model = os.getenv("SEA_INFO_NEWS_GEMINI_MODEL", "gemini-3.5-flash-lite")
    if not settings.gemini_on:
        raise RuntimeError("GEMINI_API_KEY가 설정되지 않았습니다.")
    with genai.Client(api_key=settings.gemini_api_key,
                      http_options=types.HttpOptions(timeout=settings.gemini_timeout_ms)) as client:
        response = client.models.generate_content(
            model=model,
            contents=("다음 해양수산 공공기관 보도자료의 텍스트만 근거로 한국어 2문장, 200자 이내로 요약하세요. "
                      "핵심 사실만 남기고 불필요한 수치·연도는 생략하세요. 수치를 쓰면 원문과 정확히 일치시켜 주세요. "
                      "추측하거나 없는 내용을 덧붙이지 말고 맞춤법을 확인하세요. "
                      "제목이나 출처 표시는 별도 화면에 있으므로 요약문만 답하세요.\n\n" + text),
            config=types.GenerateContentConfig(temperature=0.1),
        )
    summary = (response.text or "").strip()
    if not summary or len(summary) > 200:
        raise RuntimeError("AI 요약이 비었거나 200자를 넘었습니다.")
    return summary
