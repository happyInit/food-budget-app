"""공통 파이프라인 (방식 무관) — parse → 분류 캐스케이드. `docs/ocr-service-design.md §2`.

OcrBackend가 준 ParsedReceipt(엔진 출력, 동결)의 각 품목을 다운스트림에서 분류(§7.2):
category(식재료/가공식품/비식품)·storage·in_expense·needs_review를 채운다. item_id는 백엔드가
실 item_master DB로 채우는 구간(여기선 None 유지). 이 뒤(저장·HITL·재고/지출)는 백엔드 담당.
"""
from __future__ import annotations

from app.pipeline.backend.base import OcrBackend, ParsedReceipt
from app.pipeline.classify import get_classifier, realign_prices


async def process_image(image: bytes, backend: OcrBackend) -> ParsedReceipt:
    receipt = await backend.parse(image)
    realign_prices(receipt.items)      # §7.3.5 3층: 명확한 가격-품목 오정렬만 보수적 복원(분류 前)
    clf = get_classifier()
    for item in receipt.items:
        c = clf.classify(item.name, item.is_food, item.price)
        item.category = c.category
        item.storage = c.storage
        item.in_expense = c.in_expense
        item.needs_review = c.needs_review
        item.item_id = c.item_id      # DB 연결 시 실 item_master 코드, 파일 폴백이면 None
    return receipt
