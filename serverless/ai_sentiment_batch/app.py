"""`mp-ai-sentiment-batch` 의 Lambda 진입점 — 리뷰 감정분류(Bedrock nova-micro).

**깨우는 방식** = EventBridge Scheduler. 현행 CronJob `mp-score-review-sentiment` 를 승계한다
(온프렘 실측 `0 7 * * 0,3` = **일·수 07:00 KST**). 스케줄이 넘기는 payload 는 우리가 정한다.

🟢 **자진 중단이 안전한 배치다** — `_PENDING` 이 미분류만 고르고 **배치마다 커밋**하므로,
15분에 걸려 멈춰도 진행분이 남고 다음 실행이 이어받는다.
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

FUNCTION = "mp-ai-sentiment-batch"
log = logger(FUNCTION)
inject()

import score_review_sentiment as batch  # noqa: E402


def handler(event, context):
    """받는 키 — CLI 인자와 1:1.

        `{"limit": 500}`         ↔  `--limit 500`     상위 N건만(시범)
        `{"batch": 20}`          ↔  `--batch 20`      1회 호출당 리뷰 수
        `{"apply": true}`        ↔  `--apply`         실제 적재 (기본은 미리보기)
        `{"summary_only": true}` ↔  `--summary-only`  분류는 건너뛰고 집계만 갱신

    🔴 스케줄 실행은 `{"apply": true}` 여야 실제로 적재된다. 빠뜨리면 **매번 미리보기만 돌고
    아무것도 안 쌓이는데 로그는 정상으로 보인다** — 스케줄 등록 시 반드시 확인한다.
    """
    args = event_args(event, {"limit": int, "batch": int,
                              "apply": bool, "summary_only": bool})
    log_start(log, FUNCTION, args, context)

    kw = {"apply": args.get("apply", False),
          "summary_only": args.get("summary_only", False),
          "has_time": time_guard(context), "emit": emit_via(log)}
    if "limit" in args:
        kw["limit"] = args["limit"]
    if "batch" in args:                 # 없으면 스크립트 기본값 BATCH 를 쓴다
        kw["batch"] = args["batch"]

    result = batch.run(**kw)
    log.info("■ %s 종료 · %s", FUNCTION, result)
    return result
