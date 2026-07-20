"""ML 의도분류 로더/배선 — 교차모듈 계약(네이티브+meta.json)을 챗이 독립 로드하는지 검증.

chat-insights 를 import 하지 않고, 동일 on-disk 포맷(순수 sklearn Pipeline + meta.json)을
직접 만들어 챗 로더로 읽는다 → 커스텀 클래스 의존 없음을 챗 쪽에서 재확인.
flag off / 모델 부재면 None → 규칙 의도 유지(무해).
"""
import json
import pickle

from app.pipeline import extract, intent_ml


def _write_portable(path: str) -> None:
    """chat-insights.save() 와 동일한 on-disk 포맷을 챗 테스트에서 직접 생성(순수 Pipeline)."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    pipe = Pipeline([
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)),
        ("clf", LogisticRegression(max_iter=1000)),
    ])
    X = (["칼로리 얼마야", "영양성분 알려줘", "이거 추천해줘", "뭐 해먹을까", "이거 가격", "값 얼마"] * 12)
    y = (["nutrition", "nutrition", "recommend", "recommend", "price_lookup", "price_lookup"] * 12)
    pipe.fit(X, y)
    with open(path, "wb") as f:
        pickle.dump(pipe, f)
    with open(f"{path}.meta.json", "w", encoding="utf-8") as f:
        json.dump({"backend": "sklearn", "labels": [str(c) for c in pipe.classes_]}, f, ensure_ascii=False)


def test_chat_loader_reads_portable_contract(tmp_path):
    path = str(tmp_path / "intent.model")
    _write_portable(path)
    m = intent_ml.load_intent_model(path)          # chat-insights import 없이 로드
    assert m is not None and m.backend == "sklearn"
    assert m.predict("이거 칼로리 얼마야") in {"nutrition", "recommend", "price_lookup"}


def test_loader_absent_returns_none(tmp_path):
    assert intent_ml.load_intent_model(None) is None
    assert intent_ml.load_intent_model(str(tmp_path / "nope")) is None


def test_classify_intent_rule_first_then_ml(monkeypatch):
    # 규칙이 잡으면 ML 호출 안 함(과다전환 방지)
    class _Boom:
        def predict(self, t):
            raise AssertionError("규칙이 잡았는데 ML을 불렀다")
    monkeypatch.setattr(extract, "get_intent_model", lambda: _Boom())
    assert extract._classify_intent("칼로리 얼마야") == "nutrition"

    # 규칙 미해결(unknown)일 때만 ML 보강
    class _Fake:
        def predict(self, t):
            return "recommend"
    monkeypatch.setattr(extract, "get_intent_model", lambda: _Fake())
    assert extract._classify_intent("오늘 기분이 좀 그래") == "recommend"


def test_classify_intent_no_model_keeps_unknown(monkeypatch):
    monkeypatch.setattr(extract, "get_intent_model", lambda: None)
    assert extract._classify_intent("오늘 기분이 좀 그래") == "unknown"
