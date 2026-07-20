"""유튜브 영상→레시피 추출 스키마 (video-recipe-ai.md §1·§4).

Gemini 1차 추출이 이 스키마(JSON)로 내도록 프롬프트를 강제하고, Pydantic 검증이
곧 H1(파싱/스키마) 검증기가 된다 — 스키마 불일치 = 하드 실패.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class Ingredient(BaseModel):
    name: str                          # 원문 재료명(정규화 전 — NER이 표준품목코드로 후처리)
    quantity: str | None = None        # "2큰술", "한 줌" 등 자유텍스트
    item_id: int | None = None         # NER 정규화 결과(추출 시 None → 파이프라인 마지막 단계서 채움)


class Step(BaseModel):
    order: int                         # 1부터 단조증가
    text: str                          # 조리 지시
    timestamp_sec: int | None = None   # 영상 내 시각(초) — 단조증가여야(H4)


class RecipeExtraction(BaseModel):
    title: str | None = None           # 요리명 — null이면 '요리 영상 아님' 신호(H3)
    is_recipe: bool = True             # 모델이 요리 영상 아니라 판정 시 False(H3)
    servings: str | None = None
    ingredients: list[Ingredient] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    source_url: str | None = None
    video_seconds: int | None = None   # 영상 길이(타임스탬프 초과 검증 H4용)


class ExtractionResult(BaseModel):
    """파이프라인 최종 산출 — 성공/실패·플래그·비용추적."""
    ok: bool
    recipe: RecipeExtraction | None = None
    hard_failures: list[str] = Field(default_factory=list)   # H1~H5 코드
    soft_flags: list[str] = Field(default_factory=list)      # S1~S3 코드
    from_cache: bool = False
    retried: bool = False
    stage: str = "extracted"           # extracted|retried|refined|failed|cached
    note: str | None = None            # 실패 시 사용자 안내(수동입력 유도)
