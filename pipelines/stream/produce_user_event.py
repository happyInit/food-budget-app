"""user_event 프로듀서 헬퍼 — 백엔드가 클릭스트림 이벤트를 Kafka events.user.activity로 발행.

poller가 아니라 **인라인 호출용**(백엔드가 이벤트 발생 시 emit): ADD_CART=mealplan, VIEW=프론트→백엔드,
NOTIF_CLICK=notify. key=user_id(유저별 순서·파티션 분산). 멱등키 event_id는 호출측이 발급(uuid) —
컨슈머 `ON CONFLICT (event_id) DO NOTHING`과 짝. 메시지 계약 = consume_user_event.to_params.

사용:
    from produce_user_event import emit_user_event, build_event
    emit_user_event(build_event(user_id=7, event_type="ADD_CART", recipe_id=10,
                                session_id=sid, occurred_at=now_iso))
    flush()   # 요청 끝/주기적
"""
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _kafka import producer, TOPIC_USER_ACTIVITY   # noqa: E402

_VALID_EVENTS = {"VIEW", "ADD_CART", "NOTIF_CLICK"}
_producer = None


def _get_producer():
    global _producer
    if _producer is None:
        _producer = producer()          # _kafka: 멱등·acks=all
    return _producer


def build_event(user_id, event_type, *, occurred_at, session_id=None,
                recipe_id=None, item_id=None, context=None, event_id=None) -> dict:
    """메시지 계약대로 이벤트 dict 구성(+ event_id 자동 발급). event_type 검증."""
    if event_type not in _VALID_EVENTS:
        raise ValueError(f"invalid event_type: {event_type!r}")
    return {
        "event_id": event_id or uuid.uuid4().hex,
        "user_id": user_id, "session_id": session_id, "event_type": event_type,
        "recipe_id": recipe_id, "item_id": item_id,
        "occurred_at": occurred_at, "context": context,
    }


def emit_user_event(event: dict, prod=None) -> None:
    """이벤트 1건 발행(fire-and-forget). prod 주입 가능(테스트). key=user_id."""
    if event.get("event_type") not in _VALID_EVENTS:
        raise ValueError(f"invalid event_type: {event.get('event_type')!r}")
    p = prod or _get_producer()
    p.produce(TOPIC_USER_ACTIVITY, key=str(event["user_id"]), value=json.dumps(event).encode())
    p.poll(0)                            # 델리버리 콜백 처리(non-blocking)


def flush(timeout: float = 5.0) -> None:
    if _producer is not None:
        _producer.flush(timeout)
