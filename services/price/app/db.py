"""PG 비동기 커넥션 풀 + Redis 캐시 클라이언트. FastAPI lifespan에서 열고 닫는다."""
from __future__ import annotations

from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis
from redis.asyncio.sentinel import Sentinel

from app.config import settings


def make_pg_pool() -> AsyncConnectionPool:
    conninfo = (
        f"host={settings.pghost} port={settings.pgport} "
        f"dbname={settings.pgdatabase} user={settings.pguser} password={settings.pgpassword}"
    )
    # check: 체크아웃 시 죽은 커넥션 검사 후 재연결 — 원격 PG가 idle 커넥션을 끊어도
    # "server closed the connection unexpectedly" 500 대신 정상 재연결(간헐 실패 방지).
    return AsyncConnectionPool(
        conninfo, min_size=settings.pg_pool_min, max_size=settings.pg_pool_max, open=False,
        check=AsyncConnectionPool.check_connection,
        # prepare_threshold=None: 서버측 prepared statement 비활성. PgBouncer transaction 풀링은
        # 트랜잭션마다 백엔드가 바뀔 수 있어, 켜 두면 `prepared statement "..." does not exist` 가 난다.
        kwargs={"prepare_threshold": None},
    )


def _parse_sentinels(spec: str) -> list[tuple[str, int]]:
    """"host:port,host:port" → [(host, port), …]. sentinel 파드 3개를 전부 열거한다(단일 DNS 금지)."""
    return [(h, int(p)) for h, p in (e.strip().rsplit(":", 1) for e in spec.split(",") if e.strip())]


def make_redis_client() -> Redis:
    """읽기 캐시용 Redis. 지연 연결(첫 명령 시) — 미가용이면 캐시 헬퍼가 best-effort로 우회."""
    # REDIS_SENTINELS 있으면 Sentinel 모드(분기 C) — 노드 상실 국면에서 master Service 가 갱신되지
    # 않으므로 Service 가 아니라 Sentinel 에게 master 를 묻는다(docs/mp_k8s_redis_ha_handoff.md §4).
    # env 없으면 기존 단일 호스트 경로 — 현행 VM(.8) 동작 불변(ES basic_auth 와 같은 하위호환 패턴).
    if settings.redis_sentinels:
        return Sentinel(_parse_sentinels(settings.redis_sentinels)).master_for(
            settings.redis_master_group, decode_responses=True)
    return Redis(host=settings.redishost, port=int(settings.redisport), decode_responses=True)
