"""recipe-in-focus — 직전 추천/선택 레시피의 상세질문·선택 처리(대화 일관성).

밥풀이가 매 턴 독립 검색만 하던 문제 보완: 유저가 추천 목록에서 하나를 고르거나
("제일 빠른거/첫번째/그걸로 할게") 그 요리의 상세를 물으면("그거 재료/몇 분/몇 칼로리"),
새로 검색하지 않고 **세션에 저장된 레시피(ES 문서 필드)로 답한다**. 멀티턴 세션에 직전 추천이
있을 때만 동작하고, 대상을 특정 못 하면 조용히 통과(일반 흐름).
"""
from __future__ import annotations

import re

from app.models import ActionButton, ChatResponse

# 재료 질문 — "재료비/재료 값"(가격)과 겹치지 않게 구체 구절만(bare "재료" 금지).
_ING_KWS = ("뭐 들어", "뭐가 들어", "뭐 필요", "무슨 재료", "재료 뭐", "재료가 뭐",
            "재료는 뭐", "재료 알려", "재료뭐", "재료가뭐", "뭐뭐 들어")
_TIME_KWS = ("몇 분", "몇분", "얼마나 걸", "조리시간", "조리 시간", "시간 얼마", "오래 걸", "얼마나 오래")
_CAL_KWS = ("칼로리", "kcal", "열량")
# 속도 선택 — "간단한"은 추천 수식어("간단한 거로 해줘")라 제외, 속도어만.
_FASTEST = ("제일 빠", "가장 빠", "빨리 되", "빠른 거", "빠른거", "빠른것")
_ORDINALS = (("첫", 0), ("처음", 0), ("두 번", 1), ("두번", 1), ("세 번", 2), ("세번", 2), ("마지막", -1))
_SELECT = ("할게", "할래", "먹을래", "이걸로", "그걸로", "그거로", "이거로", "그걸루", "그거루", "정할", "만들래", "골랐", "그걸 로")
# 초점 레시피 지시어 — 상세질문이 '직전 요리'를 가리킬 때만 발동(추천·장보기 하이재킹 방지).
_DISH_REF = ("그거", "그걸", "이거", "이걸", "그 요리", "이 요리", "저거", "그것", "이것", "방금", "아까",
             "그 메뉴", "다 만들면", "만들면", "완성", "다 하면", "다하면", "그 레시피", "이 레시피")
_REF = _DISH_REF
# 선택·상세를 무효화하는 부정/전환 — "첫번째는 별로", "제일 빠른거 말고"
_NEGATE = ("별로", "말고", "싫", "아니", "다른", "빼고", "말구")


def detail_kind(msg: str) -> str | None:
    if any(k in msg for k in _ING_KWS):
        return "ingredients"
    if any(k in msg for k in _TIME_KWS):
        return "time"
    if any(k in msg for k in _CAL_KWS):
        return "calories"
    return None


def _minutes(ct) -> int:
    m = re.search(r"(\d+)", str(ct or ""))
    return int(m.group(1)) if m else 9999


def wants_focus(msg: str) -> bool:
    """이 발화가 초점 레시피 관련인지 — 선택(빠른거/서수/그걸로 할게) 또는 상세질문.
    오발동 방지: 부정/전환어("별로/말고")면 선택 아님. 상세질문(재료/시간/칼로리)은 **직전 요리
    지시어(그거/다 만들면…)가 있을 때만**(그거 칼로리 O, "칼로리 낮은거 추천" X). ※ 지시어 자체가
    '직전 요리' 신호라 재료 유무(멀티턴 상속으로 오염됨)는 보지 않는다 — '계란 칼로리'는 지시어가
    없어 자동 제외."""
    if any(n in msg for n in _NEGATE):
        return False
    if any(k in msg for k in _FASTEST):
        return True
    if any(k in msg for k, _ in _ORDINALS):
        return True
    if any(k in msg for k in _SELECT) and any(k in msg for k in _DISH_REF):
        return True
    if detail_kind(msg) is not None and any(r in msg for r in _DISH_REF):
        return True
    return False


def resolve(msg: str, shown: list[dict], focus: dict | None) -> dict | None:
    """메시지 + 세션(직전 추천 목록·초점)에서 대상 레시피 1건 특정. 못 정하면 None."""
    if shown:
        if any(k in msg for k in _FASTEST):
            return min(shown, key=lambda r: _minutes(r.get("cooking_time")))
        for key, idx in _ORDINALS:
            if key in msg:
                return shown[idx] if -len(shown) <= idx < len(shown) else shown[0]
    if focus:
        return focus
    return shown[0] if shown else None


def build(msg: str, recipe: dict, session_id: str | None) -> ChatResponse:
    """초점 레시피 응답 — 상세질문이면 해당 필드로, 선택뿐이면 확인 + 다음 안내."""
    name = recipe.get("name") or "이 요리"
    rid = recipe.get("recipe_id")
    card = [ActionButton(label=f"{name} 레시피 보기", action="open_recipe", recipe_id=rid)] if rid else []
    kind = detail_kind(msg)
    if kind == "ingredients":
        ings = [n for n in (recipe.get("ingredient_names") or []) if n]
        if ings:
            reply = (f"'{name}'에는 {', '.join(ings[:12])} 가 들어가요! "
                     f"소금·간장 같은 기본 양념은 대부분 집에 있으니 부담 없어요 🙂")
        else:
            reply = f"'{name}'의 재료를 자세히는 못 찾았어요. 아래에서 레시피를 확인해 보세요!"
        return ChatResponse(reply=reply, actions=card, session_id=session_id)
    if kind == "time":
        ct = recipe.get("cooking_time")
        reply = (f"'{name}'은 {ct}면 만들 수 있어요!" if ct
                 else f"'{name}'의 조리시간은 표기가 없어요. 아래에서 확인해 보세요!")
        return ChatResponse(reply=reply, actions=card, session_id=session_id)
    if kind == "calories":
        kcal = recipe.get("kcal")
        reply = (f"'{name}'은 약 {int(kcal)}kcal예요." if kcal is not None
                 else f"'{name}'의 칼로리는 레시피에 표기가 없어요 🥲")
        return ChatResponse(reply=reply, actions=card, session_id=session_id)
    # 선택만("제일 빠른거/첫번째/그걸로 할게") — 확인 + 다음 안내
    extra = f" ({recipe['cooking_time']})" if recipe.get("cooking_time") else ""
    reply = f"좋아요, '{name}'{extra}으로 골라볼게요! 재료·조리시간·재료비가 궁금하면 물어보세요 🙂"
    return ChatResponse(reply=reply, actions=card, session_id=session_id)
