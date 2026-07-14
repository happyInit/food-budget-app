"""SQL 조회 (psycopg3 async). 컬럼명 = foodbudget 실 스키마."""
from __future__ import annotations

from typing import Any

from psycopg_pool import AsyncConnectionPool

from app.models import Ingredient, Nutrition, RecipeCard, RecipeDetail, Step


def _num(v: Any) -> float | None:
    return None if v is None else float(v)


def _won(v: Any) -> int | None:
    return None if v is None else int(round(float(v)))


# ── #18 검색 (PG ILIKE + 재료 조인) ──
async def search_pg(
    pool: AsyncConnectionPool, q: str | None, tag: str | None, page: int, size: int
) -> tuple[list[RecipeCard], int]:
    offset = (page - 1) * size
    qlike = f"%{q}%" if q else None
    where = "WHERE TRUE"
    params: dict[str, Any] = {}
    if q:
        where += (
            " AND (r.name ILIKE %(qlike)s OR EXISTS ("
            " SELECT 1 FROM recipe_ingredient ri WHERE ri.recipe_id = r.id"
            " AND ri.ingredient_name ILIKE %(qlike)s))"
        )
        params["qlike"] = qlike
    if tag:
        where += " AND r.category = %(tag)s"
        params["tag"] = tag

    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(f"SELECT count(*) FROM recipe r {where}", params)
        total = (await cur.fetchone())[0]
        await cur.execute(
            f"""SELECT r.id, r.name, r.category, r.cooking_time, r.level_nm,
                       r.serving, r.image_url, r.source
                FROM recipe r {where}
                ORDER BY r.id
                LIMIT %(size)s OFFSET %(offset)s""",
            {**params, "size": size, "offset": offset},
        )
        rows = await cur.fetchall()

    cards = [
        RecipeCard(
            id=r[0], name=r[1], category=r[2], cooking_time=r[3], level_nm=r[4],
            serving=r[5], image_url=r[6], source=r[7],
        )
        for r in rows
    ]
    return cards, total


# ── #19 상세 (recipe + ingredient + step + nutrition + 재료 최저단가) ──
async def get_detail(pool: AsyncConnectionPool, rid: int) -> RecipeDetail | None:
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """SELECT id, source, name, category, cook_method, cooking_time, level_nm,
                      serving, image_url, kcal, carb_g, protein_g, fat_g, sodium_mg
               FROM recipe WHERE id = %s""",
            (rid,),
        )
        r = await cur.fetchone()
        if r is None:
            return None

        await cur.execute(
            """SELECT seq, ingredient_name, quantity, item_id, ner_status
               FROM recipe_ingredient WHERE recipe_id = %s ORDER BY seq""",
            (rid,),
        )
        ing_rows = await cur.fetchall()

        await cur.execute(
            """SELECT step_no, description, image_url
               FROM recipe_step WHERE recipe_id = %s ORDER BY step_no""",
            (rid,),
        )
        step_rows = await cur.fetchall()

        # 재료 item_id 최저 단가(retail_item_price_compare)
        item_ids = [row[3] for row in ing_rows if row[3] is not None]
        price_map: dict[int, tuple[str, int]] = {}
        if item_ids:
            await cur.execute(
                """SELECT item_id, kurly_100g, oasis_100g
                   FROM retail_item_price_compare WHERE item_id = ANY(%s)""",
                (item_ids,),
            )
            for iid, k, o in await cur.fetchall():
                k, o = _won(k), _won(o)
                if k is None and o is None:
                    continue
                if k is not None and (o is None or k <= o):
                    price_map[iid] = ("kurly", k)
                else:
                    price_map[iid] = ("oasis", o)

    ingredients = []
    for seq, name, qty, item_id, ner in ing_rows:
        src, price = price_map.get(item_id, (None, None)) if item_id is not None else (None, None)
        ingredients.append(
            Ingredient(
                seq=seq, ingredient_name=name, quantity=qty, item_id=item_id,
                ner_status=ner, lowest_source=src, lowest_krw_per_100g=price,
            )
        )

    return RecipeDetail(
        id=r[0], source=r[1], name=r[2], category=r[3], cook_method=r[4],
        cooking_time=r[5], level_nm=r[6], serving=r[7], image_url=r[8],
        nutrition=Nutrition(
            kcal=_num(r[9]), carb_g=_num(r[10]), protein_g=_num(r[11]),
            fat_g=_num(r[12]), sodium_mg=_num(r[13]),
        ),
        ingredients=ingredients,
        steps=[Step(step_no=s[0], description=s[1], image_url=s[2]) for s in step_rows],
    )
