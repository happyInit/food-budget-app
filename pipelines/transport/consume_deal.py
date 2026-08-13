"""deal-notifier (S3/SQS) — incoming/deal/** → PG(deal_type/timedeal_end) + Redis ZSET.

구 `pipelines/stream/consume_deal.py`(Kafka)의 대체물. 전처리·발행 로직은 그대로 재사용한다 —
바뀐 것은 운반뿐이다.

⚠️ Redis 는 **선택 의존**이다(원본과 동일) — 못 붙으면 경고만 남기고 PG 적재는 계속한다.
   딜 알림은 늦어도 되지만 가격 이력이 비는 건 복구가 안 되기 때문이다.

env: MP_SQS_URL(필수) · MP_CRAWL_BUCKET · CONSUME_IDLE_EXIT(초, 미설정 시 상주)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stream"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
import _redis                                                          # noqa: E402
from _metrics import SINK_WRITES                                       # noqa: E402
from _observability import get_pipeline_logger                         # noqa: E402
from _refinery import run                                              # noqa: E402
from load_retail import build_matcher, refine_record, stage_record     # noqa: E402

GROUP = "deal-notifier"
STREAM = "deal"
COMMIT_EVERY = 200
log = get_pipeline_logger(GROUP)


def _redis_client():
    try:
        r = _redis.client()
        r.ping()
        return r
    except Exception as exc:  # noqa: BLE001 — 붙지 않아도 PG 적재는 계속한다
        log.warning("redis unavailable; continuing with postgres only", extra={
            "event": "dependency_unavailable", "component": GROUP, "dependency": "redis",
            "operation": "connection.ping", "error_type": type(exc).__name__, "retryable": True})
        return None


def build_context(cur):
    return (build_matcher(cur), _redis_client())


def process(cur, ctx, source, payload):
    match, r = ctx
    rid = stage_record(cur, source, payload)
    iid, _ = refine_record(cur, source, payload, match)
    if rid is not None:
        cur.execute("update crawl_raw set processed_at=now() where id=%s", (rid,))
    if r is not None:
        _redis.push_deal(r, source, payload, item_id=iid)
    return (1 if iid is not None else 0, 1)


def on_failure(ctx, _exc):
    if ctx[1] is not None:
        SINK_WRITES.labels(GROUP, "redis", "failure").inc()


if __name__ == "__main__":
    run(group=GROUP, stream=STREAM, commit_every=COMMIT_EVERY,
        build_context=build_context, process=process, on_failure=on_failure)
