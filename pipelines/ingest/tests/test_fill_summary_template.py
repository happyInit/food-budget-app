"""요약 템플릿 — 문장 생성 계약(LLM·DB 불필요).

리뷰가 적어 LLM 요약을 하지 않는 레시피(4,678개)의 화면 빈칸을 메운다.
**집계 사실만 서술하므로 창작이 없다** — 검증이 필요 없는 것이 이 방식의 핵심 이점이다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fill_summary_template import build_text  # noqa: E402


def test_single_review_reads_naturally():
    """1건에 '1건 중 1건(100%)' 은 통계처럼 보여 어색하다 — 그대로 말한다."""
    assert build_text(1, 1, 0) == "후기 1건이 긍정적입니다."
    assert build_text(1, 0, 0) == "후기가 1건 있습니다."


def test_small_counts_omit_percentage():
    """4건 이하는 백분율이 오히려 오해를 준다(3/4=75%는 표본이 너무 작다)."""
    assert build_text(4, 3, 0) == "후기 4건 중 3건이 긍정적입니다."
    assert "%" not in build_text(4, 3, 0)


def test_larger_counts_include_percentage():
    assert build_text(19, 16, 0) == "후기 19건 중 16건(84%)이 긍정적입니다."


def test_negatives_are_surfaced_not_hidden():
    """아쉬운 의견을 숨기면 유저가 판단을 그르친다 — 건수로 덧붙인다."""
    t = build_text(10, 7, 2)
    assert "아쉬웠다는 의견도 2건" in t


def test_no_negatives_no_extra_sentence():
    assert "아쉬" not in build_text(10, 10, 0)


def test_zero_reviews_yields_nothing():
    """후기가 없으면 문장을 만들지 않는다 — 빈 사실을 지어내지 않는다."""
    assert build_text(0, 0, 0) is None
