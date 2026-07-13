"""가드레일 4층(docs/chat-assistant-ai.md §6) — 이번 MVP는 입력단만 실질 구현.

출력 대조·비용 상한은 TemplateGenerator가 외부 호출 비용 0이라 지금 당장은
강제하지 않는다(템플릿 모드에서 3층은 구조적으로 불필요 — 문장 전체가 검색
결과 그대로 조립). 유료 생성 백엔드로 전환되는 시점에 채울 자리로 함수만 예약.
"""
from app.config import settings

_INJECTION_PATTERNS = ["ignore previous", "시스템 프롬프트", "system prompt", "너는 이제부터", "act as"]


def check_input(text: str) -> tuple[bool, str | None]:
    if len(text) > settings.max_message_len:
        return False, "메시지가 너무 길어요."
    lowered = text.lower()
    if any(p in lowered for p in _INJECTION_PATTERNS):
        return False, "요리·식비 관련 질문만 답할 수 있어요."
    return True, None


def check_output_grounded(answer_text: str, ctx) -> bool:  # noqa: ARG001
    """TODO(유료 생성 백엔드 전환 시 구현): 응답 내 숫자·품목코드를 검색 결과와 기계 대조.
    템플릿 모드는 항상 True(문장이 검색 결과 그대로 조립되어 환각 불가)."""
    return True


async def check_daily_cap(user_id: str | None, redis_client) -> bool:  # noqa: ARG001
    """TODO(유료 생성 백엔드 전환 시 구현): 유저별 일일 요청 상한(Redis 카운터).
    템플릿 모드는 외부 호출 비용 0이라 지금은 항상 허용."""
    return True
