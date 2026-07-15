"""가드레일 4층(docs/chat-assistant-ai.md §6).

입력단(check_input)은 상시 실질 구현. 출력 근거대조(check_output_grounded)는
TemplateGenerator에선 불필요(문장이 검색결과 그대로 조립)하지만 GeminiGenerator가
활성일 때는 필수 — LLM이 근거에 없는 숫자를 지어내지 않았는지 기계 대조한다.
"""
import re

from app.config import settings

_INJECTION_PATTERNS = ["ignore previous", "시스템 프롬프트", "system prompt", "너는 이제부터", "act as"]
_DIGITS = re.compile(r"\d[\d,]*")


def check_input(text: str) -> tuple[bool, str | None]:
    if len(text) > settings.max_message_len:
        return False, "메시지가 너무 길어요."
    lowered = text.lower()
    if any(p in lowered for p in _INJECTION_PATTERNS):
        return False, "요리·식비 관련 질문만 답할 수 있어요."
    return True, None


def _numbers(text: str) -> set[str]:
    """텍스트의 숫자열을 콤마 제거한 정규형으로 추출(가격 3,990 == 3990)."""
    return {m.group().replace(",", "") for m in _DIGITS.finditer(text)}


def check_output_grounded(answer_text: str, reference_text: str) -> bool:
    """LLM 다듬기 출력이 근거 밖 숫자를 지어내지 않았는지 대조.

    엄격 다듬기(refine-only) 전제 — Gemini는 template이 조립한 근거 사실만 재작성해야
    한다. 출력의 모든 숫자(가격·kcal·수량)가 근거 텍스트에 존재하면 grounded로 본다.
    근거에 없는 숫자가 하나라도 나오면 환각으로 간주 → 호출부에서 template 출력으로 fallback.
    """
    ref = _numbers(reference_text)
    return all(n in ref for n in _numbers(answer_text))


async def check_daily_cap(user_id: str | None, redis_client) -> bool:  # noqa: ARG001
    """TODO(유료 생성 백엔드 전환 시 구현): 유저별 일일 요청 상한(Redis 카운터).
    템플릿 모드는 외부 호출 비용 0이라 지금은 항상 허용."""
    return True
