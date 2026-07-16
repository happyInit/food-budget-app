"""SQL 조회 (psycopg3 async). **conn 을 받는다** — 트랜잭션 경계는 호출측(풀)이 제어.
풀이 `row_factory=dict_row`라 fetchone/fetchall은 **dict**(`row["name"]`).

스키마 = recipebook(bookmark). public.recipe 는 데이터 티어(진짜 FK) → **읽기 조인 허용**
(schema-production.sql: bookmark.recipe_id → public.recipe(id)). 크로스-서비스 조인 아님.

A01(소유권): 조회/삭제는 SQL에 반드시 `WHERE user_id = %s` 포함 → 남의 행 접근 불가.
A05(인젝션): 모든 사용자 입력은 파라미터 바인딩(%s), f-string 결합 금지.
"""
from __future__ import annotations

import json


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


# ── user_recipe (#24 수동 등록 + 공유) ────────────────────────────────────────
# A01 소유권: 목록/조회/수정/삭제 모두 `where user_id = %s`. 공개 뷰만 예외(is_public=true 필터).
# A05: 값은 %s 바인딩, jsonb는 json.dumps + `::jsonb` 캐스트(문자열 결합 없음).

async def create_user_recipe(conn, user_id: int, title: str, ingredients: list,
                             steps: list, image_url: str | None, source_url: str | None) -> int:
    """직접 작성 레시피 저장 → id. origin은 서버가 'MANUAL' 고정(바디 신뢰 안 함)."""
    async with conn.cursor() as cur:
        await cur.execute(
            """insert into recipebook.user_recipe
                   (user_id, origin, title, ingredients, steps, image_url, source_url)
               values (%s, 'MANUAL', %s, %s::jsonb, %s::jsonb, %s, %s)
               returning id""",
            (user_id, title, json.dumps(ingredients, ensure_ascii=False),
             json.dumps(steps, ensure_ascii=False), image_url, source_url),
        )
        return (await cur.fetchone())["id"]


async def list_user_recipes(conn, user_id: int):
    """내 레시피 목록(최신순). 소유자 스코프."""
    async with conn.cursor() as cur:
        await cur.execute(
            """select id, title, image_url, is_public, created_at
               from recipebook.user_recipe
               where user_id = %s
               order by created_at desc""",
            (user_id,),
        )
        return await cur.fetchall()


async def get_user_recipe(conn, user_id: int, recipe_id: int):
    """내 레시피 상세 — dict 또는 None(남의 것/없음 → 404). jsonb는 파싱된 리스트로 반환."""
    async with conn.cursor() as cur:
        await cur.execute(
            """select id, title, origin, ingredients, steps, image_url, source_url,
                      is_public, share_token, created_at
               from recipebook.user_recipe
               where id = %s and user_id = %s""",
            (recipe_id, user_id),
        )
        return await cur.fetchone()


async def delete_user_recipe(conn, user_id: int, recipe_id: int):
    """내 레시피 삭제 — dict{id} 또는 None(남의 것/없음). 소유자 스코프."""
    async with conn.cursor() as cur:
        await cur.execute(
            """delete from recipebook.user_recipe
               where id = %s and user_id = %s returning id""",
            (recipe_id, user_id),
        )
        return await cur.fetchone()


async def set_share(conn, user_id: int, recipe_id: int, new_token: str):
    """공개 설정 + share_token 없으면 발급(있으면 유지 → 링크 안정). 소유자 스코프.
    dict{share_token, is_public} 또는 None(남의 것/없음)."""
    async with conn.cursor() as cur:
        await cur.execute(
            """update recipebook.user_recipe
               set is_public = true, share_token = coalesce(share_token, %s)
               where id = %s and user_id = %s
               returning share_token, is_public""",
            (new_token, recipe_id, user_id),
        )
        return await cur.fetchone()


async def unshare_user_recipe(conn, user_id: int, recipe_id: int):
    """공개 해제(is_public=false). share_token은 유지(재공유 시 같은 링크). 소유자 스코프."""
    async with conn.cursor() as cur:
        await cur.execute(
            """update recipebook.user_recipe set is_public = false
               where id = %s and user_id = %s returning id""",
            (recipe_id, user_id),
        )
        return await cur.fetchone()


async def get_shared_recipe(conn, share_token: str):
    """공개 공유 뷰(비인증) — is_public=true 인 것만. dict 또는 None(없음/비공개 → 404)."""
    async with conn.cursor() as cur:
        await cur.execute(
            """select title, ingredients, steps, image_url
               from recipebook.user_recipe
               where share_token = %s and is_public = true""",
            (share_token,),
        )
        return await cur.fetchone()
