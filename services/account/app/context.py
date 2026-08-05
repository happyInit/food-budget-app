"""AppCtx + 주입 seam.

★ 이 서비스의 핵심 패턴(두 명이 복사할 부분).
핸들러는 전역 `state[...]` 를 읽지 않고, 아래 Depends로 의존성을 **주입**받는다.
→ 테스트에서 `app.dependency_overrides[get_conn] = fake` 로 DB·JWT 없이 핸들러를 통째 테스트.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from psycopg_pool import AsyncConnectionPool

from app.config import Settings
from app.oauth import OAuthClients
from app.security import Security, TokenError
from app.throttle import LoginThrottle

logger = logging.getLogger("account")


@dataclass
class AppCtx:
    """서비스 조립 결과 1개 객체. lifespan이 만들어 app.state.ctx 에 얹는다."""
    pool: AsyncConnectionPool
    settings: Settings
    security: Security
    oauth: OAuthClients
    throttle: LoginThrottle


# ── seam: 핸들러가 받는 의존성 ────────────────────────────────────────────
def get_ctx(request: Request) -> AppCtx:
    return request.app.state.ctx


async def get_conn(ctx: AppCtx = Depends(get_ctx)):
    """풀에서 커넥션 하나를 꺼내 yield(성공 시 커밋, 예외 시 롤백은 psycopg_pool이 처리)."""
    async with ctx.pool.connection() as conn:
        yield conn


def get_security(ctx: AppCtx = Depends(get_ctx)) -> Security:
    return ctx.security


def get_oauth(ctx: AppCtx = Depends(get_ctx)) -> OAuthClients:
    return ctx.oauth


def get_throttle(ctx: AppCtx = Depends(get_ctx)) -> LoginThrottle:
    return ctx.throttle


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
