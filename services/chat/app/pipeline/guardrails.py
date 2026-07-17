"""가드레일 4층(docs/chat-assistant-ai.md §6).

입력단(check_input)은 상시 실질 구현. 출력 근거대조(check_output_grounded)는
TemplateGenerator에선 불필요(문장이 검색결과 그대로 조립)하지만 GeminiGenerator가
활성일 때는 필수 — LLM이 근거에 없는 숫자를 지어내지 않았는지 기계 대조한다.
"""
import re
from datetime import datetime, timezone

from app.config import settings

# 프롬프트 인젝션 denylist(방어심층 — 1차 방어는 아키텍처: refine-only + 근거대조).
# ASCII는 lower() 후 대조, 한글은 그대로. 정상 요리/식비 질문과 겹치지 않는 지시성 구절만.
_INJECTION_PATTERNS = [
    "ignore previous", "ignore all", "ignore the above", "disregard previous", "disregard all",
    "system prompt", "developer mode", "jailbreak", "act as", "pretend you are", "pretend to be",
    "roleplay as", "you are now",
    "시스템 프롬프트", "프롬프트 무시", "규칙 무시", "지시 무시", "명령 무시", "이전 지시",
    "너는 이제부터", "지금부터 너는", "역할극",
]
_DIGITS = re.compile(r"\d[\d,]*")
# uuid4().hex(32 hex) 또는 표준 uuid(36, 하이픈 포함)만 허용 — 클라이언트 임의 문자열 차단.
_SESSION_RE = re.compile(r"\A[0-9a-fA-F]{32}\Z|\A[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z")


def check_input(text: str) -> tuple[bool, str | None]:
    if len(text) > settings.max_message_len:
        return False, "메시지가 너무 길어요."
    lowered = text.lower()
    if any(p in lowered for p in _INJECTION_PATTERNS):
        return False, "요리·식비 관련 질문만 답할 수 있어요."
    return True, None


def valid_session_id(s: str | None) -> bool:
    """서버 발급 형식(uuid4 hex/표준 uuid)만 유효 — 임의 문자열은 무시하고 새 세션 발급."""
    return bool(s and _SESSION_RE.match(s))


def _numbers(text: str) -> set[str]:
    """텍스트의 숫자열을 콤마 제거한 정규형으로 추출(가격 3,990 == 3990)."""
    return {m.group().replace(",", "") for m in _DIGITS.finditer(text)}


def _mentioned_item_ids(text: str, ingredient_index: dict[str, int]) -> set[int]:
    """텍스트에 등장하는 재료 item_id 집합 — 공백 제거 후 표면형 부분일치.

    표면형→item_id라 alias/표준형 차이를 흡수한다(삼겹살·돼지고기 = 같은 item_id).
    """
    nospace = text.replace(" ", "")
    return {iid for surface, iid in ingredient_index.items() if surface in nospace}


def check_output_grounded(
    answer_text: str, reference_text: str, ingredient_index: dict[str, int] | None = None
) -> bool:
    """LLM 다듬기 출력이 근거 밖 숫자·재료를 지어내지 않았는지 대조.

    엄격 다듬기(refine-only) 전제 — Gemini는 template이 조립한 근거 사실만 재작성해야 한다.
      · 숫자: 출력의 모든 숫자(가격·kcal·수량)가 근거에 존재해야 함.
      · 재료(ingredient_index 제공 시): 출력이 언급한 재료 item_id가 전부 근거에도 있어야 함
        — 근거에 없는 재료를 넣거나(발명) 다른 재료로 바꾸면(치환) 환각으로 간주.
        표면형→id 비교라 삼겹살↔돼지고기 같은 정당한 표기차는 통과(오탐 억제).
    하나라도 어긋나면 False → 호출부에서 template 출력으로 fallback(안전 방향).
    """
    ref_nums = _numbers(reference_text)
    if not all(n in ref_nums for n in _numbers(answer_text)):
        return False
    if ingredient_index:
        ref_ids = _mentioned_item_ids(reference_text, ingredient_index)
        out_ids = _mentioned_item_ids(answer_text, ingredient_index)
        if not out_ids <= ref_ids:
            return False
    return True


async def check_daily_cap(identity: str | None, redis_client) -> bool:
    """유저/IP별 일일 요청 상한 — 상한 내면 True, 초과면 False(호출부가 유료 생성 → template 강등).

    Redis INCR 카운터(키 `chat:rate:{identity}:{yyyymmdd}`, TTL 24h). identity 없으면 상한 미적용(True).
    Redis 장애 시 fail-open(True) — 가용성 우선(상한은 비용 방어지 서비스 차단이 아님).
    """
    if not identity:
        return True
    key = f"chat:rate:{identity}:{datetime.now(timezone.utc):%Y%m%d}"
    try:
        count = await redis_client.incr(key)
        if count == 1:
            await redis_client.expire(key, settings.rate_limit_window_s)
        return count <= settings.daily_request_cap
    except Exception:
        return True
