"""PG 비동기 커넥션 풀. account/app/db.py 를 그대로 복제.

- settings를 파라미터로 받는다(전역 읽지 않음 = 주입 seam).
- 풀의 모든 커넥션에 `row_factory=dict_row` 적용 → fetchone()이 dict 반환(`row["id"]`).
"""
from __future__ import annotations

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import Settings


async def _use_dict_rows(conn: AsyncConnection) -> None:
    conn.row_factory = dict_row


def make_pg_pool(settings: Settings) -> AsyncConnectionPool:
    conninfo = (
        f"host={settings.pghost} port={settings.pgport} "
        f"dbname={settings.pgdatabase} user={settings.pguser} password={settings.pgpassword}"
    )
    return AsyncConnectionPool(
        conninfo, min_size=1, max_size=5, open=False, configure=_use_dict_rows
    )
