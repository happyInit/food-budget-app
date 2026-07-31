"""영상 레시피 재료비 산출(#11) — DB 없이 계약 검증.

이 값은 유저가 "이 영상 따라할까"를 판단하는 근거다. 틀린 총액은 잘못된 판단을 만들므로
**모르면 비우고 드러낸다**는 규칙(`servings_known` 과 동일 원칙)을 코드 밖에 고정한다.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("VIDEO_GEMINI_API_KEY", "test-key")

from app.cost import _is_staple, estimate  # noqa: E402
from app.models import CostEstimate, VideoStatusResponse  # noqa: E402


class _FakeCur:
    """density / unit_weight / 단가 3쿼리에 순서대로 답한다(cost.estimate의 호출 순서)."""

    def __init__(self, unit_rows):
        self._rows, self._n = [[], [], unit_rows], -1

    def execute(self, sql, params):
        self._n += 1

    def fetchall(self):
        return self._rows[self._n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch_pg(monkeypatch, unit_rows):
    import app.cost as c

    monkeypatch.setattr(c.psycopg, "connect", lambda *a, **k: _FakeConn(_FakeCur(unit_rows)))


def test_cost_uses_weight_and_unit_price(monkeypatch):
    """200g × 1,000원/100g = 2,000원. 팩값(9,900)보다 싸므로 상한에 걸리지 않는다."""
    _patch_pg(monkeypatch, [(7, 1000.0, 9900.0, "삼겹살")])
    out = estimate([{"name": "삼겹살", "quantity": "200g", "item_id": 7}])
    assert out["total_krw"] == 2000
    assert out["priced_count"] == 1 and out["total_count"] == 1
    assert out["lines"][0]["matched_name"] == "삼겹살"


def test_pack_price_caps_the_line(monkeypatch):
    """1kg 쓰더라도 지출은 한 팩 값을 넘지 않는다 — 챗 정본과 동일한 1팩 상한."""
    _patch_pg(monkeypatch, [(7, 1000.0, 9900.0, "삼겹살")])
    out = estimate([{"name": "삼겹살", "quantity": "1kg", "item_id": 7}])
    assert out["total_krw"] == 9900          # 10,000 이 아니라 팩값


def test_vague_quantity_is_flagged_not_guessed(monkeypatch):
    """'적당량'은 추정하지 않는다 — 지어낸 용량은 총액을 그대로 왜곡한다."""
    _patch_pg(monkeypatch, [(7, 1000.0, None, "삼겹살")])
    out = estimate([{"name": "삼겹살", "quantity": "적당량", "item_id": 7}])
    assert out["total_krw"] is None and out["priced_count"] == 0
    assert out["lines"][0]["krw"] is None
    assert "모호" in out["lines"][0]["reason"]


def test_unpriced_item_is_reported(monkeypatch):
    """가격 미수집 품목은 조용히 0원 처리하지 않고 사유를 남긴다."""
    _patch_pg(monkeypatch, [])               # 단가 행 없음
    out = estimate([{"name": "두릅", "quantity": "100g", "item_id": 99}])
    assert out["total_krw"] is None
    assert out["lines"][0]["reason"] == "가격 미수집"


def test_partial_pricing_is_underestimate_and_countable(monkeypatch):
    """일부만 산출되면 총액은 과소추정 — priced/total 로 UI가 그 사실을 말할 수 있어야 한다."""
    _patch_pg(monkeypatch, [(7, 1000.0, None, "삼겹살")])
    out = estimate([
        {"name": "삼겹살", "quantity": "100g", "item_id": 7},
        {"name": "두릅", "quantity": "적당량", "item_id": 7},
    ])
    assert out["total_krw"] == 1000
    assert out["priced_count"] == 1 and out["total_count"] == 2


def test_staples_and_water_are_excluded_not_failed(monkeypatch):
    """소금·물은 '산출 실패'가 아니라 '제외' — 실패 카운트를 오염시키면 안 된다."""
    _patch_pg(monkeypatch, [(7, 1000.0, None, "삼겹살")])
    out = estimate([
        {"name": "삼겹살", "quantity": "100g", "item_id": 7},
        {"name": "소금", "quantity": "약간", "item_id": 3},
        {"name": "물", "quantity": "2컵", "item_id": 4},
    ])
    assert out["excluded_count"] == 2
    assert out["priced_count"] == 1
    assert len(out["lines"]) == 1            # 제외분은 내역에 실패로 남지 않는다


def test_per_serving_needs_known_servings(monkeypatch):
    """인분을 모르면 1인분 단가를 내지 않는다 — 실측상 인분 미상 영상이 흔하다."""
    _patch_pg(monkeypatch, [(7, 1000.0, None, "삼겹살")])
    ing = [{"name": "삼겹살", "quantity": "200g", "item_id": 7}]
    assert estimate(ing, servings=None)["per_serving_krw"] is None
    _patch_pg(monkeypatch, [(7, 1000.0, None, "삼겹살")])
    assert estimate(ing, servings=2)["per_serving_krw"] == 1000


def test_no_item_id_yields_empty_estimate(monkeypatch):
    """정규화 실패(item_id 없음)면 가격을 붙일 대상이 없다 — DB를 건드리지도 않는다."""
    out = estimate([{"name": "알수없는재료", "quantity": "100g", "item_id": None}])
    assert out["total_krw"] is None and out["lines"] == []


def test_staple_list_matches_chat():
    """상비 목록이 챗과 갈리면 '챗 재료비 != 영상 재료비' 불일치가 난다."""
    for name in ("소금", "후추", "간장", "다진 마늘", "물", "김치"):
        assert _is_staple(name), name
    assert not _is_staple("삼겹살")


def test_status_response_carries_cost():
    """잡 결과 스키마에 cost가 실려야 프론트가 4단계(가격 산출)를 보여줄 수 있다."""
    r = VideoStatusResponse(status="DONE", cost=CostEstimate(
        total_krw=5200, per_serving_krw=2600, priced_count=4, total_count=6, excluded_count=1))
    assert r.cost.total_krw == 5200 and r.cost.per_serving_krw == 2600


def test_cost_is_optional():
    """가격 산출이 실패해도 추출 결과 자체는 유효하다."""
    assert VideoStatusResponse(status="DONE").cost is None


def test_staple_detected_by_canonical_not_raw_name(monkeypatch):
    """실측 회귀(2026-07-29): 원문 '신 김치'는 상비 목록에 없지만 표준명은 '김치'다.

    원문으로만 판정하면 김치찌개의 김치가 8,700원으로 잡혀 총액의 84%를 오염시켰다.
    챗은 표준명(names_map)으로 판정하므로, 여기서도 표준명이 기준이어야 금액이 일치한다.
    """
    _patch_pg(monkeypatch, [(11, 1450.0, 8700.0, "김치"), (7, 495.0, None, "돼지고기")])
    out = estimate([
        {"name": "신 김치", "quantity": "600g", "item_id": 11},
        {"name": "돼지고기(목살)", "quantity": "200g", "item_id": 7},
    ])
    assert out["total_krw"] == 990           # 돼지고기만 — 김치는 상비로 제외
    assert out["excluded_count"] == 1
    assert all(ln["name"] != "신 김치" for ln in out["lines"])


def test_unmatched_ingredient_is_listed_not_dropped(monkeypatch):
    """정규화 실패 재료가 조용히 사라지면 총액이 왜 낮은지 알 수 없다."""
    _patch_pg(monkeypatch, [(7, 495.0, None, "돼지고기")])
    out = estimate([
        {"name": "돼지고기", "quantity": "200g", "item_id": 7},
        {"name": "특수재료", "quantity": "100g", "item_id": None},
    ])
    assert out["priced_count"] == 1 and out["total_count"] == 2
    fail = [ln for ln in out["lines"] if ln["item_id"] is None]
    assert len(fail) == 1 and fail[0]["reason"] == "품목 매칭 실패"
