"""클릭스트림 이벤트 발행 — mealplan이 ADD_CART를 Kafka `events.user.activity`로 produce (Track 1).

개인화 랭킹(ai-spec §3)의 **주 라벨**(ADD_CART). 메시지 계약 = `consume_user_event.to_params`와 동일.
flag OFF 기본 + **best-effort**(발행 실패·Kafka 부재는 장바구니 담기를 절대 막지 않음). key=user_id.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

TOPIC = "events.user.activity"
_producer = None
_log = logging.getLogger("mealplan")


# 🔴 **조용한 실패를 없애기 위한 카운터** — 이번 사고(session_id 미전송이 3주간
#    드러나지 않음)의 교훈이다. fail-open 은 유지하되 **몇 건이 어떻게 됐는지는 센다**.
#    ⚠️ **아직 `/metrics` 에 붙어 있지 않다**(비판 검토 🟠6) — Instrumentator 는 HTTP 요청만
#    계측한다. 지금 이 값을 읽는 곳은 테스트뿐이고, 노출 배선은 별건이다.
#    그때까지 관측 수단은 아래 로그(`clickstream_write_failed` 등)다.
_COUNTS: dict[str, int] = {"success": 0, "duplicate": 0, "queued": 0, "failure": 0}


def _count(outcome: str) -> None:
    _COUNTS[outcome] = _COUNTS.get(outcome, 0) + 1


def counts() -> dict[str, int]:
    """관측·테스트용 스냅샷."""
    return dict(_COUNTS)


def _on_delivery(err, _msg) -> None:
    """delivery report — **fail-open 은 유지하되 조용하지는 않게** (#558).

    `produce()` 는 로컬 큐에 넣을 뿐이라, 콜백이 없으면 브로커에 끝내 못 들어간 이벤트가
    아무에게도 통보되지 않는다. 여기서는 **막지 않고 기록만** 한다 — 클릭스트림 유실이
    장바구니 담기를 막으면 안 된다는 이 모듈의 원칙은 그대로다.
    """
    if err is None:
        return
    try:
        _log.warning(
            "clickstream event delivery failed",
            extra={"event": "kafka_delivery_failed", "topic": TOPIC, "result": "failure",
                   "error_code": getattr(err, "name", lambda: type(err).__name__)(),
                   "retryable": False},
        )
    except Exception:   # noqa: BLE001 — 콜백 예외는 poll()/flush() 밖으로 다시 던져진다
        return


def _norm_session(session_id: str | None) -> str | None:
    """`activity.user_event.session_id` 는 **uuid 타입**이라 형식이 틀리면 행 전체가 유실된다.

    🔴 `insert_impressions` 는 형식 오류 시 서버가 uuid 를 발급해 **행은 남기는데**(비링크),
       여기서 그대로 넘기면 행이 사라져 비대칭이 된다. 형식이 틀리면 **NULL 로 떨어뜨린다** —
       조인은 어차피 안 되지만 행동 기록 자체는 남는다(비판 검토 🟡10).
    """
    if session_id is None:
        return None
    try:
        return str(uuid.UUID(str(session_id)))
    except (ValueError, TypeError, AttributeError):
        _log.warning("clickstream session_id 형식 오류 — NULL 로 기록한다",
                     extra={"event": "clickstream_bad_session"})
        return None


def build_add_cart_event(user_id: int, recipe_id: int, session_id: str | None) -> dict:
    """ADD_CART 이벤트 dict(계약대로). Kafka 무관 — 순수(테스트 가능)."""
    return {
        "event_id": uuid.uuid4().hex,
        "user_id": user_id,
        "session_id": _norm_session(session_id),
        "event_type": "ADD_CART",
        "recipe_id": recipe_id,
        "item_id": None,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "context": None,
    }


def _get_producer(bootstrap: str):
    global _producer
    if _producer is None:
        from confluent_kafka import Producer   # 지연 import — 미발행 배포에선 의존성 불필요
        _producer = Producer({
            "bootstrap.servers": bootstrap, "enable.idempotence": True,
            "acks": "all", "linger.ms": 50, "client.id": "mealplan",
            "on_delivery": _on_delivery,     # 전 메시지 기본 콜백(produce 인자 불요)
        })
    return _producer


async def emit_add_cart(settings, user_id: int, recipe_id: int | None,
                        session_id: str | None, conn=None) -> None:
    """장바구니 담기 → ADD_CART 적재. flag OFF·recipe_id 없음·실패 시 무동작(담기 무손상).

    **목적지는 `EVENT_SINK` 가 정한다** (C-88):
      `kafka` (기본) — 현행. 온프렘이 이걸 쓴다. 동작·설정 변화 0.
      `pg`           — 앱이 `activity.user_event` 에 직접 쓴다. AWS 는 Kafka 가 없다(C-44).

    🔴 **선택자가 하나라 dual-write 가 구조적으로 불가능하다** — C-72 가 상시 병행을
       미채택했고, 불린 두 개면 실수로 둘 다 켜질 수 있지만 단일 선택자는 배타적이다.
    """
    if not settings.event_produce_enabled or recipe_id is None:
        return
    ev = build_add_cart_event(user_id, recipe_id, session_id)

    if getattr(settings, "event_sink", "kafka") == "pg":
        # conn 이 없으면 조용히 버리지 않고 남긴다 — 배선 실수를 드러내기 위함(§조용한 실패 금지).
        if conn is None:
            _count("failure")
            _log.warning("EVENT_SINK=pg 인데 conn 이 없다 — 이벤트를 버린다",
                         extra={"event": "clickstream_no_conn", "sink": "pg"})
            return
        try:
            from app import queries
            n = await queries.insert_user_event(conn, ev)
        except Exception:   # noqa: BLE001 — 무엇이든 담기를 막지 않음
            _count("failure")
            _log.warning("clickstream pg write failed",
                         extra={"event": "clickstream_write_failed", "sink": "pg"})
            return
        _count("success" if n else "duplicate")
        return

    try:
        p = _get_producer(settings.kafka_bootstrap)
        p.produce(TOPIC, key=str(user_id), value=json.dumps(ev).encode())
        p.poll(0)
        _count("queued")            # 로컬 버퍼에 넣었을 뿐 — 전달 확인은 _on_delivery 가 한다
    except Exception:   # noqa: BLE001 — Kafka 부재/발행오류 무엇이든 담기를 막지 않음
        _count("failure")
        return


def flush(timeout: float = 5.0) -> None:
    """버퍼에 남은 이벤트를 밀어내고 반환 (종료 시 lifespan 이 호출).

    linger.ms=50 이라 produce 직후 메시지는 로컬 버퍼에 머문다 → flush 없이 종료하면
    ADD_CART(P1 랭킹 주 라벨)가 조용히 유실된다. 발행과 동일하게 best-effort.
    """
    if _producer is None:
        return
    try:
        _producer.flush(timeout)
    except Exception:   # noqa: BLE001 — 종료 경로라 무엇이든 셧다운을 막지 않음
        return
