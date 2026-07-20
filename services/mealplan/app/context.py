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

import asyncio
import datetime as dt
import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from psycopg_pool import AsyncConnectionPool

from app.config import Settings
from app.security import Security, TokenError

logger = logging.getLogger("mealplan")


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


@runtime_checkable
class ExclusionProvider(Protocol):
    async def get_excluded_item_ids(self, user_id: int) -> list[int]:
        """유저 제외(회피) 재료 item_id 목록. 미가용이면 ProviderUnavailable."""
        ...


def _mint(secret: str, alg: str, user_id: int) -> str:
    """크로스서비스 호출용 유저 액세스 토큰 발급(서비스 공유 JWT_SECRET). 다운스트림이 get_current_user 로 검증.
    → user_id 를 바디/쿼리로 신뢰시키지 않고 JWT로 전달(A01 유지). 라우터/Protocol 시그니처 불변.
    account 발급 access 토큰과 동일 포맷(sub·typ·iat·exp). 단명(5분) — 호출 즉시 소모."""
    now = dt.datetime.now(dt.timezone.utc)
    payload = {"sub": str(user_id), "typ": "access", "iat": now,
               "exp": now + dt.timedelta(minutes=5)}
    return jwt.encode(payload, secret, algorithm=alg)


class HttpBudgetProvider:
    """account User API(#9 GET /api/users/budget) 어댑터. 유저 토큰을 발급해 붙여 호출.

    account 미가용/네트워크 실패 → ProviderUnavailable → 호출측이 예산 필드를 null 로 degrade.
    """

    def __init__(self, base_url: str, secret: str, alg: str,
                 client: httpx.AsyncClient, timeout: float = 3.0) -> None:
        self._base = base_url.rstrip("/")
        self._secret = secret
        self._alg = alg
        self._client = client          # 공유 클라이언트(keep-alive) — 호출마다 새로 만들지 않음
        self._timeout = timeout

    async def get_budget(self, user_id: int) -> int | None:
        token = _mint(self._secret, self._alg, user_id)
        try:
            r = await self._client.get(f"{self._base}/api/users/budget",
                                       headers={"Authorization": f"Bearer {token}"},
                                       timeout=self._timeout)
        except httpx.HTTPError as e:
            raise ProviderUnavailable(f"budget provider (account) unreachable: {e}")
        if r.status_code >= 500:
            raise ProviderUnavailable(f"budget provider (account) error {r.status_code}")
        if r.status_code != 200:
            return None                       # 401/404 등 → 예산 미설정 취급
        body = r.json()
        return None if body is None else body.get("amount")


class HttpPantryProvider:
    """pantry API(#11 재고 · #15 임박) 어댑터. 유저 토큰 발급해 붙여 호출.

    미가용 → ProviderUnavailable → 재고 기반 추천(#32) degrade, 성과지표(#40) null.
    """

    def __init__(self, base_url: str, secret: str, alg: str,
                 client: httpx.AsyncClient, timeout: float = 3.0) -> None:
        self._base = base_url.rstrip("/")
        self._secret = secret
        self._alg = alg
        self._client = client          # 공유 클라이언트(keep-alive)
        self._timeout = timeout

    async def get_pantry(self, user_id: int) -> list[PantryStock]:
        token = _mint(self._secret, self._alg, user_id)
        headers = {"Authorization": f"Bearer {token}"}
        try:
            # items·expiring 은 서로 독립 → 병렬 호출(직렬 왕복 제거).
            items, exp = await asyncio.gather(
                self._client.get(f"{self._base}/api/pantry/items",
                                 headers=headers, timeout=self._timeout),
                self._client.get(f"{self._base}/api/pantry/expiring",
                                 params={"within_days": 3}, headers=headers, timeout=self._timeout),
            )
        except httpx.HTTPError as e:
            raise ProviderUnavailable(f"pantry provider unreachable: {e}")
        if items.status_code >= 500:
            raise ProviderUnavailable(f"pantry provider error {items.status_code}")
        if items.status_code != 200:
            return []
        expiring_ids = {row["item_id"] for row in (exp.json() if exp.status_code == 200 else [])
                        if row.get("item_id") is not None}
        # 표준품목(item_id) 앵커된 재고만 랭킹 대상 — item_id 없는 행은 커버리지 계산 불가.
        return [
            PantryStock(item_id=row["item_id"], name=row["name"],
                        expiring=row["item_id"] in expiring_ids)
            for row in items.json()
            if row.get("item_id") is not None and row.get("status") == "ACTIVE"
        ]

    async def saved_ingredients(self, user_id: int) -> int | None:
        """pantry #stats 의 consumed(소비완료=안 버린 재료) 수. 전체 기간(month 미지정).
        미가용 → ProviderUnavailable → 요약(#40) saved_ingredients null degrade."""
        token = _mint(self._secret, self._alg, user_id)
        try:
            r = await self._client.get(f"{self._base}/api/pantry/stats",
                                       headers={"Authorization": f"Bearer {token}"},
                                       timeout=self._timeout)
        except httpx.HTTPError as e:
            raise ProviderUnavailable(f"pantry stats unreachable: {e}")
        if r.status_code >= 500:
            raise ProviderUnavailable(f"pantry stats error {r.status_code}")
        if r.status_code != 200:
            return None
        return r.json().get("consumed")


class HttpExclusionProvider:
    """account User API(제외 재료) 어댑터. 유저 토큰 발급해 붙여 호출.

    미가용/네트워크 실패 → ProviderUnavailable → 추천(#32) 이 제외 없이 진행(degrade).
    """

    def __init__(self, base_url: str, secret: str, alg: str,
                 client: httpx.AsyncClient, timeout: float = 3.0) -> None:
        self._base = base_url.rstrip("/")
        self._secret = secret
        self._alg = alg
        self._client = client          # 공유 클라이언트(keep-alive)
        self._timeout = timeout

    async def get_excluded_item_ids(self, user_id: int) -> list[int]:
        token = _mint(self._secret, self._alg, user_id)
        try:
            r = await self._client.get(f"{self._base}/api/users/excluded-items",
                                       headers={"Authorization": f"Bearer {token}"},
                                       timeout=self._timeout)
        except httpx.HTTPError as e:
            raise ProviderUnavailable(f"exclusion provider (account) unreachable: {e}")
        if r.status_code >= 500:
            raise ProviderUnavailable(f"exclusion provider (account) error {r.status_code}")
        if r.status_code != 200:
            return []
        return [row["item_id"] for row in r.json() if row.get("item_id") is not None]


@dataclass
class AppCtx:
    """서비스 조립 결과 1개 객체. lifespan이 만들어 app.state.ctx 에 얹는다."""
    pool: AsyncConnectionPool
    settings: Settings
    security: Security
    budget_provider: BudgetProvider
    pantry_provider: PantryProvider
    exclusion_provider: ExclusionProvider


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


def get_exclusion_provider(ctx: AppCtx = Depends(get_ctx)) -> ExclusionProvider:
    return ctx.exclusion_provider


async def get_current_user(request: Request, ctx: AppCtx = Depends(get_ctx)) -> int:
    """Authorization: Bearer <access> → user_id. 인증 필요한 핸들러가 Depends로 붙인다.
    ★ user_id는 항상 JWT에서(요청 바디/쿼리의 user_id 신뢰 금지 — OWASP A01)."""
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    try:
        return ctx.security.verify_access(auth[len("Bearer "):])
    except TokenError:
        logger.warning("access token verification failed", extra={"event": "token_invalid"})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")
