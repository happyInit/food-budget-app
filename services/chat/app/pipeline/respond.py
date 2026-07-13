"""⑤ 응답 조립 — 근거 태그는 Generator 산출물 그대로, 액션 버튼은 검색으로
실존이 확인된 recipe_id/item_id에서만 생성(가드레일 4층, docs/chat-assistant-ai.md §6)."""
from __future__ import annotations

from app.models import ActionButton, ChatResponse
from app.pipeline.context import AssembledContext
from app.pipeline.generator.base import GeneratedAnswer


def build_response(answer: GeneratedAnswer, ctx: AssembledContext) -> ChatResponse:
    actions: list[ActionButton] = []
    for recipe in ctx.recipes[:3]:
        recipe_id = recipe.get("recipe_id")
        if recipe_id is not None:
            actions.append(ActionButton(label=f"{recipe['name']} 레시피 보기", action="open_recipe", recipe_id=recipe_id))
    for item_id in ctx.item_ids:
        if ctx.prices.get(item_id):
            actions.append(ActionButton(label="장바구니 담기", action="add_to_cart", item_id=item_id))

    return ChatResponse(
        reply=answer.text,
        basis=answer.basis,
        actions=actions,
        unanswered=not answer.basis,
    )
