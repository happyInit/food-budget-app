"""NER 완성 후 채울 자리 (구현계획 §2 참고). 지금은 미구현 — CRF 학습이
docs/prd/ner-training-data-spec.md §0 데이터 갭으로 블록 상태라 자리만 예약한다.

NER 서비스(/ner)가 준비되면 여기서 HTTP 호출로 인식된 재료 스팬 문자열을
반환하도록 구현하고, EXTRACTOR_BACKEND=ner로 전환하면 된다. 이 클래스 밖
(extract.py 이후 전부)은 안 건드린다.
"""


class CrfSpanExtractor:
    def __init__(self, ner_service_url: str | None = None):
        self._url = ner_service_url

    async def extract_spans(self, text: str) -> list[str]:
        raise NotImplementedError(
            "CrfSpanExtractor 미구현 — NER 학습 코퍼스 확보 후 구현 예정 "
            "(docs/prd/ner-training-data-spec.md §0 참고). 그때까지 EXTRACTOR_BACKEND=rule 사용."
        )
