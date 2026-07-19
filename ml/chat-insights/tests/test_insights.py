"""chat-insights 단위 테스트 — 합성 데이터로 3종(리포트·선호·의도) 검증. DB 불필요."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import intent_model  # noqa: E402
import preferences  # noqa: E402
import reports  # noqa: E402
from synth import make_messages  # noqa: E402

MSGS = make_messages(n_users=30, sessions_per_user=3, seed=3)


def test_metrics_unanswered_and_gaps():
    m = reports.compute_metrics(MSGS)
    assert m["n_user_messages"] > 0
    assert 0.0 <= m["unanswered_rate"] <= 1.0
    # 합성 미응답 용어(마라탕/탕후루/분모자)가 커버리지 갭에 잡혀야 함
    gap_words = {t for t, _ in m["coverage_gap_terms"]}
    assert gap_words & {"마라탕", "탕후루", "분모자"}


def test_preferences_split_like_dislike():
    sig = preferences.extract_signals(MSGS)
    assert sig, "유저 신호가 나와야 함"
    for s in sig.values():
        # 선호·비선호가 겹치지 않아야(비선호는 선호에서 제외)
        assert not (set(s["liked_item_ids"]) & set(s["disliked_item_ids"]))
        assert 0.0 <= s["budget_sensitivity"] <= 1.0


def test_intent_model_trains_and_predicts():
    ok, why = intent_model.can_train(MSGS)
    assert ok, f"합성셋은 학습 가능해야: {why}"
    model = intent_model.train(MSGS)
    pred = model.predict("두부 얼마야")
    assert isinstance(pred, str) and pred


def test_intent_model_skips_when_scarce():
    ok, _ = intent_model.can_train(MSGS[:10])   # 너무 적음
    assert ok is False


def test_report_renders_without_llm_key(monkeypatch):
    monkeypatch.delenv("REPORT_GEMINI_API_KEY", raising=False)
    m = reports.compute_metrics(MSGS)
    text = reports.render_report(m, "daily", None)
    assert "미응답률" in text and "REPORT_GEMINI_API_KEY 미설정" in text
