"""응답 스키마. docs/design/api-spec.md #18·#19 대응 (데이터 티어 실 컬럼 기준)."""
from __future__ import annotations

from pydantic import BaseModel


class RecipeCard(BaseModel):
    id: int
    name: str
    category: str | None = None
    cooking_time: str | None = None
    level_nm: str | None = None
    serving: str | None = None
    image_url: str | None = None
    source: str


class RecipeListResponse(BaseModel):
    recipes: list[RecipeCard]
    page: int
    size: int
    total: int


class Nutrition(BaseModel):
    kcal: float | None = None
    carb_g: float | None = None
    protein_g: float | None = None
    fat_g: float | None = None
    sodium_mg: float | None = None


class Ingredient(BaseModel):
    seq: int | None = None
    ingredient_name: str | None = None
    quantity: str | None = None
    item_id: int | None = None
    ner_status: str
    # 재료 최저 단가(retail_item_price_compare 조인, 원/100g) — 미매칭이면 null
    lowest_source: str | None = None
    lowest_krw_per_100g: int | None = None
    # 담기 모달 가격비교용 — 컬리·오아시스 각각 (원/100g). 없으면 null
    kurly_krw_per_100g: int | None = None
    oasis_krw_per_100g: int | None = None
    # 재료 100g당 영양 (food_nutrition 조인, item_id 매칭). 미매칭이면 null
    # ⚠️ 100g 기준값 — 레시피 사용량 환산 아님(수량이 '약간·1큰술' 자유텍스트라 합산 불가)
    kcal_100g: float | None = None
    protein_100g: float | None = None
    carb_100g: float | None = None
    fat_100g: float | None = None
    sodium_100g: float | None = None
    # 레시피 사용량 기준 비용 (분량 환산 × 최저100g가, min(usage, 1팩) 상한) — 2026-07
    usage_grams: float | None = None      # 분량→그램 (환산 불가면 null)
    usage_krw: int | None = None          # 이 재료 몫 비용 (제외/미환산/무가격이면 null)
    cost_basis: str | None = None         # usage | capped | excluded_liquid | no_convert | no_price


class Step(BaseModel):
    step_no: int
    description: str | None = None
    image_url: str | None = None


class RecipeDetail(BaseModel):
    id: int
    source: str
    name: str
    category: str | None = None
    cook_method: str | None = None
    cooking_time: str | None = None
    level_nm: str | None = None
    serving: str | None = None
    image_url: str | None = None
    nutrition: Nutrition
    ingredients: list[Ingredient]
    steps: list[Step]
    ingredient_cost_total: int = 0        # usage_krw 합 (제외·미환산 제외; 과소추정=커버리지 한계)


class RecipeReviews(BaseModel):
    """요리후기 감정·요약 (recipe_review_summary). #10 — 감정=nova-micro, 요약=claude-3.5-sonnet."""
    recipe_id: int
    review_count: int                     # 요약 근거 후기 수
    positive_rate: float | None = None    # 긍정 비율(%) — 감정분류 집계
    summary: str | None = None            # LLM 요약(존댓말)
    caution: str | None = None            # 주의 문구(있을 때만 — 위생·과장광고 등)
