"""① 질문 분석 — span_extractor(재료 스팬) + gazetteer(item_id) + 예산/인분 regex + 의도 키워드분류.

예산/인분/의도 파싱은 SpanExtractor 구현체와 무관 — NER로 전환돼도 안 바뀐다.
"""
from __future__ import annotations

import re

from app.config import settings
from app.models import ExtractedQuery
from app.pipeline.normalize import get_normalizer
from app.pipeline.span_extractor.base import SpanExtractor
from app.pipeline.span_extractor.ner import CrfSpanExtractor
from app.pipeline.span_extractor.rule_based import RuleBasedSpanExtractor

_MANWON = re.compile(r"(\d+)\s*만\s*원")
_WON = re.compile(r"([\d,]+)\s*원")
_SERVING = re.compile(r"(\d+)\s*인분")

# 순서 중요: "칼로리 얼마야"처럼 여러 키워드가 겹치면 더 구체적인 의도(nutrition)를 먼저 검사.
# "얼마"/"가격"은 어디에나 붙을 수 있는 범용 질문어라 price_lookup은 가장 뒤에 둔다.
_INTENT_KEYWORDS: list[tuple[str, list[str]]] = [
    ("nutrition", ["칼로리", "영양"]),
    ("recommend", ["뭐 해먹", "추천", "해먹지", "만들"]),
    ("price_lookup", ["얼마", "가격", "값"]),
]


def get_span_extractor(matcher, stop: set[str]) -> SpanExtractor:
    """EXTRACTOR_BACKEND 환경변수로 구현체 선택 (GENERATOR_BACKEND와 동일 패턴)."""
    if settings.extractor_backend == "rule":
        return RuleBasedSpanExtractor(matcher, stop)
    if settings.extractor_backend == "ner":
        return CrfSpanExtractor(settings.ner_model_path or None)
    raise ValueError(f"EXTRACTOR_BACKEND={settings.extractor_backend!r} 미지원 (rule|ner)")


def _parse_budget(text: str) -> int | None:
    m = _MANWON.search(text)
    if m:
        return int(m.group(1)) * 10000
    m = _WON.search(text)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def _parse_servings(text: str) -> int | None:
    m = _SERVING.search(text)
    return int(m.group(1)) if m else None


def _classify_intent(text: str) -> str:
    for intent, keywords in _INTENT_KEYWORDS:
        if any(kw in text for kw in keywords):
            return intent
    return "unknown"


async def extract(text: str, matcher, span_extractor: SpanExtractor) -> ExtractedQuery:
    spans = await span_extractor.extract_spans(text)
    normalizer = get_normalizer()
    item_ids: list[int] = []
    for span in spans:
        # 철자변형 정규화(요구르트→요거트) 후 matcher 조회 — item_master는 불변, 前처리만.
        item_id = matcher(normalizer.normalize(span))[0]
        if item_id is not None and item_id not in item_ids:
            item_ids.append(item_id)

    return ExtractedQuery(
        raw_text=text,
        item_ids=item_ids,
        budget_won=_parse_budget(text),
        servings=_parse_servings(text),
        intent=_classify_intent(text),
    )
