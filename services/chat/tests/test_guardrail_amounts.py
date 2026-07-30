"""근거대조 오탐 방지 — 한글 금액 확장 + 질문 합산 근거.

실측 1,138건에서 refine 실패의 75%가 "유저가 말한 재료·예산을 답변이 되풀이한 것"을
환각으로 오판한 오탐이었다(`docs/ai-chat-mass-measurement.md`). 아래는 그 수정의 회귀 방지.
"""
import pytest

from app.pipeline.guardrails import check_output_grounded, expand_korean_amounts


@pytest.mark.parametrize(
    "question, expected",
    [
        ("8천원으로 뭐 해먹지", "8000"),
        ("만이천원으로 닭요리", "12000"),   # 만+이천으로 쪼개지지 않아야
        ("2만원으로 푸짐하게", "20000"),
        ("만원으로 뭐 해먹지", "10000"),
        ("만오천원어치", "15000"),
        ("오천원으로", "5000"),
        ("삼만원 예산", "30000"),
    ],
)
def test_expands_korean_amount(question, expected):
    assert expected in expand_korean_amounts(question).split()


@pytest.mark.parametrize(
    "question",
    [
        "재료 추천해줘",      # '추천'의 '천'이 1000으로 잡히면 안 됨
        "추천 부탁해",
        "15000원 예산 요리",  # 이미 아라비아 숫자 → 확장 대상 아님
        "김치찌개 레시피",
    ],
)
def test_no_false_amount(question):
    assert expand_korean_amounts(question) == ""


def test_question_ingredient_is_not_hallucination():
    """유저가 말한 재료를 답변이 되풀이해도 환각이 아니다(근거에 질문을 합산)."""
    idx = {"두부": 1, "대파": 3}
    evidence = "'순두부찌개' 같은 요리는 어때요?"
    answer = "두부와 대파로 '순두부찌개' 어때요?"
    assert check_output_grounded(answer, evidence, idx) is False          # 근거만 → 오탐
    ref = f"{evidence}\n두부랑 대파로 뭐 해먹지"
    assert check_output_grounded(answer, ref, idx) is True                # 질문 합산 → 통과


def test_question_budget_notation_is_not_hallucination():
    """근거는 8000, 유저·답변은 '8천원' — 표기차가 환각으로 잡히면 안 된다."""
    evidence = "8000원으로 만들 수 있는 요리예요! '제육볶음'(약 6,500원) 어때요?"
    answer = "8천원으로 '제육볶음'(약 6,500원) 만들 수 있어요!"
    q = "8천원 예산으로 돼지고기 요리"
    ref = f"{evidence}\n{q}\n{expand_korean_amounts(q)}"
    assert check_output_grounded(answer, ref, None) is True


def test_still_blocks_real_hallucination():
    """근거에도 질문에도 없는 값은 여전히 차단돼야 한다(가드가 무력화되면 안 됨)."""
    idx = {"두부": 1, "삼겹살": 4}
    evidence = "'순두부찌개' 같은 요리는 어때요?"
    q = "두부로 뭐 해먹지"
    ref = f"{evidence}\n{q}\n{expand_korean_amounts(q)}"
    assert check_output_grounded("'순두부찌개'는 9,900원이에요.", ref, idx) is False   # 없는 금액
    assert check_output_grounded("삼겹살 넣은 '순두부찌개' 어때요?", ref, idx) is False  # 없는 재료
