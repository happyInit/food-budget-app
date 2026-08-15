"""`mp-ai-shelflife-draft` 의 Lambda 진입점 — 소비기한 참조표 AI 초안 생성.

**이 파일이 하는 일은 셋뿐이다.** 계산 로직은 `pipelines/ingest/draft_shelf_life.py` 의 `run()`
에 그대로 있고, 여기는 **문**이지 방이 아니다.
  ① `event` 를 `run()` 의 인자로 번역한다   (지금 CLI 의 `argparse` 자리)
  ② 15분 상한을 지키게 시간 감시자를 넘긴다
  ③ 시작·끝을 로그에 남기고 요약을 돌려준다

**깨우는 방식** = 수동 Invoke 2종 중 하나. 스케줄도 규칙도 없다 —
*사람이 미리보기로 돌려 눈으로 확인한 뒤, 사람이 다시 적재로 돌린다*(승인 게이트).

    aws lambda invoke --function-name mp-ai-shelflife-draft \\
      --payload '{"limit":5}' --cli-binary-format raw-in-base64-out \\
      --cli-read-timeout 0 out.json

🔴 `--cli-read-timeout 0` 이 필요한 이유 = **CLI 기본 대기가 60초**인데 이 배치는 그보다 오래 돈다.
안 붙이면 함수는 도는데 화면만 끊기고, 끊긴 뒤 CLI 가 재시도해 **같은 배치가 두 번 돌 수 있다.**
"""
from __future__ import annotations

import sys
from pathlib import Path

# 패키징 방식(zip / 컨테이너)이 아직 미정이라, **레포에서도 번들에서도 도는** 경로 해석을 쓴다.
# 확정되면 이 블록만 지우면 된다 — 그때는 번들 루트가 곧 import 루트다.
_HERE = Path(__file__).resolve()
for _p in (_HERE.parents[1], _HERE.parents[2] / "pipelines" / "ingest"):
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from common.runtime import emit_via, event_args, log_start, logger, time_guard  # noqa: E402
from common.secrets import inject                                               # noqa: E402

FUNCTION = "mp-ai-shelflife-draft"
log = logger(FUNCTION)

# 🔴 **핸들러 밖**에서 한 번만 — Lambda 는 실행 환경을 재사용하므로 다음 호출에서 다시 돌지 않는다.
# 여기서 실패하면 초기화 오류로 호출 전체가 실패한다. 자격증명이 없으면 어차피 못 도는 배치라
# **접속 시점에 터지는 것보다 여기서 터지는 편이 원인이 분명하다.**
inject()

import draft_shelf_life  # noqa: E402


def handler(event, context):
    """Lambda 가 부르는 함수. `event` 는 우리가 정한 모양이다(수동 Invoke 라 우리 소관).

    받는 키 — CLI 인자와 1:1 로 맞춰 둔다. 둘을 다르게 두면 사람이 헷갈린다.
        `{"limit": 5}`              ↔  `--limit 5`     상위 N개만(미리보기·시범)
        `{"apply": true}`           ↔  `--apply`       실제 INSERT (기본은 미리보기)
        `{"all": true}`             ↔  `--all`         이미 초안 받은 품목까지 다시

    🔴 `all` 을 켜지 말 것 — 기본값이 **과금을 막는 게이트**다. 끄면 ROOM 이 부적절한
       품목 260 종을 매 실행마다 다시 물어보고 결과는 한 행도 안 남는다
       (`draft_shelf_life._UNCOVERED` 주석의 수렴 문제). 모델을 갈아 전부 다시 받을 때만.
    """
    args = event_args(event, {"limit": int, "apply": bool, "all": bool})
    log_start(log, FUNCTION, args, context)

    result = draft_shelf_life.run(
        limit=args.get("limit"),
        apply=args.get("apply", False),
        retry_attempted=args.get("all", False),
        has_time=time_guard(context),   # 로컬·테스트에서는 None → 시간을 안 본다
        emit=emit_via(log),
    )

    log.info("■ %s 종료 · %s", FUNCTION, result)
    return result
