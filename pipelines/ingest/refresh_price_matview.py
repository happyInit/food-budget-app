"""가격 물질화 뷰(retail_unit_price) 리프레시 — 크롤 후 실행.

retail_unit_price 는 일반 뷰였을 때 매 요청마다 retail_price 시계열 전체에 윈도우+정규식을
재계산해 Price·MealPlan 병목의 근원이었다(부하테스트, #186). 물질화 후에는 크롤(일1~2회)
직후 이 스크립트로 갱신한다 — 조회는 저장된 결과를 읽어 즉시.

운영 배선(데이터 담당):
- 배치 크롤(load_retail.main())은 끝에서 이 함수를 호출해 즉시 갱신한다.
- 스트리밍(consume_retail)로 상시 적재하는 경우, 폴 윈도우(11~12시·17~18시 등) 뒤에
  이 스크립트를 cron/systemd timer 로 스케줄한다. 예) `python pipelines/ingest/refresh_price_matview.py`

CONCURRENTLY: 유니크 인덱스(retail_unit_price_id_idx)가 있어야 하며, 갱신 중에도 읽기를 막지
않는다. 단 '최초 1회'는 CONCURRENTLY 불가(미populate 상태) → 일반 REFRESH 로 폴백한다.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect                                    # noqa: E402

_MATVIEW = "retail_unit_price"
# Price 서비스가 캐싱하는 키 프리픽스(services/price/app/main.py). 크롤 후 무효화 대상.
_PRICE_CACHE_PATTERNS = ("price:current:*", "price:hotdeals:*")


def _price_cache_client():
    """무효화용 Redis 클라이언트 — 지연 연결(명령 전 네트워크 없음). redis 미설치면 ImportError.
    REDIS_SENTINELS 있으면 Sentinel 모드(분기 C — 노드 상실 국면에서 master Service 가 갱신되지
    않아 Sentinel 에게 master 를 묻는다, docs/mp_k8s_redis_ha_handoff.md §4). 없으면 REDIS_URL 폴백."""
    import redis  # 지연 import — ingest 환경에 없으면 ImportError → 호출측 skip

    sentinels = os.environ.get("REDIS_SENTINELS", "")
    if sentinels:
        hosts = [(h, int(p)) for h, p in
                 (e.strip().rsplit(":", 1) for e in sentinels.split(",") if e.strip())]
        return redis.Sentinel(hosts, socket_timeout=5).master_for(
            os.environ.get("REDIS_MASTER_GROUP", "mymaster"), socket_timeout=5, decode_responses=True)
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    return redis.Redis.from_url(url, socket_timeout=5, decode_responses=True)


def _flush_price_cache() -> str:
    """크롤 후 Price 읽기 캐시 무효화 — best-effort. redis 미설치/미가용이면 skip(TTL이 상한).
    갱신된 가격이 TTL(수 분)을 기다리지 않고 즉시 반영되게 한다."""
    try:
        r = _price_cache_client()
    except ImportError:
        return "skipped:no_redis"
    try:
        n = 0
        for pat in _PRICE_CACHE_PATTERNS:
            keys = list(r.scan_iter(match=pat, count=500))   # KEYS(블로킹) 대신 SCAN
            if keys:
                n += r.delete(*keys)
        return f"flushed:{n}"
    except Exception:                                        # noqa: BLE001 — 무효화 실패는 무시(TTL 폴백)
        return "skipped:unreachable"


def refresh_price_matview() -> str:
    """retail_unit_price 를 갱신. 반환 = 사용한 모드('concurrent'|'plain'|'skipped:<이유>').

    - 대상이 물질화 뷰가 아니면(아직 마이그레이션 전) 건너뛴다(배치가 실패하지 않게).
    - CONCURRENTLY 우선, 미populate/락 등으로 실패하면 일반 REFRESH 로 폴백.
    REFRESH ... CONCURRENTLY 는 트랜잭션 블록 안에서 못 도므로 autocommit 커넥션을 쓴다.
    """
    conn = connect()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            # relkind: 'm'=물질화 뷰, 'v'=일반 뷰, 없음=미존재. 물질화 뷰가 아니면 skip(무효화도 안 함).
            cur.execute("select relkind from pg_class where relname = %s", (_MATVIEW,))
            row = cur.fetchone()
            if row is None:
                return "skipped:absent"
            if row[0] != "m":
                return "skipped:not_materialized"   # 마이그레이션(뷰→물질화) 선행 필요
            try:
                cur.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {_MATVIEW}")
                mode = "concurrent"
            except Exception:                        # noqa: BLE001 — 최초 1회 미populate 등 → 일반 갱신 폴백
                cur.execute(f"REFRESH MATERIALIZED VIEW {_MATVIEW}")
                mode = "plain"
    finally:
        conn.close()
    # 갱신 성공 → Price 읽기 캐시 무효화(갱신값 즉시 반영). 별도 redis 연결·best-effort.
    return f"{mode} · cache={_flush_price_cache()}"


def main() -> None:
    mode = refresh_price_matview()
    print(f"retail_unit_price 리프레시: {mode}")


if __name__ == "__main__":
    main()
