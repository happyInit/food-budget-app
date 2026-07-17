"""Mock OCR 백엔드 — dev/데모/테스트용(Gemini 키·과금 없이 동작).

`OCR_BACKEND=mock` 이면 factory 가 이걸 고른다. 이미지 내용은 무시하고 **결정적**인
샘플 영수증(마켓컬리 8줄: 식재료·냉동·비식품(봉투)·조정(할인) 혼합)을 돌려준다.
목적: 프론트 연결·pantry 저장/확정·식비(total 앵커) 전 경로를 유료 호출 없이 E2E 검증.
분류(category/storage/in_expense/needs_review)·item_id 는 손대지 않는다 — 공통 파이프라인
(process_image → classify)이 vision 백엔드와 **동일하게** 채운다(계약 동형성 보장).

교체 무변경: 팀이 실제 키를 넣으면 `OCR_BACKEND=vision` 으로 바꾸기만 하면 된다.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.pipeline.backend.base import ParsedItem, ParsedReceipt

# 결정적 샘플 — 분류 전 '엔진 원출력'만(vision.py가 주는 것과 같은 층위).
# 식재료(냉장/냉동)·비식품(봉투)·조정(할인) 을 섞어 다운스트림 분류·식비 공식을 전부 태운다.
_ITEMS = [
    ("냉동 삼겹살 500g            8,900", "냉동 삼겹살", "500g", "8900", True),
    ("풀무원 국산콩 두부 1모       1,990", "두부", "1모", "1990", True),
    ("무항생제 계란 15구          5,480", "계란", "15구", "5480", True),
    ("대파 2단                    2,000", "대파", "2단", "2000", True),
    ("햇양파 1.5kg                3,290", "양파", "1.5kg", "3290", True),
    ("포기 배추김치 1kg           6,900", "배추김치", "1kg", "6900", True),
    ("종량제봉투 20L              1,200", "종량제봉투", "20L", "1200", False),  # 비식품 → 식비 차감
    ("임직원할인                 -2,000", "임직원할인", None, "-2000", True),   # 조정 → 차감 안 함
]


class MockBackend:
    """OcrBackend 계약 구현. 라이브 호출 없음 → 항상 동일 결과."""

    name = "mock"

    async def parse(self, image: bytes) -> ParsedReceipt:  # noqa: ARG002 — 내용 무시(결정적)
        items = [
            ParsedItem(
                raw_text=raw, name=name, quantity=qty,
                price=Decimal(price), is_food=is_food, confidence=0.95,
            )
            for raw, name, qty, price, is_food in _ITEMS
        ]
        return ParsedReceipt(
            items=items,
            store="마켓컬리",
            purchased_at=datetime(2026, 7, 13, 18, 42),
            total_amount=Decimal("27760"),   # 실지불액(할인 반영). 식비=total−Σ비식품=26,560
            confidence=0.95,
            backend=self.name,
        )
