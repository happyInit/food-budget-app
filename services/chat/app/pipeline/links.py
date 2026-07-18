"""외부 링크 URL 구성 — 저장 URL 없이 **규칙으로 생성**(추가비용 0·외부 API 호출 없음).

- 만개(10K): recipe.src_recipe_id로 레시피 페이지 URL 구성(티어2).
- 유튜브: 요리명으로 '검색결과 페이지' URL 구성. 실제 검색 안 함 — 링크 문자열만.
"""
from __future__ import annotations

from urllib.parse import quote_plus

_MANKAE_RECIPE = "https://www.10000recipe.com/recipe/{sid}"
_YOUTUBE_SEARCH = "https://www.youtube.com/results?search_query={q}"


def mankae_url(src_recipe_id: str) -> str:
    """만개의레시피(source=10K) 레시피 페이지 URL 규칙. ⚠️ 패턴은 1회 실검증 필요."""
    return _MANKAE_RECIPE.format(sid=src_recipe_id)


def youtube_search_url(query: str) -> str:
    """유튜브 검색결과 페이지 URL(실검색 아님). '{요리} 레시피'로 검색어 구성."""
    return _YOUTUBE_SEARCH.format(q=quote_plus(f"{query} 레시피"))
