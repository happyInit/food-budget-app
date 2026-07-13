from app.config import settings
from app.pipeline.generator.base import Generator
from app.pipeline.generator.template import TemplateGenerator


def get_generator() -> Generator:
    backend = settings.generator_backend
    if backend == "template":
        return TemplateGenerator()
    raise NotImplementedError(
        f"GENERATOR_BACKEND={backend!r} 미구현 — MVP는 template만 지원 "
        f"(bedrock/gemini는 팀 결정 대기, docs/chat-assistant-ai.md §3)"
    )
