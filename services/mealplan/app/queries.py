"""SQL 조회 (psycopg3 async). **conn 을 받는다** — 트랜잭션 경계는 호출측(풀)이 제어
(checkout: 합계→지출 insert→cart 비우기 를 한 conn/한 트랜잭션으로).
풀이 `row_factory=dict_row`라 fetchone/fetchall 은 **dict**(`row["id"]`).

컬럼 = mealplan 스키마(cart_item·expense, schema-production.sql §mealplan). public 데이터 티어
(retail_item_price_compare·recipe·recipe_ingredient)는 진짜 FK가 있어 읽기 조인 허용.
★ 모든 사용자 입력은 %s 파라미터 바인딩(f-string 결합 금지 — A05). 조회/수정/삭제는
  반드시 WHERE user_id = %s 로 소유권 확인(A01).
"""
from __future__ import annotations

import logging
from datetime import date

# 🔴 `events.py` 와 같은 로거 이름을 쓴다 — 클릭스트림 두 갈래(노출·행동)가 한 이름으로 모여야
#    한쪽만 보고 "정상"이라 판단하는 일이 안 생긴다.
_log = logging.getLogger("mealplan")


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
    """#34 담기 → id. **같은 품목이면 새 행을 만들지 않고 qty 를 더한다**(#614).

    유저는 레시피를 오가며 담으므로 프론트는 "이미 장바구니에 대파가 있는지"를 모른다 →
    합산은 여기서 한다. 근거 인덱스 = `ux_cart_item_user_item`
    (schema-production.sql, `(user_id, item_id) where item_id is not null` 부분 유니크).

    합칠 때의 결정(#614):
      * **item_id is null 인 행은 합치지 않는다** — 이름만으로 동일 품목이라 단정할 수 없다.
        부분 인덱스가 null 행을 안 담으므로 충돌 자체가 안 나 그대로 insert 된다.
      * `recipe_id` = **첫 행 유지**(update 시 안 건드림). 합쳐진 행의 출처를 뒤 레시피로
        덮으면 먼저 담은 맥락이 사라진다. 다중 출처 표기는 별건.
      * `quantity` = **첫 값 유지** — '2대' 같은 표시용 문자열이라 산술로 합칠 수 없다.
        수량 증가는 정수 `qty` 만 나타낸다(합계 `_cart_subtotal` 이 단가 × qty 로 곱한다).
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """insert into mealplan.cart_item
                   (user_id, retail_product_id, recipe_id, item_id, name, qty, quantity)
               values (%s, %s, %s, %s, %s, %s, %s)
               on conflict (user_id, item_id) where item_id is not null
                 do update set qty = cart_item.qty + excluded.qty
               returning id""",
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


async def category_breakdown(conn, user_id: int, month_start: date) -> list[dict]:
    """이번 달 카테고리별 지출 합(성과보기 '식비 구성'). 각 dict: {category, amount}.
    비중·0 채우기는 라우터가 처리. A01 소유자 WHERE user_id · A05 %s 바인딩."""
    async with conn.cursor() as cur:
        await cur.execute(
            """select category, coalesce(sum(amount), 0) as amount
               from mealplan.expense
               where user_id = %s and date_trunc('month', spent_on)::date = %s
               group by category""",
            (user_id, month_start),
        )
        return await cur.fetchall()


# ── Recommend #32 (public 데이터 티어 읽기 조인) ─────────────────────────────
async def get_candidate_recipes(conn, item_ids: list[int], exclude_ids: list[int],
                                limit: int = 50) -> list[dict]:
    """보유 item_id 를 하나라도 쓰는 후보 레시피의 (재료 item_id + 재료 최저가) flat rows.
    각 dict: {recipe_id, recipe_name, item_id, ing_cost}. 랭킹은 순수함수(ranking.py)가 담당.
    exclude_ids(제외 재료)가 하나라도 든 레시피는 후보에서 제거(빈 리스트면 제외 없음)."""
    async with conn.cursor() as cur:
        await cur.execute(
            """with matched as (
                   select distinct recipe_id
                   from public.recipe_ingredient
                   where item_id = any(%s)
                     and recipe_id not in (
                         select recipe_id from public.recipe_ingredient
                         where item_id = any(%s)
                     )
                   order by recipe_id
                   limit %s
               )
               select r.id as recipe_id, r.name as recipe_name, r.image_url as image_url,
                      ri.item_id as item_id,
                      -- 상비재료(양념·유지: 소금·통깨·들기름 등)는 재료비서 제외 → ing_cost null
                      case when im.category in ('양념','유지') then null
                           else least(pc.kurly_100g, pc.oasis_100g) end as ing_cost
               from matched m
               join public.recipe r on r.id = m.recipe_id
               join public.recipe_ingredient ri on ri.recipe_id = r.id
               left join public.retail_item_price_compare pc on pc.item_id = ri.item_id
               left join public.item_master im on im.item_id = ri.item_id
               order by r.id, ri.seq""",
            (item_ids, exclude_ids, limit),
        )
        return await cur.fetchall()


# ── 클릭스트림 ADD_CART 직접 적재 (C-88 · EVENT_SINK=pg) ──────────────────────
# 왜 여기 있나: AWS 에는 Kafka 가 없다(C-44). 종전 경로(Kafka → user-event-sink → PG)의
# 종착지가 이 테이블이라, 중간을 걷어내고 앱이 직접 쓴다. 계약(dict 키)은 Kafka 경로와 동일하고
# `consume_user_event.to_params` 가 만들던 파라미터를 그대로 만든다.
#
# 🔴 같은 커넥션 + savepoint 인 이유 — `get_conn` 은 요청 전체를 한 트랜잭션으로 묶는다
#    (`context.py:214-219`). 그냥 얹으면 이벤트 INSERT 실패가 **장바구니 담기까지 롤백**시킨다.
#    savepoint 로 감싸면 이벤트만 되돌아가고 담기는 산다 — `insert_impressions` 와 같은 구조다.
# 🟢 부수 이득: 이벤트 행이 장바구니 행과 **같은 트랜잭션에서 커밋**된다(Kafka 경로보다 정합적).
_INSERT_USER_EVENT = """
insert into activity.user_event
  (event_id, user_id, session_id, event_type, recipe_id, item_id, occurred_at, context)
values (%(event_id)s, %(user_id)s, %(session_id)s, %(event_type)s,
        %(recipe_id)s, %(item_id)s, %(occurred_at)s, %(context)s)
on conflict (event_id) do nothing
"""


async def insert_user_event(conn, ev: dict) -> int:
    """클릭스트림 이벤트 1건 적재. 적재 1 / 중복·실패 0.

    best-effort: **어떤 실패도 장바구니 담기를 막지 않는다**(savepoint 롤백).
    `event_id` UNIQUE + ON CONFLICT DO NOTHING 이라 재시도·중복 호출이 무해하다.
    """
    from psycopg.types.json import Jsonb

    ctx = ev.get("context")
    params = {
        "event_id": ev["event_id"], "user_id": ev["user_id"],
        "session_id": ev.get("session_id"), "event_type": ev["event_type"],
        "recipe_id": ev.get("recipe_id"), "item_id": ev.get("item_id"),
        "occurred_at": ev["occurred_at"],
        "context": Jsonb(ctx) if ctx is not None else None,
    }
    # 🔴 여기서 예외를 삼키지 **않는다** — 삼키면 호출부가 "0행 = 중복"과 구분하지 못해
    #    권한 거부·형식 오류가 전부 `duplicate` 로 계상되고 지표가 정상처럼 보인다(비판 검토 발견).
    #    담기를 지키는 건 호출부(`events.emit_add_cart`)의 except 다 — 거기서 failure 로 센다.
    #    savepoint 는 유지 — 실패해도 바깥 트랜잭션(장바구니)은 보존된다.
    async with conn.transaction():
        async with conn.cursor() as cur:
            await cur.execute(_INSERT_USER_EVENT, params)
            return cur.rowcount or 0


# ── P1 개인화 랭킹 학습데이터: 추천 노출 로깅 (clickstream 설계 §3ⓐ, mealplan 직접 write) ──
async def insert_impressions(conn, user_id: int, session_id: str | None, ranked, budget, prefer) -> int:
    """노출한 레시피(top N)를 activity.recipe_impression에 기록 → P1 학습 피처(규칙점수 3분해).

    best-effort: 테이블 미마이그레이션·타입 등 **어떤 실패도 추천 응답을 막지 않는다**(savepoint 롤백).
    session_id는 프론트 uuid(이벤트와 조인키) — 없거나 형식오류면 서버가 발급(비링크).
    """
    import uuid
    from datetime import datetime, timezone

    from psycopg.types.json import Jsonb

    if not ranked:
        return 0
    try:
        sess = uuid.UUID(str(session_id))
    except (ValueError, TypeError, AttributeError):
        sess = uuid.uuid4()
    now = datetime.now(timezone.utc)
    ctx = Jsonb({"budget": budget, "prefer": prefer})
    rows = []
    for pos, r in enumerate(ranked, start=1):
        score_cost = min(1.0, budget / r.est_cost) if (budget and r.est_cost) else None
        rows.append((str(uuid.uuid4()), user_id, str(sess), now, r.id, pos,
                     r.score, r.coverage, float(r.expiring_used), score_cost, ctx))
    try:
        async with conn.transaction():          # savepoint — 실패해도 바깥 트랜잭션 보존
            async with conn.cursor() as cur:
                await cur.executemany(
                    """insert into activity.recipe_impression
                       (impression_id, user_id, session_id, shown_at, recipe_id, rank,
                        rule_score, score_stock, score_expiry, score_cost, request_ctx)
                       values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       on conflict (impression_id) do nothing""", rows)
        return len(rows)
    except Exception as exc:  # noqa: BLE001 — 무엇이든 best-effort(추천 무손상). 단 **조용하진 않게**
        # 🔴 **종전에는 이 자리가 완전히 침묵이었다.** 그 대가를 2026-08-16 에 치렀다 —
        #    추천은 정상으로 화면에 떴는데(느타리두루치기 등 3건) 임프레션은 0건이었고,
        #    설정·권한·스키마·프론트를 전부 뒤져도 원인을 못 찾았다. **관측 수단이 없었기 때문**이다.
        #    `events.py` 는 같은 교훈으로 이미 카운터를 달았는데(*"session_id 미전송이 3주간
        #    드러나지 않음"*) 노출 쪽에는 안 붙어 있었다.
        # 🔵 fail-open 은 그대로다 — 라벨 유실이 추천 응답을 막으면 안 된다는 원칙은 유지한다.
        #    바뀌는 것은 *"몇 건이 왜 사라졌는지"* 가 로그에 남는다는 것뿐이다.
        # 🔴 **예외 «종류»만 싣는다.** 원문에는 SQL 과 파라미터가 섞여 들어가고, 그 안에
        #    user_id·session_id 가 있다(`chat` 이 `error_type` 만 남기는 것과 같은 규약).
        _log.warning(
            "impression write failed",
            extra={
                "event": "impression_write_failed",
                "component": "clickstream",
                "error_type": type(exc).__name__,
                "record_count": len(rows),
                "result": "failure",
                "retryable": False,
            },
        )
        return 0
