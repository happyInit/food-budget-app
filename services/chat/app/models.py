"""요청/응답 Pydantic 스키마. `docs/design/api-spec.md` #37 `POST /api/mealplan/assistant/chat` 대응."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    # 실 JWT 없음(Gateway/User 서비스 미존재) — 전달만, 인증 검증 안 함. 로깅/향후 확장 자리.
    user_id: str | None = None
    # 멀티턴 묶음(opt-in). 없으면 서버가 발급 → 응답에 담아 클라이언트가 다음 턴에 재전송.
    session_id: str | None = None


class BasisTag(BaseModel):
    type: Literal["price_snapshot", "nutrition", "recipe_match"]
    item_id: int | None = None
    source: str | None = None
    crawled_at: str | None = None
    detail: str | None = None


class ActionButton(BaseModel):
    label: str
    action: Literal["add_to_cart", "open_recipe", "open_youtube"]
    recipe_id: int | None = None
    item_id: int | None = None
    url: str | None = None   # open_youtube 전용 — 유튜브 레시피 검색 링크(데이터에 없는 음식 폴백)
    # 레시피 카드용(추가 필드 — 기존 계약 호환, 구 프론트는 무시). open_recipe에만 채움.
    image_url: str | None = None   # 썸네일
    meta: str | None = None        # "⏱30분 이내 · 초급 · 4인분" 등


class ChatResponse(BaseModel):
    reply: str
    basis: list[BasisTag] = Field(default_factory=list)
    actions: list[ActionButton] = Field(default_factory=list)
    unanswered: bool = False
    session_id: str | None = None    # 멀티턴 ON일 때 발급/유지된 세션 — 클라이언트가 다음 턴에 재전송


class ExtractedQuery(BaseModel):
    """① 질문 분석 산출물 — search.py/context.py/generator/*가 공유하는 표준 입력."""

    raw_text: str
    item_ids: list[int] = Field(default_factory=list)
    item_names: list[str] = Field(default_factory=list)   # item_ids와 병행 — 표준 품목명(제안 문구용)
    budget_won: int | None = None
    servings: int | None = None
    intent: Literal["recommend", "price_lookup", "nutrition", "recipe_cost", "unknown"] = "unknown"
    recipe_name: str | None = None   # recipe_cost 전용 — 재료비 계산 대상 레시피명(세션서 주입)
