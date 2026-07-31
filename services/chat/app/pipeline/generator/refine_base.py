"""RefineGenerator — LLM 다듬기 백엔드의 공통 골격.

Gemini·Bedrock이 **완전히 같은 안전망**을 쓰도록 파이프라인을 여기 한 곳에 둔다.
백엔드는 `_refine()`(실제 모델 호출)과 `_model_tag`(캐시 네임스페이스)만 구현한다.

핵심 원칙(설계 `docs/chat-assistant-ai.md` §2·§3):
  1. TemplateGenerator를 근거 바닥(floor)으로 품는다. template이 거절("모르겠어요")하면
     LLM을 호출하지 않는다 → 오프토픽/무근거 질문은 비용 0 + 거절 게이트·정답률 유지.
  2. 응답이 있을 때만 template의 근거 사실을 넘겨 재작성. basis(근거 태그)는 template 것을 유지.
  3. 근거대조(check_output_grounded) 실패·타임아웃·API오류는 **전부 template fallback** → 요청 실패 없음.

비용 최소화 레버: 거절 skip · recommend-only skip(가격·영양은 template 그대로) · Redis 캐시(동일 근거 재호출 0원).
"""
from __future__ import annotations

import asyncio
import hashlib
from abc import abstractmethod

from app.config import settings
from app.models import ExtractedQuery
from app.pipeline.context import AssembledContext
from app.pipeline.generator.base import GeneratedAnswer, Generator
from app.pipeline.generator.template import TemplateGenerator
from app.pipeline.guardrails import check_output_grounded, expand_korean_amounts, incr_monthly_calls


class RefineGenerator(Generator):
    """다듬기 백엔드 공통 골격. 서브클래스는 `_refine`·`_model_tag`만 채운다."""

    def __init__(self, redis_client=None, ingredient_index: dict[str, int] | None = None) -> None:
        self._template = TemplateGenerator()
        self._redis = redis_client
        # 근거대조 재료 어휘(표면형→item_id). None이면 숫자만 대조.
        self._ingredient_index = ingredient_index

    # ── 서브클래스 구현부 ────────────────────────────────────────────
    @property
    @abstractmethod
    def _model_tag(self) -> str:
        """캐시 키 네임스페이스. 모델이 다르면 출력도 달라지므로 반드시 분리한다."""

    @abstractmethod
    async def _refine(self, question: str, grounded_text: str) -> str:
        """실제 모델 호출. 타임아웃·예외는 호출부가 잡아 template으로 fallback한다."""

    @property
    def _timeout_s(self) -> float:
        raise NotImplementedError

    # ── 공통 파이프라인 ─────────────────────────────────────────────
    async def generate(self, question: ExtractedQuery, ctx: AssembledContext) -> GeneratedAnswer:
        base = await self._template.generate(question, ctx)
        if not base.basis:
            return base  # 거절 케이스 — LLM 호출 안 함(비용 0, 게이트 보존)
        if settings.gemini_refine_recommend_only and not any(b.type == "recipe_match" for b in base.basis):
            return base  # 가격·영양 = 이미 깔끔한 구조화 사실 → 다듬기 skip

        cached = await self._cache_get(base.text)
        if cached is not None:
            return GeneratedAnswer(text=cached, basis=base.basis)

        try:
            polished = await asyncio.wait_for(
                self._refine(question.raw_text, base.text), timeout=self._timeout_s
            )
        except Exception:  # noqa: BLE001 — 타임아웃·API오류 무엇이든 template로 안전 fallback
            return base
        # 실제 유료 호출 1건 발생(캐시히트·거절·recommend-only skip은 여기 못 옴) → 월 비용 계상.
        if settings.monthly_cap_enabled:
            await incr_monthly_calls(self._redis)

        # 근거 = template 출력 + 유저 질문 + 질문의 금액 표기 확장("8천원"→8000).
        # 유저가 말한 재료·예산을 되풀이하는 것은 환각이 아니므로 오탐을 막는다(guardrails 독스트링 참조).
        q = question.raw_text
        grounding_ref = f"{base.text}\n{q}\n{expand_korean_amounts(q)}"
        if not polished or not check_output_grounded(polished, grounding_ref, self._ingredient_index):
            return base  # 무근거 숫자·재료 환각 → template 출력 유지
        await self._cache_set(base.text, polished)
        return GeneratedAnswer(text=polished, basis=base.basis)

    # ── 캐시(best-effort) ──────────────────────────────────────────
    def _cache_key(self, grounded_text: str) -> str:
        h = hashlib.sha1(f"{self._model_tag}\n{grounded_text}".encode()).hexdigest()
        return f"chatgen:refine:{h}"

    async def _cache_get(self, grounded_text: str) -> str | None:
        if self._redis is None:
            return None
        try:
            return await self._redis.get(self._cache_key(grounded_text))
        except Exception:  # noqa: BLE001 — 캐시는 best-effort, 장애 시 그냥 재생성
            return None

    async def _cache_set(self, grounded_text: str, polished: str) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.set(self._cache_key(grounded_text), polished, ex=settings.gemini_cache_ttl_s)
        except Exception:  # noqa: BLE001
            pass
