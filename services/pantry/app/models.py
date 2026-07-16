"""요청/응답 스키마. api-spec #11~15. 컬럼 = pantry 스키마(docs/prd/schema-production.md §pantry).

A05: 입력은 Pydantic 으로 타입·길이·범위 검증(FastAPI가 422로 거부). 프론트 파생값(D-day·신선도)은
저장/반환하지 않음(CONVENTIONS §1) — 신선도(fresh)는 P1 AI(XGBoost) 소관이라 Dev A 범위 밖.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class Storage(str, Enum):
    ROOM = "ROOM"
    FRIDGE = "FRIDGE"
    FREEZER = "FREEZER"


class ItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"      # 다 먹음 (성과지표 '안 버린 재료'에 포함)
    DISCARDED = "DISCARDED"    # 버림 (낭비)


class PantryItemIn(BaseModel):
    """#12 수동 추가. source 는 서버가 'MANUAL' 로 세팅(OCR 저장은 AI팀 몫이나 같은 테이블)."""
    name: str = Field(min_length=1, max_length=100)
    storage: Storage
    quantity: str | None = Field(default=None, max_length=50)   # '1모'·'500g' 표시용(산술 X)
    item_id: int | None = None                                  # 표준 품목 앵커(public.item_master)
    expire_at: date | None = None                               # 없으면 shelf_life_ref 로 추정


class PantryItemPatch(BaseModel):
    """#13 부분수정 — 핸들러가 model_dump(exclude_unset=True)로 **제공된 필드만** 갱신.
    status 전이(CONSUMED/DISCARDED)로 소모·폐기 처리 → closed_at 기록(성과지표 '안 버린 재료').
    item_id(표준품목 앵커)는 생성 시 고정 — PATCH 로 안 바꿈."""
    name: str | None = Field(default=None, min_length=1, max_length=100)
    storage: Storage | None = None
    quantity: str | None = Field(default=None, max_length=50)
    expire_at: date | None = None
    status: ItemStatus | None = None


class PantryItemOut(BaseModel):
    """조회/생성 응답 1행. storage·status·source 는 DB CHECK 로 제약된 값의 pass-through(str)."""
    id: int
    item_id: int | None = None
    name: str
    quantity: str | None = None
    storage: str
    expire_at: date | None = None
    source: str
    status: str
    created_at: datetime
    closed_at: datetime | None = None


class PantryStats(BaseModel):
    """성과지표 집계 — status별 재고 개수(종). mealplan 성과보기/요약(#40) seam이 소비한다.

    active=현재 보유(스냅샷) · consumed=소비완료(안 버린 재료) · discarded=폐기(버림).
    saved_rate = consumed/(consumed+discarded) — 종료(소비+폐기)된 재료가 0이면 null(분모 0 회피)."""
    active: int
    consumed: int
    discarded: int
    saved_rate: float | None = None
