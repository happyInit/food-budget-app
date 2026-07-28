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
    # max_size=10: 상세(get_detail=쿼리 4~5개)가 피크타임(11-12·17-18시)에 겹쳐 들어와도
    # 큐잉으로 묶여 완료되는(로그 버스트) 병목을 완화. 핫패스 서비스와 동일 상한.
    return AsyncConnectionPool(
        conninfo, min_size=1, max_size=10, open=False,
        check=AsyncConnectionPool.check_connection,
    )


def make_es_client():
    # ES는 search_backend == "es" 일 때만 사용. import는 지연.
    from elasticsearch import AsyncElasticsearch

    # basic_auth: ECK(P2)는 인증 강제. env 없으면 생략 — 현행 VM ES(무인증) 동작 불변.
    auth = (settings.es_user, settings.es_password) if settings.es_user else None
    return AsyncElasticsearch(f"http://{settings.eshost}:{settings.esport}", basic_auth=auth)
