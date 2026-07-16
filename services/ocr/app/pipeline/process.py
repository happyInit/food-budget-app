"""공통 파이프라인 (방식 무관) — parse → 재료 NER 매칭. `docs/ocr-service-design.md §2`.

OcrBackend가 준 ParsedReceipt의 각 식품 품목명을 item_master 표준품목코드(item_id)로 매칭한다.
이 뒤(ocr_receipt_item 초안 저장·HITL·재고/지출)는 백엔드 담당 구간.
"""
from __future__ import annotations

from app.pipeline.backend.base import OcrBackend, ParsedReceipt


def _match_item_id(name: str) -> int | None:
    """품목명 → item_master item_id.

    TODO(NER 연동): 챗봇과 동일한 gazetteer matcher(pipelines/ingest/gazetteer) 또는
    CRF 재료 NER(ml/ingredient-ner)을 재사용해 표준품목코드 매칭. 현재는 자리만(항상 None →
    HITL에서 수동 지정). ai-spec §1: NER은 4소비처 공용 엔진 — 여기가 그 4번째 소비처(#7).
    """
    return None


async def process_image(image: bytes, backend: OcrBackend) -> ParsedReceipt:
    receipt = await backend.parse(image)
    for item in receipt.items:
        if item.is_food and item.name:
            item.item_id = _match_item_id(item.name)
    return receipt
