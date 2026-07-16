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
)


def _won(v: Any) -> int | None:
    return None if v is None else int(round(float(v)))


# ── 품목 이름 검색 (제외 재료 선택) — 사용자 입력은 %s 파라미터 바인딩(A05) ──
async def search_items(pool: AsyncConnectionPool, q: str, limit: int) -> list[ItemSearchItem]:
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """SELECT item_id, canonical_name, category FROM item_master
               WHERE canonical_name ILIKE %s
               ORDER BY canonical_name LIMIT %s""",
            (f"%{q}%", limit),
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
