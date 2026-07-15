"""만료 딜 정리: Redis retail:deals:active/detail에서 마감 지난 딜 제거 (딜 lifecycle).
deal-notifier는 KEDA로 0까지 스케일되므로(딜 없을 때) 독립 실행이 안정적.
K8s CronJob(주기 실행) 또는 --loop(로컬 상주). Redis 없으면 no-op.
사용: python prune_deals.py            # 1회
      python prune_deals.py --loop 600  # 10분 간격 상주
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _redis                                           # noqa: E402
from _metrics import (ACTIVE_DEALS, DEALS_PRUNED, LAST_SUCCESS,       # noqa: E402
                      PROCESSING_SECONDS, RECORDS, SINK_WRITES,
                      start_metrics_server)

COMPONENT = "deal-pruner"


def prune_once():
    started = time.perf_counter()
    try:
        r = _redis.client()
        r.ping()
    except Exception as e:
        RECORDS.labels(COMPONENT, "failure").inc()
        SINK_WRITES.labels(COMPONENT, "redis", "failure").inc()
        PROCESSING_SECONDS.labels(COMPONENT).observe(time.perf_counter() - started)
        print(f"Redis 연결 실패({e}) → skip", file=sys.stderr)
        return 0
    n = _redis.prune_expired(r)
    active = r.zcard(_redis.ZSET_ACTIVE)
    RECORDS.labels(COMPONENT, "success").inc()
    SINK_WRITES.labels(COMPONENT, "redis", "success").inc()
    DEALS_PRUNED.labels(COMPONENT).inc(n)
    ACTIVE_DEALS.labels(COMPONENT).set(active)
    LAST_SUCCESS.labels(COMPONENT).set_to_current_time()
    PROCESSING_SECONDS.labels(COMPONENT).observe(time.perf_counter() - started)
    print(f"만료 딜 {n}개 정리 · 활성 {active}개 잔여")
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=float, metavar="SEC", help="초 간격 반복(상주). 미지정=1회")
    args = ap.parse_args()
    start_metrics_server(COMPONENT)
    if args.loop:
        while True:
            prune_once()
            time.sleep(args.loop)
    else:
        prune_once()


if __name__ == "__main__":
    main()
