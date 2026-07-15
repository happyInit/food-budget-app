"""SQL 조회 (psycopg3 async). **conn 을 받는다** — 트랜잭션 경계는 호출측(풀)이 제어
(checkout: 합계→지출 insert→cart 비우기 를 한 conn/한 트랜잭션으로).
풀이 `row_factory=dict_row`라 fetchone/fetchall 은 **dict**(`row["id"]`).

컬럼 = mealplan 스키마(cart_item·expense, schema-production.sql §mealplan). public 데이터 티어
(retail_item_price_compare·recipe·recipe_ingredient)는 진짜 FK가 있어 읽기 조인 허용.
★ 모든 사용자 입력은 %s 파라미터 바인딩(f-string 결합 금지 — A05). 조회/수정/삭제는
  반드시 WHERE user_id = %s 로 소유권 확인(A01).
"""
from __future__ import annotations

from datetime import date


# ── Cart #33·#36 ───────────────────────────────────────────────────────────
async def get_cart(conn, user_id: int) -> list[dict]:
    """장바구니 + 품목별 더 싼 소스가(least(kurly_100g, oasis_100g)) LEFT JOIN.
    각 dict: {id, name, qty, quantity, item_id, lowest_krw_per_100g, source}."""
    async with conn.cursor() as cur:
        await cur.execute(
            """select c.id, c.name, c.qty, c.quantity, c.item_id,
                      least(pc.kurly_100g, pc.oasis_100g) as lowest_krw_per_100g,
                      case
                        when pc.kurly_100g is null and pc.oasis_100g is null then null
                        when pc.oasis_100g is null then 'kurly'
                        when pc.kurly_100g is null then 'oasis'
                        when pc.kurly_100g <= pc.oasis_100g then 'kurly'
                        else 'oasis'
                      end as source
               from mealplan.cart_item c
               left join public.retail_item_price_compare pc on pc.item_id = c.item_id
               where c.user_id = %s
               order by c.added_at, c.id""",
            (user_id,),
        )
        return await cur.fetchall()


async def insert_cart_item(conn, user_id: int, name: str, recipe_id: int | None,
                           item_id: int | None, retail_product_id: int | None,
                           qty: int, quantity: str | None) -> int:
    """#34 담기 → id."""
    async with conn.cursor() as cur:
        await cur.execute(
            """insert into mealplan.cart_item
                   (user_id, retail_product_id, recipe_id, item_id, name, qty, quantity)
               values (%s, %s, %s, %s, %s, %s, %s) returning id""",
            (user_id, retail_product_id, recipe_id, item_id, name, qty, quantity),
        )
        return (await cur.fetchone())["id"]


async def delete_cart_item(conn, user_id: int, item_row_id: int):
    """#35 제거 — 소유권(WHERE id AND user_id). 남의 행이면 아무 행도 안 지워져 None → 404."""
    async with conn.cursor() as cur:
        await cur.execute(
            "delete from mealplan.cart_item where id = %s and user_id = %s returning id",
            (item_row_id, user_id),
        )
        return await cur.fetchone()


async def insert_cart_expense(conn, user_id: int, amount: int) -> int:
    """#36 체크아웃 — cart 합계를 GROCERY/CART 지출로 기록 → expense id."""
    async with conn.cursor() as cur:
        await cur.execute(
            """insert into mealplan.expense (user_id, amount, category, spent_on, source)
               values (%s, %s, 'GROCERY', current_date, 'CART') returning id""",
            (user_id, amount),
        )
        return (await cur.fetchone())["id"]


async def clear_cart(conn, user_id: int) -> None:
    """#36 체크아웃 후 장바구니 비우기(소유권 WHERE user_id)."""
    async with conn.cursor() as cur:
        await cur.execute(
            "delete from mealplan.cart_item where user_id = %s", (user_id,)
        )


# ── Expense #38·#39·#40 ─────────────────────────────────────────────────────
async def insert_expense(conn, user_id: int, amount: int, category: str,
                         spent_on: date, memo: str | None, source: str) -> int:
    """#39 지출 기록 → id."""
    async with conn.cursor() as cur:
        await cur.execute(
            """insert into mealplan.expense (user_id, amount, category, spent_on, memo, source)
               values (%s, %s, %s, %s, %s, %s) returning id""",
            (user_id, amount, category, spent_on, memo, source),
        )
        return (await cur.fetchone())["id"]


async def calendar_by_day(conn, user_id: int, month_start: date) -> list[dict]:
    """#38 월별 캘린더 — 일자별 지출 합. month_start=해당 월 1일(date로 바인딩)."""
    async with conn.cursor() as cur:
        await cur.execute(
            """select spent_on, sum(amount) as amount
               from mealplan.expense
               where user_id = %s and date_trunc('month', spent_on)::date = %s
               group by spent_on
               order by spent_on""",
            (user_id, month_start),
        )
        return await cur.fetchall()


async def month_spent(conn, user_id: int, month_start: date) -> int:
    """#40 이번 달 지출 합(실구현). 지출 없으면 0."""
    async with conn.cursor() as cur:
        await cur.execute(
            """select coalesce(sum(amount), 0) as spent
               from mealplan.expense
               where user_id = %s and date_trunc('month', spent_on)::date = %s""",
            (user_id, month_start),
        )
        return int((await cur.fetchone())["spent"])


# ── Recommend #32 (public 데이터 티어 읽기 조인) ─────────────────────────────
async def get_candidate_recipes(conn, item_ids: list[int], limit: int = 50) -> list[dict]:
    """보유 item_id 를 하나라도 쓰는 후보 레시피의 (재료 item_id + 재료 최저가) flat rows.
    각 dict: {recipe_id, recipe_name, item_id, ing_cost}. 랭킹은 순수함수(ranking.py)가 담당."""
    async with conn.cursor() as cur:
        await cur.execute(
            """with matched as (
                   select distinct recipe_id
                   from public.recipe_ingredient
                   where item_id = any(%s)
                   order by recipe_id
                   limit %s
               )
               select r.id as recipe_id, r.name as recipe_name,
                      ri.item_id as item_id,
                      least(pc.kurly_100g, pc.oasis_100g) as ing_cost
               from matched m
               join public.recipe r on r.id = m.recipe_id
               join public.recipe_ingredient ri on ri.recipe_id = r.id
               left join public.retail_item_price_compare pc on pc.item_id = ri.item_id
               order by r.id, ri.seq""",
            (item_ids, limit),
        )
        return await cur.fetchall()
