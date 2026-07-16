"""Recipe Service — 레시피 탐색·상세 (데이터 티어 읽기).
docs/design/api-spec.md #18 GET /api/recipes · #19 GET /api/recipes/{id}.
JWT 미검증(Gateway/Auth 서비스 나오면 추가) — chat 서비스와 동일 방침.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import settings
from app.db import make_es_client, make_pg_pool
from app.models import RecipeDetail, RecipeListResponse
from app.observability import configure_service_logger
from app.queries import get_detail, search_es, search_pg

state: dict = {}
log = configure_service_logger(service="recipe")


@asynccontextmanager
async def lifespan(app: FastAPI):
    state["pg_pool"] = make_pg_pool()
    await state["pg_pool"].open()
    # 검색 백엔드 ES면 클라이언트 오픈(리스트·검색 통일). 상세(#19)는 항상 PG.
    state["es"] = make_es_client() if settings.search_backend == "es" else None
    log.info("recipe service started",
             extra={"event": "service_started", "component": settings.search_backend})
    try:
        yield
    finally:
        await state["pg_pool"].close()
        if state.get("es") is not None:
            await state["es"].close()
        log.info("recipe service stopped", extra={"event": "service_stopped"})


app = FastAPI(title="Recipe Service", version="0.1.0", lifespan=lifespan)
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
        log.error("unhandled recipe request failure", extra=fields)
        raise


@app.get("/health")
async def health():
    return {"status": "ok", "service": "recipe"}


@app.get("/api/recipes", response_model=RecipeListResponse)
async def list_recipes(
    q: str | None = Query(None, description="레시피명·재료 검색어"),
    tag: str | None = Query(None, description="카테고리(요리종류) 필터"),
    cooking_time: str | None = Query(None, description="조리시간 태그 (예: '15분 이내')"),
    level: str | None = Query(None, description="난이도 태그 (예: '아무나')"),
    page: int = Query(1, ge=1),
    size: int = Query(settings.page_size, ge=1, le=100),
):
    # 리스트·검색 모두 ES(nori) 기준으로 통일. ES 장애 시 PG로 자동 degrade(검색 완전 실패 방지).
    if state.get("es") is not None:
        try:
            cards, total = await search_es(state["es"], q, tag, page, size, cooking_time, level)
            return RecipeListResponse(recipes=cards, page=page, size=size, total=total)
        except Exception as exc:  # noqa: BLE001 — ES 장애가 검색 전체를 막으면 안 됨
            log.warning("recipe search fell back to PG",
                        extra={"event": "dependency_unavailable", "dependency": "elasticsearch",
                               "error_type": type(exc).__name__, "retryable": True})
    cards, total = await search_pg(state["pg_pool"], q, tag, page, size, cooking_time, level)
    return RecipeListResponse(recipes=cards, page=page, size=size, total=total)


@app.get("/api/recipes/{recipe_id}", response_model=RecipeDetail)
async def recipe_detail(recipe_id: int):
    detail = await get_detail(state["pg_pool"], recipe_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="recipe not found")
    return detail
