from __future__ import annotations

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import Settings


async def _configure_conn(conn: AsyncConnection) -> None:
    conn.row_factory = dict_row
    await conn.set_autocommit(True)


def make_pg_pool(settings: Settings) -> AsyncConnectionPool:
    conninfo = (
        f"host={settings.pghost} port={settings.pgport} "
        f"dbname={settings.pgdatabase} user={settings.pguser} password={settings.pgpassword}"
    )
    return AsyncConnectionPool(
        conninfo,
        min_size=settings.pg_pool_min,
        max_size=settings.pg_pool_max,
        open=False,
        configure=_configure_conn,
        check=AsyncConnectionPool.check_connection,
        # prepare_threshold=None: 서버측 prepared statement 비활성. PgBouncer transaction 풀링은
        # 트랜잭션마다 백엔드가 바뀔 수 있어, 켜 두면 `prepared statement "..." does not exist` 가 난다.
        kwargs={"prepare_threshold": None},
    )
