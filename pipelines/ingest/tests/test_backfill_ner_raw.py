"""RAW 재료 덩어리 구조화 — CRF·DB 없이 계약 검증.

이 배치는 **운영 데이터를 늘린다**. 잘못 쪼개면 레시피에 없는 재료가 생기고, 분량을 잘못
집으면 재료비가 그대로 틀어진다. 그래서 쪼개기·분량·매칭 규칙을 코드 밖에 고정한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backfill_ner_raw_ingredients import _quantity_between, structure  # noqa: E402


class _FakeExtractor:
    """CRF 대체 — 미리 정한 스팬을 돌려준다(피처·모델과 무관하게 계약만 검증)."""

    def __init__(self, spans):
        self._spans = spans

    async def extract_spans(self, text):
        return self._spans


def _resolve_all(name):
    return {"소고기": 7, "김": 11, "튀김가루": None}.get(name)


# ── 분량 집기 ────────────────────────────────────────────────────────────────
def test_quantity_taken_from_gap_after_span():
    """'소고기(치맛살)(100g), ' 처럼 스팬 뒤 구간에서 분량을 집는다."""
    raw = "소고기(100g), 김(6g)"
    assert _quantity_between(raw, len("소고기"), raw.find("김")) == "100g"


def test_quantity_none_when_no_digits():
    """숫자가 없으면 분량이 아니다 — 다음 재료의 수식어·섹션 헤더를 분량으로 오인하지 않는다."""
    assert _quantity_between("양파 다진것 마늘", 2, 7) is None


def test_quantity_strips_separators():
    """구분자(쉼표·괄호·불릿)는 분량이 아니다."""
    raw = "양파(10g), 마늘"
    assert _quantity_between(raw, 2, raw.find("마늘")) == "10g"


# ── 구조화 계약 ──────────────────────────────────────────────────────────────
def test_structure_splits_blob_into_rows():
    raw = "[주재료] 소고기(100g), 김(6g), 튀김가루(20g)"
    got = structure(raw, _FakeExtractor(["소고기", "김", "튀김가루"]), _resolve_all)

    assert [x["name"] for x in got] == ["소고기", "김", "튀김가루"]
    assert got[0]["quantity"] == "100g" and got[0]["item_id"] == 7
    assert got[2]["item_id"] is None          # 매칭 실패도 행은 남는다(원문 보존)


def test_structure_survives_span_not_found_in_text():
    """정규화 차이로 스팬이 원문에 없어도 죽지 않는다 — 분량만 비운다."""
    got = structure("양파 10g", _FakeExtractor(["없는재료"]), lambda n: None)
    assert len(got) == 1 and got[0]["quantity"] is None


def test_structure_empty_spans_yields_nothing():
    """추출 0건이면 아무 행도 만들지 않는다 — 빈 행으로 오염시키지 않는다."""
    assert structure("잡담", _FakeExtractor([]), lambda n: None) == []


def test_repeated_ingredient_names_do_not_collide():
    """같은 이름이 두 번 나오면 각각 자기 뒤 분량을 집어야 한다(커서 전진)."""
    raw = "설탕 10g, 소금 2g, 설탕 5g"
    got = structure(raw, _FakeExtractor(["설탕", "소금", "설탕"]), lambda n: None)
    assert [x["quantity"] for x in got] == ["10g", "2g", "5g"]
