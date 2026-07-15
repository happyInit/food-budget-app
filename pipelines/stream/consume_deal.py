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
from _kafka import consumer, TOPIC_DEAL_RAW               # noqa: E402
from _db import connect                                   # noqa: E402
from load_retail import build_matcher, stage_record, refine_record   # noqa: E402
import _redis                                             # noqa: E402
from _metrics import (ITEM_MATCHES, LAST_SUCCESS, PROCESSING_SECONDS,  # noqa: E402
                      RECORDS, SINK_WRITES, start_metrics_server)

GROUP = "deal-notifier"
COMMIT_EVERY = 100
IDLE_EXIT = float(os.environ["CONSUME_IDLE_EXIT"]) if os.environ.get("CONSUME_IDLE_EXIT") else None


def _redis_client():
    try:
        r = _redis.client(); r.ping(); return r
    except Exception as e:
        print(f"  ! Redis 연결 실패({e}) → PG만 적재", file=sys.stderr)
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
    match = build_matcher(cur)
    conn.commit()                       # 읽기 트랜잭션 종료 → item_master 락 즉시 해제 (#41 누수 방지)
    r = _redis_client()
    n = deals = 0; pending = 0; idle = 0.0

    def commit_pending(count):
        try:
            conn.commit()
        except Exception:
            SINK_WRITES.labels(GROUP, "postgres", "failure").inc(count)
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
                print(f"  ! consume error: {msg.error()}", file=sys.stderr)
                continue
            idle = 0.0
            started = time.perf_counter()
            try:
                source = dict(msg.headers() or {}).get("source", b"oasis").decode()
                payload = json.loads(msg.value())
                rid = stage_record(cur, source, payload)
                iid, _ = refine_record(cur, source, payload, match)  # PG(deal_type/timedeal_end)
                if rid is not None:
                    cur.execute("update crawl_raw set processed_at=now() where id=%s", (rid,))
                if r is not None:
                    _redis.push_deal(r, source, payload, item_id=iid)
                    deals += 1
            except Exception:
                RECORDS.labels(GROUP, "failure").inc()
                SINK_WRITES.labels(GROUP, "postgres", "failure").inc()
                if r is not None:
                    SINK_WRITES.labels(GROUP, "redis", "failure").inc()
                raise
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
    print(f"consumed {n} 딜 · PG 적재 {n} · Redis 등록 {deals}")


if __name__ == "__main__":
    main()
