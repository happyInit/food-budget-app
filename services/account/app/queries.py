"""SQL 조회 (psycopg3 async). **conn 을 받는다** — 트랜잭션 경계는 호출측(풀)이 제어.
풀이 `row_factory=dict_row`라 fetchone()은 **dict**(`row["id"]`). 컬럼 = account 스키마
(docs/prd/schema-production.md §1). 테스트는 fake conn 주입(DB 불요, FakeConn 응답도 dict).
"""
from __future__ import annotations


async def create_local_user(conn, email: str, password_hash: str, nickname: str) -> int:
    """이메일 회원가입. 중복 이메일이면 psycopg UniqueViolation → 라우터가 409로 매핑.
    회원가입 일괄 동의(팀 결정) — 데이터 수집 동의(activity_consent) 가입 시 opt-in 처리."""
    async with conn.cursor() as cur:
        await cur.execute(
            """insert into account.app_user
                 (email, password_hash, nickname, provider, activity_consent, consented_at)
               values (%s, %s, %s, 'local', true, now()) returning id""",
            (email, password_hash, nickname),
        )
        return (await cur.fetchone())["id"]


async def get_login_user(conn, email: str):
    """login용 — dict{id, password_hash, provider} 또는 None."""
    async with conn.cursor() as cur:
        await cur.execute(
            "select id, password_hash, provider from account.app_user where email = %s",
            (email,),
        )
        return await cur.fetchone()


async def get_user(conn, user_id: int):
    """me용 — dict{id, email, nickname, provider} 또는 None."""
    async with conn.cursor() as cur:
        await cur.execute(
            "select id, email, nickname, provider from account.app_user where id = %s",
            (user_id,),
        )
        return await cur.fetchone()


async def update_nickname(conn, user_id: int, nickname: str):
    """dict{id, email, nickname, provider}."""
    async with conn.cursor() as cur:
        await cur.execute(
            """update account.app_user set nickname = %s, updated_at = now()
               where id = %s returning id, email, nickname, provider""",
            (nickname, user_id),
        )
        return await cur.fetchone()


async def delete_user(conn, user_id: int):
    """회원 탈퇴 — app_user 삭제(예산·제외재료는 ON DELETE CASCADE). 삭제 행 없으면 None.
    ⚠️ 타 서비스 논리 user_id 데이터(pantry·mealplan 등)는 크로스서비스라 여기서 안 지움(후속 정리)."""
    async with conn.cursor() as cur:
        await cur.execute(
            "delete from account.app_user where id = %s returning id", (user_id,)
        )
        return await cur.fetchone()


async def upsert_oauth_user(conn, provider: str, provider_uid: str, nickname: str) -> int:
    """소셜 로그인 upsert — (provider, provider_uid) 로 식별. 처음이면 생성, 재로그인이면 갱신.
    ⚠️ email 은 저장하지 않는다(계정연동 결정 전 — app_user.email UNIQUE 와 로컬계정 충돌 회피, 후속 결정).
    회원가입 일괄 동의(팀 결정)와 동일하게 activity_consent opt-in."""
    async with conn.cursor() as cur:
        await cur.execute(
            """insert into account.app_user (provider, provider_uid, nickname, activity_consent, consented_at)
               values (%s, %s, %s, true, now())
               on conflict (provider, provider_uid) do update set updated_at = now()
               returning id""",
            (provider, provider_uid, nickname),
        )
        return (await cur.fetchone())["id"]


async def get_current_budget(conn, user_id: int):
    """이번 달 예산 — dict{month, amount} 또는 None."""
    async with conn.cursor() as cur:
        await cur.execute(
            """select month, amount from account.user_budget
               where user_id = %s and month = date_trunc('month', current_date)::date""",
            (user_id,),
        )
        return await cur.fetchone()


async def upsert_current_budget(conn, user_id: int, amount: int):
    """이번 달 예산 설정(upsert) — dict{month, amount} 반환."""
    async with conn.cursor() as cur:
        await cur.execute(
            """insert into account.user_budget (user_id, month, amount)
               values (%s, date_trunc('month', current_date)::date, %s)
               on conflict (user_id, month) do update set amount = excluded.amount
               returning month, amount""",
            (user_id, amount),
        )
        return await cur.fetchone()


# ── 제외 재료 (A01: 전부 user_id 소유자 스코프 · A05: %s 바인딩) ──
async def list_excluded_items(conn, user_id: int):
    """내 제외 재료 목록 — dict{item_id, name} 리스트(최근 추가 순)."""
    async with conn.cursor() as cur:
        await cur.execute(
            """select item_id, name from account.user_excluded_item
               where user_id = %s order by created_at desc""",
            (user_id,),
        )
        return await cur.fetchall()


async def add_excluded_item(conn, user_id: int, item_id: int, name: str):
    """제외 재료 추가(멱등 — 이미 있으면 표시명만 갱신). dict{item_id, name}.
    없는 item_id면 item_master FK 위반 → 라우터가 404."""
    async with conn.cursor() as cur:
        await cur.execute(
            """insert into account.user_excluded_item (user_id, item_id, name)
               values (%s, %s, %s)
               on conflict (user_id, item_id) do update set name = excluded.name
               returning item_id, name""",
            (user_id, item_id, name),
        )
        return await cur.fetchone()


async def remove_excluded_item(conn, user_id: int, item_id: int):
    """제외 재료 삭제 — 소유자 스코프. 삭제 행 없으면 None → 404."""
    async with conn.cursor() as cur:
        await cur.execute(
            "delete from account.user_excluded_item where user_id = %s and item_id = %s returning item_id",
            (user_id, item_id),
        )
        return await cur.fetchone()
