"""리뷰 감정분류 — 배치 계약 검증(Bedrock·DB 불필요).

긍정 비율은 유저에게 그대로 보이는 수치다. **형식 이탈을 억지로 채우면 비율이 조용히 왜곡**되므로,
버리는 규칙을 코드 밖에 고정한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from score_review_sentiment import MODEL_ID, build_prompt, parse_labels, score_batch  # noqa: E402


class _FakeClient:
    def __init__(self, text):
        self._text = text

    def converse(self, **kw):
        return {"output": {"message": {"content": [{"text": self._text}]}}}


_ITEMS = [(101, "정말 맛있어요"), (102, "너무 짜요"), (103, "레시피 감사합니다")]


def test_prompt_does_not_leak_db_ids():
    """모델에는 순번만 준다 — DB id 를 노출할 이유가 없다."""
    p = build_prompt(_ITEMS)
    assert "101" not in p and "1. 정말 맛있어요" in p


def test_prompt_truncates_long_body():
    long_body = "맛" * 500
    p = build_prompt([(1, long_body)])
    assert len(p) < len(long_body) + 500


def test_parse_maps_index_to_label():
    got = parse_labels('[{"i":1,"label":"positive"},{"i":2,"label":"negative"}]', 3)
    assert got == {1: "positive", 2: "negative"}


def test_parse_rejects_unknown_label():
    """스키마 CHECK 어휘 밖은 버린다 — 넣으면 INSERT 가 런타임에 깨진다."""
    assert parse_labels('[{"i":1,"label":"좋음"}]', 3) == {}


def test_parse_rejects_out_of_range_index():
    """입력보다 큰 번호는 모델이 지어낸 것이다."""
    assert parse_labels('[{"i":9,"label":"positive"}]', 3) == {}


def test_parse_survives_garbage():
    for bad in ("설명입니다", "[", "[{broken}]", ""):
        assert parse_labels(bad, 3) == {}


def test_partial_response_scores_only_what_came_back():
    """일부만 오면 그만큼만 적재한다 — 나머지는 다음 실행이 재시도한다."""
    rows = score_batch(_FakeClient('[{"i":1,"label":"positive"},{"i":3,"label":"neutral"}]'), _ITEMS)
    assert [r["review_id"] for r in rows] == [101, 103]
    assert all(r["model"] == MODEL_ID for r in rows)


def test_no_labels_yields_no_rows():
    """형식이 깨지면 아무것도 넣지 않는다 — neutral 로 채우면 긍정 비율이 왜곡된다."""
    assert score_batch(_FakeClient("분류 실패"), _ITEMS) == []
