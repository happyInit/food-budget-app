"""레시피 재료비 — 용량 × 단가(won_per_100g)로 '끼당' 비용 계산.

recipe_ingredient.quantity(비정형 텍스트)에서 **무게(g/kg)** 만 파싱해 단가와 곱한다.
개수·큰술·컵·적당량 등은 여기서 계산 못 함 → 호출측이 팩최저가로 폴백(대략 표기).
전부 read-only SELECT. 정확도는 무게 표기 재료 커버리지에 비례(정직 표기).
"""
from __future__ import annotations

import re

_G_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|g)\b", re.IGNORECASE)


def to_grams(quantity: str | None) -> float | None:
    """'500g'→500, '1kg'→1000. 무게 아니면(개·컵·T·적당량) None."""
    if not quantity:
        return None
    m = _G_RE.search(quantity)
    if not m:
        return None
    v = float(m.group(1))
    return v * 1000 if m.group(2).lower() == "kg" else v


_QTY_QUERY = """
select item_id, quantity from recipe_ingredient
where recipe_id = %(rid)s and item_id is not null and quantity is not null
"""
_UNIT_QUERY = """
select item_id, min(won_per_100g) from retail_unit_price
where item_id = any(%(ids)s) and won_per_100g is not null
group by item_id
"""


async def unit_costs(cur, recipe_id: int) -> dict[int, int]:
    """item_id → 용량×단가 비용(원). 무게 파싱 가능 + won_per_100g 있는 재료만.

    cur = **read-only** psycopg async cursor. recipe_ingredient(용량) + retail_unit_price(단가) 조회.
    """
    await cur.execute(_QTY_QUERY, {"rid": recipe_id})
    grams: dict[int, float] = {}
    for iid, q in await cur.fetchall():
        if iid not in grams:                       # 재료당 첫 용량
            g = to_grams(q)
            if g:
                grams[iid] = g
    if not grams:
        return {}
    await cur.execute(_UNIT_QUERY, {"ids": list(grams.keys())})
    out: dict[int, int] = {}
    for iid, wp100 in await cur.fetchall():
        if wp100 is not None:
            out[iid] = round(grams[iid] / 100 * float(wp100))
    return out
