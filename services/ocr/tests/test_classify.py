"""분류 캐스케이드 단위테스트 (§7.2·§7.3) — DB·파일·네트워크 없이 순수 로직 검증.

Classifier 는 __new__ 로 만들어 참조데이터를 in-memory 픽스처로 주입 → 결정적.
캐스케이드 순서(조정 → 경계 → is_food → 비식품KW → gazetteer → 미해결)와
식비 포함(in_expense)·HITL(needs_review) 플래그를 케이스별로 고정한다.
"""
from types import SimpleNamespace

from app.pipeline.classify import (
    ADJUSTMENT, INGREDIENT, NONFOOD,
    Classifier, _make_matcher, _strip_measure, realign_prices,
)


def _clf(gaz=None, shelf=None, edge=None, meat=frozenset()):
    """I/O 없는 Classifier — __init__(DB/파일 로드) 우회, 픽스처만 주입."""
    c = Classifier.__new__(Classifier)
    c._gaz = gaz or {}
    c._match = _make_matcher(c._gaz, meat)
    c._shelf = shelf or {}
    c._edge = edge or {}
    c.gaz_source = "test"
    return c


# ── 용량·단위 접미 제거 (§7.5) ──
def test_strip_measure():
    assert _strip_measure("돈생삼겹살500g") == "돈생삼겹살"
    assert _strip_measure("계란30구") == "계란"
    assert _strip_measure("우유1L") == "우유"
    assert _strip_measure("500g") == "500g"        # 순수 용량만이면 원문 보존(빈문자 방지)
    assert _strip_measure("오이") == "오이"


# ── gazetteer 매칭 4단(exact→suffix→token→prefix) ──
def test_matcher_exact_suffix_token_prefix():
    m = _make_matcher({"오이": (1, "오이"), "삼겹살": (2, "삼겹살")})
    assert m("오이") == (1, "오이", "exact")
    assert m("백다다기오이")[2] == "suffix" and m("백다다기오이")[1] == "오이"
    assert m("돈생삼겹살500g")[1] == "삼겹살"          # 용량제거 후 접미
    assert m("없는품목zzz") == (None, None, "")


def test_matcher_species_guard_remap():
    # '불고기'(canon=소고기, 육류) 앞에 '돼지' 종수식어 → 소고기 오매칭 방지, 돼지고기로 remap
    gaz = {"불고기": (1, "소고기"), "돼지고기": (2, "돼지고기"), "소고기": (3, "소고기")}
    m = _make_matcher(gaz, meat_canons=frozenset({"소고기", "돼지고기"}))
    iid, canon, method = m("돼지불고기")
    assert method == "guard-remap" and canon == "돼지고기" and iid == 2


def test_matcher_species_exclude_no_false_guard():
    # '양파'의 '양'을 종수식어(양고기)로 오인하면 안 됨 → 정상 매칭
    m = _make_matcher({"양파": (7, "양파")}, meat_canons=frozenset({"소고기"}))
    assert m("양파")[1] == "양파"


# ── 조정(할인·쿠폰·음수라인) — 식비 차감 안 함, 오정렬은 HITL ──
def test_classify_adjustment_negative_and_coupon():
    c = _clf()
    r = c.classify("할인쿠폰", price=-500)             # 음수 + 조정어 → 정상 조정
    assert r.category == ADJUSTMENT and r.in_expense is False and r.needs_review is False
    r2 = c.classify("3천원할인", price=3000)           # 조정어인데 양수 → 오정렬 의심(HITL)
    assert r2.category == ADJUSTMENT and r2.needs_review is True
    r3 = c.classify("스낵랩", price=-1200)             # 음수인데 조정어 아님 → 오정렬 의심(HITL)
    assert r3.category == ADJUSTMENT and r3.needs_review is True


# ── 비식품(is_food=false / 규칙셋) — 식비 제외 ──
def test_classify_nonfood():
    c = _clf()
    assert c.classify("주방세제").category == NONFOOD           # 규칙셋 키워드
    assert c.classify("주방세제").in_expense is False
    assert c.classify("무엇이든", is_food=False).category == NONFOOD
    assert c.classify("무엇이든", is_food=False).in_expense is False


# ── 경계정책표 우선 ──
def test_classify_edge_policy_wins():
    c = _clf(edge={"생수": (INGREDIENT, True)})
    r = c.classify("생수")
    assert r.category == INGREDIENT and r.in_expense is True and r.tier == "edge"


# ── gazetteer 식재료 — exact=신뢰, 그 외=HITL ──
def test_classify_ingredient_exact_vs_fuzzy():
    c = _clf(gaz={"오이": (1, "오이")})
    exact = c.classify("오이")
    assert exact.category == INGREDIENT and exact.in_expense is True
    assert exact.needs_review is False and exact.item_id == 1
    fuzzy = c.classify("백다다기오이")                  # 접미 매칭 → 저신뢰(HITL)
    assert fuzzy.category == INGREDIENT and fuzzy.needs_review is True


# ── 미해결 — 식비 포함 + HITL(§7.3.4) ──
def test_classify_unresolved():
    c = _clf(gaz={"오이": (1, "오이")})
    r = c.classify("zzzqq999")
    assert r.category is None and r.in_expense is True
    assert r.needs_review is True and r.tier == "unresolved"


# ── 보관법 규칙(§7.4) — 냉동/실온/냉장 키워드 ──
def test_storage_keyword_rules():
    c = _clf()                                          # shelf 비움 → 키워드만
    assert c._storage_for("냉동새우") == "FREEZER"
    assert c._storage_for("컵라면") == "ROOM"
    assert c._storage_for("우유") == "FRIDGE"
    assert c._storage_for("정체불명") == "FRIDGE"        # 기본 냉장(안전측)


# ── 가격-품목 오정렬 보수 교정(§7.3.5·§7.6) ──
def _item(name, price):
    return SimpleNamespace(name=name, price=price)


def test_realign_prices_single_pair_swaps():
    items = [_item("쿠폰", 3000), _item("스낵랩", -3000)]   # 조정-양수 1 ∧ 품목-음수 1
    assert realign_prices(items) is True
    assert items[0].price == -3000 and items[1].price == 3000   # 스왑(합계 보존)


def test_realign_prices_ambiguous_noop():
    items = [_item("스낵랩", -3000), _item("감자", -1000)]   # 음수 2개 → 애매 → 손대지 않음
    assert realign_prices(items) is False
    assert items[0].price == -3000 and items[1].price == -1000
