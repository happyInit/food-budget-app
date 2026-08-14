"""`mp-ai-ner-backfill` 의 Lambda 진입점 — RAW 재료 덩어리를 CRF 로 구조화해 채운다.

**깨우는 방식** = 수동 Invoke. 스케줄도 규칙도 없다 — *사람이 미리보기로 돌려 보고,
사람이 다시 적재로 돌린다.* 🔴 **DLQ 가 없다** — 실패는 CloudWatch 로그에만 남는다.

    aws lambda invoke --function-name mp-ai-ner-backfill \\
      --payload '{"limit":20}' --cli-binary-format raw-in-base64-out \\
      --cli-read-timeout 0 out.json
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

FUNCTION = "mp-ai-ner-backfill"
log = logger(FUNCTION)
inject()

import backfill_ner_raw_ingredients as batch  # noqa: E402


def handler(event, context):
    """받는 키 — CLI 인자와 1:1.

        `{"limit": 20}`   ↔  `--limit 20`   상위 N개 레시피만(미리보기·시범)
        `{"apply": true}` ↔  `--apply`      실제 INSERT (기본은 미리보기)
    """
    args = event_args(event, {"limit": int, "apply": bool})
    log_start(log, FUNCTION, args, context)

    result = batch.run(
        limit=args.get("limit"),
        apply=args.get("apply", False),
        has_time=time_guard(context),
        emit=emit_via(log),
    )

    log.info("■ %s 종료 · %s", FUNCTION, result)
    return result
