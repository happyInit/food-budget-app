"""보존·정리 배치: activity/chat 원문 중 retention 지난 것 삭제 + 동의철회 유저 청소 (Track 1 §4).

prune_deals(Redis) 패턴의 **PG판**. 일1회 CronJob/상주(--loop). 테이블 부재/실패는 no-op(graceful).
집계 승격(§4-1, recipe_popularity)은 후속 — MVP는 보존 원문 정리 + 철회 청소(§4-4).
사용: python prune_user_data.py            # 1회
      python prune_user_data.py --loop 86400 # 일간격 상주
"""
import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
from _db import connect                                 # noqa: E402
from _metrics import (LAST_SUCCESS, PROCESSING_SECONDS, RECORDS,   # noqa: E402
                      SINK_WRITES, start_metrics_server)
from _observability import get_pipeline_logger          # noqa: E402

COMPONENT = "user-data-pruner"
RETENTION_DAYS = int(os.environ.get("USER_DATA_RETENTION_DAYS", "180"))   # §7 미결 → 기본 180
log = get_pipeline_logger(COMPONENT)

# (테이블, 시각컬럼) — 보존창 지난 원문 삭제 기준.
_RETENTION = [
    ("activity.user_event", "occurred_at"),
    ("activity.recipe_impression", "shown_at"),
    ("chat.chat_message", "created_at"),
]
# 동의 철회(activity_consent=false) 유저의 잔여 데이터 청소(§4-4). user_id 논리참조.
_CONSENT_CLEANUP = ["activity.user_event", "activity.recipe_impression", "chat.chat_message"]

# D1(§4-1) 인기도 승격 — 삭제 대상(occurred_at < cutoff)의 ADD_CART/VIEW를 recipe_id별 집계 → 누적 upsert.
# 삭제와 같은 트랜잭션(_promote_and_delete_user_event)이라 각 행 정확히 1회 집계(멱등). NOTIF_CLICK·recipe_id NULL 제외.
_POPULARITY_PROMOTE = """
with aged as (
  select recipe_id,
         count(*) filter (where event_type = 'ADD_CART') as ac,
         count(*) filter (where event_type = 'VIEW')     as vc
  from activity.user_event
  where occurred_at < %(cutoff)s and recipe_id is not null
  group by recipe_id
)
insert into activity.recipe_popularity (recipe_id, add_cart_cnt, view_cnt, updated_at)
select recipe_id, ac, vc, now() from aged
on conflict (recipe_id) do update
  set add_cart_cnt = recipe_popularity.add_cart_cnt + excluded.add_cart_cnt,
      view_cnt     = recipe_popularity.view_cnt     + excluded.view_cnt,
      updated_at   = now()
"""


def _delete(conn, sql, params) -> int:
    """단건 DELETE — best-effort. 테이블 부재 등 실패는 savepoint 롤백 후 0(다음 대상 진행)."""
    try:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount
    except Exception:  # noqa: BLE001
        return 0


def _promote_and_delete_user_event(conn, cutoff) -> int:
    """user_event: 삭제 前 인기도 승격 → 원문 삭제를 한 트랜잭션으로(§4-1). 승격·삭제가 원자라 행당 1회 집계=멱등.
    테이블 부재 등 실패는 savepoint 롤백 후 0(다음 대상 진행) — _delete와 동일 best-effort."""
    try:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(_POPULARITY_PROMOTE, {"cutoff": cutoff})           # 승격 먼저
            cur.execute("delete from activity.user_event where occurred_at < %(cutoff)s",
                        {"cutoff": cutoff})                                # 그 다음 원문 삭제
            return cur.rowcount
    except Exception:  # noqa: BLE001
        return 0


def prune_once(conn=None) -> int:
    started = time.perf_counter()
    own = conn is None
    if own:
        try:
            conn = connect()
        except Exception as exc:  # noqa: BLE001
            RECORDS.labels(COMPONENT, "failure").inc()
            log.error("pg connect failed", extra={"event": "sink_write_failed", "component": COMPONENT,
                      "dependency": "postgres", "error_type": type(exc).__name__, "retryable": True})
            return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    total = 0
    try:
        for table, ts in _RETENTION:                    # 보존창 지난 원문
            if table == "activity.user_event":          # D1(§4-1): 삭제 前 인기도 승격
                total += _promote_and_delete_user_event(conn, cutoff)
            else:
                total += _delete(conn, f"delete from {table} where {ts} < %s", (cutoff,))
        for table in _CONSENT_CLEANUP:                  # 동의 철회 유저 잔여
            total += _delete(conn, f"""delete from {table} where user_id in
                (select id from account.app_user where activity_consent is false)""", ())
        conn.commit()
    finally:
        PROCESSING_SECONDS.labels(COMPONENT).observe(time.perf_counter() - started)
        if own:
            conn.close()
    RECORDS.labels(COMPONENT, "success").inc()
    SINK_WRITES.labels(COMPONENT, "postgres", "success").inc(total)
    LAST_SUCCESS.labels(COMPONENT).set_to_current_time()
    log.info("user data pruned", extra={"event": "batch_completed", "component": COMPONENT,
             "record_count": total, "retention_days": RETENTION_DAYS})
    return total


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
