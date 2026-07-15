"""AppCtx + 주입 seam. (account/context.py 복제 — 그대로 두는 부분)

★ 핸들러는 전역 `state[...]` 를 읽지 않고, 아래 Depends로 의존성을 **주입**받는다.
→ 테스트에서 `app.dependency_overrides[get_conn] = fake` 로 DB·JWT 없이 핸들러를 통째 테스트.
★ pantry의 A01(소유자 스코프): 핸들러는 요청 바디의 user_id를 믿지 않고 get_current_user(JWT)만 신뢰.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from psycopg_pool import AsyncConnectionPool

from app.config import Settings
from app.security import Security, TokenError


@dataclass
class AppCtx:
    """서비스 조립 결과 1개 객체. lifespan이 만들어 app.state.ctx 에 얹는다."""
    pool: AsyncConnectionPool
    settings: Settings
    security: Security


# ── seam: 핸들러가 받는 의존성 ────────────────────────────────────────────
def get_ctx(request: Request) -> AppCtx:
    return request.app.state.ctx


async def get_conn(ctx: AppCtx = Depends(get_ctx)):
    """풀에서 커넥션 하나를 꺼내 yield(성공 시 커밋, 예외 시 롤백은 psycopg_pool이 처리)."""
    async with ctx.pool.connection() as conn:
        yield conn


def get_security(ctx: AppCtx = Depends(get_ctx)) -> Security:
    return ctx.security


async def get_current_user(request: Request, ctx: AppCtx = Depends(get_ctx)) -> int:
    """Authorization: Bearer <access> → user_id. 인증 필요한 핸들러가 Depends로 붙인다.
    ★ 반환 user_id 는 서명 검증된 JWT의 sub 값 → 이후 모든 쿼리의 소유자 필터로 사용(A01)."""
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    try:
        return ctx.security.verify_access(auth[len("Bearer "):])
    except TokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")
