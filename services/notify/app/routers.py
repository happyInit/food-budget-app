"""라우터 — api-spec #41~42. 핸들러는 Depends로 의존성 주입(전역 state 없음 → 테스트 가능).
쿼리 결과는 dict(row_factory=dict_row) → `row["id"]`, 컬럼명이 모델과 같으면 `NotificationOut(**row)`.

인증(A01/A07): 두 엔드포인트 모두 `Depends(get_current_user)` — user_id 는 JWT에서만.
소유권(A01): 조회·수정 SQL에 `where user_id = %s` 포함, 남의 알림 읽음 시도 → None → 404.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app import queries
from app.context import get_conn, get_current_user
from app.models import MarkReadOut, NotificationListOut, NotificationOut

notifications = APIRouter(prefix="/api/notifications", tags=["notifications"])


@notifications.get("", response_model=NotificationListOut)  # #41
async def list_notifications(
    unread: bool = False,
    limit: int = Query(50, ge=1, le=200),   # 누적 알림 무제한 반환 방지(A05 범위 검증)
    uid: int = Depends(get_current_user),
    conn=Depends(get_conn),
):
    rows = await queries.list_notifications(conn, uid, unread, limit)
    return NotificationListOut(notifications=[NotificationOut(**row) for row in rows])


@notifications.patch("/{notification_id}/read", response_model=MarkReadOut)  # #42
async def mark_read(
    notification_id: int,
    uid: int = Depends(get_current_user),
    conn=Depends(get_conn),
):
    row = await queries.mark_read(conn, notification_id, uid)
    if row is None:                      # 없거나 남의 알림 → 소유권 실패
        raise HTTPException(status.HTTP_404_NOT_FOUND, "notification not found")
    return MarkReadOut(id=row["id"])
