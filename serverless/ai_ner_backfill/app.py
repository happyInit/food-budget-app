"""`mp-ai-ner-backfill` 의 Lambda 진입점 — RAW 재료 덩어리를 CRF 로 구조화해 채운다.

**깨우는 방식** = 수동 Invoke. 스케줄도 규칙도 없다 — *사람이 미리보기로 돌려 보고,
사람이 다시 적재로 돌린다.* 🔴 **DLQ 가 없다** — 실패는 CloudWatch 로그에만 남는다.

    aws lambda invoke --function-name mp-ai-ner-backfill \\
      --payload '{"limit":20}' --cli-binary-format raw-in-base64-out \\
      --cli-read-timeout 0 out.json
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
for _p in (_HERE.parents[1], _HERE.parents[2] / "pipelines" / "ingest"):
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from common.assets import s3_asset                                              # noqa: E402
from common.runtime import emit_via, event_args, log_start, logger, time_guard  # noqa: E402
from common.secrets import inject                                               # noqa: E402

FUNCTION = "mp-ai-ner-backfill"
log = logger(FUNCTION)
inject()

# 🔴 CRF 모델은 **번들에 없다.** `ml/ingredient-ner/.gitignore` 가 `data/*` 로 막고 있어
#    레포에 없고, 그래서 `build.sh` 의 manifest 에도 넣을 수 없다(넣으면 CI 빌드가 죽는다).
#    ⇒ S3 에서 받는다(사용자 확정 2026-08-18 · `docs/serverless/10` 결정표).
#
# 🔴 이게 없으면 증상이 이렇게 나온다 — 2026-08-18 실측:
#      FileNotFoundError: CRF 모델 없음: /ml/ingredient-ner/data/model/crf_ingredient.crfsuite
#    함수는 정상 배포되고 INIT 도 통과하며, **호출해야 비로소** 드러난다.
#
# 🔵 `import batch` **앞**이어야 한다 — 그 모듈이 import 시점에 모델 경로를 굳힌다.
s3_asset("NER_MODEL_PATH",
         os.environ.get("NER_MODEL_S3", "s3://mp-ai-model-ap2/ner/crf_ingredient.crfsuite"),
         "crf_ingredient.crfsuite")

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
