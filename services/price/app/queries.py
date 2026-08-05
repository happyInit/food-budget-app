"""SQL 조회 (psycopg3 async). 컬럼명 = foodbudget 실 스키마."""
from __future__ import annotations

from typing import Any

from psycopg_pool import AsyncConnectionPool

from app.models import (
    Baseline,
    CurrentPrice,
    HistoryPoint,
    HotdealItem,
    ItemSearchItem,
    PriceHistory,
    RecommendItem,
    SourcePrice,
    TrendItem,
    TrendResponse,
    WatchItem,
)


def _won(v: Any) -> int | None:
    return None if v is None else int(round(float(v)))


# ── 품목 이름 검색 (제외 재료 선택) — 사용자 입력은 %s 파라미터 바인딩(A05) ──
async def search_items(pool: AsyncConnectionPool, q: str, limit: int) -> list[ItemSearchItem]:
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            # 별칭(item_alias)도 검색 — '삼겹살'(돼지고기 별칭) 등 흔한 이름으로 찾게. NER/gazetteer와 일관.
            """SELECT DISTINCT m.item_id, m.canonical_name, m.category
               FROM item_master m
               LEFT JOIN item_alias a ON a.item_id = m.item_id
               WHERE m.canonical_name ILIKE %s OR a.alias ILIKE %s
               ORDER BY m.canonical_name LIMIT %s""",
            (f"%{q}%", f"%{q}%", limit),
        )
        rows = await cur.fetchall()
    return [ItemSearchItem(item_id=iid, canonical_name=name, category=cat) for iid, name, cat in rows]


# ── #28 지금 싼 재료: 크로스소스 절약률 큰 순 (관측 2건+ 필터로 노이즈↓) ──
async def recommend(pool: AsyncConnectionPool, limit: int) -> list[RecommendItem]:
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """SELECT item_id, canonical_name, category, kurly_100g, oasis_100g
               FROM retail_item_price_compare
               WHERE kurly_100g IS NOT NULL AND oasis_100g IS NOT NULL
                 AND kurly_n >= 2 AND oasis_n >= 2
                 -- 소스 단가 정규화 아티팩트(1원/100g, 수만원/100g 등) 제거
                 AND least(kurly_100g, oasis_100g) >= 50
                 AND greatest(kurly_100g, oasis_100g) <= 12000
               ORDER BY (greatest(kurly_100g,oasis_100g) - least(kurly_100g,oasis_100g))
                        / greatest(kurly_100g,oasis_100g) DESC
               LIMIT %s""",
            (limit,),
        )
        rows = await cur.fetchall()

    out = []
    for iid, name, cat, k, o in rows:
        k, o = _won(k), _won(o)
        cheaper_src, cheaper = ("kurly", k) if k <= o else ("oasis", o)
        pricier = max(k, o)
        saving = int(round((pricier - cheaper) / pricier * 100)) if pricier else 0
        out.append(
            RecommendItem(
                item_id=iid, canonical_name=name, category=cat,
                kurly_100g=k, oasis_100g=o,
                cheaper_source=cheaper_src, cheaper_krw_per_100g=cheaper, saving_pct=saving,
            )
        )
    return out


# ── #31 핫딜: 상품별 최신 딜 스냅샷(deal_type<>'general') ──
async def hotdeals(pool: AsyncConnectionPool, limit: int) -> list[HotdealItem]:
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """SELECT rp.id, rp.name, rp.source, rp.image_url, rp.url, rp.item_id,
                      lp.price, lp.original_price, lp.discount_rate, lp.deal_type,
                      lp.timedeal_end, lp.unit_price, lp.unit_basis, lp.is_sold_out
               FROM retail_product rp
               JOIN LATERAL (
                 SELECT * FROM retail_price pr
                 WHERE pr.retail_product_id = rp.id AND pr.deal_type <> 'general'
                       AND pr.price IS NOT NULL        -- 품절딜 null 가격 제외(HotdealItem.price=필수 int → 미제외 시 목록 전체 500)
                 ORDER BY pr.crawled_at DESC LIMIT 1
               ) lp ON true
               WHERE lp.timedeal_end IS NULL OR lp.timedeal_end > now()   -- 만료된 딜 제외(지난 마감세일 숨김)
               ORDER BY lp.crawled_at DESC
               LIMIT %s""",
            (limit,),
        )
        rows = await cur.fetchall()

    return [
        HotdealItem(
            retail_product_id=r[0], name=r[1], source=r[2], image_url=r[3], url=r[4], item_id=r[5],
            price=_won(r[6]), original_price=_won(r[7]), discount_rate=r[8], deal_type=r[9],
            timedeal_end=r[10], unit_price=_won(r[11]), unit_basis=r[12], is_sold_out=r[13],
        )
        for r in rows
    ]


# ── #26 현재가: 소스별 최저 단가 + (있으면)통계 baseline ──
async def current_price(pool: AsyncConnectionPool, item_id: int) -> CurrentPrice | None:
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT canonical_name, category FROM item_master WHERE item_id = %s", (item_id,)
        )
        im = await cur.fetchone()
        if im is None:
            return None

        await cur.execute(
            """SELECT source,
                      min(won_per_100g) FILTER (WHERE won_per_100g IS NOT NULL) AS w100,
                      min(won_per_piece) FILTER (WHERE won_per_piece IS NOT NULL) AS wpiece,
                      max(piece_unit) FILTER (WHERE won_per_piece IS NOT NULL) AS punit
               FROM retail_unit_price WHERE item_id = %s GROUP BY source""",
            (item_id,),
        )
        retail = [
            SourcePrice(source=s, krw_per_100g=_won(w), krw_per_piece=_won(p), piece_unit=u)
            for s, w, p, u in await cur.fetchall()
        ]

        await cur.execute(
            """SELECT pod.survey_date, pod.price_min, pod.price_med, pod.price_max
               FROM price_item pi JOIN price_online_daily pod ON pod.item_cd = pi.item_cd
               WHERE pi.item_id = %s ORDER BY pod.survey_date DESC LIMIT 1""",
            (item_id,),
        )
        b = await cur.fetchone()

    baseline = (
        Baseline(survey_date=b[0], price_min=_won(b[1]), price_med=_won(b[2]), price_max=_won(b[3]))
        if b
        else None
    )
    return CurrentPrice(
        item_id=item_id, canonical_name=im[0], category=im[1], retail=retail, baseline=baseline
    )


# ── #27 이력: item_id 소속 SKU들의 가격 스냅샷 시계열 ──
async def price_history(pool: AsyncConnectionPool, item_id: int, limit: int) -> PriceHistory:
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """SELECT pr.crawled_at, rp.source, pr.price, pr.deal_type
               FROM retail_price pr JOIN retail_product rp ON rp.id = pr.retail_product_id
               WHERE rp.item_id = %s AND pr.price IS NOT NULL
               ORDER BY pr.crawled_at DESC LIMIT %s""",
            (item_id, limit),
        )
        rows = await cur.fetchall()
    points = [
        HistoryPoint(crawled_at=r[0], source=r[1], price=_won(r[2]), deal_type=r[3]) for r in rows
    ]
    return PriceHistory(item_id=item_id, points=points)


async def price_trends(pool: AsyncConnectionPool, days: int, limit: int) -> TrendResponse:
    """'값 내린 재료' 위젯(예산앱 목적) — 품목별 대표상품의 일별 최저가 추세에서
    가격이 내린(할인) 재료만 하락률 큰 순으로 상위 limit개 반환.

    대표상품 = 서로 다른 날짜에 가장 많이 크롤된 상품 1개. 한 item_id에 여러 용량·브랜드가
    묶여 생기는 min 노이즈를 피해 단일 상품으로 고정하고, 동점은 product_id로 결정적 선택
    (안 그러면 호출마다 상품이 바뀌어 추세가 요동친다)."""
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            with base as (
                select item_id, canonical_name as nm
                from public.item_master where canonical_name is not null
            ),
            rep as (
                select distinct on (item_id) item_id, nm, product_id
                from (
                    select b.item_id, b.nm, rp.id as product_id,
                           count(distinct pr.crawled_at::date) as dcnt, count(*) as pcnt
                    from base b
                    join public.retail_product rp on rp.item_id = b.item_id
                    join public.retail_price pr on pr.retail_product_id = rp.id
                         and pr.price is not null
                         and pr.crawled_at >= now() - make_interval(days => %s)
                    group by b.item_id, b.nm, rp.id
                ) g
                order by item_id, dcnt desc, pcnt desc, product_id   -- product_id = 결정적 tiebreak
            )
            select r.item_id, r.nm, array_agg(x.p order by x.d) as prices
            from rep r
            join lateral (
                select pr.crawled_at::date as d, min(pr.price)::int as p
                from public.retail_price pr
                where pr.retail_product_id = r.product_id and pr.price is not null
                  and pr.crawled_at >= now() - make_interval(days => %s)
                group by pr.crawled_at::date
            ) x on true
            group by r.item_id, r.nm
            """,
            (days, days),
        )
        rows = await cur.fetchall()

    min_pts = min(4, days)   # 추세 신뢰 위해 최소 데이터 일수
    items: list[TrendItem] = []
    for item_id, name, prices in rows:
        prices = [int(p) for p in (prices or []) if p is not None]
        if len(prices) < min_pts:
            continue
        first, current = prices[0], prices[-1]
        delta_pct = round((current - first) / first * 100) if first else 0
        if delta_pct > -3:   # 예산앱 목적: '값 내린 재료'만(보합·상승 제외)
            continue
        items.append(TrendItem(
            item_id=item_id, name=name, prices=prices, current=current,
            avg=round(sum(prices) / len(prices)), delta_pct=delta_pct, up=False,
        ))
    items.sort(key=lambda t: t.delta_pct)   # 하락률 큰 순(가장 많이 내린 것 먼저)
    return TrendResponse(days=days, items=items[:limit])


# ── #29·#30 최저가 관심 ────────────────────────────────────────────────────
# 이 세 함수가 fan-out 컨슈머(consume_price_anomaly.py)의 수신자 명단을 만든다.
# 등록이 없으면 급락을 탐지해도 알림이 나가지 않는다 — 관심 신청한 유저에게만 보내는 정책.

async def add_watch(pool: AsyncConnectionPool, user_id: int, item_id: int) -> bool:
    """관심 등록. 반환 True=신규 생성, False=이미 등록됨.

    UNIQUE(user_id, item_id) 위에서 ON CONFLICT DO NOTHING — 중복 요청·재시도가 409가 아니라
    멱등 성공이 되게 한다(모바일에서 같은 탭이 두 번 눌리는 상황이 흔하다).
    존재하지 않는 item_id 는 FK가 막아 호출측이 404로 변환한다.
    """
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO price.price_watch (user_id, item_id) VALUES (%s, %s)
               ON CONFLICT (user_id, item_id) DO NOTHING""",
            (user_id, item_id),
        )
        return cur.rowcount == 1


async def remove_watch(pool: AsyncConnectionPool, user_id: int, item_id: int) -> bool:
    """관심 해제. 반환 True=삭제됨, False=원래 없었음(호출측이 404 판단에 사용)."""
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM price.price_watch WHERE user_id = %s AND item_id = %s",
            (user_id, item_id),
        )
        return cur.rowcount == 1


async def list_watch(pool: AsyncConnectionPool, user_id: int) -> list[WatchItem]:
    """내 관심 목록. 품목명을 함께 주어 클라이언트가 item_master를 되묻지 않게 한다."""
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """SELECT w.item_id, m.canonical_name, w.created_at
                 FROM price.price_watch w
                 LEFT JOIN item_master m ON m.item_id = w.item_id
                WHERE w.user_id = %s
                ORDER BY w.created_at DESC""",
            (user_id,),
        )
        rows = await cur.fetchall()
    return [WatchItem(item_id=iid, canonical_name=name, created_at=ts) for iid, name, ts in rows]
