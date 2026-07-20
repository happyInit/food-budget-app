"""video-recipe 파이프라인·검증 테스트 — mock 추출기로 Gemini 없이 검증."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import Ingredient, RecipeExtraction, Step  # noqa: E402
from pipeline import extract_recipe, normalize_url  # noqa: E402
from validate import hard_failures, soft_flags  # noqa: E402


def _good(url="", **kw):
    d = dict(title="김치볶음밥", is_recipe=True,
             ingredients=[Ingredient(name="김치"), Ingredient(name="밥")],
             steps=[Step(order=1, text="볶기", timestamp_sec=10), Step(order=2, text="넣기", timestamp_sec=40)],
             source_url=url, video_seconds=300)
    d.update(kw)
    return RecipeExtraction(**d)


def _extractor(recipe):
    def fn(url, model_env, default_model):
        return _good(url) if recipe == "good" else recipe(url)
    return fn


# ---- URL 정규화 ----
def test_normalize_url_variants():
    for u in ["https://www.youtube.com/watch?v=abcDEF12345",
              "https://youtu.be/abcDEF12345", "https://www.youtube.com/shorts/abcDEF12345"]:
        assert normalize_url(u) == "https://www.youtube.com/watch?v=abcDEF12345"
    assert normalize_url("https://naver.com") is None


def test_non_youtube_url_fails():
    r = extract_recipe("https://naver.com", _extractor("good"))
    assert not r.ok and r.stage == "failed"


# ---- 정상 추출 ----
def test_good_extraction_ok_no_retry():
    r = extract_recipe("https://youtu.be/abcDEF12345", _extractor("good"))
    assert r.ok and not r.retried and r.recipe.title == "김치볶음밥"


# ---- 검증 규칙 ----
def test_hard_H2_no_ingredients():
    assert "H2" in hard_failures(_good(ingredients=[]))

def test_hard_H3_no_title():
    assert "H3" in hard_failures(_good(title=None))

def test_hard_H4_timestamp_not_monotonic():
    bad = _good(steps=[Step(order=1, text="a", timestamp_sec=90), Step(order=2, text="b", timestamp_sec=10)])
    assert "H4" in hard_failures(bad)

def test_hard_H5_duplicate_steps():
    dup = _good(steps=[Step(order=1, text="같은문장"), Step(order=2, text="같은문장")])
    assert "H5" in hard_failures(dup)

def test_soft_S2_ner_miss_rate():
    r = _good(ingredients=[Ingredient(name="김치"), Ingredient(name="외계재료")])
    flags = soft_flags(r, ner_match_fn=lambda n: n == "김치")   # 50% 실패 > 40%
    assert "S2" in flags


# ---- 재분석 1회 한정 ----
def test_retry_recovers_hard_failure():
    calls = {"n": 0}
    def fn(url, model_env, default_model):
        calls["n"] += 1
        return _good(url, ingredients=[]) if calls["n"] == 1 else _good(url)   # 1차 실패, 재분석 성공
    r = extract_recipe("https://youtu.be/abcDEF12345", fn)
    assert r.ok and r.retried and calls["n"] == 2

def test_retry_exhausted_fails_with_note():
    r = extract_recipe("https://youtu.be/abcDEF12345", _extractor(lambda u: _good(u, ingredients=[])))
    assert not r.ok and r.retried and "직접 입력" in r.note


# ---- 캐시 ----
def test_cache_hit_skips_extraction():
    store = {"https://www.youtube.com/watch?v=abcDEF12345": _good()}
    class C:
        def get(self, k): return store.get(k)
        def set(self, k, v): store[k] = v
    calls = {"n": 0}
    def fn(url, m, d):
        calls["n"] += 1; return _good(url)
    r = extract_recipe("https://youtu.be/abcDEF12345", fn, cache=C())
    assert r.from_cache and calls["n"] == 0
