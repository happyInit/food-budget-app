"""GeminiGenerator — ④ 생성 층의 LLM 다듬기 구현 (opt-in, GENERATOR_BACKEND=gemini).

설계(docs/chat-assistant-ai.md §2·§3)의 "DB 병렬조회 → 컨텍스트 조립 → LLM이 응답을
다듬는다"를 그대로 구현. 핵심 원칙:

  1. TemplateGenerator를 근거 바닥(floor)으로 품는다. template이 거절("모르겠어요")하면
     Gemini를 호출하지 않는다 → 오프토픽/무근거 질문은 비용 0 + 거절 게이트·95% 정답률 유지.
  2. 응답이 있을 때만 template의 근거 사실을 Gemini에 넘겨 자연스러운 문장으로 재작성.
     basis(근거 태그)는 template 것을 그대로 유지 — 근거는 검색결과에서만 나온다.
  3. 근거대조(check_output_grounded): 근거 밖 숫자를 지어내면 template 출력으로 fallback.
     타임아웃·API오류도 전부 template fallback → 요청 실패 없음.

비용 최소화 레버:
  - 거절 건 skip(호출 0)  · Flash-Lite · max_output_tokens 작게 · temperature 낮게
  - 선택적 다듬기: 가격·영양 응답은 이미 깔끔한 구조화 사실이라 Gemini skip, 레시피 추천만 다듬음
  - Redis 캐시: 동일 근거(grounded_text)면 재호출 없이 캐시된 다듬기 결과 반환(0원)
"""
from __future__ import annotations

import asyncio
import hashlib

from app.config import settings
from app.models import ExtractedQuery
from app.pipeline.context import AssembledContext
from app.pipeline.generator.base import GeneratedAnswer, Generator
from app.pipeline.generator.template import TemplateGenerator
from app.pipeline.guardrails import check_output_grounded

_SYSTEM = (
    "너는 '월 식비 예산 밀플래닝' 앱의 어시스턴트야. "
    "아래 [근거]는 앱 DB에서 검색된 확정 사실이다. "
    "이 근거에 있는 내용만 사용해 사용자 [질문]에 친근하고 자연스러운 한국어로 답하라. "
    "근거에 없는 레시피·가격·숫자·재료를 절대 추가하거나 지어내지 마라. "
    "2~4문장으로 간결하게. 레시피 이름은 근거에 적힌 그대로 사용하라."
)


class GeminiGenerator(Generator):
    def __init__(self, redis_client=None) -> None:
        from google import genai  # 지연 import — 백엔드 미사용 시 의존성 불필요

        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY 없음 — .env 확인 (GENERATOR_BACKEND=gemini 사용 시 필수)")
        self._template = TemplateGenerator()
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._types = __import__("google.genai.types", fromlist=["types"])
        self._redis = redis_client

    async def generate(self, question: ExtractedQuery, ctx: AssembledContext) -> GeneratedAnswer:
        base = await self._template.generate(question, ctx)
        if not base.basis:
            return base  # 거절 케이스 — Gemini 호출 안 함(비용 0, 게이트 보존)
        if settings.gemini_refine_recommend_only and not any(b.type == "recipe_match" for b in base.basis):
            return base  # 가격·영양 = 이미 깔끔한 구조화 사실 → 다듬기 skip

        cached = await self._cache_get(base.text)
        if cached is not None:
            return GeneratedAnswer(text=cached, basis=base.basis)

        try:
            polished = await asyncio.wait_for(
                self._refine(question.raw_text, base.text), timeout=settings.gemini_timeout_s
            )
        except Exception:  # noqa: BLE001 — 타임아웃·API오류 무엇이든 template로 안전 fallback
            return base
        if not polished or not check_output_grounded(polished, base.text):
            return base  # 무근거 숫자 환각 → template 출력 유지
        await self._cache_set(base.text, polished)
        return GeneratedAnswer(text=polished, basis=base.basis)

    async def _refine(self, question: str, grounded_text: str) -> str:
        resp = await self._client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=f"[질문]\n{question}\n\n[근거]\n{grounded_text}",
            config=self._types.GenerateContentConfig(
                system_instruction=_SYSTEM,
                max_output_tokens=settings.gemini_max_output_tokens,
                temperature=settings.gemini_temperature,
            ),
        )
        return (resp.text or "").strip()

    def _cache_key(self, grounded_text: str) -> str:
        h = hashlib.sha1(f"{settings.gemini_model}\n{grounded_text}".encode()).hexdigest()
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
