"""PG 비동기 커넥션 풀. FastAPI lifespan에서 열고 닫는다.

- price/recipe와 달리 **settings를 파라미터로 받는다**(전역 읽지 않음 = 주입 seam).
- 풀의 모든 커넥션에 **`row_factory=dict_row`** 적용 → fetchone()이 dict 반환
  → `row["email"]`(위치 언패킹 `row[0]` 없음). ORM 없이 매핑 fragility 제거.
"""
from __future__ import annotations

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import Settings


async def _configure_conn(conn: AsyncConnection) -> None:
    conn.row_factory = dict_row
    # autocommit — 계정 작업은 전부 단일 문(signup·login·budget·excluded)이라 문마다 즉시 durable.
    #   미설정 시 pool.connection() 커밋이 요청 teardown(응답 이후)으로 밀려, signup(201) 직후
    #   login 이 커밋 전 다른 풀 커넥션에서 조회 → row 미발견 → 401 "invalid email or password"
    #   read-after-write 레이스 발생(라이브 재현됨). autocommit 이 이 창을 없앤다.
    await conn.set_autocommit(True)


def make_pg_pool(settings: Settings) -> AsyncConnectionPool:
    conninfo = (
        f"host={settings.pghost} port={settings.pgport} "
        f"dbname={settings.pgdatabase} user={settings.pguser} password={settings.pgpassword}"
    )
    return AsyncConnectionPool(
        conninfo, min_size=settings.pg_pool_min, max_size=settings.pg_pool_max,
        open=False, configure=_configure_conn,
        # 체크아웃 시 죽은 커넥션 검사 후 재연결 — 원격 PG가 idle 커넥션을 끊어도
        # "server closed the connection unexpectedly" 500 대신 정상 재연결(간헐 실패 방지).
        check=AsyncConnectionPool.check_connection,
    )
