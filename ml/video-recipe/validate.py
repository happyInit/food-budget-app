"""규칙 기반 검증 — H1~H5(하드) · S1~S3(소프트). 전부 CPU·비용 0 (video-recipe-ai.md §4).

하드 실패 = 재분석(1회) 트리거. 소프트 실패 = 재분석 없이 플래그(정제서 보정).
자체 재료 사전(NER gazetteer)이 검증기 역할을 겸한다(S2) — 매칭 실패율이 곧 환각 신호.
"""
from __future__ import annotations

from collections import Counter

from models import RecipeExtraction

_MIN_STEPS = 2
_DUP_RATIO_HARD = 0.5     # H5: 스텝 중복률 50% 초과
_NER_FAIL_SOFT = 0.4      # S2: NER 매칭 실패율 40% 초과


def video_not_received(r: RecipeExtraction) -> bool:
    """H0 — 모델이 **영상을 아예 받지 못한** 상태.

    실측(2026-07-29)에서 발견: YouTube URL 입력이 동작하지 않는 환경에서도 모델은 오류를 내지
    않고 **전 필드가 비어 있는 정상 응답**(`video_seconds=0`, `is_recipe=false`)을 돌려준다.
    이걸 H3(요리 영상 아님)으로 분류하면 원인이 감춰지고 유저에게 잘못된 안내가 나간다.

    더 위험한 변형도 있다 — 상위 모델은 "못 봤다" 대신 **그럴듯한 내용을 창작**했다
    (실측: 무관한 영상을 "귀여운 고양이의 일상 15초"로 서술). 그래서 길이가 0이면
    **재분석하지 않고 즉시 실패**시킨다(재시도해도 같은 원인이라 비용만 든다).
    """
    return r.video_seconds is not None and r.video_seconds <= 0 and not r.steps


def hard_failures(r: RecipeExtraction) -> list[str]:
    """H0~H5 — 하나라도 있으면 하드 실패. H1(스키마)은 파싱 시점에 걸러짐.

    H0은 재분석 대상이 아니다(원인이 입력 경로라 재시도로 회복 불가) — 호출부가 구분해 처리한다.
    """
    f: list[str] = []
    if video_not_received(r):
        f.append("H0")                                  # 영상 미수신 — 재분석 무의미
    if not r.is_recipe or not (r.title or "").strip():
        f.append("H3")                                  # 요리명 null / 비요리 판정
    if len(r.ingredients) == 0 or len(r.steps) < _MIN_STEPS:
        f.append("H2")                                  # 재료 0 또는 스텝<2
    # H4: 타임스탬프 단조증가 위반 / 영상 길이 초과
    ts = [s.timestamp_sec for s in r.steps if s.timestamp_sec is not None]
    if ts != sorted(ts):
        f.append("H4")
    elif r.video_seconds is not None and ts and ts[-1] > r.video_seconds:
        f.append("H4")
    # H5: 스텝 문장 중복률
    texts = [(s.text or "").strip() for s in r.steps if (s.text or "").strip()]
    if texts:
        most = Counter(texts).most_common(1)[0][1]
        if most / len(texts) > _DUP_RATIO_HARD:
            f.append("H5")
    return f


def soft_flags(r: RecipeExtraction, ner_match_fn=None, description_terms: set[str] | None = None) -> list[str]:
    """S1~S3 — 재분석 없이 플래그. ner_match_fn(name)->bool: 자체 사전 매칭 여부."""
    flags: list[str] = []
    # S2: NER 사전 매칭 실패율 > 40% (환각 의심 — 자체 재료사전이 검증기)
    if ner_match_fn and r.ingredients:
        miss = sum(0 if ner_match_fn(i.name) else 1 for i in r.ingredients)
        if miss / len(r.ingredients) > _NER_FAIL_SOFT:
            flags.append("S2")
    # S3: 설명란 교차검증 — 추출 재료가 설명란 재료목록과 겹침률 낮으면 플래그
    if description_terms and r.ingredients:
        names = {i.name for i in r.ingredients}
        overlap = len(names & description_terms) / len(names)
        if overlap < 0.2:
            flags.append("S3")
    return flags
