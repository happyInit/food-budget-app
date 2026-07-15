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
