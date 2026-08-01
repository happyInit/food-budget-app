"""리뷰 요약 배치 — 계약 검증(Bedrock·DB 불필요).

요약문은 **유저에게 그대로 보인다**. 형식 이탈을 억지로 저장하면 화면이 깨지므로
버리는 규칙을 코드 밖에 고정한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from summarize_reviews import DEFAULT_MODEL, MIN_REVIEWS, build_prompt, summarize  # noqa: E402


class _FakeClient:
    def __init__(self, text):
        self._text = text

    def converse(self, **kw):
        return {"output": {"message": {"content": [{"text": self._text}]}}}


_BODIES = ["정말 맛있어요", "면 삶을 때 식용유 넣으면 안 뭉쳐요", "좀 짰어요"]


def test_model_is_measured_choice_not_default():
    """실측 결과 nova-micro 는 존댓말 지시를 0/8 로 무시했다 — 요약에는 쓰지 않는다."""
    assert "nova-micro" not in DEFAULT_MODEL
    assert "claude-3-5-sonnet" in DEFAULT_MODEL


def test_prompt_forbids_invention_and_demands_both_sides():
    p = build_prompt(_BODIES)
    assert "지어내지 마라" in p
    assert "둘 다" in p            # 좋은 점만 쓰면 왜곡이다
    assert "존댓말" in p


def test_prompt_truncates_long_reviews():
    p = build_prompt(["맛" * 400])
    assert len(p) < 400 + len(build_prompt([]))


def test_strips_model_preamble():
    """모델이 '요약:' 머리말을 붙이는 경우가 있다 — 화면에 그대로 나가면 안 된다."""
    got = summarize(_FakeClient("요약: 전반적으로 맛있다는 평이 많습니다."), "m", _BODIES)
    assert got == "전반적으로 맛있다는 평이 많습니다."


def test_rejects_empty_or_too_short():
    for bad in ("", "   ", "짧음"):
        assert summarize(_FakeClient(bad), "m", _BODIES) is None


def test_rejects_overlong_output():
    """2~3문장을 요구했는데 장문이 오면 형식 이탈이다 — 저장하지 않는다."""
    assert summarize(_FakeClient("가" * 700), "m", _BODIES) is None


def test_accepts_normal_summary():
    t = "전반적으로 맛있다는 평이 많습니다. 면 삶을 때 식용유를 넣으면 뭉치지 않는다는 팁이 있습니다."
    assert summarize(_FakeClient(t), "m", _BODIES) == t


def test_min_reviews_threshold():
    """10건 미만은 후기를 그대로 보여주는 편이 낫다 — 6건을 2문장으로 압축하면 정보가 준다.
    비용 실측(2026-07-29): ≥5·30건 36,291원 → ≥10·15건 16,331원(55% 절감·품질 손실 없음)."""
    assert MIN_REVIEWS == 10


def test_sample_size_scales_with_review_count():
    """고정 표본이면 대표성이 갈린다 — 실측: 10~29건 97% 커버 vs 300건+ 3.7%.
    리뷰가 많을수록 표본을 늘려 신뢰도 격차를 줄인다."""
    from summarize_reviews import sample_size

    assert sample_size(12) == 12          # 20건 이하는 전수
    assert sample_size(20) == 20
    assert sample_size(50) == 20
    assert sample_size(100) == 20
    assert sample_size(500) == 30         # 큰 레시피만 30건
    # 단조 증가 — 리뷰가 늘었는데 표본이 주는 일은 없어야 한다
    prev = 0
    for n in (10, 20, 21, 100, 101, 1000):
        cur = sample_size(n)
        assert cur >= prev or n <= 20
        prev = cur


def test_caution_is_separate_from_summary():
    """소수 부정을 요약 표본에 섞으면 비율이 왜곡된다(300건 중 2건 → 15건 중 3건 = 30배).
    별도 필드라 '일부 후기' 프레이밍이 내장돼 과대대표되지 않는다."""
    from summarize_reviews import _CAUTION_PROMPT, caution_from

    assert "부정적인 것만" in _CAUTION_PROMPT
    assert "없음" in _CAUTION_PROMPT          # 쓸 것이 없으면 만들지 않는다
    assert caution_from(None, "m", []) is None  # 부정 후기 없으면 호출조차 안 한다
