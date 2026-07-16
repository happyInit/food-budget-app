"""MealPlan Service — Cart(장바구니) + Expense(식비) + Recommend(추천). api-spec #32~40.

★ 주입 패턴(레퍼런스=account): 전역 state[...] 대신 AppCtx(context.py)를 Depends로 주입.
★ 크로스서비스는 DB 조인 금지 → seam(어댑터)로: budget=account User API, pantry=Pantry API.
   account가 발급한 JWT를 verify_access 로 검증만 함(재검증 아님 — 신뢰 경계).
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import Settings
from app.context import AppCtx, HttpBudgetProvider, HttpExclusionProvider, HttpPantryProvider
from app.db import make_pg_pool
from app.routers import cart, expense, recommend
from app.security import Security


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    pool = make_pg_pool(settings)
    await pool.open()
    security = Security(settings.jwt_secret, settings.jwt_alg)
    app.state.ctx = AppCtx(
        pool=pool,
        settings=settings,
        security=security,
        # seam 어댑터에 공유 JWT_SECRET 주입 → 크로스서비스 호출용 유저 토큰 발급.
        budget_provider=HttpBudgetProvider(settings.account_base_url, settings.jwt_secret, settings.jwt_alg),
        pantry_provider=HttpPantryProvider(settings.pantry_base_url, settings.jwt_secret, settings.jwt_alg),
        exclusion_provider=HttpExclusionProvider(settings.account_base_url, settings.jwt_secret, settings.jwt_alg),
    )
    try:
        yield
    finally:
        await pool.close()


app = FastAPI(title="MealPlan Service", version="0.1.0", lifespan=lifespan)
Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    should_instrument_requests_inprogress=True,
    excluded_handlers=[r"^/metrics$", r"^/health$"],
    inprogress_name="http_requests_inprogress",
    inprogress_labels=True,
).instrument(app).expose(app, include_in_schema=False)
app.include_router(cart)
app.include_router(expense)
app.include_router(recommend)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mealplan"}
