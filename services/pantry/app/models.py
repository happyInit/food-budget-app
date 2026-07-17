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


class ReceiptItemIn(BaseModel):
    """OCR 확정 1줄 — 엔진 출력(OcrItemOut)을 HITL 편집한 값. 프론트가 보관/기한/포함여부를 채워 보냄.

    category 는 엔진 분류 결과(식재료/가공식품/비식품/조정/null=미해결)의 pass-through — 식비 공식(§3.5)
    라우팅 키. storage 없으면 pantry 미저장(비식품·조정). keep=false 면 식품이라도 냉장고에 안 담음."""
    raw_text: str | None = Field(default=None, max_length=300)  # 감사 추적(원문, 불변)
    name: str = Field(min_length=1, max_length=100)
    item_id: int | None = None                                  # 표준품목 앵커(엔진이 DB로 해결)
    quantity: str | None = Field(default=None, max_length=50)
    price: float | None = None                                  # 조정=음수. 식비는 total 앵커(§3.5)
    is_food: bool = True
    category: str | None = Field(default=None, max_length=20)   # 식재료/가공식품/비식품/조정/null
    storage: Storage | None = None                              # None=pantry 미저장
    expire_at: date | None = None                               # HITL 유저입력(엔진 미제공) — 없으면 shelf_life 추정
    keep: bool = True                                           # 냉장고에 담을지(식품만 의미)


class ReceiptConfirmIn(BaseModel):
    """POST /api/pantry/receipts — OCR 결과 HITL 확정. user_id 는 JWT(바디 불신, A01).
    저장: ocr_receipt(감사) + ocr_receipt_item(전줄) + 식품·keep → pantry_item(source=OCR).
    식비는 서버 계산(§3.5 total 앵커)해 반환 → 프론트가 mealplan /api/expenses 로 기록(순환의존 회피)."""
    store: str | None = Field(default=None, max_length=100)
    purchased_at: datetime | None = None
    total_amount: float | None = None
    items: list[ReceiptItemIn] = Field(default_factory=list, max_length=200)


class ReceiptConfirmOut(BaseModel):
    """확정 결과. expense_amount=식비(원, 정수) — 프론트가 이 값을 mealplan 지출로 기록."""
    receipt_id: int
    added_count: int                 # pantry 에 담긴 재료 수
    expense_amount: int              # 식비(원): total − Σ비식품 (또는 fallback)
    expense_basis: str               # 'total_anchor' | 'line_sum_fallback'
    needs_expense_review: bool       # total 없음/라인합≠total → 식비 HITL 권장(§3.5)


class PantryStats(BaseModel):
    """성과지표 집계 — status별 재고 개수(종). mealplan 성과보기/요약(#40) seam이 소비한다.

    active=현재 보유(스냅샷) · consumed=소비완료(안 버린 재료) · discarded=폐기(버림).
    saved_rate = consumed/(consumed+discarded) — 종료(소비+폐기)된 재료가 0이면 null(분모 0 회피)."""
    active: int
    consumed: int
    discarded: int
    saved_rate: float | None = None
