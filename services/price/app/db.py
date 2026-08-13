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
    #
    # 🔴 소켓 타임아웃(체크리스트 `1-15`) — 없으면 **무한 대기**다. 이 클라이언트는 읽기 캐시용이라
    #    호출부가 best-effort 로 우회하는데, **타임아웃이 없으면 우회로 못 간다**(예외가 안 나므로).
    #    즉 캐시 장애가 응답 지연으로 그대로 번진다. 값은 앱 서비스 선례(video·ocr = 3s)를 따른다.
    #    🔴 Sentinel 은 소켓이 **둘**이다 — 센티널에게 master 를 묻는 커넥션 / master 자체 커넥션.
    #    redis-py 는 `sentinel_kwargs` 를 안 주면 `connection_kwargs` 에서 **`socket_` 로 시작하는
    #    키만 자동 복사**해 센티널 쪽에 쓴다(`redis/asyncio/sentinel.py` Sentinel.__init__ 실측).
    #    지금 두 값이 다 `socket_*` 라 양쪽에 걸린다 — ⚠️ 접두사가 다른 옵션을 추가할 땐
    #    `sentinel_kwargs=` 를 명시해야 한다. 선례 = `pipelines/stream/_redis.py:27-28`.
    timeouts = {"socket_timeout": settings.redis_socket_timeout_s,
                "socket_connect_timeout": settings.redis_socket_timeout_s}
    if settings.redis_sentinels:
        return Sentinel(_parse_sentinels(settings.redis_sentinels), **timeouts).master_for(
            settings.redis_master_group, decode_responses=True, **timeouts)
    return Redis(host=settings.redishost, port=int(settings.redisport),
                 decode_responses=True, **timeouts)
