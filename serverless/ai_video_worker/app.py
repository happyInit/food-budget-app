"""`mp-ai-video-worker` 의 Lambda 진입점 — SQS 로 받은 잡을 실제로 처리한다.

접수(`mp-ai-video-api`)가 넘긴 `{job_id, url, norm}` 하나를 받아 추출하고 잡 상태를 마감한다.
추출 로직은 `services/video` 의 `pipeline.extract_recipe` 를 **그대로** 쓴다 — 분할은 일이 도는
자리를 옮기는 것이지 로직을 다시 짜는 것이 아니다.

🔴 **분할하면서 새로 생기는 것 3건**(설계서 §3)을 이 파일이 전부 떠안는다:

  ① **락이 워커 죽음을 못 견딘다.** 같은 프로세스였을 때는 `finally` 가 해제를 보장했지만,
     이제 워커가 통째로 죽으면 락이 남는다. `LOCK_TTL_S`(180s)가 유일한 방어선이므로
     **이 함수의 타임아웃을 그 아래로 잡아야 한다.** 길게 잡으면 "락은 풀렸는데 워커는 아직
     도는" 구간이 생겨 같은 URL 이 두 번 분석된다(비용 2배).
     ⇒ 계약표의 150s 는 이 제약에서 나온 값이다. 180 을 넘기지 말 것.

  ② **SQS 는 중복 전달이 가능하다**(표준 큐 = 최소 1회). 그래서 **진입부에서 캐시를 다시 본다** —
     두 번째 전달은 캐시 히트로 끝나고 Gemini 를 부르지 않는다. 접수 쪽에만 있던 체크를
     여기에도 둔 이유가 이것이다.

  ③ **실패가 조용해진다.** 워커 실패는 재시도 뒤 DLQ 로 가는데, 그동안 잡은 `PENDING` 이라
     **유저가 영원히 기다린다.** 마지막 시도에서 반드시 `FAILED` 를 남긴다.
     🔴 마지막이 아닐 때는 **일부러 예외를 올린다** — 그래야 SQS 가 재시도한다.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# 🔴 추출 라이브러리는 `services/video` 가 아니라 **`ml/video-recipe`** 에 있다.
#    컨테이너에서는 `/opt/video-recipe`(`VIDEO_LIB_PATH`)로 붙는다 — 그래서 `from pipeline import ...`
#    가 성립한다. 번들에서는 build.sh 가 평평하게 넣으므로 번들 루트가 곧 그 자리다.
_HERE = Path(__file__).resolve()
for _p in (_HERE.parents[1], _HERE.parents[2] / "ml" / "video-recipe"):
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from common import jobs                            # noqa: E402
from common.runtime import logger, log_start       # noqa: E402

FUNCTION = "mp-ai-video-worker"
log = logger(FUNCTION)

EXTRACT_TIMEOUT_S = float(os.environ.get("VIDEO_TIMEOUT_S", "120"))


class _CacheAdapter:
    """파이프라인이 기대하는 `get/set` 모양. 동기 redis 라 원본의 루프 브리지가 필요 없다."""

    def __init__(self, norm: str) -> None:
        self._norm = norm

    def get(self, key):
        raw = jobs.get_cached(key)
        if not raw:
            return None
        from models import RecipeExtraction       # noqa: PLC0415

        return RecipeExtraction(**raw)

    def set(self, key, recipe):
        jobs.set_cached(key, recipe.model_dump())


def _done_payload(result) -> dict:
    """현행 `_run_job` 의 DONE 본문과 **키까지 같게** 만든다 — 프론트가 이미 이 모양을 읽는다."""
    r = result.recipe
    return {
        "status": "DONE", "stage": result.stage, "from_cache": result.from_cache,
        "title": r.title, "is_recipe": r.is_recipe,
        "servings": r.servings, "servings_known": bool(r.servings),
        "source_url": r.source_url, "source_creator": r.source_creator,
        "video_seconds": r.video_seconds,
        "ingredients": [i.model_dump() for i in r.ingredients],
        "steps": [s.model_dump() for s in r.steps],
        "soft_flags": list(getattr(result, "soft_flags", []) or []),
        # 🔴 재료비는 **여기서 빼 뒀다.** 원본은 `_estimate_cost` 로 PG 를 치는데, 그건 VPC·롤·
        #    커넥션이 붙는 별개 관심사다. 원본도 "실패해도 추출 결과는 그대로 준다"고 적어 둔
        #    부가 정보라, 접수·워커 분할이 검증되기 전에 같이 옮기면 실패 원인이 섞인다.
        #    ⚠️ 이관 완료 조건이 아니다 — 별건으로 붙인다(아래 modules.txt 주석과 짝).
        "cost": None,
    }


def _process(body: dict) -> dict:
    job_id, url, norm = body.get("job_id"), body.get("url"), body.get("norm")
    if not job_id or not url:
        # 우리가 만든 메시지가 아니다 — 재시도해도 같으므로 조용히 버린다(DLQ 로 보낼 이유 없음).
        log.warning("⚠️ %s 잘못된 메시지 · %s", FUNCTION, list(body))
        return {"skipped": "bad_message"}

    # ② 중복 전달 방어 — 두 번째 전달은 여기서 끝난다(Gemini 호출 0)
    if norm:
        cached = jobs.get_cached(norm)
        if cached is not None:
            jobs.put_job(job_id, {"status": "DONE", "stage": "cached",
                                  "from_cache": True, **cached})
            jobs.release(norm)
            log.info("■ %s 중복 전달 · 캐시로 마감 · job=%s", FUNCTION, job_id)
            return {"job_id": job_id, "status": "DONE", "from_cache": True}

    from extract import gemini_extract             # noqa: PLC0415
    from pipeline import check_availability, extract_recipe   # noqa: PLC0415

    async def _run():
        return await asyncio.wait_for(
            asyncio.to_thread(
                extract_recipe, url, gemini_extract,
                cache=_CacheAdapter(norm or ""),
                item_resolver=None,
                # 삭제·비공개 영상을 모델 호출 **전에** 거른다. 없으면 api_key 는
                # "요리 영상이 아닙니다"로 오안내하고 vertex 는 500 으로 죽는다(실측 2026-07-29).
                availability_fn=check_availability,
            ),
            timeout=EXTRACT_TIMEOUT_S,
        )

    result = asyncio.run(_run())

    if result.ok and result.recipe:
        payload = _done_payload(result)
    else:
        payload = {"status": "FAILED", "stage": result.stage,
                   "reason": result.note or ", ".join(result.hard_failures) or "추출에 실패했어요."}
    jobs.put_job(job_id, payload)
    log.info("■ %s 완료 · job=%s · %s", FUNCTION, job_id, payload["status"])
    return {"job_id": job_id, "status": payload["status"]}


def handler(event, context):
    """SQS 가 부른다. 배치 크기 1 이 계약이지만 여러 건이 와도 각각 처리한다."""
    records = jobs.sqs_records(event)
    log_start(log, FUNCTION, {"records": len(records)}, context)

    results = []
    for body, received in records:
        norm = body.get("norm")
        job_id = body.get("job_id")
        try:
            results.append(_process(body))
        except Exception as exc:                  # noqa: BLE001
            last = jobs.is_last_attempt(received)
            log.exception("🔴 %s 처리 실패 · job=%s · 수신 %d회 · 마지막=%s",
                          FUNCTION, job_id, received, last)
            if last:
                # ③ 마지막 시도 — 잡을 반드시 끝낸다. 안 그러면 DLQ 로 가고 유저는 PENDING 을 본다.
                if job_id:
                    jobs.put_job(job_id, {"status": "FAILED",
                                          "reason": f"분석 중 오류: {type(exc).__name__}"})
                if norm:
                    jobs.release(norm)
                results.append({"job_id": job_id, "status": "FAILED"})
            else:
                # 🔴 아직 재시도가 남았다 — **예외를 올려야** SQS 가 다시 준다.
                #    여기서 삼키면 성공으로 간주돼 메시지가 사라지고 잡이 PENDING 에 영영 남는다.
                #    🔵 락은 일부러 안 푼다 — 재시도가 같은 URL 을 다시 잡아야 하고,
                #       못 풀어도 TTL(180s)이 받아 준다(①).
                raise
        else:
            if norm:
                jobs.release(norm)

    return {"processed": len(results), "results": results}
