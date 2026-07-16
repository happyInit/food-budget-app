"""OCR 백엔드 계약 — 방식(Vision/Tesseract) 교체점. `docs/ocr-service-design.md §3`.

이 경계 하나만 지키면 방식이 바뀌어도 process·NER·저장·HTTP는 안 바뀐다
(챗봇 EXTRACTOR_BACKEND/GENERATOR_BACKEND 패턴). 현재 구현체는 VisionBackend만
(팀장 결정: Gemini Vision 단독). Tesseract/폴백은 계약만 열어두고 보류.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol


@dataclass
class ParsedItem:
    raw_text: str                    # 원문 라인 그대로  예: '삼겹살500g  8,900'
    name: str | None = None          # 백엔드가 뽑은 품목명(재료 NER 前)  예: '삼겹살'
    quantity: str | None = None      # 예: '500g'
    price: Decimal | None = None
    is_food: bool = True             # '봉투'·'할인'·'포인트' 등 비재료 제외 플래그
    confidence: float | None = None
    item_id: int | None = None       # 백엔드는 None. 공통 파이프라인의 재료 NER이 채움(→ item_master)


@dataclass
class ParsedReceipt:
    items: list[ParsedItem] = field(default_factory=list)
    store: str | None = None
    purchased_at: datetime | None = None
    total_amount: Decimal | None = None
    confidence: float | None = None  # 전체 신뢰도(실패판정·향후 폴백 트리거)
    backend: str = ""                # 처리 백엔드명(로깅)


class OcrBackend(Protocol):
    """이미지 → 구조화 영수증. 방식 무관 계약.

    구현 주의: Tesseract 등 CPU-bound 구현은 내부에서 run_in_executor로 감쌀 것
    (async 이벤트루프 블로킹 방지). Vision은 네트워크 I/O라 자연히 async.
    """

    name: str

    async def parse(self, image: bytes) -> ParsedReceipt: ...
