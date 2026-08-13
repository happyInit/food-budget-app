"""영상→레시피 추출 서비스 (독립 FastAPI).

`ml/video-recipe`의 파이프라인을 **얇게 감싸는 층**이다 — 추출·검증(H1~H5)·재분석·정제 로직은
전부 라이브러리에 있고, 여기서는 HTTP 계약·잡 수명·상태 저장만 책임진다(로직 이중화 금지).

비동기 잡 패턴(OCR과 동일): POST 202 접수 → job_id → GET 폴링.
영상 분석은 수십 초라 동기 응답이 불가하다.

⚠️ 이 서비스는 **Gemini 전용**이다. Bedrock은 YouTube URL 입력 자체가 없어 이관 대상이 아니다
   (`docs/ai-model-selection-final.md` · `bedrock-migration-design.md` §6).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from opentelemetry import trace
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import settings
from app.models import (VideoAcceptedResponse, VideoExtractRequest, VideoStatusResponse)
from app.store import Store, make_redis

# ml/video-recipe 를 import 경로에 올린다(라이브러리 재사용 — 로직 복제 금지).
# ⚠️ 디렉터리명이 하이픈(`video-recipe`)이라 패키지 import가 불가능하다.
#    기존 테스트(`ml/video-recipe/tests/`)와 동일하게 **디렉터리 자체를 path에 넣고
#    최상위 모듈로 import**한다. 컨테이너에서는 VIDEO_LIB_PATH로 덮어쓸 수 있다.
# ⚠️ `or` 단축평가 필수 — os.environ.get(k, default) 는 default 를 **항상** 평가하므로
#    컨테이너(`/app/app/main.py`, parents 3개뿐)에서 parents[3] 이 IndexError 로 죽는다.
#    env 가 있으면(=컨테이너) 폴백을 아예 평가하지 않도록 `or` 로 지연시킨다.
_ML = Path(os.environ.get("VIDEO_LIB_PATH")
           or Path(__file__).resolve().parents[3] / "ml" / "video-recipe")
if str(_ML) not in sys.path:
    sys.path.insert(0, str(_ML))

state: dict = {}
_tracer = trace.get_tracer("food-budget-app.video")


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis = make_redis()
    state["store"] = Store(redis)
    # gazetteer 1회 로드 — 실패해도 기동은 계속(정규화 없이 동작, item_id=None)
    try:
        from app.normalize import load_item_resolver

        resolver, n = load_item_resolver()
        state["item_resolver"] = resolver
        logging.getLogger("video").info("gazetteer loaded: %d surfaces", n)
    except Exception as exc:  # noqa: BLE001
        state["item_resolver"] = None
        logging.getLogger("video").warning("gazetteer load failed (%s) — item_id 미채움", type(exc).__name__)
    try:
        yield
    finally:
        await redis.aclose()


app = FastAPI(title="food-budget-app video-recipe service", lifespan=lifespan)
Instrumentator(
    should_group_status_codes=True,
    excluded_handlers=[r"^/metrics$", r"^/health$"],
).instrument(app).expose(app, include_in_schema=False)


@app.get("/health")
async def health() -> dict:
    """의존성(Redis) 상태까지 보고한다 — 잡 저장이 안 되면 서비스는 사실상 불능이다."""
    store: Store = state["store"]
    redis_ok = await store.ping()
    return {
        "status": "ok" if redis_ok else "degraded",
        "redis": redis_ok,
        "gemini_key": bool(settings.video_gemini_api_key),   # 값은 노출하지 않는다
    }


def _to_status(payload: dict) -> VideoStatusResponse:
    return VideoStatusResponse(**payload)


async def _run_job(job_id: str, url: str) -> None:
    """백그라운드 추출. 예외는 전부 FAILED로 기록 — 잡이 PENDING에 영영 남지 않게."""
    store: Store = state["store"]
    from extract import gemini_extract                        # noqa: PLC0415
    from pipeline import check_availability, extract_recipe, normalize_url  # noqa: PLC0415

    norm = normalize_url(url)
    try:
        # 캐시는 파이프라인 인자로 넘긴다(히트 시 Gemini 호출 자체가 없음 = 비용 0).
        class _Cache:
            def get(self, key):
                fut = asyncio.run_coroutine_threadsafe(store.get_cached(key), loop)
                raw = fut.result(timeout=5)
                if not raw:
                    return None
                from models import RecipeExtraction as _RE
                return _RE(**raw)

            def set(self, key, recipe):
                asyncio.run_coroutine_threadsafe(
                    store.set_cached(key, recipe.model_dump()), loop).result(timeout=5)

        loop = asyncio.get_running_loop()
        # 영상 URL·추출 텍스트는 Span에 남기지 않는다. 조사에는 처리 단계·캐시 여부만 필요하다.
        with _tracer.start_as_current_span("video.extract_recipe") as span:
            result = await asyncio.wait_for(
                asyncio.to_thread(extract_recipe, url, gemini_extract, cache=_Cache(),
                                  item_resolver=state.get("item_resolver"),
                                  # 삭제·비공개 영상을 모델 호출 **전에** 걸러낸다(backlog §1.10).
                                  # 없으면 api_key 는 "요리 영상이 아닙니다"로 오안내하고 vertex 는
                                  # 500 으로 죽는다 — 둘 다 유저에게 틀린 말이다(실측 2026-07-29).
                                  # 파이프라인은 순수 유지, 네트워크 I/O 는 여기서 주입한다.
                                  availability_fn=check_availability),
                timeout=settings.video_timeout_s,
            )
            span.set_attribute("video.extract.stage", result.stage)
            span.set_attribute("video.extract.from_cache", result.from_cache)
            span.set_attribute("video.extract.success", bool(result.ok and result.recipe))
        if result.ok and result.recipe:
            r = result.recipe
            await store.put_job(job_id, {
                "status": "DONE", "stage": result.stage, "from_cache": result.from_cache,
                "title": r.title, "is_recipe": r.is_recipe,
                # 인분 미상은 감추지 않고 플래그로 노출 — UI가 직접 입력을 유도한다.
                "servings": r.servings, "servings_known": bool(r.servings),
                "source_url": r.source_url, "source_creator": r.source_creator, "video_seconds": r.video_seconds,
                "ingredients": [i.model_dump() for i in r.ingredients],
                "steps": [s.model_dump() for s in r.steps],
                "soft_flags": list(getattr(result, "soft_flags", []) or []),
                # #11 재료비 — 실패해도 추출 결과는 그대로 준다(가격은 부가 정보).
                "cost": await _estimate_cost(r),
            })
        else:
            await store.put_job(job_id, {
                "status": "FAILED", "stage": result.stage,
                "reason": result.note or ", ".join(result.hard_failures) or "추출에 실패했어요.",
            })
    except asyncio.TimeoutError:
        await store.put_job(job_id, {"status": "FAILED", "reason": "영상 분석이 시간을 초과했어요."})
    except Exception as exc:  # noqa: BLE001 — 사유를 남기고 잡을 반드시 종료시킨다
        await store.put_job(job_id, {"status": "FAILED", "reason": f"분석 중 오류: {type(exc).__name__}"})
    finally:
        if norm:
            await store.release(norm)


_SERVINGS_RE = re.compile(r"(\d+)")


def _servings_count(servings: str | None) -> int | None:
    """'2인분'·'2~3인분' → 2. 숫자가 없으면 None — 1인분 단가를 내지 않는다."""
    if not servings:
        return None
    m = _SERVINGS_RE.search(servings)
    return int(m.group(1)) if m else None


async def _estimate_cost(recipe) -> dict | None:
    """재료비 산출(#11). DB 접근이라 스레드로 — 실패는 삼키고 None(추출 결과는 유효)."""
    try:
        from app.cost import estimate

        items = [{"name": i.name, "quantity": i.quantity,
                  "item_id": getattr(i, "item_id", None)} for i in recipe.ingredients]
        if not any(i["item_id"] for i in items):
            return None                       # 정규화 실패 → 가격 붙일 대상 없음
        return await asyncio.to_thread(estimate, items, _servings_count(recipe.servings))
    except Exception as exc:  # noqa: BLE001 — 가격 실패가 추출 실패가 되면 안 된다
        logging.getLogger("video").warning("cost estimate failed (%s)", type(exc).__name__)
        return None


# ⚠️ 경로는 api-spec #24·#25 계약(`/api/recipes/extract`) — 프론트가 이 경로로 붙는다.
@app.post("/api/recipes/extract", response_model=VideoAcceptedResponse, status_code=202)
async def submit_video(req: VideoExtractRequest, bg: BackgroundTasks) -> VideoAcceptedResponse:
    """유튜브 URL 접수 → 202 + job_id. 캐시 히트면 즉시 DONE(비용 0)."""
    # 준비상태는 백엔드별로 판단(extract.py 와 동일 규약). vertex=SA키/프로젝트, api_key=키.
    _backend = os.environ.get("VIDEO_GENAI_BACKEND", "api_key")
    _ready = bool(os.environ.get("GCP_PROJECT_ID")) if _backend == "vertex" \
        else bool(settings.video_gemini_api_key)
    if not _ready:
        raise HTTPException(503, "영상 분석이 아직 준비되지 않았어요.")   # 백엔드 미준비 안내 폴백

    from pipeline import normalize_url                        # noqa: PLC0415
    norm = normalize_url(req.url)
    if not norm:
        raise HTTPException(400, "유튜브 영상 URL이 아니에요.")

    store: Store = state["store"]
    job_id = uuid.uuid4().hex

    cached = await store.get_cached(norm)
    if cached is not None:      # 다른 유저가 이미 분석한 영상 → Gemini 호출 없음
        await store.put_job(job_id, {"status": "DONE", "stage": "cached", "from_cache": True, **cached})
        return VideoAcceptedResponse(job_id=job_id, status="DONE", from_cache=True)

    if not await store.acquire(norm):
        raise HTTPException(409, "같은 영상을 분석 중이에요. 잠시 후 다시 시도해 주세요.")

    await store.put_job(job_id, {"status": "PENDING"})
    bg.add_task(_run_job, job_id, req.url)
    return VideoAcceptedResponse(job_id=job_id)


@app.get("/api/recipes/extract/{job_id}", response_model=VideoStatusResponse)
async def get_result(job_id: str) -> VideoStatusResponse:
    store: Store = state["store"]
    payload = await store.get_job(job_id)
    if payload is None:
        raise HTTPException(404, "결과를 찾을 수 없어요(만료되었거나 잘못된 요청).")
    return _to_status(payload)
