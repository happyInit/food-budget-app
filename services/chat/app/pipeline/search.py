"""② 병렬 검색 — SearchSource 프로토콜 + asyncio.gather fan-out.

Pantry/User(재고·예산) 소스는 스키마·서비스가 없어 스텁으로 둔다.
`available=False`를 건너뛰는 쪽에서 처리하면 되므로, 나중에 실구현으로
교체해도 이 파일의 다른 소스·context.py·respond.py는 안 건드린다.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from app.models import ExtractedQuery


@dataclass
class SearchResult:
    source: str
    available: bool
    data: dict | None = None
    reason: str | None = None


class SearchSource(Protocol):
    name: str

    async def search(self, q: ExtractedQuery) -> SearchResult: ...


class EsRecipeSource:
    name = "recipe"

    def __init__(self, es_client):
        self._es = es_client

    async def search(self, q: ExtractedQuery) -> SearchResult:
        should: list[dict] = [{"multi_match": {"query": q.raw_text, "fields": ["name^2", "ingredient_names"]}}]
        if q.item_ids:
            should.append({"terms": {"ingredient_item_ids": [str(i) for i in q.item_ids]}})
        try:
            resp = await self._es.search(
                index="recipes",
                query={"bool": {"should": should, "minimum_should_match": 1}},
                size=5,
            )
        except Exception as exc:  # noqa: BLE001 — 검색 소스 1개 장애가 전체 응답을 막으면 안 됨
            return SearchResult(source=self.name, available=False, reason=str(exc))
        recipes = [hit["_source"] for hit in resp["hits"]["hits"]]
        return SearchResult(source=self.name, available=True, data={"recipes": recipes})


_RETAIL_PRICE_QUERY = """
select distinct on (rp.item_id, rp.source)
       rp.item_id, rp.source, rp.name, rp.storage, rp.origin,
       p.price, p.original_price, p.discount_rate, p.deal_type, p.crawled_at
from retail_product rp
join retail_price p on p.retail_product_id = rp.id
where rp.item_id = any(%(item_ids)s)
order by rp.item_id, rp.source, p.crawled_at desc
"""


class PgRetailPriceSource:
    name = "price"

    def __init__(self, pg_pool):
        self._pool = pg_pool

    async def search(self, q: ExtractedQuery) -> SearchResult:
        if not q.item_ids:
            return SearchResult(source=self.name, available=True, data={"prices": []})
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(_RETAIL_PRICE_QUERY, {"item_ids": q.item_ids})
            rows = await cur.fetchall()
        prices = [
            {
                "item_id": r[0], "source": r[1], "name": r[2], "storage": r[3], "origin": r[4],
                "price": float(r[5]) if r[5] is not None else None,
                "original_price": float(r[6]) if r[6] is not None else None,
                "discount_rate": r[7], "deal_type": r[8],
                "crawled_at": r[9].isoformat() if r[9] else None,
            }
            for r in rows
        ]
        return SearchResult(source=self.name, available=True, data={"prices": prices})


_NUTRITION_QUERY = """
select item_id, food_name, kcal, carb_g, protein_g, fat_g, sugar_g, sodium_mg
from food_nutrition
where item_id = any(%(item_ids)s)
"""


class PgNutritionSource:
    name = "nutrition"

    def __init__(self, pg_pool):
        self._pool = pg_pool

    async def search(self, q: ExtractedQuery) -> SearchResult:
        if not q.item_ids:
            return SearchResult(source=self.name, available=True, data={"nutrition": []})
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(_NUTRITION_QUERY, {"item_ids": q.item_ids})
            rows = await cur.fetchall()
        nutrition = [
            {
                "item_id": r[0], "food_name": r[1],
                "kcal": float(r[2]) if r[2] is not None else None,
                "carb_g": float(r[3]) if r[3] is not None else None,
                "protein_g": float(r[4]) if r[4] is not None else None,
                "fat_g": float(r[5]) if r[5] is not None else None,
                "sugar_g": float(r[6]) if r[6] is not None else None,
                "sodium_mg": float(r[7]) if r[7] is not None else None,
            }
            for r in rows
        ]
        return SearchResult(source=self.name, available=True, data={"nutrition": nutrition})


class StubPantryBudgetSource:
    """Pantry/User 서비스·스키마 부재 — 실구현 전까지 자리만 예약(구현계획 §2 참고)."""

    name = "pantry_budget"

    async def search(self, q: ExtractedQuery) -> SearchResult:
        return SearchResult(source=self.name, available=False, reason="not_implemented_mvp")


def build_sources(pg_pool, es_client) -> list[SearchSource]:
    return [
        EsRecipeSource(es_client),
        PgRetailPriceSource(pg_pool),
        PgNutritionSource(pg_pool),
        StubPantryBudgetSource(),
    ]


async def fan_out(sources: list[SearchSource], q: ExtractedQuery) -> list[SearchResult]:
    return list(await asyncio.gather(*(s.search(q) for s in sources)))
