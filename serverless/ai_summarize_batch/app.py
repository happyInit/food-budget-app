"""`mp-ai-summarize-batch` 의 Lambda 진입점 — 리뷰 종합 요약(Bedrock).

**깨우는 방식** = EventBridge Scheduler. 현행 CronJob `mp-summarize-reviews` 를 승계한다.
감정분류(`mp-ai-sentiment-batch`)가 **선행**이다 — 집계행이 없으면 요약이 저장되지 않는다.

🟢 자진 중단이 안전하다 — `_TARGETS` 가 아직 요약 없는 것만 고르고 **레시피마다 커밋**한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
for _p in (_HERE.parents[1], _HERE.parents[2] / "pipelines" / "ingest"):
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from common.runtime import emit_via, event_args, log_start, logger, time_guard  # noqa: E402
from common.secrets import inject                                               # noqa: E402

FUNCTION = "mp-ai-summarize-batch"
log = logger(FUNCTION)
inject()

import summarize_reviews as batch  # noqa: E402


def handler(event, context):
    """받는 키 — CLI 인자와 1:1. **단 두 개는 일부러 뺐다.**

        `{"limit": 100}`        ↔  `--limit 100`
        `{"min_reviews": 5}`    ↔  `--min-reviews 5`
        `{"model": "..."}`      ↔  `--model ...`
        `{"temperature": 0.0}`  ↔  `--temperature 0.0`
        `{"redo": true}`        ↔  `--redo`        이미 요약된 것도 다시 생성
        `{"apply": true}`       ↔  `--apply`       실제 저장 (기본은 미리보기)

    🔴 **`--audit` 와 `--compare` 는 노출하지 않는다.** 둘은 *사람이 눈으로 대조하는 모드*다 —
    `audit` 은 원문 표본을 통째로 찍어 **로그를 덮고**, `compare` 는 후보 모델을 나란히 돌려
    **호출 비용이 배로 든다.** 필요하면 사람이 CLI 로 돌린다.
    """
    args = event_args(event, {"limit": int, "min_reviews": int, "model": str,
                              "temperature": float, "redo": bool, "apply": bool})
    log_start(log, FUNCTION, args, context)

    kw = {"redo": args.get("redo", False), "apply": args.get("apply", False),
          "has_time": time_guard(context), "emit": emit_via(log)}
    for k in ("limit", "min_reviews", "model", "temperature"):
        if k in args:                   # 없으면 스크립트 기본값을 쓴다
            kw[k] = args[k]

    result = batch.run(**kw)
    log.info("■ %s 종료 · %s", FUNCTION, result)
    return result
