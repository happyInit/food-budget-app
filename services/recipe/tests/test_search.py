"""search_es 단위 테스트 (ES 불필요 — FakeEs 주입). 쿼리 구성·매핑·A05(값 바인딩) 검증.
CONVENTIONS: 네트워크/ES 없이 순수 로직 검증 → asyncio.run 으로 코루틴 실행(별도 async 플러그인 불요)."""
import asyncio

from app.queries import search_es


class FakeEs:
    """psycopg 아닌 ES 클라이언트의 최소 fake — search(**kwargs) 를 기록하고 canned 응답."""

    def __init__(self, hits=None, total=0):
        self._hits = hits or []
        self._total = total
        self.last_kwargs = None

    async def search(self, **kwargs):
        self.last_kwargs = kwargs
        return {"hits": {"total": {"value": self._total},
                         "hits": [{"_source": s} for s in self._hits]}}


def test_search_es_maps_hits_and_uses_cross_fields_and():
    es = FakeEs(
        hits=[{"recipe_id": 5, "name": "김치찌개", "source": "10K",
               "cooking_time": "30분 이내", "level_nm": "초급", "image_url": None}],
        total=1,
    )
    cards, total = asyncio.run(search_es(es, "김치", None, 1, 20))
    assert total == 1
    assert cards[0].id == 5 and cards[0].name == "김치찌개"
    assert cards[0].cooking_time == "30분 이내"
    # 검색어는 DSL 값으로만 전달(A05) + 정밀 매칭(cross_fields AND)
    mm = es.last_kwargs["query"]["bool"]["must"][0]["multi_match"]
    assert mm["query"] == "김치"
    assert mm["type"] == "cross_fields" and mm["operator"] == "and"
    assert mm["fields"] == ["name^3", "ingredient_names"]


def test_search_es_no_query_uses_match_all_and_id_sort():
    es = FakeEs(hits=[], total=0)
    asyncio.run(search_es(es, None, None, 2, 10))
    bool_q = es.last_kwargs["query"]["bool"]
    assert bool_q["must"] == [{"match_all": {}}]
    assert es.last_kwargs["from_"] == 10 and es.last_kwargs["size"] == 10   # page 2 오프셋
    assert es.last_kwargs["sort"] == [{"recipe_id": "asc"}]                 # 브라우징 id순


def test_search_es_applies_tag_cooking_time_level_filters():
    es = FakeEs(hits=[], total=0)
    asyncio.run(search_es(es, "김치", "밑반찬", 1, 20, cooking_time="15분 이내", level="아무나"))
    filters = es.last_kwargs["query"]["bool"]["filter"]
    assert {"term": {"category": "밑반찬"}} in filters
    assert {"term": {"cooking_time": "15분 이내"}} in filters
    assert {"term": {"level_nm": "아무나"}} in filters
