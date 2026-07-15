"""RecipeBook Service — 레시피 북마크(스크랩). api-spec #20~22.

★ 신원은 account가 발급한 JWT를 **신뢰**(재검증 안 함) — 여기선 verify_access만.
★ 주입 패턴(account 레퍼런스 복제): 전역 state[...] 대신 AppCtx(context.py)를 Depends로 주입.
   테이블 = recipebook.bookmark 만 소유(user_recipe·extract_job 은 AI 담당 #24~25 몫).
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from app.context import AppCtx
from app.db import make_pg_pool
from app.routers import book
from app.security import Security


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    pool = make_pg_pool(settings)
    await pool.open()
    app.state.ctx = AppCtx(
        pool=pool,
        settings=settings,
        security=Security(
            settings.jwt_secret, settings.jwt_alg,
            settings.access_ttl_min, settings.refresh_ttl_days,
        ),
    )
    try:
        yield
    finally:
        await pool.close()


app = FastAPI(title="RecipeBook Service", version="0.1.0", lifespan=lifespan)
app.include_router(book)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "recipebook"}
