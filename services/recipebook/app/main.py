"""RecipeBook Service — 레시피 북마크(스크랩). api-spec #20~22.

★ 신원은 account가 발급한 JWT를 **신뢰**(재검증 안 함) — 여기선 verify_access만.
★ 주입 패턴(account 레퍼런스 복제): 전역 state[...] 대신 AppCtx(context.py)를 Depends로 주입.
   테이블 = recipebook.bookmark 만 소유(user_recipe·extract_job 은 AI 담당 #24~25 몫).
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import Settings
from app.context import AppCtx
from app.db import make_pg_pool
from app.observability import configure_service_logger
from app.routers import book
from app.security import Security


log = configure_service_logger(service="recipebook")


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
    log.info("recipebook service started", extra={"event": "service_started"})
    try:
        yield
    finally:
        await pool.close()
        log.info("recipebook service stopped", extra={"event": "service_stopped"})


app = FastAPI(title="RecipeBook Service", version="0.1.0", lifespan=lifespan)
Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    should_instrument_requests_inprogress=True,
    excluded_handlers=[r"^/metrics$", r"^/health$"],
    inprogress_name="http_requests_inprogress",
    inprogress_labels=True,
).instrument(app).expose(app, include_in_schema=False)
app.include_router(book)


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
        log.error("unhandled recipebook request failure", extra=fields)
        raise


@app.get("/health")
async def health():
    return {"status": "ok", "service": "recipebook"}
