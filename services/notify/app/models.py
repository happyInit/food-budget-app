"""요청/응답 스키마. docs/design/api-spec.md #41~42, notify.notification DDL."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

# notify.notification.type CHECK 제약과 동일 — Pydantic Literal로 검증(A05).
NotificationType = Literal["LOW_PRICE", "EXPIRING", "HOTDEAL", "BUDGET"]


# ── #41 알림함 목록 ──
class NotificationOut(BaseModel):
    id: int
    type: NotificationType
    title: str
    body: str | None = None
    payload: dict | None = None       # jsonb — 우리가 발행한 데이터
    is_read: bool
    created_at: datetime


class NotificationListOut(BaseModel):
    notifications: list[NotificationOut]


# ── #42 읽음 처리 ──
class MarkReadOut(BaseModel):
    id: int
    is_read: bool = True
