"""레시피 재료비 — 용량 × 단가(won_per_100g)로 '끼당' 비용 계산.

quantity(비정형 텍스트)를 정본 컨버터(vendor.quantity)로 그램 환산 → 단가와 곱하고
**1팩 상한**(min(usage, pack))을 씌운다. 육수/물·상비는 호출측(_recipe_cost·batch)에서 제외.
전부 read-only SELECT. 환산불가·가격없음은 빠져 과소추정(정직 표기).
"""
from __future__ import annotations

from app.vendor.quantity import is_liquid_excl, to_grams   # 정본 컨버터·육수제외 — 단일 소스(챗·상세 공용)


_QTY_QUERY = """
select item_id, quantity from recipe_ingredient
where recipe_id = %(rid)s and item_id is not null and quantity is not null
"""
_WEIGHT_QUERY = "select item_id, unit, grams from item_unit_weight where item_id = any(%(ids)s)"
_UNIT_QUERY = """
select item_id, min(won_per_100g), min(price) from retail_unit_price
where item_id = any(%(ids)s) and won_per_100g is not null
group by item_id
"""
_DENSITY_QUERY = (
    "select item_id, density_g_per_ml from item_master "
    "where item_id = any(%(ids)s) and density_g_per_ml is not null"
)


async def _load_refs(cur, ids: list[int]) -> dict:
    """quantity.to_grams 용 refs({density, uw}) — quantity.load_refs(동기)의 async 대응."""
    await cur.execute(_DENSITY_QUERY, {"ids": ids})
    density = {iid: float(d) for iid, d in await cur.fetchall()}
    await cur.execute(_WEIGHT_QUERY, {"ids": ids})
    uw = {(iid, unit): float(g) for iid, unit, g in await cur.fetchall()}
    return {"density": density, "uw": uw}


async def unit_costs(cur, recipe_id: int) -> dict[int, int]:
    """item_id → 용량×단가 비용(원), 1팩 상한. 통합 컨버터(무게/부피/계량·밀도/낱개).

    cur = **read-only** psycopg async cursor. 육수/물·상비 제외는 호출측(_recipe_cost).
    """
    await cur.execute(_QTY_QUERY, {"rid": recipe_id})
    qty: dict[int, str] = {}
    for iid, q in await cur.fetchall():
        qty.setdefault(iid, q)                     # 재료당 첫 용량
    if not qty:
        return {}
    ids = list(qty.keys())
    refs = await _load_refs(cur, ids)
    grams_by: dict[int, float] = {}
    for iid, q in qty.items():
        g, _conf = to_grams(q, iid, refs)          # 무게/부피/계량(밀도)/낱개 통합
        if g:
            grams_by[iid] = g
    if not grams_by:
        return {}
    await cur.execute(_UNIT_QUERY, {"ids": list(grams_by.keys())})
    out: dict[int, int] = {}
    for iid, wp100, pack in await cur.fetchall():
        if wp100 is not None:
            usage = grams_by[iid] / 100 * float(wp100)
            out[iid] = round(min(usage, float(pack)) if pack is not None else usage)  # 1팩 상한
    return out


_BATCH_QTY_QUERY = """
select recipe_id, item_id, quantity from recipe_ingredient
where recipe_id = any(%(rids)s) and item_id is not null and quantity is not null
"""


async def batch_costs(cur, recipe_ids: list[int], names_map: dict, is_staple) -> dict[int, int]:
    """여러 레시피의 재료비를 **한 번에**(3쿼리) 추정 — 예산 필터용.
    통합 컨버터 + 1팩 상한. 상비·육수/물 제외. 단가 없는 재료는
    빠져 과소추정될 수 있음(예산 필터엔 충분). cur=read-only.
    """
    if not recipe_ids:
        return {}
    await cur.execute(_BATCH_QTY_QUERY, {"rids": recipe_ids})
    rows = await cur.fetchall()                         # (recipe_id, item_id, quantity)
    item_ids = list({iid for _, iid, _ in rows})
    if not item_ids:
        return {}
    refs = await _load_refs(cur, item_ids)
    await cur.execute(_UNIT_QUERY, {"ids": item_ids})
    wp: dict[int, tuple[float, float | None]] = {}
    for iid, w, pack in await cur.fetchall():
        if w is not None:
            wp[iid] = (float(w), float(pack) if pack is not None else None)

    seen: set[tuple] = set()
    cost: dict[int, int] = {}
    for rid, iid, q in rows:
        if (rid, iid) in seen:
            continue
        seen.add((rid, iid))
        nm = names_map.get(iid)
        if is_staple(nm) or is_liquid_excl(nm):        # 상비 + 육수/물 제외
            continue
        g, _conf = to_grams(q, iid, refs)
        if g and iid in wp:
            w100, pack = wp[iid]
            usage = g / 100 * w100
            cost[rid] = cost.get(rid, 0) + round(min(usage, pack) if pack is not None else usage)
    return cost
