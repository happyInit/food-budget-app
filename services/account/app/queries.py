"""SQL 조회 (psycopg3 async). **conn 을 받는다** — 트랜잭션 경계는 호출측(풀)이 제어.
컬럼 = account 스키마 (docs/prd/schema-production.md §1). 테스트는 fake conn 주입(DB 불요).
"""
from __future__ import annotations


async def create_local_user(conn, email: str, password_hash: str, nickname: str) -> int:
    """이메일 회원가입. 중복 이메일이면 psycopg UniqueViolation → 라우터가 409로 매핑."""
    async with conn.cursor() as cur:
        await cur.execute(
            """insert into account.app_user (email, password_hash, nickname, provider)
               values (%s, %s, %s, 'local') returning id""",
            (email, password_hash, nickname),
        )
        return (await cur.fetchone())[0]


async def get_login_user(conn, email: str):
    """login용 — (id, password_hash, provider) 또는 None."""
    async with conn.cursor() as cur:
        await cur.execute(
            "select id, password_hash, provider from account.app_user where email = %s",
            (email,),
        )
        return await cur.fetchone()


async def get_user(conn, user_id: int):
    """me용 — (id, email, nickname, provider) 또는 None."""
    async with conn.cursor() as cur:
        await cur.execute(
            "select id, email, nickname, provider from account.app_user where id = %s",
            (user_id,),
        )
        return await cur.fetchone()


async def update_nickname(conn, user_id: int, nickname: str):
    async with conn.cursor() as cur:
        await cur.execute(
            """update account.app_user set nickname = %s, updated_at = now()
               where id = %s returning id, email, nickname, provider""",
            (nickname, user_id),
        )
        return await cur.fetchone()


async def upsert_kakao_user(conn, provider_uid: str, nickname: str) -> int:
    async with conn.cursor() as cur:
        await cur.execute(
            """insert into account.app_user (provider, provider_uid, nickname)
               values ('kakao', %s, %s)
               on conflict (provider, provider_uid) do update set updated_at = now()
               returning id""",
            (provider_uid, nickname),
        )
        return (await cur.fetchone())[0]


async def get_current_budget(conn, user_id: int):
    """이번 달 예산 — (month, amount) 또는 None."""
    async with conn.cursor() as cur:
        await cur.execute(
            """select month, amount from account.user_budget
               where user_id = %s and month = date_trunc('month', current_date)::date""",
            (user_id,),
        )
        return await cur.fetchone()


async def upsert_current_budget(conn, user_id: int, amount: int):
    """이번 달 예산 설정(upsert) — (month, amount) 반환."""
    async with conn.cursor() as cur:
        await cur.execute(
            """insert into account.user_budget (user_id, month, amount)
               values (%s, date_trunc('month', current_date)::date, %s)
               on conflict (user_id, month) do update set amount = excluded.amount
               returning month, amount""",
            (user_id, amount),
        )
        return await cur.fetchone()
