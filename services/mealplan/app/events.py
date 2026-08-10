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


def build_add_cart_event(user_id: int, recipe_id: int, session_id: str | None) -> dict:
    """ADD_CART 이벤트 dict(계약대로). Kafka 무관 — 순수(테스트 가능)."""
    return {
        "event_id": uuid.uuid4().hex,
        "user_id": user_id,
        "session_id": session_id,
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


def emit_add_cart(settings, user_id: int, recipe_id: int | None, session_id: str | None) -> None:
    """장바구니 담기 → ADD_CART 발행. flag OFF·recipe_id 없음·발행 실패 시 무동작(담기 무손상)."""
    if not settings.event_produce_enabled or recipe_id is None:
        return
    try:
        ev = build_add_cart_event(user_id, recipe_id, session_id)
        p = _get_producer(settings.kafka_bootstrap)
        p.produce(TOPIC, key=str(user_id), value=json.dumps(ev).encode())
        p.poll(0)
    except Exception:   # noqa: BLE001 — Kafka 부재/발행오류 무엇이든 담기를 막지 않음
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
