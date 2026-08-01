"""Price Service — 현재가·이력·시세추천·핫딜 (데이터 티어 읽기).
docs/design/api-spec.md #26·#27·#28·#31. JWT 미검증(chat 서비스와 동일 방침).

라우트 순서 주의: 정적 경로(/recommend·/hotdeals)를 /{item_id} 보다 먼저 선언.
"""
from __future__ import annotations

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


async def _cache_get(key: str) -> str | None:
    """캐시 조회 — best-effort. redis 미가용/장애면 None(=미스)로 우회(엔드포인트 무손상)."""
    r = state.get("redis")
    if r is None:
        return None
    try:
        return await r.get(key)
    except Exception:              # noqa: BLE001 — 캐시 장애가 조회를 막지 않게
        return None


async def _cache_set(key: str, value: str, ttl: int) -> None:
    """캐시 저장 — best-effort. 실패는 무시(캐시는 조회 성능 보조일 뿐)."""
    r = state.get("redis")
    if r is None:
        return
    try:
        await r.set(key, value, ex=ttl)
    except Exception:              # noqa: BLE001
        pass


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
async def prices_hotdeals(limit: int = Query(settings.default_limit, ge=1, le=100)):
    key = f"price:hotdeals:{limit}"
    cached = await _cache_get(key)
    if cached is not None:
        return HotdealResponse.model_validate_json(cached)
    resp = HotdealResponse(deals=await hotdeals(state["pg_pool"], limit))
    await _cache_set(key, resp.model_dump_json(), settings.cache_hotdeals_ttl_s)
    return resp


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
    key = f"price:current:{item_id}"
    cached = await _cache_get(key)
    if cached is not None:
        return CurrentPrice.model_validate_json(cached)
    cp = await current_price(state["pg_pool"], item_id)
    if cp is None:                                  # 404는 캐시 안 함(품목 생기면 즉시 반영)
        raise HTTPException(status_code=404, detail="item not found")
    await _cache_set(key, cp.model_dump_json(), settings.cache_current_ttl_s)
    return cp
