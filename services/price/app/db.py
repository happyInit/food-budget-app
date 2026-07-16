"""PG 비동기 커넥션 풀. FastAPI lifespan에서 열고 닫는다."""
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
    return AsyncConnectionPool(
        conninfo, min_size=1, max_size=5, open=False,
        check=AsyncConnectionPool.check_connection,
    )
