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
from _kafka import producer, TOPIC_RECIPE_RAW          # noqa: E402
from load_10k_recipe import build_recipe_records        # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    p = producer()
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
    p.flush()
    print(f"produced {n} recipes → {TOPIC_RECIPE_RAW}")


if __name__ == "__main__":
    main()
