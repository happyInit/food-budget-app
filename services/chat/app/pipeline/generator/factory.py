from app.config import settings
from app.pipeline.generator.base import Generator
from app.pipeline.generator.template import TemplateGenerator


def get_generator(redis_client=None, ingredient_index: dict[str, int] | None = None) -> Generator:
    """GENERATOR_BACKEND로 생성 백엔드 선택.

    redis=다듬기 결과 캐시 · ingredient_index=근거대조 재료 어휘(표면형→item_id).
    """
    backend = settings.generator_backend
    if backend == "template":
        return TemplateGenerator()
    if backend == "gemini":
        # 유료 API(AGENTS.md 유료예외). 개인 키 기반이라 Bedrock 이전 대상.
        from app.pipeline.generator.gemini import GeminiGenerator

        return GeminiGenerator(redis_client=redis_client, ingredient_index=ingredient_index)
    if backend == "bedrock":
        # 팀 AWS 크레딧. 실측상 프로덕션 refine 경로에서 Gemini와 품질 동률이며
        # 40% 저렴·2배 빠르고 데이터가 서울에 머문다(docs/ai-model-selection-final.md).
        from app.pipeline.generator.bedrock import BedrockGenerator

        return BedrockGenerator(redis_client=redis_client, ingredient_index=ingredient_index)
    raise NotImplementedError(
        f"GENERATOR_BACKEND={backend!r} 미지원 — template | gemini | bedrock"
    )
