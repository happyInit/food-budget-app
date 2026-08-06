"""SQL 조회 (psycopg3 async). 컬럼명 = foodbudget 실 스키마."""
from __future__ import annotations

from typing import Any

from psycopg_pool import AsyncConnectionPool

from app.config import settings
from app.models import Ingredient, Nutrition, RecipeCard, RecipeDetail, RecipeReviews, Step
from app.vendor.quantity import is_liquid_excl, to_grams


def _num(v: Any) -> float | None:
    return None if v is None else float(v)


def _won(v: Any) -> int | None:
    return None if v is None else int(round(float(v)))


async def _load_refs(cur, ids: list[int]) -> dict:
    """quantity.to_grams 용 refs({density, uw}) — get_detail 전용 async 로더."""
    await cur.execute(
        "SELECT item_id, density_g_per_ml FROM item_master "
        "WHERE item_id = ANY(%s) AND density_g_per_ml IS NOT NULL", (ids,))
    density = {iid: float(d) for iid, d in await cur.fetchall()}
    await cur.execute(
        "SELECT item_id, unit, grams FROM item_unit_weight WHERE item_id = ANY(%s)", (ids,))
    uw = {(iid, u): float(g) for iid, u, g in await cur.fetchall()}
    return {"density": density, "uw": uw}


# ── #18 검색 (PG ILIKE + 재료 조인) ──
async def search_pg(
    pool: AsyncConnectionPool, q: str | None, tag: str | None, page: int, size: int,
    cooking_time: str | None = None, level: str | None = None,
) -> tuple[list[RecipeCard], int]:
    offset = (page - 1) * size
    qlike = f"%{q}%" if q else None
    # 만개의레시피(10K)만 서빙 — EPIS·식약처 제외 (config.serve_source)
    where = "WHERE r.source = %(serve_source)s"
    params: dict[str, Any] = {"serve_source": settings.serve_source}
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
    if cooking_time:  # 조리시간 태그 (예: '15분 이내')
        where += " AND r.cooking_time = %(cooking_time)s"
        params["cooking_time"] = cooking_time
    if level:  # 난이도 태그 (예: '아무나')
        where += " AND r.level_nm = %(level)s"
        params["level"] = level

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


# ── #18 검색 (ES nori 형태소) — search_pg 와 동일 시그니처·반환 ──
async def search_es(
    es, q: str | None, tag: str | None, page: int, size: int,
    cooking_time: str | None = None, level: str | None = None,
) -> tuple[list[RecipeCard], int]:
    """ES(nori)로 name·ingredient_names 검색. 리스트(무검색)는 recipe_id 순, 검색은 관련도순.
    인덱스엔 전건이 담기고(PGSync CDC) servable=true 만 서빙 — 리스트·검색이 같은 집합으로 통일된다.
    (배치 폴백 인덱스도 servable=true 스탬프 → 필터 동일 동작.)
    A05: 사용자 입력(q·tag·cooking_time·level)은 전부 DSL의 '값'으로만 전달 —
    query_string(ES 문법 해석) 금지 → 검색 문법 주입 불가."""
    filters: list[dict] = [{"term": {"servable": True}}]  # 항상 — non-servable/코퍼스 제외
    if tag:
        filters.append({"term": {"category": tag}})
    if cooking_time:
        filters.append({"term": {"cooking_time": cooking_time}})
    if level:
        filters.append({"term": {"level_nm": level}})
    if q:
        # cross_fields + and: 모든 검색어 토큰이 name·ingredient_names 를 합쳐 다 있어야 매칭.
        # OR는 흔한 한국어 토큰(없/말 등)이 잡음 매칭 → 무의미 검색어도 다량 결과. AND로 정밀도 확보.
        must: list[dict] = [{"multi_match": {
            "query": q, "fields": ["name^3", "ingredient_names"],
            "type": "cross_fields", "operator": "and",
        }}]
        sort: list = ["_score", {"recipe_id": "asc"}]   # 관련도 우선, 동점은 id 안정정렬
    else:
        must = [{"match_all": {}}]
        sort = [{"recipe_id": "asc"}]                    # 브라우징은 id 순(PG 동작과 동일)

    resp = await es.search(
        index=settings.es_index,
        query={"bool": {"must": must, "filter": filters}},
        sort=sort,
        from_=(page - 1) * size,
        size=size,
        track_total_hits=True,
    )
    total = resp["hits"]["total"]["value"]
    cards: list[RecipeCard] = []
    for h in resp["hits"]["hits"]:
        s = h["_source"]
        cards.append(RecipeCard(
            id=s["recipe_id"], name=s["name"], category=s.get("category"),
            cooking_time=s.get("cooking_time"), level_nm=s.get("level_nm"),
            serving=s.get("serving"), image_url=s.get("image_url"),
            source=s.get("source", settings.serve_source),
        ))
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
            # 이름 없는 행은 내보내지 않는다 — 유저 화면에 **빈 재료 줄**로 보인다.
            #
            # `ner_status='RAW'` 행은 크롤러가 쪼개지 못한 재료 덩어리를 `ingredient_raw` 에
            # 통째로 담고 `ingredient_name` 은 비워 둔다. 실측(2026-07-30): **빈 이름 1,143행이
            # 전부 RAW** 이고(CRAWLER·LABELED·NER_PARSED 는 0건) 그중 1,142개 레시피는 CRF
            # 구조화 결과(NER_PARSED)도 함께 가진다 → **레시피마다 재료 목록에 빈 줄이 하나씩** 떴다.
            #
            # 행을 지우지 않고 **조회에서 거른다** — `ingredient_raw` 원문은 재백필·감사에 필요하다.
            #
            # ⚠️ 재료비에는 영향이 없다: 빈 행은 `item_id IS NULL`(실측 0건 예외 없음)이라
            #    `item_ids` 에 들어가지 않고, 아래 루프에서도 `low_price=None` → `basis='no_price'`
            #    로 `total` 에 누적되지 않는다. 즉 `ingredient_cost_total` 은 불변이고
            #    **표시 목록에서 빈 줄만 사라진다.**
            """SELECT seq, ingredient_name, quantity, item_id, ner_status
               FROM recipe_ingredient
               WHERE recipe_id = %s AND coalesce(btrim(ingredient_name), '') <> ''
               ORDER BY seq""",
            (rid,),
        )
        ing_rows = await cur.fetchall()

        await cur.execute(
            """SELECT step_no, description, image_url
               FROM recipe_step WHERE recipe_id = %s ORDER BY step_no""",
            (rid,),
        )
        step_rows = await cur.fetchall()

        # 재료 item_id 단가(retail_item_price_compare) — 컬리·오아시스 각각 + 최저
        item_ids = [row[3] for row in ing_rows if row[3] is not None]
        # item_id → (kurly, oasis) 원/100g
        price_map: dict[int, tuple[int | None, int | None]] = {}
        # item_id → (kcal, protein, carb, fat, sodium) 100g당 (food_nutrition = 식약처)
        nutri_map: dict[int, tuple[float | None, ...]] = {}
        refs: dict = {"density": {}, "uw": {}}          # 분량→그램 환산 참조
        pack_map: dict[int, int] = {}                    # item_id → 최저 팩값(1팩 상한용)
        cat_map: dict[int, str] = {}                     # item_id → category(상비재료 제외용)
        if item_ids:
            await cur.execute(
                "SELECT item_id, category FROM item_master WHERE item_id = ANY(%s)", (item_ids,))
            cat_map = {iid: cat for iid, cat in await cur.fetchall() if cat is not None}
            await cur.execute(
                """SELECT item_id, kurly_100g, oasis_100g
                   FROM retail_item_price_compare WHERE item_id = ANY(%s)""",
                (item_ids,),
            )
            for iid, k, o in await cur.fetchall():
                price_map[iid] = (_won(k), _won(o))

            await cur.execute(
                """SELECT item_id, kcal, protein_g, carb_g, fat_g, sodium_mg
                   FROM food_nutrition WHERE item_id = ANY(%s)""",
                (item_ids,),
            )
            for iid, kc, pr, cb, ft, so in await cur.fetchall():
                nutri_map[iid] = (_num(kc), _num(pr), _num(cb), _num(ft), _num(so))

            refs = await _load_refs(cur, item_ids)
            await cur.execute(
                "SELECT item_id, min(price) FROM retail_unit_price "
                "WHERE item_id = ANY(%s) GROUP BY item_id", (item_ids,))
            pack_map = {iid: int(p) for iid, p in await cur.fetchall() if p is not None}

    ingredients = []
    total = 0
    for seq, name, qty, item_id, ner in ing_rows:
        kurly, oasis = price_map.get(item_id, (None, None)) if item_id is not None else (None, None)
        # 최저가 소스/가격 산출
        if kurly is not None and (oasis is None or kurly <= oasis):
            low_src, low_price = "kurly", kurly
        elif oasis is not None:
            low_src, low_price = "oasis", oasis
        else:
            low_src, low_price = None, None
        # 사용량 기준 비용 — 육수/물·미환산·무가격 제외, min(usage, 1팩) 상한
        u_grams = u_krw = None
        # 상비재료 제외 — 액체(간장·기름) + item_master category '양념'·'유지'(소금·설탕·마요네즈 등).
        if is_liquid_excl(name) or cat_map.get(item_id) in ("양념", "유지"):
            basis = "excluded_staple"
        elif low_price is None:
            basis = "no_price"
        else:
            g, _conf = to_grams(qty, item_id, refs) if item_id is not None else (None, None)
            if not g:
                basis = "no_convert"
            else:
                u_grams = round(g, 1)
                usage = g / 100 * low_price
                pk = pack_map.get(item_id)
                u_krw = round(min(usage, pk) if pk is not None else usage)
                basis = "capped" if (pk is not None and usage > pk) else "usage"
                total += u_krw
        kcal, prot, carb, fat, sod = (
            nutri_map.get(item_id, (None, None, None, None, None))
            if item_id is not None else (None, None, None, None, None)
        )
        ingredients.append(
            Ingredient(
                seq=seq, ingredient_name=name, quantity=qty, item_id=item_id,
                ner_status=ner, lowest_source=low_src, lowest_krw_per_100g=low_price,
                kurly_krw_per_100g=kurly, oasis_krw_per_100g=oasis,
                kcal_100g=kcal, protein_100g=prot, carb_100g=carb,
                fat_100g=fat, sodium_100g=sod,
                usage_grams=u_grams, usage_krw=u_krw, cost_basis=basis,
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
        ingredient_cost_total=total,
    )


async def get_reviews(pool: AsyncConnectionPool, rid: int) -> RecipeReviews | None:
    """레시피 후기 감정·요약. recipe_review_summary.recipe_id 는 text 라 텍스트로 비교
    (::int 캐스팅은 비숫자 행 하나가 모든 조회를 crash 시켜 제거)."""
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """SELECT review_count, positive_rate, summary, caution
               FROM recipe_review_summary WHERE recipe_id = %s""",
            (str(rid),),
        )
        r = await cur.fetchone()
        if r is None:
            return None
        # caution 은 배치가 미검출 시 문자열 'None'/'' 을 남기기도 함 → 실제 주의문만 노출.
        caution = r[3] if r[3] not in (None, "", "None", "null") else None
        return RecipeReviews(
            recipe_id=rid, review_count=r[0] or 0, positive_rate=_num(r[1]),
            summary=r[2], caution=caution,
        )
