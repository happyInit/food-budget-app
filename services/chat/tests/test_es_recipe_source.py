"""`EsRecipeSource` 의 ES DSL 검증 — 인덱스 이름과 servable 필터.

**왜 이 테스트가 필요한가.** 이 두 가지는 **틀려도 예외가 안 난다** — 조용히 잘못된 결과를 준다.

- 인덱스 이름이 틀리면 `NotFoundError` 로 소스만 죽고 챗봇은 *"근거 없음"* 으로 답한다.
  실제로 그렇게 됐다(2026-08-14 라이브: `index="recipes"` 하드코딩 · 실물은 `recipes_live`).
- `servable` 필터가 빠지면 **학습 코퍼스가 추천에 섞인다.** 예외는 안 나고 결과만 오염된다
  (#560 실측: `recipes_live` 9,280건 중 servable=false 3,173건 = 식약처·농식품·재료 미매칭).

형제 서비스의 `services/recipe/tests/test_search.py` · `recipebook/tests/test_shared_es.py` 와
같은 방식이다 — fake ES 가 받은 kwargs 를 그대로 들여다본다.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings                       # noqa: E402
from app.models import ExtractedQuery                 # noqa: E402
from app.pipeline.search import EsRecipeSource        # noqa: E402


class FakeEs:
    """`search()` 가 받은 인자를 그대로 보관한다. 실패 주입도 된다."""

    def __init__(self, hits=None, raise_exc=None):
        self._hits = hits or []
        self._raise = raise_exc
        self.last_kwargs = None

    async def search(self, **kwargs):
        self.last_kwargs = kwargs
        if self._raise:
            raise self._raise
        return {"hits": {"hits": [{"_source": h} for h in self._hits]}}


def _run(es, text="김치찌개 만들래", item_ids=None):
    q = ExtractedQuery(raw_text=text, item_ids=item_ids or [])
    return asyncio.run(EsRecipeSource(es).search(q))


# ── 인덱스 이름 ─────────────────────────────────────────────────────────────
def test_인덱스는_설정값을_쓴다():
    """하드코딩이면 사이트마다 다른 인덱스명을 못 따라간다 — 그게 라이브 장애의 원인이었다."""
    es = FakeEs()
    _run(es)
    assert es.last_kwargs["index"] == settings.es_index


def test_기본_인덱스는_CDC_인덱스다():
    """배치 인덱서가 만드는 `recipes` 는 수동 갱신·단일 카피라 재파생 사이트에는 없다."""
    assert settings.es_index == "recipes_live"


# ── servable 필터 ───────────────────────────────────────────────────────────
def test_재료없는_질의에도_servable_필터가_붙는다():
    es = FakeEs()
    _run(es)
    filters = es.last_kwargs["query"]["bool"]["filter"]
    assert {"term": {"servable": True}} in filters


def test_재료있는_질의에도_servable_필터가_남는다():
    """item_ids 분기에서 필터를 덮어쓰면 코퍼스가 새어 나온다 — 그 회귀를 막는다."""
    es = FakeEs()
    _run(es, item_ids=[11, 22])
    filters = es.last_kwargs["query"]["bool"]["filter"]
    assert {"term": {"servable": True}} in filters
    assert {"terms": {"ingredient_item_ids": ["11", "22"]}} in filters


def test_텍스트는_should_로만_들어간다():
    """텍스트를 filter 로 올리면 재료 한정이 풀린다(멀티턴 품질 회귀)."""
    es = FakeEs()
    _run(es, item_ids=[7])
    assert "multi_match" in es.last_kwargs["query"]["bool"]["should"][0]


# ── 실패 경로 ───────────────────────────────────────────────────────────────
def test_실패하면_예외종류를_담고_available_False():
    """로그에 실을 수 있는 것은 종류뿐이다 — 원문(reason)에는 사용자 챗 원문이 섞인다."""
    es = FakeEs(raise_exc=KeyError("index_not_found_exception"))
    r = _run(es)
    assert r.available is False
    assert r.error_type == "KeyError"
    assert r.source == "recipe"


def test_성공하면_레시피를_돌려준다():
    es = FakeEs(hits=[{"recipe_id": 1, "name": "김치찌개"}])
    r = _run(es)
    assert r.available is True
    assert r.data["recipes"][0]["name"] == "김치찌개"
