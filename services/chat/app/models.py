"""요청/응답 Pydantic 스키마. `docs/design/api-spec.md` #37 `POST /api/mealplan/assistant/chat` 대응."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    # 실 JWT 없음(Gateway/User 서비스 미존재) — 전달만, 인증 검증 안 함. 로깅/향후 확장 자리.
    user_id: str | None = None


class BasisTag(BaseModel):
    type: Literal["price_snapshot", "nutrition", "recipe_match"]
    item_id: int | None = None
    source: str | None = None
    crawled_at: str | None = None
    detail: str | None = None


class ActionButton(BaseModel):
    label: str
    action: Literal["add_to_cart", "open_recipe"]
    recipe_id: int | None = None
    item_id: int | None = None


class ChatResponse(BaseModel):
    reply: str
    basis: list[BasisTag] = Field(default_factory=list)
    actions: list[ActionButton] = Field(default_factory=list)
    unanswered: bool = False


class ExtractedQuery(BaseModel):
    """① 질문 분석 산출물 — search.py/context.py/generator/*가 공유하는 표준 입력."""

    raw_text: str
    item_ids: list[int] = Field(default_factory=list)
    budget_won: int | None = None
    servings: int | None = None
    intent: Literal["recommend", "price_lookup", "nutrition", "unknown"] = "unknown"
