"""추출 파이프라인 오케스트레이션 (video-recipe-ai.md §2).

  URL 정규화 → 교차유저 캐시 조회(히트=비용0) → 1차 추출 → 규칙검증(H1~H5)
  → (하드실패 1회 한정) 재분석 → 소프트플래그(S1~S3) → (선택)정제 → 캐시저장.

의존성(추출기·캐시·NER매칭)은 주입 → 실제는 Gemini·Redis·gazetteer, 테스트는 mock.
무한 재시도 금지: 재분석도 실패면 안내 폴백(수동입력 유도).
"""
from __future__ import annotations

import re
from typing import Callable

from models import ExtractionResult, RecipeExtraction
from validate import hard_failures, soft_flags

_YT_ID = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})")


def normalize_url(url: str) -> str | None:
    """유튜브 영상ID 추출 → 표준 URL(캐시 키 안정화). 아니면 None."""
    m = _YT_ID.search(url or "")
    return f"https://www.youtube.com/watch?v={m.group(1)}" if m else None


def extract_recipe(
    url: str,
    extractor: Callable[[str, str, str], RecipeExtraction],   # (url, model_env, default_model)->RecipeExtraction
    *,
    cache=None,                       # get(key)->RecipeExtraction|None · set(key, recipe)
    ner_match_fn: Callable[[str], bool] | None = None,
    description_terms: set[str] | None = None,
    retry_enabled: bool = True,
    item_resolver: Callable[[str], int | None] | None = None,
) -> ExtractionResult:
    """`item_resolver`: 재료명 → 표준품목코드(item_id). 없으면 item_id는 None으로 남는다.

    ⚠️ `ner_match_fn`(bool)과 역할이 다르다 — 그건 S2 소프트플래그 판정(매칭 됐나?)용이고,
       실제 **item_id를 채우는 건 `item_resolver`** 다. item_id가 없으면 추출 결과가
       재료비·냉장고 재고·최저가 알림 어디에도 연결되지 않는다(앱 기능과 단절).
    """
    norm = normalize_url(url)
    if not norm:
        return ExtractionResult(ok=False, stage="failed", note="유튜브 영상 URL이 아니에요.")

    # 1) 교차유저 캐시 (히트 = Gemini 생략, 비용 0)
    if cache is not None:
        cached = cache.get(norm)
        if cached is not None:
            return ExtractionResult(ok=True, recipe=cached, from_cache=True, stage="cached")

    # 2) 1차 추출 → 검증
    result = _extract_and_validate(norm, extractor, "VIDEO_EXTRACT_MODEL", "gemini-3.5-flash-lite",
                                   ner_match_fn, description_terms)

    # 3) 하드 실패 → 재분석 1회 한정(더 나은 모델로 영상 재분석)
    #    단 H0(영상 미수신)은 제외 — 원인이 입력 경로라 재시도해도 같은 결과이고 비용만 든다.
    if "H0" in result.hard_failures:
        result.ok = False
        result.stage = "failed"
        result.note = "영상을 불러오지 못했어요. 공개된 영상인지 확인해 주세요."
        return result

    if result.hard_failures and retry_enabled:
        retried = _extract_and_validate(norm, extractor, "VIDEO_RETRY_MODEL", "gemini-3.5-flash",
                                        ner_match_fn, description_terms)
        retried.retried = True
        retried.stage = "retried"
        result = retried

    # 4) 최종 판정
    if result.hard_failures:
        result.ok = False
        result.stage = "failed"
        result.note = "영상에서 레시피를 정확히 읽지 못했어요. 직접 입력해 주시겠어요?"
        return result

    # 5) NER 정규화 — 재료명 → 표준품목코드. **캐시 저장 전**에 채워야 캐시 히트에도 반영된다.
    if item_resolver is not None and result.recipe is not None:
        for ing in result.recipe.ingredients:
            if ing.item_id is None:
                try:
                    ing.item_id = item_resolver(ing.name)
                except Exception:  # noqa: BLE001 — 정규화 실패로 추출 결과를 버리지 않는다
                    ing.item_id = None

    result.ok = True
    if cache is not None and result.recipe is not None:
        cache.set(norm, result.recipe)
    return result


def _extract_and_validate(url, extractor, model_env, default_model, ner_match_fn, description_terms) -> ExtractionResult:
    try:
        recipe = extractor(url, model_env, default_model)
    except Exception as exc:   # noqa: BLE001 — 파싱/스키마/네트워크 실패 = H1(하드)
        return ExtractionResult(ok=False, hard_failures=["H1"], note=f"추출 실패: {type(exc).__name__}")
    hf = hard_failures(recipe)
    sf = soft_flags(recipe, ner_match_fn, description_terms)
    return ExtractionResult(ok=not hf, recipe=recipe, hard_failures=hf, soft_flags=sf)
