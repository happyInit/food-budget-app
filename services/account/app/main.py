"""Account Service — Auth(로그인·JWT 발급) + User(프로필·월 예산). api-spec #2~10.

★ 신원의 뿌리: 여기서 JWT를 발급하면 나머지 서비스는 그 user_id를 **신뢰**(재검증 안 함).
★ 주입 패턴(레퍼런스): 전역 state[...] 대신 AppCtx(context.py)를 Depends로 주입 → 핸들러 테스트 가능.
   두 명이 각 서비스 만들 때 이 구조(config·db·context·security·models·queries·routers·main)를 복사.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import Settings
from app.context import AppCtx
from app.db import make_pg_pool
from app.oauth import (
    GoogleProvider,
    KakaoProvider,
    OAuthClients,
    WARMUP_URLS,
    make_http_client,
    warm_dns,
)
from app.observability import configure_service_logger
from app.routers import auth, users
from app.security import Security
from app.throttle import LoginThrottle


log = configure_service_logger(service="account")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    pool = make_pg_pool(settings)
    await pool.open()
    http = make_http_client()          # provider 공유 커넥션 풀(매 로그인 새로 열지 않음)
    warmup = asyncio.create_task(warm_dns(WARMUP_URLS))  # DNS 선캐싱(백그라운드·기동 안 막음)
    app.state.ctx = AppCtx(
        pool=pool,
        settings=settings,
        security=Security(
            settings.jwt_secret, settings.jwt_alg,
            settings.access_ttl_min, settings.refresh_ttl_days,
        ),
        oauth=OAuthClients(
            kakao=KakaoProvider(settings.kakao_client_id, settings.kakao_client_secret,
                                settings.kakao_redirect_uri, http),
            google=GoogleProvider(settings.google_client_id, settings.google_client_secret,
                                  settings.google_redirect_uri, http),
        ),
        throttle=LoginThrottle(
            bcrypt_max_concurrent=settings.login_bcrypt_max_concurrent,
            bcrypt_max_waiting=settings.login_bcrypt_max_waiting,
            per_email=settings.login_rate_per_email,
            per_ip=settings.login_rate_per_ip,
            window_s=settings.login_rate_window_s,
        ),
    )
    log.info("account service started", extra={"event": "service_started"})
    try:
        yield
    finally:
        warmup.cancel()
        try:
            await warmup
        except asyncio.CancelledError:
            pass
        await http.aclose()
        await pool.close()
        log.info("account service stopped", extra={"event": "service_stopped"})


app = FastAPI(title="Account Service", version="0.1.0", lifespan=lifespan)
Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    should_instrument_requests_inprogress=True,
    excluded_handlers=[r"^/metrics$", r"^/health$"],
    inprogress_name="http_requests_inprogress",
    inprogress_labels=True,
).instrument(app).expose(app, include_in_schema=False)
app.include_router(auth)
app.include_router(users)


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
        log.error("unhandled account request failure", extra=fields)
        raise


@app.get("/health")
async def health():
    return {"status": "ok", "service": "account"}
