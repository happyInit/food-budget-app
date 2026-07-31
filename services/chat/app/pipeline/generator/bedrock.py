"""BedrockGenerator — AWS Bedrock 다듬기 구현 (GENERATOR_BACKEND=bedrock).

파이프라인은 `RefineGenerator` 공유. 여기서는 **Bedrock Converse 호출만** 구현한다.
프롬프트도 Gemini와 동일한 `prompts.REFINE_SYSTEM`을 쓴다(회귀 검증 완료).

모델 선정 근거(`docs/ai-model-selection-final.md`):
  실측에서 `apac.amazon.nova-micro-v1:0`가 **프로덕션 refine 경로 20/20으로 Gemini와 동률**,
  안전(환각) 25/25 동일 · 40% 저렴 · 2배 빠름(p50 ~410ms) · **데이터가 서울에 머문다**.

⚠️ 호출 규약: **서울 리전은 on-demand 직접 호출이 불가**하고 cross-region inference profile이
   필요하다 — Nova는 `apac.` / Claude는 `global.` 프리픽스. 기본값이 이미 프로필 ID다.
⚠️ 인증: boto3 기본 자격증명 체인(온프렘=ESO가 주입한 access key env → EKS 이관 시 IRSA).
   코드는 자격증명을 직접 다루지 않는다.
"""
from __future__ import annotations

import asyncio

from app.config import settings
from app.pipeline.generator.prompts import REFINE_SYSTEM, build_user_content
from app.pipeline.generator.refine_base import RefineGenerator


class BedrockGenerator(RefineGenerator):
    def __init__(self, redis_client=None, ingredient_index: dict[str, int] | None = None) -> None:
        import boto3  # 지연 import — 백엔드 미사용 시 의존성 불필요
        from botocore.config import Config

        super().__init__(redis_client=redis_client, ingredient_index=ingredient_index)
        # 앱 타임아웃(_timeout_s)이 상위 상한이므로 SDK 타임아웃은 그보다 살짝 낮게 두고,
        # 재시도는 adaptive로 스로틀을 흡수한다(실측: 동시성 2에서 스로틀 0건).
        self._client = boto3.client(
            "bedrock-runtime",
            region_name=settings.bedrock_region,
            config=Config(
                retries={"max_attempts": settings.bedrock_max_attempts, "mode": "adaptive"},
                connect_timeout=settings.bedrock_timeout_s,
                read_timeout=settings.bedrock_timeout_s,
            ),
        )

    @property
    def _model_tag(self) -> str:
        return settings.bedrock_model_id

    @property
    def _timeout_s(self) -> float:
        # SDK 자체 타임아웃보다 여유를 둬 재시도 1회분을 흡수한다.
        return settings.bedrock_timeout_s * 1.5

    async def _refine(self, question: str, grounded_text: str) -> str:
        # boto3는 동기 API — 이벤트 루프를 막지 않도록 스레드로 넘긴다.
        resp = await asyncio.to_thread(
            self._client.converse,
            modelId=settings.bedrock_model_id,
            system=[{"text": REFINE_SYSTEM}],
            messages=[{"role": "user", "content": [{"text": build_user_content(question, grounded_text)}]}],
            inferenceConfig={
                "maxTokens": settings.bedrock_max_output_tokens,
                "temperature": settings.bedrock_temperature,
            },
        )
        # reasoning 블록을 함께 주는 모델이 있어 text 블록만 골라 잇는다.
        blocks = resp["output"]["message"]["content"]
        return "".join(b.get("text", "") for b in blocks if isinstance(b, dict)).strip()
