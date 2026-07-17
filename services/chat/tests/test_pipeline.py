"""파이프라인 단위 테스트 — 실 DB/ES 없이 픽스처만으로 검증(§6 로컬 e2e와 별개).

RuleBasedSpanExtractor의 자유문장 매칭 정확도는 여기 나온 몇 개 예시로는
충분히 검증되지 않는다 — 배포 전 README에 적어둔 수기 질문 샘플 20~30개로
반드시 추가 확인할 것.
"""
import pytest

from app.models import BasisTag, ExtractedQuery
from app.pipeline.context import assemble
from app.pipeline.extract import _classify_intent, _parse_budget, _parse_servings, extract
from app.pipeline.generator.template import TemplateGenerator
from app.pipeline.respond import build_response
from app.pipeline.search import SearchResult
from app.pipeline.span_extractor.rule_based import RuleBasedSpanExtractor, _candidates


def _fake_matcher(mapping: dict[str, int]):
    def matcher(name: str):
        nc = (name or "").replace(" ", "")
        if nc in mapping:
            return (mapping[nc], nc, "exact")
        return (None, None, None)

    return matcher


# ---- extract.py: 예산/인분/의도 (NER과 무관, span_extractor 교체와 상관없이 안정) ----


def test_parse_budget_manwon():
    assert _parse_budget("오늘 2만원으로 뭐 해먹지") == 20000


def test_parse_budget_won():
    assert _parse_budget("15000원 정도면 될까") == 15000


def test_parse_budget_none():
    assert _parse_budget("두부 얼마야") is None


def test_parse_servings():
    assert _parse_servings("2인분만 만들어줘") == 2


def test_classify_intent_price():
    assert _classify_intent("두부 얼마야") == "price_lookup"


def test_classify_intent_nutrition_wins_over_generic_price_word():
    # "얼마"도 있지만 "칼로리"가 더 구체적인 의도라 nutrition이 우선해야 함
    assert _classify_intent("닭가슴살 칼로리 얼마야") == "nutrition"


def test_classify_intent_recommend():
    assert _classify_intent("오늘 2만원으로 뭐 해먹지") == "recommend"


# ---- span_extractor/rule_based.py ----


def test_candidates_splits_on_conjunction():
    cands = _candidates("두부랑 대파로 뭐 해먹지")
    assert "두부" in cands


def test_candidates_strips_trailing_particle():
    # "대파로"는 원문 그대로는 조사가 붙어있어, 조사 제거판("대파")도 후보에 있어야 함
    cands = _candidates("두부랑 대파로 뭐 해먹지")
    assert "대파" in cands


@pytest.mark.asyncio
async def test_rule_based_extractor_finds_known_ingredients():
    matcher = _fake_matcher({"두부": 1, "대파": 2})
    extractor = RuleBasedSpanExtractor(matcher, stop=set())
    spans = await extractor.extract_spans("두부랑 대파로 뭐 해먹지")
    assert set(spans) == {"두부", "대파"}


@pytest.mark.asyncio
async def test_rule_based_extractor_skips_stop_words():
    matcher = _fake_matcher({"물": 99})
    extractor = RuleBasedSpanExtractor(matcher, stop={"물"})
    spans = await extractor.extract_spans("물 좀 주세요")
    assert "물" not in spans


# ---- extract() 조립 ----


@pytest.mark.asyncio
async def test_extract_end_to_end():
    matcher = _fake_matcher({"두부": 1, "대파": 2})
    extractor = RuleBasedSpanExtractor(matcher, stop=set())
    q = await extract("두부랑 대파로 2만원에 2인분 뭐 해먹지", matcher, extractor)
    assert set(q.item_ids) == {1, 2}
    assert q.budget_won == 20000
    assert q.servings == 2
    assert q.intent == "recommend"


# ---- 멀티턴 팔로우업 승계 (extract history 인자) ----


@pytest.mark.asyncio
async def test_multiturn_carries_prior_items_on_followup():
    """현재 턴에 품목이 없으면 직전 맥락 상속 — "그럼 가격은?"."""
    matcher = _fake_matcher({"삼겹살": 10})
    extractor = RuleBasedSpanExtractor(matcher, stop=set())
    history = [{"role": "user", "text": "삼겹살 추천", "item_ids": [10],
                "item_names": ["삼겹살"], "intent": "recommend"}]
    q = await extract("그럼 가격은?", matcher, extractor, history)
    assert q.item_ids == [10]
    assert q.intent == "price_lookup"        # 현재 턴 의도가 우선


@pytest.mark.asyncio
async def test_multiturn_none_history_does_not_carry():
    """history=None(멀티턴 OFF) → 상속 없음 = 기존 단일턴과 동일(무손상)."""
    matcher = _fake_matcher({"삼겹살": 10})
    extractor = RuleBasedSpanExtractor(matcher, stop=set())
    q = await extract("그럼 가격은?", matcher, extractor, None)
    assert q.item_ids == []
    assert q.intent == "price_lookup"


@pytest.mark.asyncio
async def test_multiturn_new_items_ignore_history():
    """현재 턴에 새 품목이 있으면 history 무시(새 주제)."""
    matcher = _fake_matcher({"삼겹살": 10, "두부": 1})
    extractor = RuleBasedSpanExtractor(matcher, stop=set())
    history = [{"role": "user", "text": "삼겹살", "item_ids": [10],
                "item_names": ["삼겹살"], "intent": "price_lookup"}]
    q = await extract("두부 추천해줘", matcher, extractor, history)
    assert q.item_ids == [1]
    assert q.intent == "recommend"


@pytest.mark.asyncio
async def test_multiturn_inherits_intent_when_unknown():
    """의도 미상 팔로우업("다른 거")은 직전 의도(추천) 유지."""
    matcher = _fake_matcher({"삼겹살": 10})
    extractor = RuleBasedSpanExtractor(matcher, stop=set())
    history = [{"role": "user", "text": "삼겹살 추천", "item_ids": [10],
                "item_names": ["삼겹살"], "intent": "recommend"}]
    q = await extract("다른 거 없어?", matcher, extractor, history)
    assert q.item_ids == [10]
    assert q.intent == "recommend"


# ---- context.py ----


def test_assemble_joins_by_item_id_and_flags_unavailable_sources():
    results = [
        SearchResult(source="recipe", available=True, data={"recipes": [{"recipe_id": 10, "name": "두부조림"}]}),
        SearchResult(
            source="price", available=True,
            data={"prices": [{"item_id": 1, "source": "oasis", "price": 1800.0, "crawled_at": "2026-07-13T00:00:00"}]},
        ),
        SearchResult(source="nutrition", available=True, data={"nutrition": []}),
        SearchResult(source="pantry_budget", available=False, reason="not_implemented_mvp"),
    ]
    ctx = assemble([1], results)
    assert ctx.recipes[0]["name"] == "두부조림"
    assert ctx.prices[1][0]["price"] == 1800.0
    assert ctx.unavailable_sources == ["pantry_budget"]


# ---- generator/template.py + respond.py ----


@pytest.mark.asyncio
async def test_template_generator_price_lookup():
    ctx = assemble(
        [1],
        [
            SearchResult(source="recipe", available=True, data={"recipes": []}),
            SearchResult(
                source="price", available=True,
                data={"prices": [{"item_id": 1, "source": "oasis", "price": 1800.0, "crawled_at": None}]},
            ),
            SearchResult(source="nutrition", available=True, data={"nutrition": []}),
            SearchResult(source="pantry_budget", available=False, reason="not_implemented_mvp"),
        ],
    )
    q = ExtractedQuery(raw_text="두부 얼마야", item_ids=[1], intent="price_lookup")
    answer = await TemplateGenerator().generate(q, ctx)
    assert "1,800" in answer.text
    assert answer.basis and answer.basis[0].type == "price_snapshot"


@pytest.mark.asyncio
async def test_template_generator_unanswered_when_nothing_found():
    ctx = assemble(
        [],
        [
            SearchResult(source="recipe", available=True, data={"recipes": []}),
            SearchResult(source="price", available=True, data={"prices": []}),
            SearchResult(source="nutrition", available=True, data={"nutrition": []}),
            SearchResult(source="pantry_budget", available=False, reason="not_implemented_mvp"),
        ],
    )
    # 내용어 0개(오프토픽 잔여) → 유튜브 폴백도 안 붙어 액션 완전 비어있음.
    q = ExtractedQuery(raw_text="그냥", item_ids=[], intent="unknown")
    answer = await TemplateGenerator().generate(q, ctx)
    response = build_response(answer, ctx, q)
    assert response.unanswered is True
    assert response.actions == []


def test_build_response_only_actions_verified_entities():
    ctx = assemble(
        [1],
        [
            SearchResult(source="recipe", available=True, data={"recipes": [{"recipe_id": 10, "name": "두부조림"}]}),
            SearchResult(
                source="price", available=True,
                data={"prices": [{"item_id": 1, "source": "oasis", "price": 1800.0, "crawled_at": None}]},
            ),
            SearchResult(source="nutrition", available=True, data={"nutrition": []}),
            SearchResult(source="pantry_budget", available=False, reason="not_implemented_mvp"),
        ],
    )
    answer_basis = [BasisTag(type="recipe_match", detail="두부조림")]
    from app.pipeline.generator.base import GeneratedAnswer

    q = ExtractedQuery(raw_text="두부조림", item_ids=[1], intent="recommend")
    response = build_response(GeneratedAnswer(text="두부조림 어때요", basis=answer_basis), ctx, q)
    actions = {(a.action, a.recipe_id, a.item_id) for a in response.actions}
    assert ("open_recipe", 10, None) in actions
    assert ("add_to_cart", None, 1) in actions
    assert all(a.action != "open_youtube" for a in response.actions)  # 근거 있으면 폴백 안 붙음


def _empty_ctx():
    """검색 0건 컨텍스트 — 유튜브 폴백 경로 테스트용."""
    return assemble([], [
        SearchResult(source="recipe", available=True, data={"recipes": []}),
        SearchResult(source="price", available=True, data={"prices": []}),
        SearchResult(source="nutrition", available=True, data={"nutrition": []}),
        SearchResult(source="pantry_budget", available=False, reason="not_implemented_mvp"),
    ])


def test_youtube_fallback_for_unknown_food():
    from app.pipeline.generator.base import GeneratedAnswer

    # DB에 없는 요리("쌀국수") 요청 → 유튜브 레시피 검색 링크 폴백. unanswered는 유지.
    q = ExtractedQuery(raw_text="쌀국수 만들어줘", item_ids=[], intent="recommend")
    resp = build_response(GeneratedAnswer(text="모르겠어요 — 관련 정보를 찾지 못했습니다."), _empty_ctx(), q)
    assert resp.unanswered is True
    yt = [a for a in resp.actions if a.action == "open_youtube"]
    assert len(yt) == 1
    assert yt[0].url and "youtube.com/results" in yt[0].url
    assert "쌀국수" in yt[0].label and "쌀국수" in resp.reply


def test_youtube_fallback_prefers_user_words_over_canonical():
    from app.pipeline.generator.base import GeneratedAnswer

    # gazetteer가 '쌀국수'를 '국수'로 매칭해도, 유튜브 검색어는 유저가 친 말('쌀국수')을 우선.
    q = ExtractedQuery(raw_text="쌀국수 만들어줘", item_ids=[9], item_names=["국수"], intent="recommend")
    resp = build_response(GeneratedAnswer(text="모르겠어요"), _empty_ctx(), q)
    yt = [a for a in resp.actions if a.action == "open_youtube"]
    assert len(yt) == 1 and "쌀국수" in yt[0].label
    # 무응답이면 근거 없는 레시피/장바구니 액션은 안 붙음 — 유튜브 폴백만.
    assert all(a.action == "open_youtube" for a in resp.actions)


def test_unanswered_suppresses_ungrounded_recipe_actions():
    from app.pipeline.generator.base import GeneratedAnswer

    # ES가 느슨히 매칭한 레시피가 ctx에 있어도, 무응답(근거0)이면 open_recipe 액션 안 붙음.
    ctx = assemble([], [
        SearchResult(source="recipe", available=True, data={"recipes": [{"recipe_id": 5, "name": "국수"}]}),
        SearchResult(source="price", available=True, data={"prices": []}),
        SearchResult(source="nutrition", available=True, data={"nutrition": []}),
        SearchResult(source="pantry_budget", available=False, reason="not_implemented_mvp"),
    ])
    q = ExtractedQuery(raw_text="쌀국수 만들어줘", item_ids=[], intent="recommend")
    resp = build_response(GeneratedAnswer(text="모르겠어요"), ctx, q)
    assert all(a.action != "open_recipe" for a in resp.actions)  # 근거 없는 레시피 버튼 억제
    assert any(a.action == "open_youtube" for a in resp.actions)  # 유튜브 폴백은 노출


def test_no_youtube_fallback_for_price_or_nutrition_intent():
    from app.pipeline.generator.base import GeneratedAnswer

    # 가격/영양 무응답엔 유튜브 레시피 링크가 무의미 → 안 붙임.
    for intent in ("price_lookup", "nutrition"):
        q = ExtractedQuery(raw_text="트러플오일 얼마야", item_ids=[], intent=intent)
        resp = build_response(GeneratedAnswer(text="모르겠어요"), _empty_ctx(), q)
        assert all(a.action != "open_youtube" for a in resp.actions)
