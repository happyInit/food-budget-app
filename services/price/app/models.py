"""응답 스키마. docs/design/api-spec.md #26·#27·#28·#31 (데이터 티어 실 컬럼 기준)."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


# ── #28 지금 싼 재료 (retail_item_price_compare) ──
class RecommendItem(BaseModel):
    item_id: int
    canonical_name: str
    category: str | None = None
    kurly_100g: int | None = None
    oasis_100g: int | None = None
    cheaper_source: str
    cheaper_krw_per_100g: int
    saving_pct: int  # 비싼 소스 대비 절약률


class RecommendResponse(BaseModel):
    items: list[RecommendItem]


# ── 품목 검색 (제외 재료 선택 등) — item_master 이름 검색 ──
class ItemSearchItem(BaseModel):
    item_id: int
    canonical_name: str
    category: str | None = None


class ItemSearchResponse(BaseModel):
    items: list[ItemSearchItem]


# ── #31 핫딜 (retail_product + retail_price) ──
class HotdealItem(BaseModel):
    retail_product_id: int
    name: str
    source: str
    image_url: str | None = None
    url: str | None = None                # 소스(오아시스/컬리) 상품 상세 URL — 클릭 시 구매 페이지로 이동
    item_id: int | None = None
    price: int
    original_price: int | None = None
    discount_rate: int | None = None
    deal_type: str
    timedeal_end: datetime | None = None
    unit_price: int | None = None
    unit_basis: str | None = None
    is_sold_out: bool | None = None


class HotdealResponse(BaseModel):
    deals: list[HotdealItem]


# ── #26 현재가 ──
class SourcePrice(BaseModel):
    source: str
    krw_per_100g: int | None = None
    krw_per_piece: int | None = None
    piece_unit: str | None = None


class Baseline(BaseModel):
    survey_date: date
    price_min: int | None = None
    price_med: int | None = None
    price_max: int | None = None


class CurrentPrice(BaseModel):
    item_id: int
    canonical_name: str | None = None
    category: str | None = None
    retail: list[SourcePrice]
    baseline: Baseline | None = None  # price_online_daily 희소 → 대부분 null


# ── #27 이력 ──
class HistoryPoint(BaseModel):
    crawled_at: datetime
    source: str
    price: int
    deal_type: str


class PriceHistory(BaseModel):
    item_id: int
    points: list[HistoryPoint]


class TrendItem(BaseModel):
    """재료 시세 위젯용 — 품목별 '대표상품(가장 꾸준히 크롤된 1개)'의 일별 최저가 추세.
    여러 용량·브랜드가 한 item_id에 묶여 생기는 노이즈를 피하려 단일 상품으로 고정한다."""
    item_id: int
    name: str
    prices: list[int]      # 대표상품 일별 최저가(오래된→최신)
    current: int           # 최신값 = prices[-1]
    avg: int               # 기간 평균
    delta_pct: int         # (current-첫값)/첫값 * 100, 반올림(순변화)
    up: bool               # current > 첫값


class TrendResponse(BaseModel):
    days: int
    items: list[TrendItem]


# ── #29·#30 최저가 관심 ──
class WatchRequest(BaseModel):
    """POST /api/prices/watch — 관심 등록. user_id는 **바디가 아니라 JWT에서** 온다(A01)."""
    item_id: int = Field(gt=0)


class WatchItem(BaseModel):
    item_id: int
    canonical_name: str | None = None
    created_at: datetime


class WatchListResponse(BaseModel):
    items: list[WatchItem]


class WatchMutationResponse(BaseModel):
    """등록/해제 결과. created=false 는 이미 등록된 상태(멱등) — 클라이언트가 재시도해도 안전."""
    item_id: int
    watching: bool
    created: bool = False
