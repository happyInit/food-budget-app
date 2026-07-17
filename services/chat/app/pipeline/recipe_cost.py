"""레시피 재료비 — 용량 × 단가(won_per_100g)로 '끼당' 비용 계산.

recipe_ingredient.quantity(비정형 텍스트)에서 **무게(g/kg)** 만 파싱해 단가와 곱한다.
개수·큰술·컵·적당량 등은 여기서 계산 못 함 → 호출측이 팩최저가로 폴백(대략 표기).
전부 read-only SELECT. 정확도는 무게 표기 재료 커버리지에 비례(정직 표기).
"""
from __future__ import annotations

import re

_G_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|g)\b", re.IGNORECASE)
_COUNT_RE = re.compile(r"(\d+/\d+|\d+(?:\.\d+)?)\s*([가-힣]+)")


def to_grams(quantity: str | None) -> float | None:
    """'500g'→500, '1kg'→1000. 무게 아니면(개·컵·T·적당량) None."""
    if not quantity:
        return None
    m = _G_RE.search(quantity)
    if not m:
        return None
    v = float(m.group(1))
    return v * 1000 if m.group(2).lower() == "kg" else v


def parse_count(quantity: str | None) -> tuple[float, str] | None:
    """'1개'→(1,'개'), '1/4개'→(0.25,'개'), '2봉지'→(2,'봉지'). 숫자+한글단위."""
    if not quantity:
        return None
    m = _COUNT_RE.search(quantity)
    if not m:
        return None
    num_s = m.group(1)
    num = (float(num_s.split("/")[0]) / float(num_s.split("/")[1])) if "/" in num_s else float(num_s)
    return num, m.group(2)


_QTY_QUERY = """
select item_id, quantity from recipe_ingredient
where recipe_id = %(rid)s and item_id is not null and quantity is not null
"""
_WEIGHT_QUERY = "select item_id, unit, grams from item_unit_weight where item_id = any(%(ids)s)"
_UNIT_QUERY = """
select item_id, min(won_per_100g) from retail_unit_price
where item_id = any(%(ids)s) and won_per_100g is not null
group by item_id
"""


async def unit_costs(cur, recipe_id: int) -> dict[int, int]:
    """item_id → 용량×단가 비용(원). 무게(g/kg) 직접 + 개수(개·대…)→item_unit_weight 환산.

    cur = **read-only** psycopg async cursor. recipe_ingredient·item_unit_weight·retail_unit_price 조회.
    """
    await cur.execute(_QTY_QUERY, {"rid": recipe_id})
    qty: dict[int, str] = {}
    for iid, q in await cur.fetchall():
        qty.setdefault(iid, q)                     # 재료당 첫 용량
    if not qty:
        return {}
    ids = list(qty.keys())
    # 개당 중량 맵: item_id → {unit: grams}
    await cur.execute(_WEIGHT_QUERY, {"ids": ids})
    uw: dict[int, dict[str, float]] = {}
    for iid, unit, grams in await cur.fetchall():
        uw.setdefault(iid, {})[unit] = float(grams)

    grams_by: dict[int, float] = {}
    for iid, q in qty.items():
        g = to_grams(q)                            # 1) 무게 표기
        if g is None:                              # 2) 개수 → 개당중량 환산
            pc = parse_count(q)
            if pc and iid in uw and pc[1] in uw[iid]:
                g = pc[0] * uw[iid][pc[1]]
        if g:
            grams_by[iid] = g
    if not grams_by:
        return {}
    await cur.execute(_UNIT_QUERY, {"ids": list(grams_by.keys())})
    out: dict[int, int] = {}
    for iid, wp100 in await cur.fetchall():
        if wp100 is not None:
            out[iid] = round(grams_by[iid] / 100 * float(wp100))
    return out


_BATCH_QTY_QUERY = """
select recipe_id, item_id, quantity from recipe_ingredient
where recipe_id = any(%(rids)s) and item_id is not null and quantity is not null
"""


async def batch_costs(cur, recipe_ids: list[int], names_map: dict, is_staple) -> dict[int, int]:
    """여러 레시피의 재료비를 **한 번에**(3쿼리) 추정 — 예산 필터용.
    무게·개수(→item_unit_weight) 파싱 + 단가(won_per_100g). 상비재료 제외. 단가 없는 재료는
    빠져 과소추정될 수 있음(예산 필터엔 충분). cur=read-only.
    """
    if not recipe_ids:
        return {}
    await cur.execute(_BATCH_QTY_QUERY, {"rids": recipe_ids})
    rows = await cur.fetchall()                         # (recipe_id, item_id, quantity)
    item_ids = list({iid for _, iid, _ in rows})
    if not item_ids:
        return {}
    await cur.execute(_WEIGHT_QUERY, {"ids": item_ids})
    uw: dict[int, dict[str, float]] = {}
    for iid, unit, grams in await cur.fetchall():
        uw.setdefault(iid, {})[unit] = float(grams)
    await cur.execute(_UNIT_QUERY, {"ids": item_ids})
    wp = {iid: float(w) for iid, w in await cur.fetchall() if w is not None}

    seen: set[tuple] = set()
    cost: dict[int, int] = {}
    for rid, iid, q in rows:
        if (rid, iid) in seen:
            continue
        seen.add((rid, iid))
        if is_staple(names_map.get(iid)):
            continue
        g = to_grams(q)
        if g is None:
            pc = parse_count(q)
            if pc and iid in uw and pc[1] in uw[iid]:
                g = pc[0] * uw[iid][pc[1]]
        if g and iid in wp:
            cost[rid] = cost.get(rid, 0) + round(g / 100 * wp[iid])
    return cost
