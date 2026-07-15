"""Notify Service — 알림함 목록·읽음 처리. api-spec #41~42.

★ 주입 패턴(account 레퍼런스): 전역 state[...] 대신 AppCtx(context.py)를 Depends로 주입 → 핸들러 테스트 가능.
★ 신원: account가 발급한 access JWT를 **검증만** 한다(재발급 X). user_id 는 토큰에서 온 값.
   구조(config·db·context·security·models·queries·routers·main)는 account에서 복제.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from app.context import AppCtx
from app.db import make_pg_pool
from app.routers import notifications
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


app = FastAPI(title="Notify Service", version="0.1.0", lifespan=lifespan)
app.include_router(notifications)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "notify"}
