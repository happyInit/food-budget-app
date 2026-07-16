"""Chat Service — RAG 5단계 파이프라인(①질문분석 ②병렬검색 ③컨텍스트조립 ④생성 ⑤응답조립).
`docs/chat-assistant-ai.md` §2 대응, 구현계획 zesty-mapping-firefly.md 참고.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

import psycopg
from fastapi import FastAPI
from fastapi.responses import FileResponse
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import settings
from app.db import make_es_client, make_pg_pool, make_redis_client
from app.models import ChatRequest, ChatResponse
from app.pipeline.context import assemble
from app.pipeline.extract import extract, get_span_extractor
from app.pipeline.generator.factory import get_generator
from app.pipeline.guardrails import check_input
from app.pipeline.respond import build_response
from app.pipeline.search import build_sources, fan_out
from app.vendor.gazetteer import STOP, load_gazetteer, make_matcher

log = logging.getLogger("chat")
state: dict = {}
_init_lock = asyncio.Lock()


def _load_matcher() -> Callable:
    """gazetteer는 시작 시 1회 동기 로드(psycopg sync) — 요청마다 다시 안 읽음."""
    conninfo = (
        f"host={settings.pghost} port={settings.pgport} "
        f"dbname={settings.pgdatabase} user={settings.pguser} password={settings.pgpassword}"
    )
    with psycopg.connect(conninfo) as conn, conn.cursor() as cur:
        gaz = load_gazetteer(cur)
    return make_matcher(gaz)


async def _init_pipeline() -> None:
    """의존성(PG·ES·Redis·gazetteer) 초기화. 하나라도 실패하면 열린 PG 풀을 롤백하고
    예외를 올린다(호출측이 degraded 판단). 성공 시에만 state 를 원자적으로 채운다."""
    pool = make_pg_pool()
    try:
        await pool.open()
        es_client = make_es_client()
        redis_client = make_redis_client()
        matcher = _load_matcher()
    except Exception:
        await pool.close()                     # 부분 초기화 롤백 — 열린 풀 누수 방지
        raise
    state.update(
        {
            "pg_pool": pool,
            "es_client": es_client,
            "redis_client": redis_client,
            "matcher": matcher,
            "span_extractor": get_span_extractor(matcher, STOP),
            "generator": get_generator(redis_client=redis_client),
            "sources": build_sources(pool, es_client),
            "ready": True,
        }
    )


async def _ensure_ready() -> bool:
    """준비됐으면 True. 아니면 1회 재초기화 시도(일시적 PG 장애 자가복구) — 동시요청은 락으로 1회만."""
    if state.get("ready"):
        return True
    async with _init_lock:
        if state.get("ready"):                 # 락 대기 중 다른 요청이 복구했을 수 있음
            return True
        try:
            await _init_pipeline()
            log.info("chat pipeline recovered")
            return True
        except Exception as exc:
            log.warning("chat still degraded: %r", exc)
            return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    # degraded 부팅 — 의존성이 없어도 프로세스는 살려서 /health 응답·요청별 재시도 가능.
    # (일시적 PG blip 에 startup 크래시→502→docker 재시작 루프 나던 것을 방지)
    state["ready"] = False
    try:
        await _init_pipeline()
    except Exception as exc:
        state["startup_error"] = repr(exc)
        log.error("startup degraded — dependencies unavailable: %r", exc)
    try:
        yield
    finally:
        pool, es, redis = state.get("pg_pool"), state.get("es_client"), state.get("redis_client")
        if pool is not None:
            await pool.close()
        if es is not None:
            await es.close()
        if redis is not None:
            await redis.aclose()


app = FastAPI(title="food-budget-app chat service", lifespan=lifespan)
Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    should_instrument_requests_inprogress=True,
    excluded_handlers=[r"^/metrics$", r"^/health$"],
    inprogress_name="http_requests_inprogress",
    inprogress_labels=True,
).instrument(app).expose(app, include_in_schema=False)


_DEMO_HTML = Path(__file__).parent / "static" / "demo.html"


@app.get("/")
async def demo() -> FileResponse:
    """시연용 채팅 UI (같은 오리진 → CORS 불필요). API만 쓰려면 /chat 직접 호출."""
    return FileResponse(_DEMO_HTML)


@app.get("/health")
async def health() -> dict:
    # 프로세스 liveness — degraded 여도 200(재시작 루프 방지). 의존성 준비 상태는 필드로 노출.
    return {"status": "ok" if state.get("ready") else "degraded"}


async def _handle_chat(req: ChatRequest) -> ChatResponse:
    if not await _ensure_ready():             # degraded → 크래시 대신 정중한 안내(502 아님)
        return ChatResponse(
            reply="지금은 어시스턴트를 일시적으로 사용할 수 없어요. 잠시 후 다시 시도해 주세요.",
            unanswered=True,
        )
    ok, reason = check_input(req.message)
    if not ok:
        return ChatResponse(reply=reason or "요청을 처리할 수 없어요.", unanswered=True)

    query = await extract(req.message, state["matcher"], state["span_extractor"])
    results = await fan_out(state["sources"], query)
    ctx = assemble(query.item_ids, results)
    answer = await state["generator"].generate(query, ctx)
    return build_response(answer, ctx)


# 인증 갭: Gateway/User 서비스가 없어 JWT 체계 자체가 없다. user_id는 옵션 바디 필드로만
# 받고 검증하지 않는다 — 이 엔드포인트는 현재 "누구나 호출 가능한 데모용"이다.
@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    return await _handle_chat(req)


# docs/design/api-spec.md #37 스펙과 정합되는 별칭 — Gateway가 생기면 코드 변경 없이 프록시 가능
@app.post("/api/mealplan/assistant/chat", response_model=ChatResponse)
async def chat_alias(req: ChatRequest) -> ChatResponse:
    return await _handle_chat(req)
