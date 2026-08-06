"""RecipeBook Service — 레시피 북마크(스크랩). api-spec #20~22.

★ 신원은 account가 발급한 JWT를 **신뢰**(재검증 안 함) — 여기선 verify_access만.
★ 주입 패턴(account 레퍼런스 복제): 전역 state[...] 대신 AppCtx(context.py)를 Depends로 주입.
   테이블 = recipebook.bookmark + user_recipe(수동 등록·공유) 소유.
   extract_job(유튜브 URL 추출=Gemini) 은 여전히 AI 담당 몫 — 여기선 안 만든다.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import Settings
from app.context import AppCtx
from app.db import make_pg_pool
from app.observability import configure_service_logger
from app.routers import book, mine, shared
from app.security import Security


log = configure_service_logger(service="recipebook")


def make_es_client(settings: Settings):
    # 공개 발행 레시피 목록/검색용 ES 클라이언트. import 는 지연(테스트/무사용 시 로드 회피).
    from elasticsearch import AsyncElasticsearch

    # basic_auth: ECK(P2)는 인증 강제. env 없으면 생략 — 현행 VM ES(무인증) 동작 불변.
    auth = (settings.es_user, settings.es_password) if settings.es_user else None
    # ES 는 클러스터 내부 구간이고 TLS 미적용은 #521 에서 확정된 결정이다(인증 켬 · TLS 끔).
    # 외부 구간이 아니라 억제한다 — load_recipe.py 의 외부 http 는 신호로 남긴다.
    return AsyncElasticsearch(f"http://{settings.eshost}:{settings.esport}",  # NOSONAR(S5332)
                              basic_auth=auth)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    pool = make_pg_pool(settings)
    await pool.open()
    # 공개 발행 레시피 목록/검색용 ES 1회 생성 → AppCtx 에 담아 핸들러가 Depends 로 주입받는다.
    es = make_es_client(settings)
    app.state.ctx = AppCtx(
        pool=pool,
        settings=settings,
        security=Security(settings.jwt_secret, settings.jwt_alg),
        es=es,
    )
    log.info("recipebook service started", extra={"event": "service_started"})
    try:
        yield
    finally:
        await pool.close()
        # 🔴 ES 커넥션을 닫지 않으면 이벤트 루프 종료 시 경고가 뜨고 커넥션이 샌다(pool.close()와 같은 자리).
        await es.close()
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
app.include_router(mine)     # #24 내 레시피(수동 등록)
app.include_router(shared)   # #24 공개 공유 뷰(비인증)


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
