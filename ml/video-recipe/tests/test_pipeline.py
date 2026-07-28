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


# ── H0: 영상 미수신 (2026-07-29 실측에서 발견) ──────────────────────────────
def test_h0_detects_video_not_received():
    """전 필드가 비고 video_seconds=0이면 '영상 미수신'으로 구분한다.

    실측: YouTube URL 입력이 동작하지 않는 환경에서 모델은 오류 없이
    {"title":null,"is_recipe":false,...,"video_seconds":0}을 돌려줬다.
    이를 H3(요리 영상 아님)으로 뭉뚱그리면 원인이 감춰진다.
    """
    from validate import video_not_received

    empty = RecipeExtraction(title=None, is_recipe=False, ingredients=[], steps=[], video_seconds=0)
    assert video_not_received(empty) is True
    assert "H0" in hard_failures(empty)


def test_h0_not_triggered_for_real_non_recipe():
    """길이가 있는 '진짜 비요리 영상'은 H0가 아니라 H3다(오분류 방지)."""
    from validate import video_not_received

    non_recipe = RecipeExtraction(title=None, is_recipe=False, ingredients=[], steps=[], video_seconds=180)
    assert video_not_received(non_recipe) is False
    hf = hard_failures(non_recipe)
    assert "H0" not in hf and "H3" in hf


def test_h0_skips_retry():
    """H0는 재분석하지 않는다 — 입력 경로 문제라 재시도해도 같고 비용만 든다."""
    calls = []

    def _extractor(url, model_env, default_model):
        calls.append(model_env)
        return RecipeExtraction(title=None, is_recipe=False, ingredients=[], steps=[], video_seconds=0)

    r = extract_recipe("https://www.youtube.com/watch?v=abcdefghijk", _extractor)
    assert r.ok is False
    assert len(calls) == 1                      # 재분석 호출 없음
    assert "영상을 불러오지" in (r.note or "")   # 원인에 맞는 안내


def test_h0_allows_real_video_with_length():
    """실측 회귀 방지 — 정상 영상(길이 607s, 재료·스텝 있음)은 H0가 아니다.

    실제 검증(2026-07-29, https://youtu.be/qWbHSOplcvY '돼지고기 김치찌개'):
    재료 10개·스텝 7개·타임스탬프 단조증가로 DONE(stage=retried) 성공.
    """
    from validate import video_not_received

    ok = RecipeExtraction(
        title="돼지고기 김치찌개", is_recipe=True, video_seconds=607,
        ingredients=[Ingredient(name="돼지고기", quantity="130g"),
                     Ingredient(name="신 김치", quantity="390g")],
        steps=[Step(order=1, text="고기와 물을 넣는다", timestamp_sec=111),
               Step(order=2, text="새우젓을 넣고 끓인다", timestamp_sec=163)],
    )
    assert video_not_received(ok) is False
    assert hard_failures(ok) == []


# ── item_resolver: NER 정규화 배선 (2026-07-29) ─────────────────────────────
def test_item_resolver_fills_item_id():
    """추출된 재료명이 표준품목코드로 채워진다 — 재료비·재고·알림 연결의 전제."""
    def _extractor(url, model_env, default_model):
        return RecipeExtraction(
            title="김치찌개", is_recipe=True, video_seconds=600,
            ingredients=[Ingredient(name="돼지고기"), Ingredient(name="신 김치"), Ingredient(name="물")],
            steps=[Step(order=1, text="끓인다", timestamp_sec=10),
                   Step(order=2, text="더 끓인다", timestamp_sec=20)])

    table = {"돼지고기": 10, "신 김치": 5}     # '물'은 item_master에 없음(정상)
    r = extract_recipe("https://www.youtube.com/watch?v=abcdefghijk", _extractor,
                       item_resolver=lambda n: table.get(n))
    assert r.ok is True
    assert [i.item_id for i in r.recipe.ingredients] == [10, 5, None]


def test_item_resolver_failure_does_not_drop_result():
    """정규화가 터져도 추출 결과는 살린다(item_id만 비운다)."""
    def _extractor(url, model_env, default_model):
        return RecipeExtraction(
            title="된장찌개", is_recipe=True, video_seconds=300,
            ingredients=[Ingredient(name="두부")],
            steps=[Step(order=1, text="끓인다", timestamp_sec=5),
                   Step(order=2, text="담는다", timestamp_sec=9)])

    def _boom(_name):
        raise RuntimeError("gazetteer down")

    r = extract_recipe("https://www.youtube.com/watch?v=abcdefghijk", _extractor, item_resolver=_boom)
    assert r.ok is True and r.recipe.ingredients[0].item_id is None


def test_item_id_filled_before_cache():
    """캐시에는 item_id가 채워진 상태로 저장돼야 한다(히트 시에도 앱 기능과 연결)."""
    saved = {}

    class _Cache:
        def get(self, k): return None
        def set(self, k, recipe): saved["r"] = recipe

    def _extractor(url, model_env, default_model):
        return RecipeExtraction(
            title="계란찜", is_recipe=True, video_seconds=200,
            ingredients=[Ingredient(name="계란")],
            steps=[Step(order=1, text="푼다", timestamp_sec=3),
                   Step(order=2, text="찐다", timestamp_sec=8)])

    extract_recipe("https://www.youtube.com/watch?v=abcdefghijk", _extractor,
                   cache=_Cache(), item_resolver=lambda n: 42)
    assert saved["r"].ingredients[0].item_id == 42


# ── 타임스탬프 국소 역전 복구 (2026-07-29 실측 기반) ─────────────────────────
def _mk(ts_list, secs=600):
    return RecipeExtraction(
        title="김치찌개", is_recipe=True, video_seconds=secs,
        ingredients=[Ingredient(name="김치")],
        steps=[Step(order=i + 1, text=f"단계{i+1}", timestamp_sec=t) for i, t in enumerate(ts_list)])


def test_local_inversion_is_repaired_without_retry():
    """1곳 역전은 정렬로 복구하고 재분석하지 않는다(비용·지연 절약)."""
    calls = []

    def _ex(url, model_env, default_model):
        calls.append(model_env)
        return _mk([151, 248, 444, 357, 520])      # 3↔4 역전

    r = extract_recipe("https://www.youtube.com/watch?v=abcdefghijk", _ex)
    assert r.ok is True and r.stage == "repaired"
    assert len(calls) == 1                          # 재분석 호출 없음
    ts = [s.timestamp_sec for s in r.recipe.steps]
    assert ts == sorted(ts) == [151, 248, 357, 444, 520]
    assert [s.order for s in r.recipe.steps] == [1, 2, 3, 4, 5]


def test_step_texts_keep_their_order_when_repairing():
    """시각만 재배열하고 **스텝 내용 순서는 보존**한다(조리 논리는 모델이 맞게 냈다)."""
    def _ex(url, model_env, default_model):
        rec = _mk([100, 300, 200])
        rec.steps[0].text = "고기를 넣는다"
        rec.steps[1].text = "10분 끓인다"
        rec.steps[2].text = "채소를 썬다"
        return rec

    r = extract_recipe("https://www.youtube.com/watch?v=abcdefghijk", _ex)
    assert [s.text for s in r.recipe.steps] == ["고기를 넣는다", "10분 끓인다", "채소를 썬다"]


def test_widespread_disorder_falls_back_to_retry():
    """광범위한 혼란(>25%)은 복구하지 않고 재분석에 넘긴다 — 틀린 결과를 정상처럼 만들지 않기 위해."""
    calls = []

    def _ex(url, model_env, default_model):
        calls.append(model_env)
        if len(calls) == 1:
            return _mk([500, 100, 400, 200, 300])   # 역전 3곳/4 = 75%
        return _mk([100, 200, 300, 400, 500])       # 재분석은 정상

    r = extract_recipe("https://www.youtube.com/watch?v=abcdefghijk", _ex)
    assert r.stage == "retried" and r.ok is True
    assert calls == ["VIDEO_EXTRACT_MODEL", "VIDEO_RETRY_MODEL"]


def test_video_seconds_overrun_is_soft_not_hard():
    """영상 길이 초과는 S4(소프트) — video_seconds가 모델 추정치라 결과를 버릴 근거가 못 된다."""
    from validate import hard_failures as hf, soft_flags as sf

    rec = _mk([100, 200, 639], secs=602)            # 마지막이 길이 초과
    assert hf(rec) == []                            # 하드 실패 아님
    assert "S4" in sf(rec)
