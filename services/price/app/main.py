"""Price Service — 현재가·이력·시세추천·핫딜 (데이터 티어 읽기).
docs/design/api-spec.md #26·#27·#28·#31. JWT 미검증(chat 서비스와 동일 방침).

라우트 순서 주의: 정적 경로(/recommend·/hotdeals)를 /{item_id} 보다 먼저 선언.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import settings
from app.db import make_pg_pool
from app.models import CurrentPrice, HotdealResponse, ItemSearchResponse, PriceHistory, RecommendResponse
from app.queries import current_price, hotdeals, price_history, recommend, search_items

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    state["pg_pool"] = make_pg_pool()
    await state["pg_pool"].open()
    try:
        yield
    finally:
        await state["pg_pool"].close()


app = FastAPI(title="Price Service", version="0.1.0", lifespan=lifespan)
Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    should_instrument_requests_inprogress=True,
    excluded_handlers=[r"^/metrics$", r"^/health$"],
    inprogress_name="http_requests_inprogress",
    inprogress_labels=True,
).instrument(app).expose(app, include_in_schema=False)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "price"}


@app.get("/api/prices/recommend", response_model=RecommendResponse)
async def prices_recommend(limit: int = Query(settings.default_limit, ge=1, le=100)):
    return RecommendResponse(items=await recommend(state["pg_pool"], limit))


@app.get("/api/prices/hotdeals", response_model=HotdealResponse)
async def prices_hotdeals(limit: int = Query(settings.default_limit, ge=1, le=100)):
    return HotdealResponse(deals=await hotdeals(state["pg_pool"], limit))


# 품목 이름 검색 — 정적 경로라 /{item_id} 보다 먼저 선언.
@app.get("/api/prices/items", response_model=ItemSearchResponse)
async def prices_items(q: str = Query(..., min_length=1, max_length=50),
                       limit: int = Query(20, ge=1, le=50)):
    return ItemSearchResponse(items=await search_items(state["pg_pool"], q, limit))


@app.get("/api/prices/{item_id}/history", response_model=PriceHistory)
async def prices_history(item_id: int, limit: int = Query(settings.history_limit, ge=1, le=1000)):
    return await price_history(state["pg_pool"], item_id, limit)


@app.get("/api/prices/{item_id}", response_model=CurrentPrice)
async def prices_current(item_id: int):
    cp = await current_price(state["pg_pool"], item_id)
    if cp is None:
        raise HTTPException(status_code=404, detail="item not found")
    return cp
