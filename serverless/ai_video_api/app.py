"""`mp-ai-video-api` 의 Lambda 진입점 — 유튜브 URL **접수**와 결과 **폴링**.

**이 함수는 Gemini 를 부르지 않는다.** 무거운 일은 `mp-ai-video-worker` 가 하고, 여기는
받아서 큐에 넣고 202 를 돌려주는 문이다. 그래서 타임아웃이 10초다(계약표).

바뀌는 것은 **일이 도는 자리 하나**다. 현행 `services/video/app/main.py` 는 `BackgroundTasks`
로 같은 프로세스에서 이어 돌리는데, 🔴 **Lambda 에서는 그게 안 된다** — 응답을 돌려준 직후
실행 환경이 얼어붙어 백그라운드 작업이 멈춘다. 그래서 SQS 로 넘긴다.

캐시·락·잡 상태 계약은 **그대로 쓴다**(`serverless/common/jobs.py` 머리말 참조).
특히 **캐시 히트면 워커를 아예 안 부른다** — 다른 유저가 이미 분석한 영상은 비용 0 이다.

경로 2개:
    POST /api/recipes/extract            {"url": "..."} → 202 {"job_id": "..."}
    GET  /api/recipes/extract/{job_id}                  → 200 상태
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

# 🔴 URL 정규화는 **`ml/video-recipe`** 의 `pipeline` 에 있다(컨테이너에선 `VIDEO_LIB_PATH`).
#    `services/video/app` 이 아니다 — 거기엔 FastAPI 껍데기만 있다.
_HERE = Path(__file__).resolve()
for _p in (_HERE.parents[1], _HERE.parents[2] / "ml" / "video-recipe"):
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from common import alb, jobs                       # noqa: E402
from common.runtime import logger, log_start       # noqa: E402

FUNCTION = "mp-ai-video-api"
log = logger(FUNCTION)

QUEUE_URL = os.environ.get("VIDEO_JOBS_QUEUE_URL", "")


def _normalize(url: str) -> str | None:
    """URL 정규화는 파이프라인의 것을 그대로 쓴다 — 캐시 키가 갈리면 캐시가 통째로 무의미해진다.

    🔴 접수와 워커가 **반드시 같은 함수**를 써야 한다. 여기서 정규화한 키로 락을 잡고 워커가
       다른 키로 캐시를 쓰면, 락은 걸렸는데 캐시는 안 맞는 상태가 된다(중복 분석이 영구화).
    """
    from pipeline import normalize_url             # noqa: PLC0415

    return normalize_url(url)


def _backend_ready() -> bool:
    """현행 라우트와 같은 규약 — vertex 는 프로젝트 ID, api_key 는 키."""
    backend = os.environ.get("VIDEO_GENAI_BACKEND", "api_key")
    if backend == "vertex":
        return bool(os.environ.get("GCP_PROJECT_ID"))
    return bool(os.environ.get("VIDEO_GEMINI_API_KEY"))


def _submit(event: dict) -> dict:
    if not _backend_ready():
        return alb.error(503, "영상 분석이 아직 준비되지 않았어요.")

    url = (alb.body(event).get("url") or "").strip()
    if not url:
        return alb.error(400, "유튜브 영상 URL이 아니에요.")

    norm = _normalize(url)
    if not norm:
        return alb.error(400, "유튜브 영상 URL이 아니에요.")

    job_id = uuid.uuid4().hex

    cached = jobs.get_cached(norm)
    if cached is not None:                        # 이미 분석된 영상 → 워커도 Gemini 도 안 부른다
        jobs.put_job(job_id, {"status": "DONE", "stage": "cached", "from_cache": True, **cached})
        log.info("■ %s 캐시 히트 · job=%s", FUNCTION, job_id)
        return alb.reply(202, {"job_id": job_id, "status": "DONE", "from_cache": True})

    if not jobs.acquire(norm):
        return alb.error(409, "같은 영상을 분석 중이에요. 잠시 후 다시 시도해 주세요.")

    jobs.put_job(job_id, {"status": "PENDING"})
    try:
        jobs.enqueue(QUEUE_URL, {"job_id": job_id, "url": url, "norm": norm})
    except Exception:                             # noqa: BLE001
        # 🔴 큐 전송이 실패했는데 락과 PENDING 을 남기면 **아무도 처리하지 않는 잡**이 되고
        #    유저는 폴링만 계속한다. 되돌리고 정직하게 실패로 답한다.
        jobs.release(norm)
        jobs.put_job(job_id, {"status": "FAILED", "error": "queue_unavailable"})
        log.exception("🔴 %s 큐 전송 실패 · job=%s", FUNCTION, job_id)
        return alb.error(503, "잠시 후 다시 시도해 주세요.")

    log.info("■ %s 접수 · job=%s", FUNCTION, job_id)
    return alb.reply(202, {"job_id": job_id, "status": "PENDING", "from_cache": False})


def _poll(job_id: str) -> dict:
    payload = jobs.get_job(job_id)
    if payload is None:
        return alb.error(404, "결과를 찾을 수 없어요(만료되었거나 잘못된 요청).")
    return alb.reply(200, {"job_id": job_id, **payload})


def handler(event, context):
    """ALB 가 부른다. 경로 2개를 메서드로 가른다."""
    method, path = alb.method(event), alb.path(event)
    log_start(log, FUNCTION, {"method": method, "path": path}, context)

    if method == "POST":
        return _submit(event)
    if method == "GET":
        job_id = alb.tail_segment(path)
        # `/api/recipes/extract` 로 GET 이 오면 job_id 자리가 'extract' 다 — 폴링이 아니다.
        if not job_id or job_id == "extract":
            return alb.error(400, "job_id 가 필요해요.")
        return _poll(job_id)
    return alb.error(405, "지원하지 않는 메서드예요.")
