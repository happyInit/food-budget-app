"""객체 단위 리파이너 골격 — 컨슈머 3종 공통 (C-44).

Kafka 컨슈머 3종(`pipelines/stream/consume_*.py`)은 각자 poll 루프를 복제하고 있었다.
여기서는 그 루프가 **"DB 커밋 → 메시지 삭제"** 라는 유실 방지 계약을 품고 있어서, 복제하면
세 번 틀릴 수 있다. 골격을 하나만 두고 레코드 처리만 주입한다.

주입 계약:
    build_context(cur) -> ctx            매처 등 1회 로드분
    process(cur, ctx, source, payload) -> (matched, total)
                                         ITEM_MATCHES 라벨 분해에 쓴다.
                                         retail·deal 은 (1,1)/(0,1) · recipe 는 (재료매칭, 재료수)
    on_failure(ctx, exc)                 선택. 컨슈머 고유 실패 계측(deal 의 redis 등)

메트릭·로그 스키마는 Kafka 컨슈머와 **동일하게 유지한다** — 대시보드·알림이 GROUP 라벨에
붙어 있어서, 이름이 바뀌면 관측이 조용히 빈다.
"""
import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stream"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
from _s3 import iter_records, parse_source, quarantine_record          # noqa: E402
from _sqs import consume                                              # noqa: E402
from _db import connect                                               # noqa: E402
from _metrics import (ITEM_MATCHES, LAST_SUCCESS, PROCESSING_SECONDS,  # noqa: E402
                      RECORDS, SINK_WRITES, start_metrics_server)
from _observability import get_pipeline_logger                        # noqa: E402
from _dlq import is_permanent, record_savepoint                       # noqa: E402  (#252 — Kafka 무관)

IDLE_EXIT = float(os.environ["CONSUME_IDLE_EXIT"]) if os.environ.get("CONSUME_IDLE_EXIT") else None


def run(*, group, stream, commit_every, build_context, process, on_failure=None):
    log = get_pipeline_logger(group)
    start_metrics_server(group)

    conn = connect()
    cur = conn.cursor()
    ctx = build_context(cur)
    conn.commit()  # 읽기 트랜잭션 종료 → item_master 락 즉시 해제 (#41 누수 방지)

    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    log.info(f"{group} started", extra={
        "event": "service_started", "component": group, "consumer_group": group, "stream": stream})

    def commit_pending(count):
        try:
            conn.commit()
        except Exception as exc:
            SINK_WRITES.labels(group, "postgres", "failure").inc(count)
            log.exception("postgres commit failed", extra={
                "event": "sink_write_failed", "component": group,
                "operation": "transaction.commit", "error_type": type(exc).__name__, "retryable": True})
            raise
        SINK_WRITES.labels(group, "postgres", "success").inc(count)
        LAST_SUCCESS.labels(group).set_to_current_time()

    def handle(bucket, key, heartbeat):
        """객체 1개 = 크롤 1회분. 🔴 정상 반환해야만 _sqs 가 메시지를 지운다."""
        source = parse_source(key)
        rid = key.rsplit("/", 1)[-1].removesuffix(".jsonl")
        pending = n = quarantined = 0
        began = time.perf_counter()

        for seq, payload in iter_records(bucket, key):
            started = time.perf_counter()
            try:
                # savepoint — 제약 위반은 트랜잭션을 abort 시킨다. 그냥 rollback 하면 **같은 객체의
                # 앞선 정상 레코드까지** 사라진다(#252).
                with record_savepoint(cur):
                    matched, total = process(cur, ctx, source, payload)
            except Exception as exc:
                RECORDS.labels(group, "failure").inc()
                SINK_WRITES.labels(group, "postgres", "failure").inc()
                if on_failure is not None:
                    on_failure(ctx, exc)
                log.exception(f"{group} record processing failed", extra={
                    "event": "pipeline_record_rejected", "component": group, "stream": stream,
                    "consumer_group": group, "object_key": key, "seq": seq,
                    "error_type": type(exc).__name__, "retryable": not is_permanent(exc)})
                # 일시 실패는 메시지를 남긴다 — 가시성 타임아웃 뒤 재전달되고 객체를 다시 읽는다.
                # 적재가 전부 멱등이라 재처리는 무해하다(load_retail.py: on conflict do nothing).
                if not is_permanent(exc):
                    raise
                # 영구 실패는 그 레코드만 S3 failed/ 로 격리하고 진행한다(구 Kafka DLQ 토픽의 대체).
                # 🔴 객체 하나를 통째로 DLQ 로 보내면 정상 레코드 수천 건이 같이 죽는다.
                failed_at = quarantine_record(stream, source, rid, seq, payload, exc, group)
                log.warning(f"quarantined → s3://{failed_at}", extra={
                    "event": "pipeline_record_quarantined", "component": group, "stream": stream,
                    "consumer_group": group, "object_key": key, "seq": seq,
                    "error_type": type(exc).__name__, "retryable": False})
                RECORDS.labels(group, "dlq").inc()
                quarantined += 1
                pending += 1
            else:
                RECORDS.labels(group, "success").inc()
                ITEM_MATCHES.labels(group, "matched").inc(matched)
                ITEM_MATCHES.labels(group, "unmatched").inc(total - matched)
                n += 1
                pending += 1
            finally:
                PROCESSING_SECONDS.labels(group).observe(time.perf_counter() - started)

            if pending >= commit_every:
                commit_pending(pending)
                pending = 0
                heartbeat()  # 커밋 지점마다 가시성 연장 — 긴 객체를 남의 파드가 다시 집는 것 방지

        if pending:
            commit_pending(pending)

        log.info(f"{group} object ingested", extra={
            "event": "object_ingested", "component": group, "stream": stream,
            "object_key": key, "record_count": n, "quarantined": quarantined,
            "duration_seconds": round(time.perf_counter() - began, 3), "result": "success"})

    try:
        objects = consume(handle, log=log, component=group, idle_exit=IDLE_EXIT,
                          should_run=lambda: running)
    finally:
        cur.close()
        conn.close()

    log.info(f"{group} stopped", extra={
        "event": "service_stopped", "component": group, "consumer_group": group,
        "stream": stream, "result": "completed", "record_count": objects})
