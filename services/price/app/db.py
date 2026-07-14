"""PG 비동기 커넥션 풀. FastAPI lifespan에서 열고 닫는다."""
from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

from app.config import settings


def make_pg_pool() -> AsyncConnectionPool:
    conninfo = (
        f"host={settings.pghost} port={settings.pgport} "
        f"dbname={settings.pgdatabase} user={settings.pguser} password={settings.pgpassword}"
    )
    return AsyncConnectionPool(conninfo, min_size=1, max_size=5, open=False)
