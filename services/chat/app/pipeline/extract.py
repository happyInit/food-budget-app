"""① 질문 분석 — span_extractor(재료 스팬) + gazetteer(item_id) + 예산/인분 regex + 의도 키워드분류.

예산/인분/의도 파싱은 SpanExtractor 구현체와 무관 — NER로 전환돼도 안 바뀐다.
"""
from __future__ import annotations

import re

from app.config import settings
from app.models import ExtractedQuery
from app.pipeline.intent_ml import get_intent_model
from app.pipeline.normalize import get_normalizer
from app.pipeline.span_extractor.base import SpanExtractor
from app.pipeline.span_extractor.ner import CrfSpanExtractor
from app.pipeline.span_extractor.rule_based import RuleBasedSpanExtractor

_DISLIKE_MARKERS = ("빼고", "빼줘", "빼서", "제외", "말고", "없이", "싫어", "안 먹", "안먹", "알레르기", "못 먹", "못먹")
# 제외/비선호 '등록' 의도를 가르는 좁은 마커(필터성 "말고·없이" 제외) — 카탈로그 미등재 재료 오안내 방지.
_EXCLUDE_REGISTER_MARKERS = ("제외", "싫어", "싫은", "안 먹", "안먹", "못 먹", "못먹", "알레르기", "빼줘", "빼고")

_MANWON = re.compile(r"(\d+)\s*만\s*원?")
_CHEONWON = re.compile(r"(\d+)\s*천\s*원?")
_WON = re.compile(r"([\d,]+)\s*원")
_SERVING = re.compile(r"(\d+)\s*인분")

# 순서 중요: "칼로리 얼마야"처럼 여러 키워드가 겹치면 더 구체적인 의도(nutrition)를 먼저 검사.
# "얼마"/"가격"은 어디에나 붙을 수 있는 범용 질문어라 price_lookup은 가장 뒤에 둔다.
_INTENT_KEYWORDS: list[tuple[str, list[str]]] = [
    # 영양소명은 "얼마(나)"와 겹쳐 price로 오분류되기 쉬움("라면 나트륨 얼마나 돼?") → nutrition을
    #   price보다 먼저 두고 주요 영양소를 명시 포함. "단백질"은 "단백질 많은 재료 추천"처럼 추천 질의와
    #   겹쳐 오히려 손해라 제외(품목 없는 일반질의는 어차피 무응답) — 특정품목 영양은 item-aware 개선 과제.
    ("nutrition", ["칼로리", "영양", "열량", "나트륨", "지방", "탄수화물", "당류", "콜레스테롤"]),
    # recipe_cost는 "가격"·"만들"을 포함하므로 price_lookup·recommend보다 **먼저** 검사.
    ("recipe_cost", ["총 가격", "총가격", "재료비", "재료 값", "재료값", "재료 가격",
                     "만드는데 얼마", "만드는 데 얼마", "만들면 얼마", "얼마 들어", "얼마들어"]),
    ("recommend", ["뭐 해먹", "추천", "해먹지", "만들"]),
    ("price_lookup", ["얼마", "가격", "값"]),
]


def get_span_extractor(matcher, stop: set[str]) -> SpanExtractor:
    """EXTRACTOR_BACKEND 환경변수로 구현체 선택 (GENERATOR_BACKEND와 동일 패턴)."""
    if settings.extractor_backend == "rule":
        return RuleBasedSpanExtractor(matcher, stop, get_normalizer())
    if settings.extractor_backend == "ner":
        return CrfSpanExtractor(settings.ner_model_path or None)
    raise ValueError(f"EXTRACTOR_BACKEND={settings.extractor_backend!r} 미지원 (rule|ner)")


def _parse_budget(text: str) -> int | None:
    m = _MANWON.search(text)
    if m:
        return int(m.group(1)) * 10000
    m = _CHEONWON.search(text)
    if m:
        return int(m.group(1)) * 1000
    m = _WON.search(text)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def _parse_servings(text: str) -> int | None:
    m = _SERVING.search(text)
    return int(m.group(1)) if m else None


def _classify_intent(text: str) -> str:
    # 규칙(키워드)이 1차 — 챗 안정성(과다전환 방지) 위해 규칙이 잡으면 그대로 사용.
    for intent, keywords in _INTENT_KEYWORDS:
        if any(kw in text for kw in keywords):
            return intent
    # 규칙 미해결("unknown")일 때만 ML 의도모델로 보강(flag+모델 있을 때만; 없으면 unknown 유지).
    #   chat-insights가 이식포맷으로 저장한 모델을 intent_ml이 네이티브 로드(교차모듈 pickle 문제 없음).
    ml = get_intent_model()
    if ml is not None:
        try:
            pred = ml.predict(text)
            if pred:
                return pred
        except Exception:   # noqa: BLE001 — 추론 실패 → 규칙 결과(unknown) 유지
            pass
    return "unknown"


async def extract(
    text: str,
    matcher,
    span_extractor: SpanExtractor,
    history: list[dict] | None = None,
) -> ExtractedQuery:
    spans = await span_extractor.extract_spans(text)
    normalizer = get_normalizer()
    item_ids: list[int] = []
    item_names: list[str] = []
    for span in spans:
        # 철자변형 정규화(요구르트→요거트) 후 matcher 조회 — item_master는 불변, 前처리만.
        item_id, canonical, _method = matcher(normalizer.normalize(span))
        if item_id is not None and item_id not in item_ids:
            item_ids.append(item_id)
            if canonical:  # 표준 품목명 — 0건 시 제안 문구용(item_master 바뀌면 자동 반영)
                item_names.append(canonical)

    intent = _classify_intent(text)

    # 세션 개인화 — 비선호/제외 재료 감지("돼지고기 빼고 추천"). 제외 맥락이면 추출 품목을
    #   검색 대상이 아니라 '비선호'로 돌린다(그 재료가 든 레시피를 추천서 제외, main·session에서 누적).
    disliked_item_ids: list[int] = []
    if item_ids and any(k in text for k in _DISLIKE_MARKERS):
        disliked_item_ids = list(item_ids)
        item_ids, item_names = [], []

    # 멀티턴 팔로우업 승계 — 현재 턴에 품목이 없으면 직전 맥락 상속("그럼 가격은?"→직전 품목).
    #   history=None(멀티턴 OFF)이면 아래는 스킵 → 기존 단일턴과 동일. 비선호 맥락이면 승계 안 함.
    items_inherited = False
    if not item_ids and history and not disliked_item_ids:
        for turn in reversed(history):
            if turn.get("item_ids"):
                item_ids = list(turn["item_ids"])
                item_names = list(turn.get("item_names") or [])
                items_inherited = True     # 이번 턴 텍스트가 아니라 상속으로 채움(recipe-focus '새 재료' 판별)
                if intent == "unknown" and turn.get("intent"):
                    intent = turn["intent"]   # "다른 거"류: 직전 의도(추천 등) 유지
                break

    return ExtractedQuery(
        raw_text=text,
        item_ids=item_ids,
        item_names=item_names,
        budget_won=_parse_budget(text),
        servings=_parse_servings(text),
        intent=intent,
        disliked_item_ids=disliked_item_ids,
        exclude_request=any(k in text for k in _EXCLUDE_REGISTER_MARKERS),
        items_inherited=items_inherited,
    )
