"""Chat Service — RAG 5단계 파이프라인(①질문분석 ②병렬검색 ③컨텍스트조립 ④생성 ⑤응답조립).
`docs/chat-assistant-ai.md` §2 대응, 구현계획 zesty-mapping-firefly.md 참고.
"""
from __future__ import annotations

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

state: dict = {}


def _load_matcher() -> Callable:
    """gazetteer는 시작 시 1회 동기 로드(psycopg sync) — 요청마다 다시 안 읽음."""
    conninfo = (
        f"host={settings.pghost} port={settings.pgport} "
        f"dbname={settings.pgdatabase} user={settings.pguser} password={settings.pgpassword}"
    )
    with psycopg.connect(conninfo) as conn, conn.cursor() as cur:
        gaz = load_gazetteer(cur)
    return make_matcher(gaz)


@asynccontextmanager
async def lifespan(app: FastAPI):
    state["pg_pool"] = make_pg_pool()
    await state["pg_pool"].open()
    state["es_client"] = make_es_client()
    state["redis_client"] = make_redis_client()
    state["matcher"] = _load_matcher()
    state["span_extractor"] = get_span_extractor(state["matcher"], STOP)
    state["generator"] = get_generator(redis_client=state["redis_client"])
    state["sources"] = build_sources(state["pg_pool"], state["es_client"])
    try:
        yield
    finally:
        await state["pg_pool"].close()
        await state["es_client"].close()
        await state["redis_client"].aclose()


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
    return {"status": "ok"}


async def _handle_chat(req: ChatRequest) -> ChatResponse:
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
