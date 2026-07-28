"""BedrockGenerator — 공통 안전망(RefineGenerator)이 Bedrock 경로에서도 동작하는지.

실제 AWS를 호출하지 않는다. `_refine`만 대체해 파이프라인 계약을 검증한다:
거절 skip · recommend-only skip · 캐시 · 근거대조 fallback · 예외 fallback.
"""
import pytest

from app.models import BasisTag, ExtractedQuery
from app.pipeline.context import AssembledContext
from app.pipeline.generator.base import GeneratedAnswer
from app.pipeline.generator.refine_base import RefineGenerator


class _Fake(RefineGenerator):
    """_refine만 가짜로 채운 백엔드 — 공통 골격을 그대로 태운다."""

    def __init__(self, reply="", raises=None, **kw):
        super().__init__(**kw)
        self.reply, self.raises, self.calls = reply, raises, 0

    _model_tag = "fake-model"

    @property
    def _timeout_s(self) -> float:
        return 3.0

    async def _refine(self, question, grounded_text):
        self.calls += 1
        if self.raises:
            raise self.raises
        return self.reply


def _q(text="두부로 뭐 해먹지"):
    return ExtractedQuery(raw_text=text)


def _stub_template(gen, text, basis):
    async def _gen(question, ctx):
        return GeneratedAnswer(text=text, basis=basis)
    gen._template.generate = _gen


REC = [BasisTag(type="recipe_match", detail="순두부찌개")]
CTX = AssembledContext(item_ids=[])


@pytest.mark.asyncio
async def test_skips_llm_when_template_refuses():
    """거절(basis 없음)이면 LLM을 호출하지 않는다 — 비용 0·거절 게이트 보존."""
    g = _Fake(reply="아무말")
    _stub_template(g, "모르겠어요 — 관련 정보를 찾지 못했습니다.", [])
    out = await g.generate(_q(), CTX)
    assert g.calls == 0
    assert out.text.startswith("모르겠어요")


@pytest.mark.asyncio
async def test_skips_llm_for_non_recipe_basis():
    """recommend-only — 가격·영양 근거는 template 그대로 나간다."""
    g = _Fake(reply="다듬은 문장")
    _stub_template(g, "돼지고기 가격은?\n· 컬리마켓 기준 12,900원", [BasisTag(type="price_snapshot", item_id=4)])
    out = await g.generate(_q("돼지고기 가격"), CTX)
    assert g.calls == 0
    assert "12,900원" in out.text


@pytest.mark.asyncio
async def test_returns_polished_when_grounded():
    """근거 안에서만 재작성했으면 다듬은 문장을 쓴다."""
    g = _Fake(reply="'순두부찌개' 어때요? 자세한 재료는 앱에서 확인해 보세요!")
    _stub_template(g, "'순두부찌개' 같은 요리는 어때요?", REC)
    out = await g.generate(_q(), CTX)
    assert g.calls == 1
    assert out.text.startswith("'순두부찌개' 어때요?")
    assert out.basis == REC          # basis는 template 것을 유지


@pytest.mark.asyncio
async def test_falls_back_when_hallucinated():
    """근거에 없는 금액을 지어내면 template 출력으로 되돌린다."""
    g = _Fake(reply="'순두부찌개'는 9,900원이에요!")
    _stub_template(g, "'순두부찌개' 같은 요리는 어때요?", REC)
    out = await g.generate(_q(), CTX)
    assert out.text == "'순두부찌개' 같은 요리는 어때요?"


@pytest.mark.asyncio
async def test_question_echo_is_allowed():
    """유저가 말한 재료를 되풀이하는 것은 환각이 아니다(오탐 방지)."""
    g = _Fake(reply="두부로 '순두부찌개' 어때요?", ingredient_index={"두부": 1})
    _stub_template(g, "'순두부찌개' 같은 요리는 어때요?", REC)
    out = await g.generate(_q("두부로 뭐 해먹지"), CTX)
    assert out.text == "두부로 '순두부찌개' 어때요?"


@pytest.mark.asyncio
async def test_falls_back_on_api_error():
    """API 오류·타임아웃은 요청 실패가 아니라 template fallback."""
    g = _Fake(raises=RuntimeError("boom"))
    _stub_template(g, "'순두부찌개' 같은 요리는 어때요?", REC)
    out = await g.generate(_q(), CTX)
    assert out.text == "'순두부찌개' 같은 요리는 어때요?"


@pytest.mark.asyncio
async def test_cache_hit_skips_llm():
    """동일 근거는 캐시로 재사용 — 재호출 0원."""
    store = {}

    class _Redis:
        async def get(self, k): return store.get(k)
        async def set(self, k, v, ex=None): store[k] = v

    g1 = _Fake(reply="'순두부찌개' 어때요!", redis_client=_Redis())
    _stub_template(g1, "'순두부찌개' 같은 요리는 어때요?", REC)
    await g1.generate(_q(), CTX)
    assert g1.calls == 1 and store

    g2 = _Fake(reply="다른 문장", redis_client=_Redis())
    _stub_template(g2, "'순두부찌개' 같은 요리는 어때요?", REC)
    out = await g2.generate(_q(), CTX)
    assert g2.calls == 0                      # 캐시 히트 → 호출 없음
    assert out.text == "'순두부찌개' 어때요!"


def test_cache_key_is_model_scoped():
    """모델이 다르면 출력도 다르므로 캐시 네임스페이스가 분리돼야 한다."""
    a, b = _Fake(), _Fake()
    b._model_tag = "other-model"
    assert a._cache_key("같은 근거") != b._cache_key("같은 근거")


def test_factory_supports_bedrock_backend():
    """팩토리가 bedrock 분기를 갖는다(미지원 예외로 떨어지지 않음)."""
    import inspect

    from app.pipeline.generator import factory

    src = inspect.getsource(factory.get_generator)
    assert '"bedrock"' in src or "'bedrock'" in src
