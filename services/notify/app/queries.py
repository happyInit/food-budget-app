"""SQL 조회 (psycopg3 async). **conn 을 받는다** — 트랜잭션 경계는 호출측(풀)이 제어.
풀이 `row_factory=dict_row`라 fetchone()/fetchall()은 **dict**(`row["id"]`). 컬럼 = notify 스키마
(docs/prd/schema-production.sql). 테스트는 fake conn 주입(DB 불요, FakeConn 응답도 dict).

소유권(A01): 모든 쿼리에 `where user_id = %s`. user_id 는 JWT에서 온 값(요청 바디 신뢰 X).
SQL 인젝션(A05): 모든 값은 %s 파라미터 바인딩. `unread` 필터는 사용자 값이 아니라
고정 SQL 조각을 bool로 붙일지 말지 결정할 뿐(문자열 결합에 사용자 입력 없음).
"""
from __future__ import annotations


async def list_notifications(conn, user_id: int, unread_only: bool, limit: int = 50):
    """알림함 목록 — dict 리스트. unread_only=True면 안 읽은 것만. 최신순.
    알림은 시간이 지날수록 누적되므로 limit 로 상한(무제한 반환·직렬화 비용 방지)."""
    sql = (
        "select id, type, title, body, payload, is_read, created_at "
        "from notify.notification where user_id = %s"
    )
    if unread_only:
        sql += " and is_read = false"
    sql += " order by created_at desc limit %s"
    async with conn.cursor() as cur:
        await cur.execute(sql, (user_id, limit))
        return await cur.fetchall()


async def mark_read(conn, notification_id: int, user_id: int):
    """읽음 처리 — 소유자(user_id) 행만. dict{id} 또는 None(남의 행/없음 → 라우터 404)."""
    async with conn.cursor() as cur:
        await cur.execute(
            """update notify.notification set is_read = true
               where id = %s and user_id = %s returning id""",
            (notification_id, user_id),
        )
        return await cur.fetchone()
