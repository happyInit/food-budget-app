"""recipe-refiner 컨슈머: Kafka recipe.crawl.raw → process_recipe → PG (design.md §7.1).
'파싱/전처리를 Kafka 파이프라인이' = 이 컨슈머가 재료 gazetteer 매칭 + recipe/step/ingredient 적재.
전처리 로직 = load_10k_recipe.process_recipe (배치와 동일 재사용). 멱등 upsert.
(§7.1 recipe→NER→ES 중 NER=크롤러 사전분할+gazetteer, ES 색인은 후속.)
env CONSUME_IDLE_EXIT=초 → backlog 소진 후 종료. 현재는 Docker Compose 상주.
"""
import json
import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
from _kafka import consumer, TOPIC_RECIPE_RAW           # noqa: E402
from _db import connect                                 # noqa: E402
from gazetteer import load_gazetteer, make_matcher      # noqa: E402
from load_10k_recipe import process_recipe              # noqa: E402
from _metrics import (ITEM_MATCHES, LAST_SUCCESS, PROCESSING_SECONDS,        # noqa: E402
                      RECORDS, SINK_WRITES, start_metrics_server)
from _observability import get_pipeline_logger                    # noqa: E402

GROUP = "recipe-refiner"
COMMIT_EVERY = 100
IDLE_EXIT = float(os.environ["CONSUME_IDLE_EXIT"]) if os.environ.get("CONSUME_IDLE_EXIT") else None
log = get_pipeline_logger(GROUP)


def main():
    start_metrics_server(GROUP)
    c = consumer(GROUP)
    c.subscribe([TOPIC_RECIPE_RAW])
    running = True

    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    conn = connect(); cur = conn.cursor()
    match = make_matcher(load_gazetteer(cur))       # 레시피 재료 = plain gazetteer 매처
    conn.commit()                                   # 읽기 트랜잭션 종료 → item_master 락 즉시 해제 (#41 누수 방지)
    log.info(
        "recipe refiner started",
        extra={
            "event": "service_started",
            "component": GROUP,
            "topic": TOPIC_RECIPE_RAW,
            "consumer_group": GROUP,
        },
    )
    n = hit = tot = pending = 0
    idle = 0.0

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
                        "topic": TOPIC_RECIPE_RAW,
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
                rec = json.loads(msg.value())
                _, _, h, t = process_recipe(cur, rec, match)
            except Exception as exc:
                RECORDS.labels(GROUP, "failure").inc()
                SINK_WRITES.labels(GROUP, "postgres", "failure").inc()
                log.error(
                    "recipe record processing failed",
                    extra={
                        "event": "pipeline_record_rejected",
                        "component": GROUP,
                        "topic": TOPIC_RECIPE_RAW,
                        "consumer_group": GROUP,
                        "error_type": type(exc).__name__,
                        "retryable": False,
                    },
                )
                raise
            else:
                RECORDS.labels(GROUP, "success").inc()
                ITEM_MATCHES.labels(GROUP, "matched").inc(h)
                ITEM_MATCHES.labels(GROUP, "unmatched").inc(t - h)
                n += 1; hit += h; tot += t; pending += 1
            finally:
                PROCESSING_SECONDS.labels(GROUP).observe(time.perf_counter() - started)
            if pending >= COMMIT_EVERY:
                commit_pending(pending); pending = 0
        if pending:
            commit_pending(pending)
    finally:
        cur.close(); conn.close(); c.close()
    log.info(
        "recipe refiner stopped",
        extra={
            "event": "service_stopped",
            "component": GROUP,
            "topic": TOPIC_RECIPE_RAW,
            "consumer_group": GROUP,
            "result": "completed",
            "record_count": n,
        },
    )


if __name__ == "__main__":
    main()
