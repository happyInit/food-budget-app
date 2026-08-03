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
    # external_recipe = 티어2(타 서비스 링크) — recipe_match가 아니라 Gemini refine이 자동 우회(0원)
    type: Literal["price_snapshot", "nutrition", "recipe_match", "external_recipe"]
    item_id: int | None = None
    source: str | None = None
    crawled_at: str | None = None
    detail: str | None = None


class ActionButton(BaseModel):
    label: str
    action: Literal["add_to_cart", "open_recipe", "open_youtube", "navigate", "open_url"]
    recipe_id: int | None = None
    item_id: int | None = None
    url: str | None = None   # open_youtube/open_url 전용 — 외부 링크(유튜브 검색·티어2 만개 레시피)
    route: str | None = None # navigate 전용 — 인앱 라우트(예 /recipebook?compose=write)
    # 레시피 카드용(추가 필드 — 기존 계약 호환, 구 프론트는 무시). open_recipe에만 채움.
    image_url: str | None = None   # 썸네일
    meta: str | None = None        # "⏱30분 이내 · 초급 · 4인분" 등


class ChatResponse(BaseModel):
    reply: str
    basis: list[BasisTag] = Field(default_factory=list)
    actions: list[ActionButton] = Field(default_factory=list)
    unanswered: bool = False
    session_id: str | None = None    # 멀티턴 ON일 때 발급/유지된 세션 — 클라이언트가 다음 턴에 재전송
    pref_changed: bool = False       # 제외재료 등 계정 선호 영속 변경됨 — 프론트가 해당 쿼리 무효화(새로고침 없이 반영)


class ExtractedQuery(BaseModel):
    """① 질문 분석 산출물 — search.py/context.py/generator/*가 공유하는 표준 입력."""

    raw_text: str
    item_ids: list[int] = Field(default_factory=list)
    item_names: list[str] = Field(default_factory=list)   # item_ids와 병행 — 표준 품목명(제안 문구용)
    budget_won: int | None = None
    servings: int | None = None
    intent: Literal["recommend", "price_lookup", "nutrition", "recipe_cost", "unknown"] = "unknown"
    recipe_name: str | None = None   # recipe_cost 전용 — 재료비 계산 대상 레시피명(세션서 주입)
    unit_costs: dict[int, int] = Field(default_factory=dict)   # recipe_cost: item_id→용량×단가 비용(정확분)
    disliked_item_ids: list[int] = Field(default_factory=list) # 세션 개인화 — 비선호/제외 재료("돼지고기 빼고")
    exclude_recipe_ids: list[int] = Field(default_factory=list) # 이미 보여준 레시피(세션) — 추천 중복 방지
    exclude_request: bool = False   # 제외/비선호 '등록' 의도("청양고추 싫어"·"제외 재료에 등록") — 레시피 검색으로 새지 않게
    items_inherited: bool = False   # item_ids가 이번 턴 텍스트가 아니라 멀티턴 상속으로 채워졌는지(recipe-focus가 '새 재료' 판별에 사용)
