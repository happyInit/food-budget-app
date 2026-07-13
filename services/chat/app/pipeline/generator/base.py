"""④ 생성 — 교체 가능 1개 층. GENERATOR_BACKEND env var로 구현체 선택(factory.py)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.models import BasisTag, ExtractedQuery
from app.pipeline.context import AssembledContext


@dataclass
class GeneratedAnswer:
    text: str
    basis: list[BasisTag] = field(default_factory=list)


class Generator(ABC):
    @abstractmethod
    async def generate(self, question: ExtractedQuery, ctx: AssembledContext) -> GeneratedAnswer: ...
