"""AppCtx + 주입 seam. account에서 그대로 복사.

★ 이 서비스의 핵심 패턴.
핸들러는 전역 `state[...]` 를 읽지 않고, 아래 Depends로 의존성을 **주입**받는다.
→ 테스트에서 `app.dependency_overrides[get_conn] = fake` 로 DB·JWT 없이 핸들러를 통째 테스트.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from psycopg_pool import AsyncConnectionPool

from app.config import Settings
from app.security import Security, TokenError

logger = logging.getLogger("recipebook")


@dataclass
class AppCtx:
    """서비스 조립 결과 1개 객체. lifespan이 만들어 app.state.ctx 에 얹는다."""
    pool: AsyncConnectionPool
    settings: Settings
    security: Security
    # 공개 발행 레시피 검색/목록용 ES(AsyncElasticsearch) — 공유 상세(get_shared_recipe)는 PG 그대로.
    es: Any


# ── seam: 핸들러가 받는 의존성 ────────────────────────────────────────────
def get_ctx(request: Request) -> AppCtx:
    return request.app.state.ctx


async def get_conn(ctx: AppCtx = Depends(get_ctx)):
    """풀에서 커넥션 하나를 꺼내 yield(성공 시 커밋, 예외 시 롤백은 psycopg_pool이 처리)."""
    async with ctx.pool.connection() as conn:
        yield conn


def get_es(ctx: AppCtx = Depends(get_ctx)) -> Any:
    """공개 발행 레시피 목록/검색에 쓰는 ES 클라이언트. 테스트에서 fake 로 갈아끼운다."""
    return ctx.es


def get_security(ctx: AppCtx = Depends(get_ctx)) -> Security:
    return ctx.security


async def get_current_user(request: Request, ctx: AppCtx = Depends(get_ctx)) -> int:
    """Authorization: Bearer <access> → user_id. 인증 필요한 핸들러가 Depends로 붙인다."""
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    try:
        return ctx.security.verify_access(auth[len("Bearer "):])
    except TokenError:
        logger.warning("access token verification failed", extra={"event": "token_invalid"})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")
