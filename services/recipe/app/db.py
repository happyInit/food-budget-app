"""PG(필수) / ES(선택) 비동기 클라이언트. FastAPI lifespan에서 열고 닫는다."""
from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

from app.config import settings


def make_pg_pool() -> AsyncConnectionPool:
    conninfo = (
        f"host={settings.pghost} port={settings.pgport} "
        f"dbname={settings.pgdatabase} user={settings.pguser} password={settings.pgpassword}"
    )
    # check: 체크아웃 시 죽은 커넥션 검사 후 재연결 — 원격 PG가 idle 커넥션을 끊어도
    # "server closed the connection unexpectedly" 500 대신 정상 재연결(간헐 실패 방지).
    # 🔴 이 서비스는 풀 크기 관측 대상이다 — 상세(get_detail=쿼리 4~5개)가 피크타임(11-12·17-18시)에
    # 겹치면 대기가 생길 수 있어 종전 10 을 썼다. Pooler 도입으로 기본 5(PG_POOL_MAX)로 내렸으니,
    # 대기가 실측되면 이 서비스만 env 로 올린다(다중화는 Pooler 가 한다 — object_spec §4.5).
    return AsyncConnectionPool(
        conninfo, min_size=settings.pg_pool_min, max_size=settings.pg_pool_max, open=False,
        check=AsyncConnectionPool.check_connection,
        # prepare_threshold=None: 서버측 prepared statement 비활성. PgBouncer transaction 풀링은
        # 트랜잭션마다 백엔드가 바뀔 수 있어, 켜 두면 `prepared statement "..." does not exist` 가 난다.
        kwargs={"prepare_threshold": None},
    )


def make_es_client():
    # ES는 search_backend == "es" 일 때만 사용. import는 지연.
    from elasticsearch import AsyncElasticsearch

    # basic_auth: ECK(P2)는 인증 강제. env 없으면 생략 — 현행 VM ES(무인증) 동작 불변.
    auth = (settings.es_user, settings.es_password) if settings.es_user else None
    return AsyncElasticsearch(f"http://{settings.eshost}:{settings.esport}", basic_auth=auth)
