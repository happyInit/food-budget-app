"""API 스키마 — 영상→레시피 추출.

OCR과 같은 **비동기 잡 패턴**(202 접수 → 폴링). 영상 분석은 수십 초가 걸려 동기 응답이 불가하다.
추출 결과 본문은 `ml/video-recipe/models.py`의 `RecipeExtraction`을 그대로 재사용한다
(파이프라인이 이미 검증·정규화까지 마친 스키마라 서비스가 다시 정의하면 이중 관리가 된다).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

JobStatus = Literal["PENDING", "DONE", "FAILED"]


class VideoExtractRequest(BaseModel):
    """POST /api/recipes/video — 유튜브 URL 제출(온디맨드)."""
    url: str = Field(min_length=1, max_length=500)


class VideoAcceptedResponse(BaseModel):
    """202 접수 — 즉시 job_id 반환."""
    job_id: str
    status: JobStatus = "PENDING"
    from_cache: bool = False        # 캐시 히트면 즉시 DONE(비용 0)


class IngredientOut(BaseModel):
    name: str
    quantity: str | None = None
    item_id: int | None = None      # NER 정규화 결과(표준품목코드)


class StepOut(BaseModel):
    order: int
    text: str
    timestamp_sec: int | None = None


class VideoStatusResponse(BaseModel):
    """GET /api/recipes/video/{jobId} — 상태·결과."""
    status: JobStatus
    stage: str | None = None                 # extracted|retried|refined|cached|failed
    from_cache: bool = False
    title: str | None = None
    is_recipe: bool = True                   # False = 요리 영상 아님(H3)
    # 영상에 인분 명시가 없으면 null이다(실측: 3회 중 2회 null).
    # ⚠️ 추정값으로 채우지 않는다 — 틀린 인분은 재료비를 그대로 왜곡한다.
    #    기존 `recipe.serving`도 10%(871/8,419)가 null이라 시스템이 이미 다루는 정상 상태다.
    servings: str | None = None
    servings_known: bool = True              # false면 UI가 "인분 미상 · 직접 입력"을 유도
    source_url: str | None = None
    video_seconds: int | None = None
    ingredients: list[IngredientOut] = Field(default_factory=list)
    steps: list[StepOut] = Field(default_factory=list)
    soft_flags: list[str] = Field(default_factory=list)   # S1~S3 — 결과는 주되 품질 주의
    reason: str | None = None                # FAILED 사유(H1~H5 또는 안내문)
