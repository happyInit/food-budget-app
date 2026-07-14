"""recipe-refiner 컨슈머: Kafka recipe.crawl.raw → process_recipe → PG (design.md §7.1).
'파싱/전처리를 Kafka 파이프라인이' = 이 컨슈머가 재료 gazetteer 매칭 + recipe/step/ingredient 적재.
전처리 로직 = load_10k_recipe.process_recipe (배치와 동일 재사용). 멱등 upsert.
(§7.1 recipe→NER→ES 중 NER=크롤러 사전분할+gazetteer, ES 색인은 후속.)
env CONSUME_IDLE_EXIT=초 → backlog 소진 후 종료. K8s Deployment+KEDA(lag).
"""
import json
import os
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
from _kafka import consumer, TOPIC_RECIPE_RAW           # noqa: E402
from _db import connect                                 # noqa: E402
from gazetteer import load_gazetteer, make_matcher      # noqa: E402
from load_10k_recipe import process_recipe              # noqa: E402

GROUP = "recipe-refiner"
COMMIT_EVERY = 100
IDLE_EXIT = float(os.environ["CONSUME_IDLE_EXIT"]) if os.environ.get("CONSUME_IDLE_EXIT") else None


def main():
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
    n = hit = tot = pending = 0
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
            rec = json.loads(msg.value())
            _, _, h, t = process_recipe(cur, rec, match)
            n += 1; hit += h; tot += t; pending += 1
            if pending >= COMMIT_EVERY:
                conn.commit(); c.commit(); pending = 0
        if pending:
            conn.commit(); c.commit()
    finally:
        cur.close(); conn.close(); c.close()
    pct = f"{round(100 * hit / tot, 1)}%" if tot else "—"
    print(f"consumed {n} recipes · 재료 item_id 매칭 {hit}/{tot} = {pct}")


if __name__ == "__main__":
    main()
