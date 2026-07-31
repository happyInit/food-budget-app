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


def check_availability(url: str, timeout_s: float = 4.0) -> bool | None:
    """영상 접근 가능 여부. `True`=가능 · `False`=불가(삭제·비공개) · `None`=판정불가.

    URL 이 문법적으로 옳아도 **영상이 없을 수 있다**. 이때 두 백엔드가 서로 다르게 죽는데
    둘 다 유저에게 틀린 말을 한다(실측 2026-07-29):

        api_key : 1초 만에 is_recipe=false  → **"요리 영상이 아닙니다"로 오안내**
        vertex  : 500 INTERNAL (3/3 재현)   → 잡 실패 · 원인 불명

    oEmbed 는 무료·수백ms 이고, 여기서 걸러내면 **모델 호출 비용도 아낀다.**

    ⚠️ `None`(네트워크 오류·타임아웃)일 때는 **막지 않는다.** 선점검이 새로운 실패 지점이
       되면 안 된다 — 우리 쪽 일시 장애로 멀쩡한 추출을 거부하는 게 더 나쁘다.
    """
    import json  # noqa: PLC0415  — 지연 import(이 경로에서만 필요)
    import urllib.error  # noqa: PLC0415
    import urllib.parse  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    api = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(url or "", safe="")
    try:
        with urllib.request.urlopen(api, timeout=timeout_s) as resp:
            if resp.status != 200:
                return None
            json.loads(resp.read().decode("utf-8", "replace"))   # 형식까지 확인
            return True
    except urllib.error.HTTPError as exc:
        # 404=삭제/없음 · 401·403=비공개·임베드 차단 → 어느 쪽이든 모델이 읽지 못한다.
        return False if exc.code in (400, 401, 403, 404) else None
    except Exception:  # noqa: BLE001 — 네트워크·타임아웃·파싱 전부 '판정불가'로 수렴
        return None


def extract_recipe(
    url: str,
    extractor: Callable[[str, str, str], RecipeExtraction],   # (url, model_env, default_model)->RecipeExtraction
    *,
    cache=None,                       # get(key)->RecipeExtraction|None · set(key, recipe)
    ner_match_fn: Callable[[str], bool] | None = None,
    description_terms: set[str] | None = None,
    retry_enabled: bool = True,
    item_resolver: Callable[[str], int | None] | None = None,
    # 접근성 선점검. **주입하지 않으면 검사하지 않는다** — 이 모듈은 순수 오케스트레이션이라
    # 네트워크 I/O 를 기본값으로 들이면 단위테스트가 외부망을 타게 된다(추출기·캐시와 같은 규약).
    # 실서비스 배선은 `services/video` 가 `check_availability` 를 넘긴다.
    availability_fn: Callable[[str], bool | None] | None = None,
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

    # 1-5) 접근성 선점검 — **캐시 뒤, 모델 앞**이 유일하게 옳은 자리다.
    #      캐시 히트는 이미 추출해 둔 결과라 영상이 나중에 내려가도 계속 쓸모가 있고(무료),
    #      미스일 때만 확인하므로 헛된 모델 호출을 막는다.
    if availability_fn is not None and availability_fn(norm) is False:
        return ExtractionResult(
            ok=False, stage="unavailable",
            note="영상을 불러올 수 없어요. 삭제됐거나 비공개·연령제한 영상일 수 있어요. 다른 URL을 넣어주세요.")

    # 2) 1차 추출 → 검증
    result = _extract_and_validate(norm, extractor, "VIDEO_EXTRACT_MODEL", "gemini-3.5-flash-lite",
                                   ner_match_fn, description_terms)

    # 2-1) 타임스탬프 국소 역전은 재분석 대신 **정렬로 복구**한다(2026-07-29 실측 근거).
    #      관측된 실패는 12스텝 중 1곳 역전(444↔357)이었고, **스텝 내용의 순서는 조리 논리상 옳았다**
    #      (채소 손질이 10분 끓이기보다 앞서는 게 자연스러움). 즉 틀린 건 시각 하나뿐이다.
    #      이걸 재분석하면 30초·상위모델 비용을 쓰고도 같은 결과를 얻을 뿐이다.
    if result.recipe is not None and _repair_timestamps(result.recipe):
        result.hard_failures = hard_failures(result.recipe)
        result.soft_flags = soft_flags(result.recipe, ner_match_fn, description_terms)
        result.ok = not result.hard_failures
        result.stage = "repaired"

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


_MAX_REPAIR_RATIO = 0.25   # 역전이 스텝의 25%를 넘으면 '국소 오류'가 아니다 → 재분석에 맡긴다


def _repair_timestamps(recipe) -> bool:
    """타임스탬프 국소 역전을 정렬로 복구한다. 고쳤으면 True.

    **스텝 텍스트의 순서는 건드리지 않는다** — 조리 논리는 모델이 맞게 냈고(실측 확인),
    틀린 것은 시각뿐이기 때문이다. 시각만 오름차순으로 재배열하고 order를 다시 매긴다.

    광범위하게 흐트러졌다면(>25%) 모델이 영상을 제대로 못 따라간 것이므로 복구하지 않고
    재분석으로 넘긴다 — 잘못된 시각을 억지로 정렬하면 '틀린 결과를 정상처럼' 만들 위험이 있다.
    """
    ts = [s.timestamp_sec for s in recipe.steps]
    if not ts or any(t is None for t in ts) or ts == sorted(ts):
        return False
    inversions = sum(1 for i in range(1, len(ts)) if ts[i] < ts[i - 1])
    if inversions / max(len(ts) - 1, 1) > _MAX_REPAIR_RATIO:
        return False                      # 국소 오류가 아님 → 재분석
    for step, t in zip(recipe.steps, sorted(ts)):
        step.timestamp_sec = t
    for i, step in enumerate(recipe.steps, 1):
        step.order = i
    return True


def _extract_and_validate(url, extractor, model_env, default_model, ner_match_fn, description_terms) -> ExtractionResult:
    try:
        recipe = extractor(url, model_env, default_model)
    except Exception as exc:   # noqa: BLE001 — 파싱/스키마/네트워크 실패 = H1(하드)
        return ExtractionResult(ok=False, hard_failures=["H1"], note=f"추출 실패: {type(exc).__name__}")
    hf = hard_failures(recipe)
    sf = soft_flags(recipe, ner_match_fn, description_terms)
    return ExtractionResult(ok=not hf, recipe=recipe, hard_failures=hf, soft_flags=sf)
