"""deal-notifier 컨슈머: Kafka retail.deal.raw → PG(가격이력, deal_type) + Redis(핫딜 알림).
design.md §7.1 '딜 → PG + Redis' · §8.2 핫딜 fan-out(보조축).
  메시지 → stage_record + refine_record(PG, deal_type/timedeal_end) + push_deal(Redis ZSET).
Redis 없으면 PG만(graceful). 멱등: PG upsert · Redis zadd(product 단위).
env CONSUME_IDLE_EXIT=초 → backlog 소진 후 종료(시연). 현재는 Docker Compose 상주.
"""
import json
import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
from _kafka import consumer, producer, TOPIC_DEAL_RAW               # noqa: E402
from _db import connect                                   # noqa: E402
from load_retail import build_matcher, stage_record, refine_record   # noqa: E402
import _redis                                             # noqa: E402
from _metrics import (ITEM_MATCHES, LAST_SUCCESS, PROCESSING_SECONDS,  # noqa: E402
                      RECORDS, SINK_WRITES, start_metrics_server)
from _observability import get_pipeline_logger                    # noqa: E402
from _dlq import quarantine, record_savepoint, summary   # noqa: E402  poison 격리(#252)

GROUP = "deal-notifier"
COMMIT_EVERY = 100
IDLE_EXIT = float(os.environ["CONSUME_IDLE_EXIT"]) if os.environ.get("CONSUME_IDLE_EXIT") else None
log = get_pipeline_logger(GROUP)


def _redis_client():
    try:
        r = _redis.client(); r.ping(); return r
    except Exception as exc:
        log.warning(
            "redis unavailable; continuing with postgres only",
            extra={
                "event": "dependency_unavailable",
                "component": GROUP,
                "dependency": "redis",
                "operation": "connection.ping",
                "error_type": type(exc).__name__,
                "retryable": True,
            },
        )
        return None


def main():
    start_metrics_server(GROUP)
    c = consumer(GROUP)
    c.subscribe([TOPIC_DEAL_RAW])
    running = True

    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    conn = connect(); cur = conn.cursor()
    # poison 격리용(#252). librdkafka 지연 연결이라 여기서 브로커에 붙지 않는다.
    dlq = producer()
    match = build_matcher(cur)
    conn.commit()                       # 읽기 트랜잭션 종료 → item_master 락 즉시 해제 (#41 누수 방지)
    r = _redis_client()
    log.info(
        "deal notifier started",
        extra={
            "event": "service_started",
            "component": GROUP,
            "topic": TOPIC_DEAL_RAW,
            "consumer_group": GROUP,
        },
    )
    n = deals = 0; pending = 0; idle = 0.0

    def commit_pending(count):
        try:
            conn.commit()
        except Exception as exc:
            SINK_WRITES.labels(GROUP, "postgres", "failure").inc(count)
            log.error(
                "postgres commit failed",
                extra={
                    "event": "sink_write_failed",
                    "component": GROUP,
                    "dependency": "postgres",
                    "operation": "transaction.commit",
                    "consumer_group": GROUP,
                    "record_count": count,
                    "error_type": type(exc).__name__,
                    "retryable": True,
                },
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
                    extra={
                        "event": "kafka_consume_failed",
                        "component": GROUP,
                        "topic": TOPIC_DEAL_RAW,
                        "consumer_group": GROUP,
                        "error_type": "KafkaMessageError",
                        "error_code": msg.error().code(),
                        "retryable": True,
                    },
                )
                continue
            idle = 0.0
            started = time.perf_counter()
            try:
                # savepoint — 제약 위반은 트랜잭션을 abort 시킨다. 그냥 rollback 하면 **같은 배치의
                # 앞선 정상 레코드까지** 사라지고(오프셋은 뒤에 커밋) 조용히 유실된다(#252).
                with record_savepoint(cur):
                    source = dict(msg.headers() or {}).get("source", b"oasis").decode()
                    payload = json.loads(msg.value())
                    rid = stage_record(cur, source, payload)
                    iid, _ = refine_record(cur, source, payload, match)  # PG(deal_type/timedeal_end)
                    if rid is not None:
                        cur.execute("update crawl_raw set processed_at=now() where id=%s", (rid,))
                    if r is not None:
                        _redis.push_deal(r, source, payload, item_id=iid)
                        deals += 1
            except Exception as exc:
                RECORDS.labels(GROUP, "failure").inc()
                SINK_WRITES.labels(GROUP, "postgres", "failure").inc()
                if r is not None:
                    SINK_WRITES.labels(GROUP, "redis", "failure").inc()
                log.error(
                    "deal record processing failed",
                    extra={
                        "event": "pipeline_record_rejected",
                        "component": GROUP,
                        "topic": TOPIC_DEAL_RAW,
                        "consumer_group": GROUP,
                        "error_type": type(exc).__name__,
                        "retryable": False,
                    },
                )
                # 영구 실패(payload 파손·제약 위반)면 DLQ 로 격리하고 진행 · 일시 실패는 raise(#252).
                # ⚠️ Redis 장애(ConnectionError 등)는 화이트리스트에 없어 **raise 된다** — 맞는 동작이다.
                #    딜은 Redis 가 조회면이라, 못 넣은 채 오프셋을 전진시키면 핫딜이 조용히 빈다.
                if not quarantine(dlq, msg, exc, GROUP, TOPIC_DEAL_RAW):
                    raise
                log.warning(summary(msg, exc, TOPIC_DEAL_RAW),
                            extra={"event": "pipeline_record_quarantined", "component": GROUP,
                                   "topic": TOPIC_DEAL_RAW, "consumer_group": GROUP,
                                   "error_type": type(exc).__name__, "retryable": False})
                RECORDS.labels(GROUP, "dlq").inc()
                pending += 1     # 🔴 오프셋이 전진해야 루프가 풀린다(continue 금지 — finally 중복)
            else:
                RECORDS.labels(GROUP, "success").inc()
                ITEM_MATCHES.labels(GROUP, "matched" if iid is not None else "unmatched").inc()
                SINK_WRITES.labels(GROUP, "redis", "success" if r is not None else "failure").inc()
                n += 1; pending += 1
            finally:
                PROCESSING_SECONDS.labels(GROUP).observe(time.perf_counter() - started)
            if pending >= COMMIT_EVERY:
                commit_pending(pending); pending = 0
        if pending:
            commit_pending(pending)
    finally:
        cur.close(); conn.close(); c.close()
    log.info(
        "deal notifier stopped",
        extra={
            "event": "service_stopped",
            "component": GROUP,
            "topic": TOPIC_DEAL_RAW,
            "consumer_group": GROUP,
            "result": "completed",
            "record_count": n,
        },
    )


if __name__ == "__main__":
    main()
