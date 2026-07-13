"""Poller: 크롤 결과 → Kafka retail.crawl.raw (design.md §7.1 [정기 폴링] 프로듀서).
K8s CronJob으로 주기 실행(일1~2회). 크롤러 출력 파일을 읽어 레코드별 produce.
  key=source:product_id (파티션·SKU 순서) · value=원본 JSON · header source.
사용:
  python produce_retail.py                         # 모든 output 파일(컬리+오아시스)
  python produce_retail.py --source oasis --file X.jsonl   # 특정 파일(단일 폴 시연)
  python produce_retail.py --limit 20
"""
import argparse
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _kafka import producer, TOPIC_RETAIL_RAW, TOPIC_DEAL_RAW    # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def iter_records(source=None, file=None):
    """(source, record) 제너레이터. file 지정 시 그 파일만, 아니면 output 글롭."""
    if file:
        src = source or ("kurly" if file.endswith(".json") else "oasis")
        if file.endswith(".jsonl"):
            for line in open(file, encoding="utf-8"):
                if line.strip():
                    yield src, json.loads(line)
        else:
            for r in json.load(open(file, encoding="utf-8")):
                yield src, r
        return
    for f in glob.glob(str(ROOT / "crawler/kurly/output/*.json")):
        for r in json.load(open(f, encoding="utf-8")):
            yield "kurly", r
    for f in glob.glob(str(ROOT / "crawler/oasis/output/*.jsonl")):
        for line in open(f, encoding="utf-8"):
            if line.strip():
                yield "oasis", json.loads(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["kurly", "oasis"])
    ap.add_argument("--file")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    p = producer()
    n = 0
    for source, rec in iter_records(args.source, args.file):
        pid = rec.get("product_id")
        if pid is None:
            continue
        topic = TOPIC_DEAL_RAW if rec.get("deal_type") in ("closeSale", "timeSale") else TOPIC_RETAIL_RAW
        p.produce(topic,
                  key=f"{source}:{pid}".encode(),
                  value=json.dumps(rec, ensure_ascii=False).encode(),
                  headers=[("source", source.encode())])
        n += 1
        if n % 500 == 0:
            p.poll(0)
        if args.limit and n >= args.limit:
            break
    p.flush()
    print(f"produced {n} records → Kafka ({TOPIC_RETAIL_RAW}/{TOPIC_DEAL_RAW} deal_type 라우팅)")


if __name__ == "__main__":
    main()
