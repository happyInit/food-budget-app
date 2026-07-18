"""⑤ 응답 조립 — 근거 태그는 Generator 산출물 그대로, 액션 버튼은 검색으로
실존이 확인된 recipe_id/item_id에서만 생성(가드레일 4층, docs/chat-assistant-ai.md §6).

무응답(근거 0) + 요리 요청이면 유튜브 레시피 검색 링크를 폴백 액션으로 제공한다 —
우리 레시피 DB에 없는 음식도 최소한 영상으로 안내(외부 API 호출 0, 검색 URL만 생성).
"""
from __future__ import annotations

from urllib.parse import quote_plus

from app.models import ActionButton, ChatResponse, ExtractedQuery
from app.pipeline.context import AssembledContext
from app.pipeline.generator.base import GeneratedAnswer
from app.pipeline.text_relevance import meaningful_words

# 유튜브 폴백을 붙일 의도 — 요리/레시피를 원하는 질문만(가격·영양 무응답엔 무의미).
_YOUTUBE_INTENTS = {"recommend", "unknown"}

# 커버리지 절벽 방어(chat-assistant-ai §3-①) — 미분류 질문에 바닥 "모르겠어요" 대신 기능 안내.
#   무엇을 물어볼 수 있는지 예시로 유도 → 대화가 막다른 길 대신 다음 행동으로 이어짐.
_CAPABILITY_GUIDE = (
    "제가 잘 이해하지 못했어요 🙏 이런 걸 도와드릴 수 있어요:\n"
    "· 레시피 추천 — \"두부로 뭐 해먹지\"\n"
    "· 재료 가격 — \"양파 얼마야\"\n"
    "· 영양 정보 — \"닭가슴살 칼로리\"\n"
    "· 레시피 재료비 — \"김치찌개 재료비\""
)


def _recipe_meta(recipe: dict) -> str | None:
    """레시피 카드 메타 — 조리시간·난이도·인분·칼로리 중 있는 것만("⏱30분 이내 · 초급 · 4인분")."""
    parts: list[str] = []
    if recipe.get("cooking_time"):
        parts.append(f"⏱{recipe['cooking_time']}")
    if recipe.get("level_nm"):
        parts.append(str(recipe["level_nm"]))
    if recipe.get("serving"):
        parts.append(str(recipe["serving"]))
    if recipe.get("kcal"):
        parts.append(f"{int(recipe['kcal'])}kcal")
    return " · ".join(parts) if parts else None


def _youtube_term(query: ExtractedQuery) -> str | None:
    """유튜브 검색어 — 유저가 친 말(내용어) 우선, 없으면 표준 품목명(gazetteer 매칭).
    ('쌀국수'가 '국수'로 매칭돼도 유저 표현을 살림.) 내용어 0개(오프토픽 잔여)면
    item_names도 없을 때 None → 폴백 안 붙임(오프토픽에 유튜브 안내 방지)."""
    words = meaningful_words(query.raw_text)
    if words:
        return " ".join(words[:2])
    return query.item_names[0] if query.item_names else None


def build_response(answer: GeneratedAnswer, ctx: AssembledContext, query: ExtractedQuery) -> ChatResponse:
    unanswered = not answer.basis
    actions: list[ActionButton] = list(answer.actions)   # 티어2 외부링크(open_url) 먼저
    # 근거 있는 답에만 실존 확인된 액션(레시피·장바구니)을 붙인다 — 무응답엔 근거 없는
    # 느슨히 매칭된 레시피 버튼을 노출하지 않음(응답과 액션 일관성).
    if not unanswered:
        # 레시피 카드는 '실제 레시피를 추천한' 응답에만(근거=recipe_match) — intent 키워드("추천")
        # 유무와 무관하게 "삼겹살 레시피"도 카드 노출, 가격·영양·재료비엔 무관 카드 억제.
        if any(b.type == "recipe_match" for b in answer.basis):
            for recipe in ctx.recipes[:3]:
                recipe_id = recipe.get("recipe_id")
                if recipe_id is not None:
                    actions.append(ActionButton(
                        label=f"{recipe['name']} 레시피 보기", action="open_recipe", recipe_id=recipe_id,
                        image_url=recipe.get("image_url"), meta=_recipe_meta(recipe),
                    ))
        for item_id in ctx.item_ids:
            if ctx.prices.get(item_id):
                actions.append(ActionButton(label="장바구니 담기", action="add_to_cart", item_id=item_id))

    reply = answer.text
    if unanswered:
        # 데이터에 없는 요리 요청 → 유튜브 검색 링크(폴백). unanswered는 유지(로깅 정직성).
        term = _youtube_term(query) if query.intent in _YOUTUBE_INTENTS else None
        if term:
            url = "https://www.youtube.com/results?search_query=" + quote_plus(f"{term} 레시피")
            actions.append(ActionButton(label=f"유튜브에서 '{term}' 레시피 찾기", action="open_youtube", url=url))
            reply = f"'{term}' 레시피는 아직 저희 데이터에 없어요. 유튜브에서 영상을 찾아볼까요?"
        elif query.intent == "recommend" and not query.item_ids:
            # 모호한 추천 요청("뭐 해먹지") — 거절 대신 재료를 되묻는다(UX 견고성).
            reply = "어떤 재료로 만들까요? 냉장고에 있는 재료를 알려주시면 딱 맞는 레시피를 찾아드릴게요! 🥕"
        elif query.intent == "unknown":
            # 커버리지 절벽 방어 — 미분류(뭘 원하는지 모를) 질문에 기능 안내로 유도(막다른 길 방지).
            reply = _CAPABILITY_GUIDE

    return ChatResponse(reply=reply, basis=answer.basis, actions=actions, unanswered=unanswered)
