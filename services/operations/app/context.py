from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from psycopg_pool import AsyncConnectionPool

from app.config import Settings


@dataclass
class AppCtx:
    pool: AsyncConnectionPool | None
    settings: Settings


def get_ctx(request: Request) -> AppCtx:
    return request.app.state.ctx


async def get_conn(ctx: AppCtx = Depends(get_ctx)):
    if ctx.pool is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "operations alert persistence is not configured",
        )
    async with ctx.pool.connection() as conn:
        yield conn
