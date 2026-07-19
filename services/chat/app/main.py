"""Chat Service — RAG 5단계 파이프라인(①질문분석 ②병렬검색 ③컨텍스트조립 ④생성 ⑤응답조립).
`docs/chat-assistant-ai.md` §2 대응, 구현계획 zesty-mapping-firefly.md 참고.
"""
from __future__ import annotations

import asyncio
import re
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
from app.models import ActionButton, ChatRequest, ChatResponse
from app.observability import configure_service_logger
from app.pipeline.context import assemble
from app.pipeline.extract import extract, get_span_extractor
from app.pipeline import feature_nav
from app.pipeline.generator.factory import get_generator
from app.pipeline.guardrails import check_daily_cap, check_input, monthly_budget_exceeded, valid_session_id
from app.pipeline.respond import build_response
from app.pipeline.search import build_sources, fan_out
from app.pipeline.generator.template import _as_int, _is_staple, TemplateGenerator
from app.pipeline.recipe_cost import batch_costs, unit_costs
from app.pipeline.account_client import add_excluded_items, get_excluded_item_ids
from app.pipeline.session import (
    add_dislikes, add_shown_recipes, append_turn, get_dislikes, get_recipes,
    get_shown_recipes, load_history, set_recipes,
)
from app.tracing import configure_tracing, start_span
from app.vendor.gazetteer import STOP, load_gazetteer, load_meat_canons, make_matcher

log = configure_service_logger(
    service="chat",
    environment=settings.environment,
    level=settings.log_level,
)
state: dict = {}
_init_lock = asyncio.Lock()


def _load_matcher() -> tuple[Callable, dict[int, str], dict[str, int]]:
    """gazetteer 시작 시 1회 동기 로드. matcher + item_id→표준품목명 역맵(재료비 라벨용)
    + 재료 인덱스(표면형→item_id, 근거대조용) 반환."""
    conninfo = (
        f"host={settings.pghost} port={settings.pgport} "
        f"dbname={settings.pgdatabase} user={settings.pguser} password={settings.pgpassword}"
    )
    with psycopg.connect(conninfo) as conn, conn.cursor() as cur:
        gaz = load_gazetteer(cur)
        meat_canons = load_meat_canons(cur)      # 종세분화 가드(정책2)
    names_by_id = {iid: canon for (iid, canon) in gaz.values() if iid is not None}
    # 근거대조 재료 어휘 — 표면형(공백제거)→item_id. 1글자 표면형은 오탐 커서 제외.
    ingredient_index = {s: iid for s, (iid, _c) in gaz.items() if iid is not None and len(s) >= 2}
    return make_matcher(gaz, meat_canons), names_by_id, ingredient_index


async def _init_pipeline() -> None:
    """의존성(PG·ES·Redis·gazetteer) 초기화. 하나라도 실패하면 열린 PG 풀을 롤백하고
    예외를 올린다(호출측이 degraded 판단). 성공 시에만 state 를 원자적으로 채운다."""
    pool = make_pg_pool()
    try:
        await pool.open()
        es_client = make_es_client()
        redis_client = make_redis_client()
        matcher, item_names, ingredient_index = _load_matcher()
    except Exception:
        await pool.close()                     # 부분 초기화 롤백 — 열린 풀 누수 방지
        raise
    state.update(
        {
            "pg_pool": pool,
            "es_client": es_client,
            "redis_client": redis_client,
            "matcher": matcher,
            "item_names": item_names,          # item_id→표준명(recipe_cost 재료 라벨)
            "span_extractor": get_span_extractor(matcher, STOP),
            "generator": get_generator(redis_client=redis_client, ingredient_index=ingredient_index),
            "template_generator": TemplateGenerator(),   # 상한 초과 시 강등용(무료·근거바닥)
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


_GREETINGS = ("안녕", "하이", "반가", "hello", "hi", "헬로", "여보세요")
_THANKS = ("고마", "감사", "잘 먹을", "맛있겠", "굿")


def _serving_num(text) -> int | None:
    """'4인분'→4 (레시피 기본 인분 파싱)."""
    m = re.search(r"(\d+)", str(text or ""))
    return int(m.group(1)) if m else None


def _social_reply(message: str) -> str | None:
    """인사·감사 등 짧은 소셜 발화 → 고정 친근 응답(검색·생성 불필요)."""
    m = message.strip().lower()
    if len(m) <= 12 and any(g in m for g in _GREETINGS):
        return "안녕하세요! 밥풀이예요 🐶 레시피·가격·영양이 궁금하면 물어보세요!"
    if len(m) <= 12 and any(t in m for t in _THANKS):
        return "천만에요! 맛있게 드세요 😊"
    return None


_RATE_BANNER = "오늘 이용량이 많아 잠시 간단 안내 모드로 답했어요."


async def _handle_chat(
    req: ChatRequest, auth_token: str | None = None, client_ip: str | None = None
) -> ChatResponse:
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

        # 인사·감사 등 소셜 발화 — 검색 없이 즉답(고정 응답이라 하드코딩이 즉답·0원으로 효율적).
        social = _social_reply(req.message)
        if social:
            request_span.set_attribute("chat.result", "social")
            return ChatResponse(reply=social)

        # 세션 ID 검증 — 클라이언트가 임의 문자열/타인 세션을 주입하지 못하게 형식 강제.
        #   유효하지 않으면 무시(→ 새 세션 발급). 없으면 None.
        client_session = req.session_id if valid_session_id(req.session_id) else None

        # 기능 안내 — "레시피 등록" 등 앱 기능 요청 → 인앱 라우트 딥링크(검색 없이 즉답).
        feature = feature_nav.match(req.message)
        if feature:
            request_span.set_attribute("chat.result", "feature_nav")
            return ChatResponse(reply=feature["reply"],
                                actions=feature_nav.build_actions(feature),
                                session_id=client_session)

        # 멀티턴 세션 로드(opt-in) — OFF면 history=None → 기존 단일턴과 완전 동일.
        session_id: str | None = None
        history: list[dict] | None = None
        if settings.multiturn_enabled:
            session_id = client_session or uuid.uuid4().hex
            history = await load_history(state["redis_client"], session_id)

        with start_span("chat.extract") as extract_span:
            query = await extract(req.message, state["matcher"], state["span_extractor"], history)
            extract_span.set_attribute("chat.intent", query.intent)
            extract_span.set_attribute("chat.multiturn", settings.multiturn_enabled)
            extract_span.set_attribute("chat.extracted_item_count", len(query.item_ids))

        # 제외/비선호 재료 '등록' 의도 — 검색보다 먼저 처리(레시피 검색으로 새지 않게).
        #  추천 의도("빼고 추천")는 아래 추천 흐름 유지 — 여기선 '순수 등록'만(intent≠recommend).
        #  멀티턴 OFF여도 동작: 등록된 재료는 (계정연동 시)영속·(멀티턴 시)세션, 둘 다 OFF면 마이페이지 유도.
        if query.exclude_request and query.intent != "recommend":
            nmap = state.get("item_names", {})
            targets = query.disliked_item_ids   # 마커+아이템이면 채워짐(청양고추 등 known 재료)
            excl_actions = [ActionButton(action="navigate", label="제외 재료 설정 열기", route="/my")]
            if targets:
                names = [nmap.get(i) for i in targets if nmap.get(i)]
                label = ", ".join(names) if names else "해당 재료"
                account_persisted = False   # 마이 페이지(account.user_excluded_item) 영속
                session_stored = False       # 세션(Redis, 이번 대화 한정)
                if settings.account_integration_enabled and auth_token:
                    await add_excluded_items(auth_token, [(i, nmap.get(i) or "") for i in targets])
                    account_persisted = True
                if settings.multiturn_enabled and session_id:
                    await add_dislikes(state["redis_client"], session_id, targets)
                    session_stored = True
                # 메시지는 '실제 저장된 범위'만 주장(마이페이지 반영 여부로 문구 구분 — 거짓 등록 안내 금지).
                if account_persisted:
                    request_span.set_attribute("chat.result", "exclude_registered")
                    return ChatResponse(reply=f"{label}를 제외 재료로 등록했어요. 앞으로 추천에서 빼드릴게요!",
                                        session_id=session_id)
                if session_stored:
                    # 세션에만 저장됨(마이 페이지 영속 X — 계정연동 대기). 이번 대화 스코프임을 명시 + 영구등록 유도.
                    request_span.set_attribute("chat.result", "exclude_session_only")
                    return ChatResponse(
                        reply=(f"이번 대화에서는 {label}를 빼고 추천할게요. "
                               f"계속(영구) 제외하려면 마이 페이지 > 제외 재료 설정에서 등록해 주세요."),
                        session_id=session_id, actions=excl_actions)
                # 저장할 곳이 없음(계정연동·멀티턴 모두 OFF) → 마이 페이지 유도
                request_span.set_attribute("chat.result", "exclude_guide_known")
                return ChatResponse(reply=f"{label}는 마이 페이지 > 제외 재료 설정에서 등록할 수 있어요.",
                                    session_id=session_id, actions=excl_actions)
            # 우리 데이터에 없는 재료(item_master 미등재) — 정직히 안내(레시피 검색 금지)
            request_span.set_attribute("chat.result", "exclude_unresolved")
            return ChatResponse(reply=("제외하고 싶으신 재료를 저희 재료 목록에서 찾지 못했어요 🥲 "
                                       "아직 서비스에 등록되지 않은 재료일 수 있어요. "
                                       "마이 페이지 > 제외 재료 설정에서 등록된 재료로 관리하실 수 있어요."),
                                session_id=session_id, actions=excl_actions)

        # recipe_cost: 직전 추천 레시피의 재료 전체를 가격조회 대상으로 주입(검색 前).
        if query.intent == "recipe_cost" and session_id:
            recipes = await get_recipes(state["redis_client"], session_id)
            if recipes:
                target = recipes[0]
                ids = [int(i) for i in target.get("ingredient_item_ids", [])]
                query.item_ids = ids
                # 이름은 item_master 역맵으로 해석 — 레시피의 ingredient_names는 ids와 정렬이
                # 어긋나(가나다순 vs 숫자순) 신뢰 불가. id→표준명이 정답.
                nmap = state.get("item_names", {})
                query.item_names = [nmap.get(i) for i in ids]
                query.recipe_name = target.get("name")
                # 용량×단가 정확 비용(무게 표기 재료분) — recipe_id로 용량·단가 조회(read-only)
                rid = target.get("recipe_id")
                if rid is not None:
                    try:
                        async with state["pg_pool"].connection() as conn, conn.cursor() as cur:
                            query.unit_costs = await unit_costs(cur, int(rid))
                    except Exception:
                        query.unit_costs = {}
                    # 인분 반영 — 요청 인분 / 레시피 기본 인분 비율로 정확분(용량) 스케일
                    if query.servings and query.unit_costs:
                        base = _serving_num(target.get("serving"))
                        if base and base > 0:
                            scale = query.servings / base
                            query.unit_costs = {k: max(1, round(v * scale)) for k, v in query.unit_costs.items()}

        # 세션 개인화 — 비선호 재료 (+ account 마이 페이지 제외재료 양방향 연동; flag OFF면 무동작)
        if settings.multiturn_enabled and session_id:
            nmap = state.get("item_names", {})
            if query.disliked_item_ids:
                # 비선호 등록 턴 → 세션 저장 + (인증 시)마이 페이지 영속 + 확인 응답(검색 스킵).
                await add_dislikes(state["redis_client"], session_id, query.disliked_item_ids)
                await add_excluded_items(auth_token, [(i, nmap.get(i) or "") for i in query.disliked_item_ids])
                dnames = [nmap[i] for i in query.disliked_item_ids if nmap.get(i)]
                if dnames:
                    reply = f"알겠어요, {', '.join(dnames)}는 빼고 추천할게요! 어떤 요리가 궁금하세요?"
                    await append_turn(state["redis_client"], session_id, "user", req.message)
                    await append_turn(state["redis_client"], session_id, "bot", reply)
                    return ChatResponse(reply=reply, session_id=session_id)
            # 세션 비선호 + 마이 페이지 제외재료(account, 인증 시) 합산 적용
            merged = set(await get_dislikes(state["redis_client"], session_id))
            merged.update(await get_excluded_item_ids(auth_token))
            query.disliked_item_ids = list(merged)
            # 이미 보여준 레시피 → 추천 중복 방지("다른 추천은?")
            query.exclude_recipe_ids = await get_shown_recipes(state["redis_client"], session_id)

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

        # 예산 기반 추천 — 후보 레시피 재료비를 배치 계산해 부착(생성기가 예산으로 필터·표기)
        if query.intent == "recommend" and query.budget_won and ctx.recipes:
            rids = [i for r in ctx.recipes if (i := _as_int(r.get("recipe_id"))) is not None]
            if rids:
                try:
                    async with state["pg_pool"].connection() as conn, conn.cursor() as cur:
                        costs = await batch_costs(cur, rids, state.get("item_names", {}), _is_staple)
                    for r in ctx.recipes:
                        rid = _as_int(r.get("recipe_id"))
                        if rid in costs:
                            r["_cost"] = costs[rid]
                except Exception:
                    pass

        # 비용/DoS 상한(가드레일 §7) — 유료 생성(Gemini) 백엔드에서 identity(유저/IP)별 일일
        #   상한 초과 시 무료 template로 강등(요청 차단 아님 — 데이터는 계속 나감). 기본 flag OFF.
        gen = state["generator"]
        degraded = False
        if settings.generator_backend != "template":
            # 일일 상한(유저/IP별 남용) + 월 예산 상한(글로벌 비용 폭주) — 하나라도 초과면 template 강등.
            over_daily = settings.rate_limit_enabled and not await check_daily_cap(
                req.user_id or client_ip, state["redis_client"])
            over_monthly = settings.monthly_cap_enabled and await monthly_budget_exceeded(
                state["redis_client"])
            if over_daily or over_monthly:
                gen = state["template_generator"]
                degraded = True

        with start_span(
            "chat.generate",
            attributes={"chat.generator.type": settings.generator_backend},
        ) as generate_span:
            answer = await gen.generate(query, ctx)
            generate_span.set_attribute("chat.answer.basis_count", len(answer.basis))
            generate_span.set_attribute("chat.generator.degraded", degraded)

        with start_span("chat.response.build") as response_span:
            response = build_response(answer, ctx, query)
            if degraded:
                response.reply = f"{response.reply}\n\n{_RATE_BANNER}"
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
                    recipes.append({"name": r["name"], "recipe_id": r.get("recipe_id"),
                                    "serving": r.get("serving"),
                                    "ingredient_item_ids": fids, "ingredient_names": fnms})
                if recipes:
                    await set_recipes(redis_client, session_id, recipes)
                    await add_shown_recipes(redis_client, session_id,
                                            [r["recipe_id"] for r in recipes if r.get("recipe_id")])
        return response


# 인증 갭: Gateway/User 서비스가 없어 JWT 체계 자체가 없다. user_id는 옵션 바디 필드로만
# 받고 검증하지 않는다 — 이 엔드포인트는 현재 "누구나 호출 가능한 데모용"이다.
def _client_ip(request: Request) -> str | None:
    """레이트리밋 identity용 IP — 프록시/게이트웨이 뒤면 X-Forwarded-For 첫 홉 우선."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request) -> ChatResponse:
    return await _handle_chat(req, request.headers.get("authorization"), _client_ip(request))


# docs/design/api-spec.md #37 스펙과 정합되는 별칭 — Gateway가 생기면 코드 변경 없이 프록시 가능
@app.post("/api/mealplan/assistant/chat", response_model=ChatResponse)
async def chat_alias(req: ChatRequest, request: Request) -> ChatResponse:
    return await _handle_chat(req, request.headers.get("authorization"), _client_ip(request))
