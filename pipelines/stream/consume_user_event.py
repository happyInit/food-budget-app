"""user-event-sink 컨슈머: Kafka events.user.activity → PG activity.user_event (설계 §2).

클릭스트림(VIEW·ADD_CART·NOTIF_CLICK)을 적재해 P1 개인화 랭킹(ai-spec §3)의 학습 라벨을 만든다.
consume_recipe.py 패턴 복제: 수동커밋(at-least-once) + `event_id` UNIQUE `ON CONFLICT DO NOTHING`
= DB 멱등(재전달 중복 무해 — 특히 ADD_CART 주라벨 중복 방지, §2.3 갭 해소는 #146 event_id로 완료).
env CONSUME_IDLE_EXIT=초 → backlog 소진 후 종료. 상주는 Compose/CronJob.
"""
import json
import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
from _kafka import consumer, producer, TOPIC_USER_ACTIVITY   # noqa: E402
from _db import connect                                 # noqa: E402
from _metrics import (LAST_SUCCESS, PROCESSING_SECONDS, RECORDS,   # noqa: E402
                      SINK_WRITES, start_metrics_server)
from _observability import get_pipeline_logger          # noqa: E402
from _dlq import quarantine, record_savepoint, summary   # noqa: E402  poison 격리(#252)
from psycopg.types.json import Jsonb                     # noqa: E402

GROUP = "user-event-sink"
COMMIT_EVERY = 100
IDLE_EXIT = float(os.environ["CONSUME_IDLE_EXIT"]) if os.environ.get("CONSUME_IDLE_EXIT") else None
log = get_pipeline_logger(GROUP)

_VALID_EVENTS = {"VIEW", "ADD_CART", "NOTIF_CLICK"}
_INSERT = """
insert into activity.user_event
  (event_id, user_id, session_id, event_type, recipe_id, item_id, occurred_at, context)
values (%(event_id)s, %(user_id)s, %(session_id)s, %(event_type)s,
        %(recipe_id)s, %(item_id)s, %(occurred_at)s, %(context)s)
on conflict (event_id) do nothing
"""


def to_params(rec: dict) -> dict:
    """메시지 → INSERT 파라미터. event_type을 스키마 CHECK와 동일 검증(불량은 ValueError → 레코드 거절)."""
    et = rec["event_type"]
    if et not in _VALID_EVENTS:
        raise ValueError(f"invalid event_type: {et!r}")
    ctx = rec.get("context")
    return {
        "event_id": rec["event_id"],
        "user_id": rec["user_id"],
        "session_id": rec.get("session_id"),
        "event_type": et,
        "recipe_id": rec.get("recipe_id"),
        "item_id": rec.get("item_id"),
        "occurred_at": rec["occurred_at"],
        "context": Jsonb(ctx) if ctx is not None else None,
    }


def process_event(cur, rec: dict) -> int:
    """1건 처리 → 적재 1 / 중복(멱등) 0. 검증 실패·필수키 누락은 예외(호출측이 거절 카운트)."""
    cur.execute(_INSERT, to_params(rec))
    return cur.rowcount


def main():
    start_metrics_server(GROUP)
    c = consumer(GROUP)
    c.subscribe([TOPIC_USER_ACTIVITY])
    running = True

    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    conn = connect(); cur = conn.cursor()
    # poison 격리용 프로듀서(#252). librdkafka 는 지연 연결이라 여기서 브로커에 붙지 않는다 —
    # 기동 실패 위험이 없다. 발행은 send_to_dlq 가 flush 로 전달을 확인한다.
    dlq = producer(GROUP)          # DLQ 발행용 — 전달실패 로그에 컨슈머 이름이 붙는다(#558)
    log.info(
        "user-event sink started",
        extra={"event": "service_started", "component": GROUP,
               "topic": TOPIC_USER_ACTIVITY, "consumer_group": GROUP},
    )
    n = dup = pending = 0
    idle = 0.0

    def commit_pending(count):
        try:
            conn.commit()
        except Exception as exc:
            SINK_WRITES.labels(GROUP, "postgres", "failure").inc(count)
            log.exception(
                "postgres commit failed",
                extra={"event": "sink_write_failed", "component": GROUP, "dependency": "postgres",
                       "operation": "transaction.commit", "consumer_group": GROUP,
                       "record_count": count, "error_type": type(exc).__name__, "retryable": True},
            )
            raise
        SINK_WRITES.labels(GROUP, "postgres", "success").inc(count)
        LAST_SUCCESS.labels(GROUP).set_to_current_time()
        c.commit()
    try:
        while running:
            msg = c.poll(1.0)
            if msg is None:
                idle += 1.0
                if pending:
                    commit_pending(pending); pending = 0
                if IDLE_EXIT and idle >= IDLE_EXIT:
                    break
                continue
            if msg.error():
                RECORDS.labels(GROUP, "kafka_error").inc()
                log.warning(
                    "kafka consumer returned an error",
                    extra={"event": "kafka_consume_failed", "component": GROUP,
                           "topic": TOPIC_USER_ACTIVITY, "consumer_group": GROUP,
                           "error_type": "KafkaMessageError", "error_code": msg.error().code(),
                           "retryable": True},
                )
                continue
            idle = 0.0
            started = time.perf_counter()
            try:
                # savepoint 로 감싼다 — 제약 위반은 트랜잭션을 abort 시키므로, 그냥 rollback 하면
                # **같은 배치의 앞선 정상 레코드까지** 사라진다(오프셋은 뒤에 커밋되어 조용히 유실).
                with record_savepoint(cur):
                    rec = json.loads(msg.value())
                    inserted = process_event(cur, rec)
            except Exception as exc:
                RECORDS.labels(GROUP, "failure").inc()
                SINK_WRITES.labels(GROUP, "postgres", "failure").inc()
                log.exception(
                    "user event processing failed",
                    extra={"event": "pipeline_record_rejected", "component": GROUP,
                           "topic": TOPIC_USER_ACTIVITY, "consumer_group": GROUP,
                           "error_type": type(exc).__name__, "retryable": False},
                )
                # 영구 실패(payload 파손·제약 위반)면 DLQ 로 격리하고 진행한다(#252).
                # 일시 실패(인프라)는 기존대로 raise — 파드 재시작이 곧 재시도다.
                if not quarantine(dlq, msg, exc, GROUP, TOPIC_USER_ACTIVITY):
                    raise
                log.warning(summary(msg, exc, TOPIC_USER_ACTIVITY),
                            extra={"event": "pipeline_record_quarantined", "component": GROUP,
                                   "topic": TOPIC_USER_ACTIVITY, "consumer_group": GROUP,
                                   "error_type": type(exc).__name__, "retryable": False})
                RECORDS.labels(GROUP, "dlq").inc()
                pending += 1        # 🔴 오프셋이 전진해야 루프가 풀린다
                # continue 하지 않는다 — 그냥 흘려보내면 finally(지연 관측) → COMMIT_EVERY 검사가
                # 기존 경로 그대로 실행된다. continue 를 쓰면 finally 가 중복 관측된다.
            else:
                RECORDS.labels(GROUP, "success").inc()
                n += 1; pending += 1
                if inserted == 0:
                    dup += 1                          # event_id 멱등 — 재전달 중복(무해)
            finally:
                PROCESSING_SECONDS.labels(GROUP).observe(time.perf_counter() - started)
            if pending >= COMMIT_EVERY:
                commit_pending(pending); pending = 0
        if pending:
            commit_pending(pending)
    finally:
        cur.close(); conn.close(); c.close()
    log.info(
        "user-event sink stopped",
        extra={"event": "service_stopped", "component": GROUP, "topic": TOPIC_USER_ACTIVITY,
               "consumer_group": GROUP, "result": "completed", "record_count": n, "duplicates": dup},
    )


if __name__ == "__main__":
    main()
