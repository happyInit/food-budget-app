"""③ 검색 결과를 item_id로 조인해 Generator에 넘길 컨텍스트로 조립."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.pipeline.search import SearchResult


@dataclass
class AssembledContext:
    item_ids: list[int]
    recipes: list[dict] = field(default_factory=list)                 # ES 색인 레시피(티어1)
    pg_recipes: list[dict] = field(default_factory=list)              # PG 이름검색 레시피(티어2/3 폴백)
    prices: dict[int, list[dict]] = field(default_factory=dict)      # item_id -> 소스별 가격 목록
    nutrition: dict[int, dict] = field(default_factory=dict)          # item_id -> 영양 1행
    unavailable_sources: list[str] = field(default_factory=list)      # 스텁/장애로 빠진 소스명


def assemble(item_ids: list[int], results: list[SearchResult]) -> AssembledContext:
    by_source = {r.source: r for r in results}
    unavailable = [r.source for r in results if not r.available]

    recipe_result = by_source.get("recipe")
    recipes = recipe_result.data["recipes"] if recipe_result and recipe_result.available else []

    pg_recipe_result = by_source.get("recipe_name")
    pg_recipes = pg_recipe_result.data["recipes"] if pg_recipe_result and pg_recipe_result.available else []

    price_result = by_source.get("price")
    prices_flat = price_result.data["prices"] if price_result and price_result.available else []
    prices: dict[int, list[dict]] = {}
    for p in prices_flat:
        prices.setdefault(p["item_id"], []).append(p)

    nutrition_result = by_source.get("nutrition")
    nutrition_flat = nutrition_result.data["nutrition"] if nutrition_result and nutrition_result.available else []
    nutrition = {n["item_id"]: n for n in nutrition_flat}

    return AssembledContext(
        item_ids=item_ids,
        recipes=recipes,
        pg_recipes=pg_recipes,
        prices=prices,
        nutrition=nutrition,
        unavailable_sources=unavailable,
    )
