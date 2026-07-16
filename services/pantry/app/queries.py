"""SQL 조회 (psycopg3 async). **conn 을 받는다** — 트랜잭션 경계는 호출측(풀)이 제어.
풀이 `row_factory=dict_row`라 fetchone()은 **dict**(`row["id"]`). 컬럼 = pantry 스키마
(docs/prd/schema-production.md §pantry). 테스트는 fake conn 주입(DB 불요, FakeConn 응답도 dict).

★ A01: 모든 재고 접근에 `user_id = %s`(JWT uid) 소유자 필터 — 다른 유저 데이터 차단.
★ A05: 값은 전부 `%s` 파라미터 바인딩(문자열 결합 금지). 아래 f-string 은 **고정 컬럼명 상수**(유저입력 X)만 삽입.
"""
from __future__ import annotations

# 출력 컬럼 목록(고정 상수 — 유저입력 아님). PantryItemOut 필드와 1:1.
_ITEM_COLS = "id, item_id, name, quantity, storage, expire_at, source, status, created_at, closed_at"

# PATCH 로 값 갱신 가능한 컬럼(고정 화이트리스트 — 유저입력 아님). status 는 아래 별도 처리(closed_at 동반).
_PATCH_COLS = ("name", "quantity", "storage", "expire_at")


async def create_item(conn, user_id, name, storage, quantity, item_id, expire_at, source="MANUAL"):
    """#12 재고 추가 → 생성된 행(dict) 반환. user_id 는 JWT uid(소유자)."""
    async with conn.cursor() as cur:
        await cur.execute(
            f"""insert into pantry.pantry_item
                    (user_id, item_id, name, quantity, storage, expire_at, source)
                values (%s, %s, %s, %s, %s, %s, %s)
                returning {_ITEM_COLS}""",
            (user_id, item_id, name, quantity, storage, expire_at, source),
        )
        return await cur.fetchone()


async def list_items(conn, user_id):
    """#11 내 ACTIVE 재고 목록(dict 리스트). 소비기한 임박 순(null 은 맨 뒤)."""
    async with conn.cursor() as cur:
        await cur.execute(
            f"""select {_ITEM_COLS} from pantry.pantry_item
                where user_id = %s and status = 'ACTIVE'
                order by expire_at asc nulls last, created_at desc""",
            (user_id,),
        )
        return await cur.fetchall()


async def list_expiring(conn, user_id, within_days):
    """#15 소비기한 임박 목록 — ACTIVE·expire_at 있고 today+within_days 이내. 임박 순(오름차순)."""
    async with conn.cursor() as cur:
        await cur.execute(
            f"""select {_ITEM_COLS} from pantry.pantry_item
                where user_id = %s and status = 'ACTIVE'
                  and expire_at is not null and expire_at <= current_date + %s
                order by expire_at asc""",
            (user_id, within_days),
        )
        return await cur.fetchall()


async def update_item(conn, user_id, item_id, fields: dict):
    """#13 부분수정. fields = 제공된 컬럼→값(문자열/날짜; enum 은 라우터가 이미 .value 로 정규화).
    status 있으면 closed_at 도 함께 세팅(소모/폐기=now, ACTIVE=null). 소유자 스코프(id + user_id).
    갱신 행 없으면(다른 유저/없음) None → 라우터가 404. A05: 컬럼=화이트리스트, 값=%s 바인딩."""
    set_parts: list[str] = []
    params: list = []
    for col in _PATCH_COLS:
        if col in fields:
            set_parts.append(f"{col} = %s")
            params.append(fields[col])
    if "status" in fields:
        set_parts.append("status = %s")
        params.append(fields["status"])
        # 고정 SQL 조각(유저값 아님): 소모/폐기 → closed_at 기록, ACTIVE 복귀 → 해제.
        set_parts.append(
            "closed_at = now()" if fields["status"] in ("CONSUMED", "DISCARDED") else "closed_at = null"
        )
    async with conn.cursor() as cur:
        await cur.execute(
            f"""update pantry.pantry_item set {', '.join(set_parts)}
                where id = %s and user_id = %s
                returning {_ITEM_COLS}""",
            tuple(params + [item_id, user_id]),
        )
        return await cur.fetchone()


async def delete_item(conn, user_id, item_id):
    """#14 하드삭제(오입력 정정 전용). 소유자 스코프. 삭제 행 없으면 None → 라우터가 404.
    ※ 소모/폐기는 DELETE 아님 — status 전이(#13)로 이력 보존(성과지표). RETURNING id 로 삭제 여부 확인."""
    async with conn.cursor() as cur:
        await cur.execute(
            "delete from pantry.pantry_item where id = %s and user_id = %s returning id",
            (item_id, user_id),
        )
        return await cur.fetchone()


async def pantry_stats(conn, user_id, month_start):
    """성과지표 집계 — status별 개수 1행(dict{active, consumed, discarded}).
    month_start(해당 월 1일 date) 있으면 CONSUMED/DISCARDED 를 closed_at 그 달로 한정
    (active=현재 보유 스냅샷이라 month 무관). A01: user_id 소유자 필터. A05: 값은 %s 바인딩.
    `%s::date is null`(month 미지정) → in_month 항상 true → 전체 기간 집계."""
    async with conn.cursor() as cur:
        await cur.execute(
            """select
                   count(*) filter (where status = 'ACTIVE')            as active,
                   count(*) filter (where status = 'CONSUMED'  and in_month) as consumed,
                   count(*) filter (where status = 'DISCARDED' and in_month) as discarded
               from (
                   select status,
                          (%s::date is null
                           or date_trunc('month', closed_at)::date = %s) as in_month
                   from pantry.pantry_item
                   where user_id = %s
               ) t""",
            (month_start, month_start, user_id),
        )
        return await cur.fetchone()


async def lookup_shelf_life(conn, item_id, storage):
    """(item_id, storage) → dict{days_min, days_max} 또는 None.
    소비기한 참조표는 문서상 data.shelf_life_ref 이나 현재 물리 위치는 public(public→data 이전 시 일괄 치환).
    item_id 앵커는 CURATED 153품목만 → 미앵커 재료는 조회 실패(None) → expire_at null(유저입력)."""
    async with conn.cursor() as cur:
        await cur.execute(
            """select days_min, days_max from public.shelf_life_ref
               where item_id = %s and storage = %s limit 1""",
            (item_id, storage),
        )
        return await cur.fetchone()
