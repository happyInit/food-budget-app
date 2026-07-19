"""클릭스트림 이벤트 발행 — mealplan이 ADD_CART를 Kafka `events.user.activity`로 produce (Track 1).

개인화 랭킹(ai-spec §3)의 **주 라벨**(ADD_CART). 메시지 계약 = `consume_user_event.to_params`와 동일.
flag OFF 기본 + **best-effort**(발행 실패·Kafka 부재는 장바구니 담기를 절대 막지 않음). key=user_id.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

TOPIC = "events.user.activity"
_producer = None


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
