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


# ── 조용한 폐기 → 관측 가능 (영구 미분류 원인 규명, 2026-07-30) ──────────────────
def test_label_aliases_normalize_notation_variants_only():
    """같은 라벨의 **표기 변형만** 되돌린다 — 뜻이 다른 값은 여전히 버린다.

    실측 배경: 리뷰 16건이 영구 미분류로 남았고 원인이 어휘 밖 라벨 폐기였다.
    `temperature=0` 이라 재실행해도 같은 출력이 나와 **저절로 낫지 않는다.**
    표기 변형(긍정/POSITIVE/공백)이 원인이면 이 정규화만으로 해소된다.
    """
    import score_review_sentiment as m

    for raw, want in [("긍정", "positive"), ("부정", "negative"), ("중립", "neutral"),
                      ("POSITIVE", "positive"), ("  positive  ", "positive"),
                      ("Neg", "negative")]:
        got = m.parse_labels('[{"i":1,"label":"%s"}]' % raw, 1)
        assert got == {1: want}, f"{raw!r} → {got}"

    # 🔴 뜻이 다른 값은 **넣지 않는다** — 그건 새 판정이고 추측이다
    for raw in ("좋음", "mixed", "혼합", "복합", "unknown"):
        assert m.parse_labels('[{"i":1,"label":"%s"}]' % raw, 1) == {}, raw


def test_discarded_labels_are_recorded_not_silent():
    """버린 라벨은 집계에 남아야 한다 — 조용히 사라지면 원인을 특정할 수 없다.

    이게 16건이 왜 미분류인지 3일간 알 수 없었던 이유다. 다음 실행 1회가 스스로
    원인(표기 변형인가, 뜻이 다른 라벨인가)을 알려주게 만든다.
    """
    import score_review_sentiment as m

    m.discarded_labels.clear()
    m.parse_labels('[{"i":1,"label":"mixed"},{"i":2,"label":"positive"},'
                   '{"i":3,"label":"mixed"}]', 3)
    assert m.discarded_labels == {"'mixed'": 2}, m.discarded_labels

    # 번호가 범위를 벗어난 건 모델이 지어낸 것이라 라벨 집계에 넣지 않는다(원인이 다르다)
    m.discarded_labels.clear()
    m.parse_labels('[{"i":99,"label":"mixed"}]', 3)
    assert m.discarded_labels == {}, m.discarded_labels
