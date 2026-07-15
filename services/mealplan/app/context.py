"""AppCtx + 주입 seam. account/app/context.py 를 복제 + 크로스서비스 provider seam 추가.

핸들러는 전역 `state[...]` 를 읽지 않고 Depends로 의존성을 **주입**받는다
→ 테스트에서 `app.dependency_overrides[get_conn] = fake` 로 DB·JWT·크로스서비스 없이 통째 테스트.

★ 크로스서비스 seam (schema-per-service: DB 조인 금지 → API 호출):
   - BudgetProvider  = account User API(#9 GET /api/users/budget) 어댑터.
   - PantryProvider  = pantry API(#11 재고, 안버린재료) 어댑터.
   실제 HTTP 배선은 TODO — 미배선/네트워크 실패는 `ProviderUnavailable` 로 신호 → 핸들러가 degrade.
   테스트는 get_budget_provider/get_pantry_provider 를 override 해 fake 주입.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from fastapi import Depends, HTTPException, Request, status
from psycopg_pool import AsyncConnectionPool

from app.config import Settings
from app.security import Security, TokenError


# ── 크로스서비스 seam ──────────────────────────────────────────────────────
class ProviderUnavailable(Exception):
    """크로스서비스 어댑터 미가용(미배선·네트워크 실패·타임아웃) → 호출측이 degrade."""


@dataclass(frozen=True)
class PantryStock:
    """pantry API가 돌려주는 재고 1건(정규화된 표준 품목 축). expiring=소비기한 임박."""
    item_id: int
    name: str
    expiring: bool = False


@runtime_checkable
class BudgetProvider(Protocol):
    async def get_budget(self, user_id: int) -> int | None:
        """이번 달 예산(원, 정수) 또는 None(미설정). 미가용이면 ProviderUnavailable."""
        ...


@runtime_checkable
class PantryProvider(Protocol):
    async def get_pantry(self, user_id: int) -> list[PantryStock]:
        """유저 냉장고 재고. 미가용이면 ProviderUnavailable."""
        ...

    async def saved_ingredients(self, user_id: int) -> int | None:
        """안 버리고 소비한 재료 수(성과지표). 미가용이면 ProviderUnavailable."""
        ...


class HttpBudgetProvider:
    """account User API(#9) 어댑터. TODO(seam): httpx 로 GET {base}/api/users/budget 배선.

    배선 전엔 ProviderUnavailable 을 던져 호출측이 예산 관련 필드를 null 로 degrade 하게 둔다.
    """

    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")

    async def get_budget(self, user_id: int) -> int | None:
        # TODO(seam): async with httpx.AsyncClient() as c: r = await c.get(
        #   f"{self._base}/api/users/budget", headers={서비스간 토큰}); return r.json()["amount"]
        raise ProviderUnavailable("budget provider (account) not wired yet")


class HttpPantryProvider:
    """pantry API 어댑터. TODO(seam): httpx 로 재고·안버린재료 조회 배선.

    배선 전엔 ProviderUnavailable → 재고 기반 기능(#32)은 degrade, 성과지표(#40)는 null.
    """

    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")

    async def get_pantry(self, user_id: int) -> list[PantryStock]:
        # TODO(seam): GET {self._base}/api/pantry/items → [PantryStock(...)]
        raise ProviderUnavailable("pantry provider not wired yet")

    async def saved_ingredients(self, user_id: int) -> int | None:
        # TODO(seam): GET {self._base}/api/pantry/stats → saved count
        raise ProviderUnavailable("pantry provider not wired yet")


@dataclass
class AppCtx:
    """서비스 조립 결과 1개 객체. lifespan이 만들어 app.state.ctx 에 얹는다."""
    pool: AsyncConnectionPool
    settings: Settings
    security: Security
    budget_provider: BudgetProvider
    pantry_provider: PantryProvider


# ── seam: 핸들러가 받는 의존성 ────────────────────────────────────────────
def get_ctx(request: Request) -> AppCtx:
    return request.app.state.ctx


async def get_conn(ctx: AppCtx = Depends(get_ctx)):
    """풀에서 커넥션 하나를 꺼내 yield(성공 시 커밋, 예외 시 롤백은 psycopg_pool이 처리).
    conn 을 쿼리에 넘겨 트랜잭션 경계를 호출측이 제어 → checkout(합계→지출→비우기) 원자 실행."""
    async with ctx.pool.connection() as conn:
        yield conn


def get_security(ctx: AppCtx = Depends(get_ctx)) -> Security:
    return ctx.security


def get_budget_provider(ctx: AppCtx = Depends(get_ctx)) -> BudgetProvider:
    return ctx.budget_provider


def get_pantry_provider(ctx: AppCtx = Depends(get_ctx)) -> PantryProvider:
    return ctx.pantry_provider


async def get_current_user(request: Request, ctx: AppCtx = Depends(get_ctx)) -> int:
    """Authorization: Bearer <access> → user_id. 인증 필요한 핸들러가 Depends로 붙인다.
    ★ user_id는 항상 JWT에서(요청 바디/쿼리의 user_id 신뢰 금지 — OWASP A01)."""
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    try:
        return ctx.security.verify_access(auth[len("Bearer "):])
    except TokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")
