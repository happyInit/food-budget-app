"""Lambda 진입점 공통 계층 — 함수 12종이 같이 쓴다.

**이 파일에 들어오는 것의 기준** = *"AWS 가 어떻게 생겼든 안 바뀌는 것"* 만이다.
PG 주소·Valkey 엔드포인트·시크릿 이름·아키텍처처럼 **아직 확인 못 한 값은 여기 오지 않는다**
(전부 환경변수로 받는다). 그래서 이 파일은 실물 확인 뒤에도 수정 대상이 아니다.

핸들러가 하는 일은 셋뿐이고, 그 셋을 여기서 제공한다.
  ① 입력을 번역한다      → `event_args`
  ② 시간을 지킨다        → `time_guard`
  ③ 결과를 남긴다        → `logger` · `emit_via` · `log_start`
계산 로직은 배치 스크립트의 `run()` 에 그대로 있다 — 이쪽은 **문**이지 방이 아니다.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable

# Lambda 15분 상한에서 **마무리에 남겨둘 여유**(밀리초).
# 커밋 + 요약 로그 + 런타임 종료 처리가 이 안에 들어가야 한다.
# 짧게 잡으면 마무리 도중에 잘리고, 길게 잡으면 매 실행마다 그만큼 일을 덜 한다.
DEFAULT_RESERVE_MS = 30_000


def logger(name: str) -> logging.Logger:
    """CloudWatch 로 나가는 로거.

    🔴 Lambda 런타임은 **이미 root 로거에 핸들러를 붙여 둔다.**
    그래서 `logging.basicConfig()` 는 조용히 무시된다 — 레벨만 직접 세운다.
    로컬(CLI·테스트)에서는 핸들러가 없으므로 그때만 하나 붙인다.
    """
    log = logging.getLogger(name)
    log.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    if not logging.getLogger().handlers:          # 로컬에서만 참
        logging.basicConfig(format="%(levelname)s %(message)s")
    return log


def emit_via(log: logging.Logger) -> Callable[[str], None]:
    """배치 `run(emit=...)` 에 넘길 한 줄 출력기.

    CLI 는 `print` 를 그대로 쓰고 Lambda 는 이걸 쓴다.
    `run()` 쪽은 자기가 어디에 찍히는지 모른 채 그대로 동작한다.
    """
    return lambda msg: log.info("%s", msg)


def time_guard(context: Any, reserve_ms: int = DEFAULT_RESERVE_MS) -> Callable[[], bool] | None:
    """*"아직 시간이 남았나"* 를 bool 로 답하는 함수를 만든다.

    배치 `run(has_time=...)` 이 **품목 사이마다** 이걸 부른다.
    남은 시간이 `reserve_ms` 아래로 내려가면 False → `run()` 이 **스스로 멈추고**
    몇/몇 까지 했는지 보고한다. 잘리는 것과 달리 **어디까지 했는지가 남는다.**

    `context` 가 없으면(로컬 실행·테스트) `None` 을 돌려 **시간을 아예 안 보게** 한다 —
    프로세스에는 15분 상한이 없으므로 그게 맞는 동작이다.
    """
    if context is None or not hasattr(context, "get_remaining_time_in_millis"):
        return None
    return lambda: context.get_remaining_time_in_millis() > reserve_ms


def event_args(event: Any, spec: dict[str, type]) -> dict[str, Any]:
    """`event` 에서 **허용된 키만** 꺼내 타입을 맞춘다.

    지금 CLI 의 `argparse` 가 하는 일과 같은 자리다.
        `--limit 5 --apply`  ↔  `{"limit": 5, "apply": true}`

    두 가지를 일부러 한다.
    ① **모르는 키는 조용히 버린다** — 스케줄러가 붙이는 메타데이터가 섞여 들어와도 안 깨진다.
    ② **문자열 bool 을 받아 준다** — AWS 콘솔 Test 버튼은 값을 문자열로 보내는 경우가 있어
       `"true"` 가 그대로 오면 파이썬에서는 *참*이 되어 **미리보기가 실제 적재로 둔갑한다.**
       식품안전 배치라 이 사고는 실제로 위험해서 여기서 막는다.
    """
    if not isinstance(event, dict):
        return {}
    out: dict[str, Any] = {}
    for key, typ in spec.items():
        if key not in event or event[key] is None:
            continue
        raw = event[key]
        if typ is bool:
            out[key] = raw.strip().lower() in ("1", "true", "yes") if isinstance(raw, str) else bool(raw)
        elif typ is int:
            out[key] = int(raw)          # 잘못된 값은 여기서 터진다 — 조용히 0 이 되는 것보다 낫다
        else:
            out[key] = typ(raw)
    return out


def log_start(log: logging.Logger, name: str, args: dict, context: Any = None) -> None:
    """실행 첫 줄에 **누가 무엇으로 깨웠는지**를 남긴다.

    🔴 이 줄이 필요한 이유 = **CloudTrail 은 호출 payload 를 기록하지 않는다.**
    *"누가 언제 이 함수를 불렀다"* 까지는 남지만 *"미리보기였나 실제 적재였나"* 는 안 남는다.
    그래서 **함수가 스스로 찍어야** 사후에 구분이 된다.

    요청 ID 도 같이 찍는다 — 로그에서 **이 실행 하나**만 골라내는 열쇠다.
    """
    req = getattr(context, "aws_request_id", "local")
    budget = getattr(context, "get_remaining_time_in_millis", lambda: None)()
    log.info("▶ %s 시작 · args=%s · request_id=%s · 남은시간=%sms", name, args or "{}", req, budget)
