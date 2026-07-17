"""Chat Service — RAG 5단계 파이프라인(①질문분석 ②병렬검색 ③컨텍스트조립 ④생성 ⑤응답조립).
`docs/chat-assistant-ai.md` §2 대응, 구현계획 zesty-mapping-firefly.md 참고.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import settings
from app.db import make_es_client, make_pg_pool, make_redis_client
from app.models import ChatRequest, ChatResponse
from app.observability import configure_service_logger
from app.pipeline.context import assemble
from app.pipeline.extract import extract, get_span_extractor
from app.pipeline.generator.factory import get_generator
from app.pipeline.guardrails import check_input
from app.pipeline.respond import build_response
from app.pipeline.search import build_sources, fan_out
from app.pipeline.session import append_turn, get_recipes, load_history, set_recipes
from app.tracing import configure_tracing, start_span
from app.vendor.gazetteer import STOP, load_gazetteer, make_matcher

log = configure_service_logger(
    service="chat",
    environment=settings.environment,
    level=settings.log_level,
)
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
            log.info(
                "chat pipeline dependencies recovered",
                extra={"event": "dependency_recovered", "dependency": "chat_pipeline"},
            )
            return True
        except Exception as exc:
            log.warning(
                "chat pipeline dependencies remain unavailable",
                extra={
                    "event": "dependency_unavailable",
                    "dependency": "chat_pipeline",
                    "error_type": type(exc).__name__,
                    "retryable": True,
                },
            )
            return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    # degraded 부팅 — 의존성이 없어도 프로세스는 살려서 /health 응답·요청별 재시도 가능.
    # (일시적 PG blip 에 startup 크래시→502→docker 재시작 루프 나던 것을 방지)
    state["ready"] = False
    try:
        await _init_pipeline()
        log.info("chat service started", extra={"event": "service_started"})
    except Exception as exc:
        state["startup_error"] = repr(exc)
        log.error(
            "chat service started with unavailable dependencies",
            extra={
                "event": "dependency_unavailable",
                "dependency": "chat_pipeline",
                "error_type": type(exc).__name__,
                "retryable": True,
            },
        )
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
        log.info("chat service stopped", extra={"event": "service_stopped"})


app = FastAPI(title="food-budget-app chat service", lifespan=lifespan)
configure_tracing(
    app,
    service_name="chat",
    environment=settings.environment,
    endpoint=settings.otel_exporter_otlp_endpoint,
    enabled=settings.otel_traces_enabled,
    insecure=settings.otel_exporter_otlp_insecure,
    sample_ratio=settings.otel_traces_sampler_ratio,
)
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
    """응답 형식은 건드리지 않고 처리되지 않은 요청 예외만 구조화 기록한다."""
    try:
        return await call_next(request)
    except Exception as exc:
        route = request.scope.get("route")
        route_template = getattr(route, "path", None)
        fields = {
            "event": "request_failed",
            "method": request.method,
            "error_type": type(exc).__name__,
            "retryable": False,
        }
        if route_template:
            fields["route"] = route_template
        log.error("unhandled chat request failure", extra=fields)
        raise


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
    with start_span("chat.request") as request_span:
        if not await _ensure_ready():             # degraded → 크래시 대신 정중한 안내(502 아님)
            request_span.set_attribute("chat.result", "dependency_unavailable")
            request_span.set_attribute("chat.unanswered", True)
            return ChatResponse(
                reply="지금은 어시스턴트를 일시적으로 사용할 수 없어요. 잠시 후 다시 시도해 주세요.",
                unanswered=True,
            )

        with start_span("chat.input.check") as input_span:
            ok, reason = check_input(req.message)
            input_span.set_attribute("chat.input.accepted", ok)
        if not ok:
            request_span.set_attribute("chat.result", "rejected")
            request_span.set_attribute("chat.unanswered", True)
            log.info(
                "chat input rejected by guardrail",
                extra={"event": "chat_input_rejected", "result": "rejected"},
            )
            return ChatResponse(reply=reason or "요청을 처리할 수 없어요.", unanswered=True)

        # 멀티턴 세션 로드(opt-in) — OFF면 history=None → 기존 단일턴과 완전 동일.
        session_id: str | None = None
        history: list[dict] | None = None
        if settings.multiturn_enabled:
            session_id = req.session_id or uuid.uuid4().hex
            history = await load_history(state["redis_client"], session_id)

        with start_span("chat.extract") as extract_span:
            query = await extract(req.message, state["matcher"], state["span_extractor"], history)
            extract_span.set_attribute("chat.intent", query.intent)
            extract_span.set_attribute("chat.multiturn", settings.multiturn_enabled)
            extract_span.set_attribute("chat.extracted_item_count", len(query.item_ids))

        # recipe_cost: 직전 추천 레시피의 재료 전체를 가격조회 대상으로 주입(검색 前).
        if query.intent == "recipe_cost" and session_id:
            recipes = await get_recipes(state["redis_client"], session_id)
            if recipes:
                target = recipes[0]
                query.item_ids = [int(i) for i in target.get("ingredient_item_ids", [])]
                query.item_names = list(target.get("ingredient_names", []))   # 내역 라벨용
                query.recipe_name = target.get("name")

        with start_span("chat.search") as search_span:
            results = await fan_out(state["sources"], query)
            unavailable_sources = [
                result.source
                for result in results
                if not result.available and result.reason != "not_implemented_mvp"
            ]
            search_span.set_attribute("chat.search.source_count", len(results))
            search_span.set_attribute("chat.search.unavailable_count", len(unavailable_sources))

        for search_result in results:
            if not search_result.available and search_result.reason != "not_implemented_mvp":
                log.warning(
                    "chat search source unavailable",
                    extra={
                        "event": "chat_search_source_failed",
                        "dependency": search_result.source,
                        "result": "unavailable",
                        "retryable": True,
                    },
                )

        with start_span("chat.context.build") as context_span:
            ctx = assemble(query.item_ids, results)
            context_span.set_attribute("chat.context.recipe_count", len(ctx.recipes))
            context_span.set_attribute("chat.context.price_item_count", len(ctx.prices))
            context_span.set_attribute("chat.context.nutrition_item_count", len(ctx.nutrition))
            context_span.set_attribute(
                "chat.context.unavailable_source_count",
                len(ctx.unavailable_sources),
            )

        with start_span(
            "chat.generate",
            attributes={"chat.generator.type": settings.generator_backend},
        ) as generate_span:
            answer = await state["generator"].generate(query, ctx)
            generate_span.set_attribute("chat.answer.basis_count", len(answer.basis))

        with start_span("chat.response.build") as response_span:
            response = build_response(answer, ctx, query)
            response_span.set_attribute("chat.response.unanswered", response.unanswered)
            response_span.set_attribute("chat.response.action_count", len(response.actions))

        request_span.set_attribute("chat.intent", query.intent)
        request_span.set_attribute("chat.result", "unanswered" if response.unanswered else "answered")
        request_span.set_attribute("chat.unanswered", response.unanswered)
        if response.unanswered:
            log.warning(
                "chat response has no supporting basis",
                extra={"event": "chat_unanswered", "result": "unanswered"},
            )

        # 멀티턴 세션 저장(opt-in) — user·bot 턴 적재 + 세션 반환(클라이언트 재전송용).
        if settings.multiturn_enabled and session_id:
            response.session_id = session_id
            redis_client = state["redis_client"]
            await append_turn(redis_client, session_id, "user", req.message,
                              item_ids=query.item_ids, item_names=query.item_names, intent=query.intent)
            await append_turn(redis_client, session_id, "bot", response.reply,
                              item_ids=query.item_ids, item_names=query.item_names, intent=query.intent)
            # recipe_cost용: 추천된 레시피(이름 + 재료 item_ids·names 병렬)를 세션에 저장
            if query.intent == "recommend" and answer.basis:
                rec_names = {b.detail for b in answer.basis if b.type == "recipe_match"}
                recipes = []
                for r in ctx.recipes:
                    if r.get("name") not in rec_names:
                        continue
                    ids = r.get("ingredient_item_ids") or []
                    nms = r.get("ingredient_names") or []
                    fids, fnms = [], []
                    for k, i in enumerate(ids):
                        if str(i).isdigit():
                            fids.append(int(i))
                            fnms.append(nms[k] if k < len(nms) else None)
                    recipes.append({"name": r["name"], "ingredient_item_ids": fids, "ingredient_names": fnms})
                if recipes:
                    await set_recipes(redis_client, session_id, recipes)
        return response


# 인증 갭: Gateway/User 서비스가 없어 JWT 체계 자체가 없다. user_id는 옵션 바디 필드로만
# 받고 검증하지 않는다 — 이 엔드포인트는 현재 "누구나 호출 가능한 데모용"이다.
@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    return await _handle_chat(req)


# docs/design/api-spec.md #37 스펙과 정합되는 별칭 — Gateway가 생기면 코드 변경 없이 프록시 가능
@app.post("/api/mealplan/assistant/chat", response_model=ChatResponse)
async def chat_alias(req: ChatRequest) -> ChatResponse:
    return await _handle_chat(req)
