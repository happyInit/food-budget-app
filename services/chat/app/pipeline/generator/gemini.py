"""GeminiGenerator — ④ 생성 층의 LLM 다듬기 구현 (opt-in, GENERATOR_BACKEND=gemini).

파이프라인(거절 skip·recommend-only skip·캐시·근거대조·fallback)은 `RefineGenerator`가 갖고,
여기서는 **Gemini API 호출만** 구현한다. 프롬프트는 `prompts.REFINE_SYSTEM` 공유
— Bedrock과 같은 프롬프트를 쓰는 근거는 `docs/ai-chat-mass-measurement.md` §6.

⚠️ 유료 API(AGENTS.md 유료예외). GEMINI_API_KEY 필요.
"""
from __future__ import annotations

from app.config import settings
from app.pipeline.generator.prompts import REFINE_SYSTEM, build_user_content
from app.pipeline.generator.refine_base import RefineGenerator


class GeminiGenerator(RefineGenerator):
    def __init__(self, redis_client=None, ingredient_index: dict[str, int] | None = None) -> None:
        from google import genai  # 지연 import — 백엔드 미사용 시 의존성 불필요

        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY 없음 — .env 확인 (GENERATOR_BACKEND=gemini 사용 시 필수)")
        super().__init__(redis_client=redis_client, ingredient_index=ingredient_index)
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._types = __import__("google.genai.types", fromlist=["types"])

    @property
    def _model_tag(self) -> str:
        return settings.gemini_model

    @property
    def _timeout_s(self) -> float:
        return settings.gemini_timeout_s

    async def _refine(self, question: str, grounded_text: str) -> str:
        resp = await self._client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=build_user_content(question, grounded_text),
            config=self._types.GenerateContentConfig(
                system_instruction=REFINE_SYSTEM,
                max_output_tokens=settings.gemini_max_output_tokens,
                temperature=settings.gemini_temperature,
            ),
        )
        return (resp.text or "").strip()
