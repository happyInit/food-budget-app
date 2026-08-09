"""Poller: 만개 레시피 → Kafka recipe.crawl.raw (design.md §7.1, 주1회 CronJob).
build_recipe_records()로 CSV→레시피별 중첩레코드(재료·스텝) → produce. key=10K:src_recipe_id.
사용: python produce_recipe.py [--limit N]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
from _delivery import finalize                          # noqa: E402
from _kafka import producer, TOPIC_RECIPE_RAW          # noqa: E402
from _observability import get_pipeline_logger          # noqa: E402
from load_10k_recipe import build_recipe_records        # noqa: E402


COMPONENT = "poller-recipe"
log = get_pipeline_logger(COMPONENT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    log.info(
        "recipe poller started",
        extra={
            "event": "poller_started",
            "component": COMPONENT,
            "source": "10K",
            "topic": TOPIC_RECIPE_RAW,
        },
    )

    p = producer(COMPONENT)
    n = 0
    for rec in build_recipe_records():
        p.produce(TOPIC_RECIPE_RAW,
                  key=f"10K:{rec['src_recipe_id']}".encode(),
                  value=json.dumps(rec, ensure_ascii=False).encode(),
                  headers=[("source", b"10K")])
        n += 1
        if n % 500 == 0:
            p.poll(0)
        if args.limit and n >= args.limit:
            break
    # 🔴 종전엔 `p.flush()` 반환값을 버리고 `record_count: n`(= produce 호출 수) 을
    #    `result: "success"` 로 찍었다. 이제 **전달 확인된 수**로 마감한다(#558).
    report = finalize(p, produced=n)
    return report.emit(log, component=COMPONENT, source="10K", topic=TOPIC_RECIPE_RAW)


if __name__ == "__main__":
    # 종료코드 전달 — 없으면 판정이 로그에만 남고 CronJob 은 "성공"으로 보인다.
    sys.exit(main())
