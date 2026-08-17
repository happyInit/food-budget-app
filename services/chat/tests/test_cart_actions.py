"""장바구니 액션 — 개수 상한과 라벨 (2026-08-16 실사용 보고).

🔴 **사고**: 김치찌개 재료비를 물었더니 «장바구니 담기» 버튼이 **11개** 줄줄이 났다.
   원인은 `main.py` 의 `recipe_cost` 경로가 **레시피 재료 전체를 `item_ids` 에 주입**하는데
   (`query.item_ids = ids`), `build_response` 가 그 하나하나에 **똑같은 라벨**의 버튼을 붙였기 때문.
   유저는 어느 것을 담는지 알 수 없고 화면은 버튼으로 뒤덮인다.

🔵 액션 스키마(`action`·`item_id`)는 그대로다 — 프론트는 받은 대로 그리므로 수정이 필요 없다.
   바뀌는 것은 **라벨과 개수**뿐이다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import BasisTag, ExtractedQuery                # noqa: E402
from app.pipeline.context import AssembledContext              # noqa: E402
from app.pipeline.generator.base import GeneratedAnswer        # noqa: E402
from app.pipeline.respond import _CART_BUTTON_MAX, build_response  # noqa: E402


def _ctx(n: int, named: bool = True):
    ids = list(range(101, 101 + n))
    prices = {i: [{"item_id": i, "name": f"품목{i}" if named else None, "price": 3000}]
              for i in ids}
    return AssembledContext(item_ids=ids, prices=prices), ids


def _answer():
    return GeneratedAnswer(text="재료비는 약 12,000원이에요.",
                           basis=[BasisTag(type="price_snapshot", ref="…")])


def _build(n: int, named: bool = True):
    ctx, ids = _ctx(n, named)
    q = ExtractedQuery(raw_text="김치찌개 재료비 얼마야", item_ids=ids, intent="recipe_cost")
    return build_response(_answer(), ctx, q).actions


def _cart(actions):
    return [a for a in actions if a.action == "add_to_cart"]


def test_재료가_많아도_버튼이_쏟아지지_않는다():
    """🔴 이 상한이 없으면 김치찌개 한 번에 11개가 난다 — 실제로 그랬다."""
    cart = _cart(_build(11))
    assert len(cart) == _CART_BUTTON_MAX == 3


def test_잘렸으면_남은_수를_밝히고_길을_준다():
    """조용히 자르면 «왜 일부만 나오지» 가 된다."""
    actions = _build(11)
    nav = [a for a in actions if a.action == "navigate"]
    assert len(nav) == 1
    assert "11" in nav[0].label, "남은 총 개수를 라벨에 밝혀야 한다"
    assert nav[0].route == "/cart"


def test_상한_이하면_전체보기_버튼이_없다():
    """3개 이하는 다 보여주므로 «전체 담기» 가 붙으면 군더더기다."""
    actions = _build(2)
    assert len(_cart(actions)) == 2
    assert not [a for a in actions if a.action == "navigate"]


def test_라벨에_품목명이_들어간다():
    """🔴 라벨이 전부 같으면 유저가 무엇을 담는지 모른다 — 그게 이 사고의 본질이었다."""
    cart = _cart(_build(3))
    labels = [a.label for a in cart]
    assert len(set(labels)) == 3, f"라벨이 겹친다: {labels}"
    assert all("담기" in x for x in labels)
    assert any("품목101" in x for x in labels)


def test_이름이_없으면_기본_라벨로_떨어진다():
    """가격행에 이름이 비어도 버튼은 나와야 한다(폴백)."""
    cart = _cart(_build(2, named=False))
    assert len(cart) == 2
    assert all(a.label == "장바구니 담기" for a in cart)


def test_가격이_없는_품목은_버튼을_안_만든다():
    """담을 수 없는 것에 버튼을 주면 눌렀을 때 아무 일도 안 난다 — 종전 동작 유지."""
    ctx = AssembledContext(item_ids=[1, 2, 3], prices={2: [{"item_id": 2, "name": "두부"}]})
    q = ExtractedQuery(raw_text="재료비", item_ids=[1, 2, 3], intent="recipe_cost")
    cart = _cart(build_response(_answer(), ctx, q).actions)
    assert len(cart) == 1 and cart[0].item_id == 2


def test_액션_스키마는_그대로다():
    """🔵 프론트는 `action`·`item_id` 로 동작한다 — 라벨만 바뀌어야 한다."""
    for a in _cart(_build(3)):
        assert a.action == "add_to_cart"
        assert isinstance(a.item_id, int)
