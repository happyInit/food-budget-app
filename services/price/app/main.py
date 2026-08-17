"""Price Service — 현재가·이력·시세추천·핫딜 (데이터 티어 읽기).
docs/design/api-spec.md #26·#27·#28·#31. JWT 미검증(chat 서비스와 동일 방침).

라우트 순서 주의: 정적 경로(/recommend·/hotdeals)를 /{item_id} 보다 먼저 선언.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import settings
from app.db import make_pg_pool, make_redis_client
from app.models import (CurrentPrice, HotdealResponse, ItemSearchResponse, PriceHistory,
                        RecommendResponse, TrendResponse, WatchListResponse,
                        WatchMutationResponse, WatchRequest)
from app.observability import configure_service_logger
from app.queries import (add_watch, current_price, hotdeals, list_watch, price_history,
                         price_trends, recommend, remove_watch, search_items)
from app.security import Security, TokenError

state: dict = {}
log = configure_service_logger(service="price")


@asynccontextmanager
async def lifespan(app: FastAPI):
    state["pg_pool"] = make_pg_pool()
    await state["pg_pool"].open()
    state["redis"] = make_redis_client() if settings.cache_enabled else None
    state["security"] = Security(settings.jwt_secret, settings.jwt_alg)
    log.info("price service started", extra={"event": "service_started"})
    try:
        yield
    finally:
        if state.get("redis") is not None:
            await state["redis"].aclose()
        await state["pg_pool"].close()
        log.info("price service stopped", extra={"event": "service_stopped"})


# ── 읽기 캐시 = stale-while-revalidate + single-flight ───────────────────────
# 🔴 평범한 read-through 로는 왜 안 되는가 (2026-08-17 AWS Stage1 부하시험 실측)
#   핫딜은 **캐시 키가 하나**(`price:hotdeals:20`)고 TTL 120초, 미스 비용 **1.36초**(히트 34ms)다.
#   초당 526건이 들어오는 상태에서 TTL 이 끝나면 그 1.36초 동안 도착한 **약 715건이 전부 미스**가
#   되어 같은 쿼리를 동시에 실행한다 → PG 커넥션 고갈 → 줄서기 → max 45.19초 · 5xx 1,783건.
#   지표는 p50 42ms / p99 1.74s 로 **양봉**이 되는데, 평균만 보면 건강해 보여서 안 잡힌다.
#   🔴 그리고 이건 **HPA 로 못 고친다 — 오히려 나빠진다.** replica 를 늘리면 만료 순간
#      PG 를 동시에 때리는 주체가 그 배수만큼 늘어난다. 스케일아웃은 증상 처방이다.
#   ⚠️ 미스가 비싼 것도 한몫한다 — hotdeals 는 matview 가 없고 `JOIN LATERAL` 이 상품마다
#      돈다(EXPLAIN: `loops=5867` → 유효 딜 65건). 그건 별건이고 여기서 고치는 건 **동시성**이다.
#
# 고치는 방식 = 둘을 겹친다
#   ① stale-while-revalidate — 만료돼도 **옛 값을 즉시 준다.** 사용자는 한 번도 안 기다린다.
#      핫딜·현재가는 크롤이 하루 1~2회라 2분 지난 값이 무해하다(신선도 요구가 낮다).
#   ② single-flight — 갱신은 **하나만** 한다. 나머지는 옛 값을 받고 지나간다.
#
# 키 3개를 쓴다 (payload 안에 메타를 섞지 않는다 — 파싱이 없고 옛 값과도 충돌하지 않는다):
#   `<key>`        payload    · 물리 TTL = ttl + stale  (신선기간 + 유예기간)
#   `<key>:fresh`  신선 마커   · TTL = ttl   → **이게 없으면 stale** 이다
#   `<key>:lock`   단일비행 락 · SET NX EX
#
# 🔵 캐시가 죽으면 **지금과 똑같이 동작한다** — `_cache_lock` 이 True(=승자)를 주므로 각자
#    쿼리해서 응답이 나간다. best-effort 라는 기존 성질을 그대로 유지한다.
_COLD_POLL_S = 0.05                    # 콜드 대기 폴링 간격
_refresh_tasks: set = set()            # 백그라운드 태스크 강참조 — 없으면 GC 가 걷어간다


async def _cache_read(key: str) -> tuple[str | None, bool]:
    """(payload, 신선한가). 캐시 미가용/장애면 (None, False) = 미스로 우회(엔드포인트 무손상)."""
    r = state.get("redis")
    if r is None:
        return None, False
    try:
        payload, fresh = await r.mget([key, f"{key}:fresh"])
        return payload, fresh is not None
    except Exception:              # noqa: BLE001 — 캐시 장애가 조회를 막지 않게
        return None, False


async def _cache_store(key: str, value: str, ttl: int) -> None:
    """payload + 신선 마커. payload 만 유예기간(`cache_stale_ttl_s`)만큼 더 살려 둔다."""
    r = state.get("redis")
    if r is None:
        return
    try:
        await r.set(key, value, ex=ttl + settings.cache_stale_ttl_s)
        await r.set(f"{key}:fresh", "1", ex=ttl)
    except Exception:              # noqa: BLE001
        pass


async def _cache_lock(key: str) -> bool:
    """단일비행 락. 🔴 캐시 미가용이면 **True**(=승자) — 그래야 캐시 없이도 조회가 산다."""
    r = state.get("redis")
    if r is None:
        return True
    try:
        return bool(await r.set(f"{key}:lock", "1", nx=True, ex=settings.cache_lock_ttl_s))
    except Exception:              # noqa: BLE001
        return True


async def _cache_unlock(key: str) -> None:
    r = state.get("redis")
    if r is None:
        return
    try:
        await r.delete(f"{key}:lock")
    except Exception:              # noqa: BLE001
        pass


async def _cache_refresh(key: str, ttl: int, produce) -> None:
    """백그라운드 갱신 — 실패해도 옛 값이 유예기간 동안 계속 나간다(사용자는 모른다)."""
    try:
        value = await produce()
        if value is not None:
            await _cache_store(key, value, ttl)
    except Exception:              # noqa: BLE001 — 태스크 예외는 받아 줄 호출부가 없다
        log.warning("cache refresh failed",
                    extra={"event": "cache_refresh_failed", "cache_key": key, "retryable": True})
    finally:
        await _cache_unlock(key)


async def _cache_wait(key: str) -> str | None:
    """콜드에서 락을 못 잡은 쪽이 승자의 결과를 기다린다. 못 받으면 None(호출부가 직접 조회)."""
    for _ in range(int(settings.cache_cold_wait_s / _COLD_POLL_S)):
        await asyncio.sleep(_COLD_POLL_S)
        payload, _fresh = await _cache_read(key)
        if payload is not None:
            return payload
    return None


async def cached_json(key: str, ttl: int, produce) -> str | None:
    """읽기 캐시 본체. `produce()` = JSON 문자열(없으면 None)을 주는 코루틴 팩토리."""
    payload, fresh = await _cache_read(key)

    if payload is not None and fresh:
        return payload

    if payload is not None:
        # stale — 옛 값을 **즉시** 주고, 락을 잡은 하나만 뒤에서 갱신한다.
        if await _cache_lock(key):
            task = asyncio.create_task(_cache_refresh(key, ttl, produce))
            _refresh_tasks.add(task)
            task.add_done_callback(_refresh_tasks.discard)
        return payload

    # cold — 값이 아예 없다. 하나만 쿼리하고 나머지는 그 결과를 기다린다.
    if await _cache_lock(key):
        try:
            value = await produce()
            if value is not None:
                await _cache_store(key, value, ttl)
            return value
        finally:
            await _cache_unlock(key)

    waited = await _cache_wait(key)
    if waited is not None:
        return waited
    # 승자가 실패했거나 유예를 넘겼다 — **여기서만** 중복 쿼리가 난다(최후 안전망).
    return await produce()


app = FastAPI(title="Price Service", version="0.1.0", lifespan=lifespan)
Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    should_instrument_requests_inprogress=True,
    excluded_handlers=[r"^/metrics$", r"^/health$"],
    inprogress_name="http_requests_inprogress",
    inprogress_labels=True,
).instrument(app).expose(app, include_in_schema=False)


@app.middleware("http")
async def log_unhandled_request_error(request: Request, call_next):
    """처리되지 않은 예외를 기록한 뒤 기존 FastAPI 처리기로 다시 전달한다."""
    try:
        return await call_next(request)
    except Exception as exc:
        route = request.scope.get("route")
        fields = {
            "event": "request_failed",
            "method": request.method,
            "error_type": type(exc).__name__,
            "retryable": False,
        }
        route_template = getattr(route, "path", None)
        if route_template:
            fields["route"] = route_template
        log.error("unhandled price request failure", extra=fields)
        raise


@app.get("/health")
async def health():
    return {"status": "ok", "service": "price"}


@app.get("/api/prices/recommend", response_model=RecommendResponse)
async def prices_recommend(limit: int = Query(settings.default_limit, ge=1, le=100)):
    return RecommendResponse(items=await recommend(state["pg_pool"], limit))


@app.get("/api/prices/hotdeals", response_model=HotdealResponse)
# 상한(le)은 남용 방지 가드지 표시 개수가 아니다 — 유효한 딜은 전부 보여야 한다.
# 구 상한 100 은 실측치(유효 62건 · 일 크롤 ~120건) 바로 위라 아슬아슬했다.
async def prices_hotdeals(limit: int = Query(settings.default_limit, ge=1,
                                             le=settings.hotdeals_max_limit)):
    async def produce() -> str:
        return HotdealResponse(deals=await hotdeals(state["pg_pool"], limit)).model_dump_json()

    body = await cached_json(f"price:hotdeals:{limit}", settings.cache_hotdeals_ttl_s, produce)
    return HotdealResponse.model_validate_json(body)


# 품목 이름 검색 — 정적 경로라 /{item_id} 보다 먼저 선언.
@app.get("/api/prices/items", response_model=ItemSearchResponse)
async def prices_items(q: str = Query(..., min_length=1, max_length=50),
                       limit: int = Query(20, ge=1, le=50)):
    return ItemSearchResponse(items=await search_items(state["pg_pool"], q, limit))


# ── #29·#30 최저가 관심 ─────────────────────────────────────────────────────
# ⚠️ 정적 경로 `/watch` 는 `/{item_id}` 보다 **먼저** 선언해야 한다(파일 상단 라우트 순서 주의).
#    뒤에 두면 `/api/prices/watch` 가 item_id="watch" 로 잡혀 422가 난다.
# 조회 API와 달리 유저 귀속 데이터라 인증이 필수다 — user_id는 **JWT에서만** 받는다(A01).
# 바디/쿼리로 user_id를 받으면 남의 관심 목록을 조작할 수 있다.
async def get_current_user(request: Request) -> int:
    """Authorization: Bearer <access> → user_id."""
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    try:
        return state["security"].verify_access(auth[len("Bearer "):])
    except TokenError:
        log.warning("access token verification failed", extra={"event": "token_invalid"})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")


@app.get("/api/prices/watch", response_model=WatchListResponse)
async def prices_watch_list(uid: int = Depends(get_current_user)):
    """내 관심 목록. api-spec 미기재지만 등록/해제 UI가 현재 상태를 보여주려면 필요하다(#29 후속)."""
    return WatchListResponse(items=await list_watch(state["pg_pool"], uid))


@app.post("/api/prices/watch", response_model=WatchMutationResponse,
          status_code=status.HTTP_201_CREATED)
async def prices_watch_add(body: WatchRequest, uid: int = Depends(get_current_user)):
    try:
        created = await add_watch(state["pg_pool"], uid, body.item_id)
    except Exception as exc:                       # FK 위반 = 없는 품목
        if "price_watch_item_id_fkey" in str(exc) or "foreign key" in str(exc).lower():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown item_id")
        raise
    return WatchMutationResponse(item_id=body.item_id, watching=True, created=created)


@app.delete("/api/prices/watch/{item_id}", response_model=WatchMutationResponse)
async def prices_watch_remove(item_id: int, uid: int = Depends(get_current_user)):
    if not await remove_watch(state["pg_pool"], uid, item_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not watching this item")
    return WatchMutationResponse(item_id=item_id, watching=False)


@app.get("/api/prices/{item_id}/history", response_model=PriceHistory)
async def prices_history(item_id: int, limit: int = Query(settings.history_limit, ge=1, le=1000)):
    return await price_history(state["pg_pool"], item_id, limit)


# ⚠️ '/api/prices/{item_id}' 보다 먼저 선언 — 'trends'가 int item_id로 파싱되지 않게.
@app.get("/api/prices/trends", response_model=TrendResponse)
async def prices_trends(days: int = Query(7, ge=2, le=30), limit: int = Query(6, ge=1, le=12)):
    return await price_trends(state["pg_pool"], days, limit)


@app.get("/api/prices/{item_id}", response_model=CurrentPrice)
async def prices_current(item_id: int):
    async def produce() -> str | None:
        cp = await current_price(state["pg_pool"], item_id)
        return None if cp is None else cp.model_dump_json()   # 404는 캐시 안 함(품목 생기면 즉시 반영)

    body = await cached_json(f"price:current:{item_id}", settings.cache_current_ttl_s, produce)
    if body is None:
        raise HTTPException(status_code=404, detail="item not found")
    return CurrentPrice.model_validate_json(body)
