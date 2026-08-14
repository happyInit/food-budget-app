"""`mp-ai-price-detect` 의 Lambda 진입점 — 최저가 이상탐지(z-score) + 알림 fan-out.

**깨우는 방식** = EventBridge Scheduler. 현행 CronJob `mp-poller-price-anomaly` 를 승계한다
(온프렘 실측 `40 4 * * *` = **매일 04:40 KST**).

🔴 **`--emit`(Kafka 발행)은 노출하지 않는다 — AWS 에 Kafka 가 없다(C-44).**
AWS 경로는 **`emit_direct` 하나뿐**이다(C-88 — 배치가 fan-out SQL 을 직접 실행).
온프렘 CronJob 은 `--emit` 을 그대로 쓰고, 그쪽 CLI 는 한 글자도 안 바꿨다(C-72·C-83 동결).

🔴 **`--json`(파일 저장)도 노출하지 않는다** — Lambda 에서 쓸 수 있는 곳은 `/tmp` 뿐이고
그 파일은 실행이 끝나면 아무도 못 본다. 결과는 반환값과 로그로 남는다.
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

FUNCTION = "mp-ai-price-detect"
log = logger(FUNCTION)
inject()

import detect_price_anomaly as batch  # noqa: E402


class FanoutIncomplete(RuntimeError):
    """fan-out 이 일부 실패했다. **예외로 올려야** 런타임이 실패로 세고 알람이 걸린다.

    CLI 는 같은 상황에서 `sys.exit(1)` 을 낸다 — CronJob 이 종료코드로만 성패를 알기 때문이다.
    Lambda 는 종료코드가 없으므로 **예외가 그 자리**다. 조용히 성공으로 반환하면
    *"알림이 통째로 멈춘 걸 아무도 모르는"* 상태가 그대로 재현된다.
    """


def handler(event, context):
    """받는 키 — CLI 인자와 1:1(위 두 개 제외).

        `{"window": 28}`            ↔  `--window 28`         baseline 상한 일수
        `{"z": -2.0}`               ↔  `--z -2.0`            급락 z 임계
        `{"min_drop": 15.0}`        ↔  `--min-drop 15.0`     최소 하락률 %
        `{"min_samples": 5}`        ↔  `--min-samples 5`
        `{"top_n": 20}`             ↔  `--top-n 20`          0 = 무제한
        `{"persist": true}`         ↔  `--persist`           기준선·이상치 기록
        `{"emit_direct": true}`     ↔  `--emit-direct`       알림 fan-out (persist 함의)
        `{"mature_samples": 14}`    ↔  `--mature-samples 14` 발행 최소 표본
        `{"allow_immature": true}`  ↔  `--allow-immature`    성숙도 게이트 무시(검증용)

    🔴 기본은 **탐지만 하고 아무것도 안 내보낸다.** 알림은 되돌릴 수 없어서
    (유저에게 이미 나감) 명시적으로 켜야 나간다 — CLI 와 같은 원칙이다.
    """
    args = event_args(event, {"window": int, "z": float, "min_drop": float,
                              "min_samples": int, "top_n": int,
                              "persist": bool, "emit_direct": bool,
                              "mature_samples": int, "allow_immature": bool})
    log_start(log, FUNCTION, args, context)

    kw = {"persist": args.get("persist", False),
          "emit_direct": args.get("emit_direct", False),
          "allow_immature": args.get("allow_immature", False),
          "has_time": time_guard(context), "emit_line": emit_via(log)}
    for k in ("window", "z", "min_drop", "min_samples", "top_n", "mature_samples"):
        if k in args:                   # 없으면 스크립트 기본값을 쓴다
            kw[k] = args[k]

    result = batch.run(**kw)
    log.info("■ %s 종료 · %s", FUNCTION, result)

    if result["fanout_failed"]:
        # 🔴 결과를 메시지에 실어 보낸다 — 예외만 던지면 «몇 건 성공했는지» 가 사라진다.
        raise FanoutIncomplete(f"fan-out {result['fanout_failed']}건 실패 · {result}")
    return result
