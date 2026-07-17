from app.config import settings
from app.pipeline.generator.base import Generator
from app.pipeline.generator.template import TemplateGenerator


def get_generator(redis_client=None, ingredient_index: dict[str, int] | None = None) -> Generator:
    backend = settings.generator_backend
    if backend == "template":
        return TemplateGenerator()
    if backend == "gemini":
        # opt-in 실험 백엔드. 프로덕션 활성은 AGENTS.md 유료예외 재승인 필요
        # (chat-assistant-ai.md §3). 기본값은 template 유지. redis=다듬기 결과 캐시.
        # ingredient_index=근거대조 재료 어휘(표면형→item_id).
        from app.pipeline.generator.gemini import GeminiGenerator

        return GeminiGenerator(redis_client=redis_client, ingredient_index=ingredient_index)
    raise NotImplementedError(
        f"GENERATOR_BACKEND={backend!r} 미지원 — template | gemini "
        f"(bedrock=Nova/Claude는 AWS 이전 후, docs/chat-assistant-ai.md §3)"
    )
