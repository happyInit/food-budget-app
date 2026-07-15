"""SQL 조회 (psycopg3 async). **conn 을 받는다** — 트랜잭션 경계는 호출측(풀)이 제어.
풀이 `row_factory=dict_row`라 fetchone/fetchall은 **dict**(`row["name"]`).

스키마 = recipebook(bookmark). public.recipe 는 데이터 티어(진짜 FK) → **읽기 조인 허용**
(schema-production.sql: bookmark.recipe_id → public.recipe(id)). 크로스-서비스 조인 아님.

A01(소유권): 조회/삭제는 SQL에 반드시 `WHERE user_id = %s` 포함 → 남의 행 접근 불가.
A05(인젝션): 모든 사용자 입력은 파라미터 바인딩(%s), f-string 결합 금지.
"""
from __future__ import annotations


async def list_bookmarks(conn, user_id: int):
    """#20 내 북마크 목록 — dict{id, recipe_id, name, image_url, cooking_time, level_nm} 리스트.
    최신순(bookmark_user_created_idx 활용). user_id는 JWT 값(소유권 필터)."""
    async with conn.cursor() as cur:
        await cur.execute(
            """select b.id, b.recipe_id,
                      r.name, r.image_url, r.cooking_time, r.level_nm
               from recipebook.bookmark b
               join public.recipe r on r.id = b.recipe_id
               where b.user_id = %s
               order by b.created_at desc""",
            (user_id,),
        )
        return await cur.fetchall()


async def create_bookmark(conn, user_id: int, recipe_id: int) -> int:
    """#21 레시피 저장 — 생성된 bookmark id 반환.
    UNIQUE(user_id, recipe_id) 위반 시 psycopg UniqueViolation → 라우터가 409로 매핑.
    존재하지 않는 recipe_id → FK 위반 ForeignKeyViolation → 라우터가 404로 매핑."""
    async with conn.cursor() as cur:
        await cur.execute(
            """insert into recipebook.bookmark (user_id, recipe_id)
               values (%s, %s) returning id""",
            (user_id, recipe_id),
        )
        return (await cur.fetchone())["id"]


async def delete_bookmark(conn, user_id: int, bookmark_id: int):
    """#22 레시피북에서 삭제 — dict{id} 또는 None(내 소유가 아니거나 없음 → 404).
    소유권: `id = %s AND user_id = %s` 로 남의 북마크는 매칭 0건 → RETURNING None."""
    async with conn.cursor() as cur:
        await cur.execute(
            """delete from recipebook.bookmark
               where id = %s and user_id = %s
               returning id""",
            (bookmark_id, user_id),
        )
        return await cur.fetchone()
