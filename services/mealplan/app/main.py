"""MealPlan Service — Cart(장바구니) + Expense(식비) + Recommend(추천). api-spec #32~40.

★ 주입 패턴(레퍼런스=account): 전역 state[...] 대신 AppCtx(context.py)를 Depends로 주입.
★ 크로스서비스는 DB 조인 금지 → seam(어댑터)로: budget=account User API, pantry=Pantry API.
   account가 발급한 JWT를 verify_access 로 검증만 함(재검증 아님 — 신뢰 경계).
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from app.context import AppCtx, HttpBudgetProvider, HttpPantryProvider
from app.db import make_pg_pool
from app.routers import cart, expense, recommend
from app.security import Security


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    pool = make_pg_pool(settings)
    await pool.open()
    app.state.ctx = AppCtx(
        pool=pool,
        settings=settings,
        security=Security(settings.jwt_secret, settings.jwt_alg),
        budget_provider=HttpBudgetProvider(settings.account_base_url),
        pantry_provider=HttpPantryProvider(settings.pantry_base_url),
    )
    try:
        yield
    finally:
        await pool.close()


app = FastAPI(title="MealPlan Service", version="0.1.0", lifespan=lifespan)
app.include_router(cart)
app.include_router(expense)
app.include_router(recommend)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mealplan"}
