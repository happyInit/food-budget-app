"""API 스키마 — `docs/design/api-spec.md #16·17`(POST/GET /api/pantry/ocr)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class OcrAcceptedResponse(BaseModel):
    """POST /api/pantry/ocr — 비동기 접수(202)."""
    job_id: str
    status: Literal["PENDING", "DONE", "FAILED"] = "PENDING"


class OcrItemOut(BaseModel):
    raw_text: str
    name: str | None = None
    item_id: int | None = None
    quantity: str | None = None
    price: float | None = None
    is_food: bool = True
    # 분류 캐스케이드(§7.2) 산출 — 백엔드 라우팅용
    category: str | None = None    # 식재료/가공식품/비식품, None=미해결
    storage: str | None = None     # FRIDGE/FREEZER/ROOM, None=비-pantry
    in_expense: bool = True        # 식비 포함 여부(§7.3.5). 비식품=false
    needs_review: bool = False     # HITL 하이라이트(§7.6): 저신뢰·미해결→"확인" 플래그
    confirmed: bool = False        # 초안=false. HITL 확정은 백엔드 담당


class OcrStatusResponse(BaseModel):
    """GET /api/pantry/ocr/{jobId} — 상태·결과."""
    status: Literal["PENDING", "DONE", "FAILED"]
    store: str | None = None
    purchased_at: str | None = None
    total_amount: float | None = None
    backend: str | None = None
    items: list[OcrItemOut] = Field(default_factory=list)
    reason: str | None = None      # FAILED 사유
