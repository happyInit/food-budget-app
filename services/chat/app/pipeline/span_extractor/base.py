"""NER 교체 지점 (구현 계획 zesty-mapping-firefly.md §2 참고).

SpanExtractor는 "문장에서 재료로 보이는 문자열을 찾는" 일만 한다. 찾은 문자열을
표준 item_id로 바꾸는 건 언제나 gazetteer 몫(NER이 와도 안 바뀜) — 이 둘은
대체 관계가 아니라 상호보완 관계라 인터페이스를 분리해뒀다.
"""
from typing import Protocol


class SpanExtractor(Protocol):
    async def extract_spans(self, text: str) -> list[str]:
        """text에서 재료명으로 보이는 후보 문자열 목록을 반환한다."""
        ...
