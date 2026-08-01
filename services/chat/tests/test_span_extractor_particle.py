"""rule 스팬 추출 — 조사 낀 접미 오탐 회귀 (실측 2026-07-29).

**무엇이 문제였나.** "양파로 볶음밥"에서 후보 `양파로` 가 접미매칭으로 item 2572 **'파로'**
(곡물 farro)에 걸렸다. 유저가 말한 적 없는 재료가 추출돼 추천 입력을 오염시킨다.

조사는 명사에 붙는다 — 조사째 **다른 품목**에 걸리는 것은 우연이므로, 조사를 뗀 쪽이 진짜다.
정상 접미매칭("국물용멸치"→멸치)은 품목이 같으므로 영향받지 않는다.
"""
import asyncio

from app.pipeline.span_extractor.rule_based import RuleBasedSpanExtractor

# (표면형) → (item_id, canonical, method) — gazetteer matcher 대역.
_TABLE = {
    "양파": (29, "양파", "exact"),
    "양파로": (2572, "파로", "suffix"),        # ← 오탐의 정체
    "대파": (9, "대파", "exact"),
    "대파로": (2572, "파로", "suffix"),
    "파로": (2572, "파로", "exact"),
    "멸치": (441, "멸치", "exact"),
    "국물용멸치": (441, "멸치", "suffix"),      # 정상 접미 — 품목이 같다
    "돼지고기": (10, "돼지고기", "exact"),
}


def _matcher(name):
    return _TABLE.get(name, (None, None, None))


def _spans(text):
    ex = RuleBasedSpanExtractor(_matcher, set())
    return sorted({_TABLE[s][1] for s in asyncio.run(ex.extract_spans(text))})


def test_particle_suffix_false_positive_dropped():
    """'양파로' 가 '파로'(곡물)로 잡히면 안 된다 — 조사를 뗀 '양파' 가 진짜다."""
    assert _spans("양파로 볶음밥") == ["양파"]


def test_multiple_ingredients_with_particles():
    assert _spans("돼지고기랑 양파로 뭐 해먹지") == ["돼지고기", "양파"]


def test_legit_suffix_match_preserved():
    """정상 접미매칭은 품목이 같으므로 살아남아야 한다 — 필터가 과잉 작동하면 안 된다."""
    assert _spans("국물용멸치 있어") == ["멸치"]


def test_genuine_mention_of_the_confusable_item_kept():
    """유저가 진짜 '파로'를 말하면(exact) 지우지 않는다 — 필터는 접미매칭에만 적용된다."""
    assert "파로" in _spans("파로 사왔어")


def test_no_ingredient_yields_nothing():
    assert _spans("오늘 뭐 먹지") == []
