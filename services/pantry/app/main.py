"""Pantry Service — 냉장고 재고 CRUD + 소비기한 임박. api-spec #11~15.

★ account가 발급한 JWT를 **신뢰**(로컬 서명검증만, 재검증 안 함) → user_id 소유자 스코프로
   모든 재고 접근을 제한(A01). ★ 주입 패턴(account 레퍼런스 복제):
   config·db·context·security·models·queries·routers·main 를 그대로 복사, 스키마만 pantry로 교체.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import Settings
from app.context import AppCtx
from app.db import make_pg_pool
from app.routers import pantry
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
    )
    try:
        yield
    finally:
        await pool.close()


app = FastAPI(title="Pantry Service", version="0.1.0", lifespan=lifespan)
Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    should_instrument_requests_inprogress=True,
    excluded_handlers=[r"^/metrics$", r"^/health$"],
    inprogress_name="http_requests_inprogress",
    inprogress_labels=True,
).instrument(app).expose(app, include_in_schema=False)
app.include_router(pantry)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "pantry"}
