"""생물 이름 검색 화면의 FastAPI 호출 창구. 외부 키·업무 처리는 서버에 둔다."""
from services import api

# [BARO-SCOPE-EXTENSION] 별도 검색 기능을 위해 사용자가 추가 승인한 신규 파일.
# [BARO-CHANGE-035] 화면과 외부 공급자 사이에 기존 FastAPI 서비스 계층을 유지한다.
SOURCES = {"mbris": "국립해양생물자원관", "worms": "WoRMS"}


# [BARO-CHANGE-043] 새 API가 반영되지 않은 서버의 기본 404를 종 검색 결과 없음과 구별한다.
# 종 상세의 업무상 404는 보존하며, UI에서 직접 외부 API를 호출하는 우회는 하지 않는다.
def _get(path: str, **kwargs) -> dict:
    try:
        return api.get(path, **kwargs)
    except api.ApiError as exc:
        if exc.status == 404 and exc.message.strip().casefold() == "not found":
            raise api.ApiError(503, "생물 검색 기능이 서버에 아직 반영되지 않았어요. 서버 갱신 후 다시 시도해 주세요.",
                               "species_search_not_registered") from None
        raise


def search(query: str, page: int = 1) -> dict:
    return _get("/species-search", params={"q": query, "page": page})


def detail(provider: str, record_id: str) -> dict:
    if provider not in SOURCES or not record_id.isascii() or not record_id.isdigit():
        raise api.ApiError(422, "검색 결과에서 생물을 다시 선택해 주세요.")
    return _get(f"/species-search/{provider}/{record_id}")
