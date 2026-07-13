"""retail-refiner 컨슈머: Kafka retail.crawl.raw → 전처리 → 현재 테이블 (design.md §7.1).
'파싱/전처리를 Kafka 파이프라인이' = 이 컨슈머 단계가 정규화(retail_norm)+매칭(gazetteer)+적재.
  메시지 → stage_record(crawl_raw 원본) + refine_record(retail_product/price) → 커밋.
멱등: product upsert · price on-conflict · crawl_raw on-conflict. at-least-once + 재처리 안전.
K8s Deployment로 상주 · KEDA가 컨슈머 lag으로 스케일(deploy/k8s/keda-retail-refiner.yaml).
env CONSUME_IDLE_EXIT=초 → backlog 소진 후 종료(CronJob/시연). 미설정 시 상주.
"""
import json
import os
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
from _kafka import consumer, TOPIC_RETAIL_RAW              # noqa: E402
from _db import connect                                    # noqa: E402
from load_retail import build_matcher, stage_record, refine_record   # noqa: E402

GROUP = "retail-refiner"
COMMIT_EVERY = 200
IDLE_EXIT = float(os.environ["CONSUME_IDLE_EXIT"]) if os.environ.get("CONSUME_IDLE_EXIT") else None


def main():
    c = consumer(GROUP)
    c.subscribe([TOPIC_RETAIL_RAW])
    running = True

    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    conn = connect()
    cur = conn.cursor()
    match = build_matcher(cur)          # gazetteer 1회 로드(큐레이션 변경 시 재시작)
    n = hit = pending = 0
    idle = 0.0
    try:
        while running:
            msg = c.poll(1.0)
            if msg is None:
                idle += 1.0
                if pending:
                    conn.commit(); c.commit(); pending = 0
                if IDLE_EXIT and idle >= IDLE_EXIT:
                    break
                continue
            if msg.error():
                print(f"  ! consume error: {msg.error()}", file=sys.stderr)
                continue
            idle = 0.0
            source = dict(msg.headers() or {}).get("source", b"oasis").decode()
            payload = json.loads(msg.value())
            rid = stage_record(cur, source, payload)
            iid, _ = refine_record(cur, source, payload, match)
            if rid is not None:
                cur.execute("update crawl_raw set processed_at=now() where id=%s", (rid,))
            n += 1; hit += iid is not None; pending += 1
            if pending >= COMMIT_EVERY:
                conn.commit(); c.commit(); pending = 0    # DB 먼저→오프셋(유실 방지)
        if pending:
            conn.commit(); c.commit()
    finally:
        cur.close(); conn.close(); c.close()
    print(f"consumed {n} · item_id 매칭 {hit}")


if __name__ == "__main__":
    main()
