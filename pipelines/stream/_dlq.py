"""DLQ(Dead Letter Queue) — poison message 를 격리해 **무한 크래시 루프를 끊는다** (#252).

## 무엇이 문제였나

상주 컨슈머는 레코드 처리 실패 시 `raise` 로 프로세스를 종료한다. 그런데 실패한 메시지는
**오프셋이 커밋되지 않으므로**, K8s Deployment(`restartPolicy: Always` 강제)가 재시작하면
**같은 메시지를 다시 읽고 또 죽는다.** 한 건이 파티션 전체를 멈춘다.

2026-07-30 운영 PG 에서 실제로 재현했다:

    ERROR: violates foreign key constraint "price_alert_sent_anomaly_id_fkey"
    DETAIL: Key (anomaly_id)=(...) is not present in table "price_anomaly"

## 🔴 왜 "재시도 횟수"가 아니라 "예외 유형"으로 나누나

컨슈머 로그는 **이미** `"retryable": False` 를 찍고 있는데 동작은 무한 재시도였다 —
**의도와 동작이 어긋나 있었다.** 재시도 횟수를 세려면 오프셋별 상태를 저장해야 하지만,
유형으로 나누면 **상태가 필요 없고 판정 근거가 코드에 드러난다.**

    영구(데이터)  → DLQ 발행 + 오프셋 전진   ← 재시도해도 절대 성공하지 않는다
    일시(인프라)  → raise                    ← 파드 재시작이 곧 자연스러운 재시도

⚠️ **화이트리스트 방식이다.** 영구라고 *아는* 것만 DLQ 로 보내고, **모르는 예외는 `raise`** 한다.
   모르는 것을 조용히 버리면 이 장치가 새로운 유실 경로가 된다.

## 🔴 savepoint 가 선택이 아니라 필수인 이유

`IntegrityError` 는 **트랜잭션을 abort** 시킨다. 이후 모든 쿼리가
`current transaction is aborted` 로 실패하므로 다음 레코드를 처리할 수 없다.

그렇다고 `conn.rollback()` 을 하면 **같은 배치의 앞선 정상 레코드까지 사라지는데**,
오프셋은 나중에 커밋되므로 **그 건들이 조용히 유실된다.**

→ 레코드마다 savepoint 를 잡고 실패 시 **그 레코드만** 되돌린다.
   (`COMMIT_EVERY=1` 로 낮추는 대안도 있으나, 커밋은 WAL fsync 를 유발해 savepoint 보다 비싸고
    모든 컨슈머의 처리량 특성을 바꾼다.)

## 안전 속성

**이 모듈이 하는 모든 판단은 "확실할 때만 격리"** 다. 분류에 실패하거나 DLQ 발행이 실패하면
**기존과 똑같이 `raise`** 한다 — 즉 이 변경은 크래시 루프를 줄일 뿐 새 실패를 만들지 않는다.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone

DLQ_SUFFIX = ".dlq"

# flush 대기(초). 짧게 두면 브로커 지연에 오탐이 나고, 길게 두면 컨슈머가 멈춘다.
DLQ_FLUSH_TIMEOUT = float(os.environ.get("DLQ_FLUSH_TIMEOUT", "10"))


class DlqDeliveryFailed(RuntimeError):
    """DLQ 발행이 확인되지 않았다 — **격리에 실패했으므로 진행하면 안 된다.**"""


# ── 영구 실패 화이트리스트 ─────────────────────────────────────────────────────
# 여기 없는 예외는 전부 일시 실패로 보고 `raise` 한다(보수적).
#   · 클래스명으로 판정하는 이유: psycopg 하위 예외를 import 하면 드라이버 없는 환경에서
#     이 모듈을 테스트할 수 없다(컨슈머 정책 함수는 드라이버 없이 검증 가능해야 한다).
_PERMANENT_NAMES = frozenset({
    # payload 자체가 깨짐 — 몇 번을 다시 읽어도 같다
    "JSONDecodeError", "UnicodeDecodeError", "KeyError", "ValueError", "TypeError",
    # 제약 위반 — 참조/필수값이 되돌아오지 않는다 (psycopg3: IntegrityError 하위)
    "IntegrityError", "ForeignKeyViolation", "NotNullViolation",
    "CheckViolation", "UniqueViolation", "InvalidTextRepresentation",
    "NumericValueOutOfRange", "StringDataRightTruncation",
})

# 🔴 **일시 실패는 명시적으로 제외**한다. 위 목록과 이름이 겹칠 여지를 없앤다.
#    OperationalError 는 커넥션 단절·서버 종료라 재시도가 정당하다.
_TRANSIENT_NAMES = frozenset({
    "OperationalError", "InterfaceError", "AdminShutdown", "CannotConnectNow",
    "ConnectionException", "KafkaException", "KafkaError", "TimeoutError",
})


def is_permanent(exc: BaseException) -> bool:
    """영구 실패(= DLQ 대상)인가. **모르면 False**(→ 호출측이 raise)."""
    for cls in type(exc).__mro__:
        name = cls.__name__
        if name in _TRANSIENT_NAMES:      # 일시가 먼저 — 상속 관계가 겹쳐도 안전측
            return False
        if name in _PERMANENT_NAMES:
            return True
    return False


@contextmanager
def record_savepoint(cur, name: str = "mp_rec"):
    """레코드 1건을 savepoint 로 감싼다 — 실패해도 **그 레코드만** 되돌린다.

    ⚠️ 커넥션 자체가 끊긴 경우 `ROLLBACK TO SAVEPOINT` 도 실패한다. 그때는 원래 예외를
       그대로 올린다(롤백 실패로 원인이 가려지면 진단이 불가능해진다).
    """
    cur.execute(f"SAVEPOINT {name}")
    try:
        yield
    except BaseException:
        try:
            cur.execute(f"ROLLBACK TO SAVEPOINT {name}")
        except Exception:  # noqa: BLE001 — 원래 예외를 가리지 않는다
            pass
        raise
    else:
        cur.execute(f"RELEASE SAVEPOINT {name}")


def dlq_topic(topic: str) -> str:
    return f"{topic}{DLQ_SUFFIX}"


def build_headers(msg, exc: BaseException, component: str, topic: str) -> list[tuple[str, bytes]]:
    """원본 헤더 + `dlq.*` 컨텍스트.

    **원본 payload 는 감싸지 않는다** — 재투입이 곧 원본 재생산이어야 하기 때문이다.
    컨텍스트는 헤더로만 붙인다.
    """
    out = list(msg.headers() or [])
    out += [
        ("dlq.error", type(exc).__name__.encode()),
        ("dlq.detail", str(exc)[:500].encode("utf-8", "replace")),
        ("dlq.component", component.encode()),
        ("dlq.topic", topic.encode()),
        ("dlq.partition", str(msg.partition()).encode()),
        ("dlq.offset", str(msg.offset()).encode()),   # 사후 조사·중복 판정에 쓴다
        ("dlq.at", datetime.now(timezone.utc).isoformat().encode()),
    ]
    return out


def send_to_dlq(producer, msg, exc: BaseException, component: str, topic: str) -> None:
    """원본 메시지를 `<topic>.dlq` 로 그대로 옮긴다. **전달이 확인될 때까지 기다린다.**

    ⚠️ 발행 확인 없이 오프셋을 커밋하면 메시지가 **진짜로** 사라진다.
       브로커가 `auto.create.topics.enable=false` 라 **토픽이 없으면 produce 는 성공한 것처럼
       보이고 flush 만 타임아웃한다**(2026-07-29 실측). 그래서 반환값을 반드시 확인한다.
    """
    producer.produce(
        dlq_topic(topic),
        key=msg.key(),
        value=msg.value(),                      # 가공 금지 — 원본 그대로
        headers=build_headers(msg, exc, component, topic),
    )
    remaining = producer.flush(DLQ_FLUSH_TIMEOUT)
    if remaining:
        raise DlqDeliveryFailed(
            f"{dlq_topic(topic)} 미전달 {remaining}건 — 토픽이 없거나 브로커 장애. "
            f"격리에 실패했으므로 오프셋을 전진시키지 않는다.")


def quarantine(producer, msg, exc: BaseException, component: str, topic: str) -> bool:
    """실패 1건을 처리한다. **격리했으면 True(진행) · 아니면 False(호출측이 raise)**.

    호출측 관례:

        except Exception as exc:
            ...메트릭·로그(기존 그대로)...
            if not quarantine(dlq_producer, msg, exc, GROUP, TOPIC):
                raise                      # 일시 실패 → 재시작이 재시도
            RECORDS.labels(GROUP, "dlq").inc()
            pending += 1                   # 🔴 오프셋이 전진해야 루프가 풀린다
            continue

    `pending += 1` 이 빠지면 **DLQ 로 보내고도 오프셋이 안 올라가** 같은 메시지를 계속
    DLQ 에 중복 적재한다(크래시는 안 나지만 루프는 그대로다).
    """
    if not is_permanent(exc):
        return False
    send_to_dlq(producer, msg, exc, component, topic)   # 실패하면 예외가 그대로 올라간다
    return True


def summary(msg, exc: BaseException, topic: str) -> str:
    """운영 로그용 한 줄."""
    return (f"DLQ→{dlq_topic(topic)} p{msg.partition()}@{msg.offset()} "
            f"{type(exc).__name__}: {str(exc)[:120]}")


__all__ = ["DlqDeliveryFailed", "build_headers", "dlq_topic", "is_permanent",
           "quarantine", "record_savepoint", "send_to_dlq", "summary",
           "DLQ_SUFFIX", "DLQ_FLUSH_TIMEOUT"]
