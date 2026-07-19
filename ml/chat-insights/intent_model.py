"""의도 분류기 학습 — 대화 로그(text→intent)로 규칙 키워드 분류를 보강(ai-spec §5).

현행 챗 의도분류는 키워드 규칙(extract.py _INTENT_KEYWORDS). 대화가 쌓이면 실제 발화로
분류기를 학습해 규칙이 놓치는 표현을 잡는다. 정식은 FastText(빠른 텍스트 분류), 미설치
환경은 sklearn TF-IDF+LogisticRegression 폴백 — 둘 다 predict(text)로 의도를 낸다.

데이터 부족(라벨 다양성·건수 미달)이면 학습 skip(규칙 유지). 학습 산출물은 pickle 저장.
"""
from __future__ import annotations

import os
import pickle

MIN_SAMPLES = int(os.environ.get("INTENT_MIN_SAMPLES", "200"))
MIN_CLASSES = 3


def _labeled(messages: list[dict]) -> tuple[list[str], list[str]]:
    """user 메시지에서 (text, intent) 라벨셋. intent 없는 것 제외."""
    X, y = [], []
    for m in messages:
        if m.get("role") != "user":
            continue
        text, intent = (m.get("text") or "").strip(), m.get("intent")
        if text and intent:
            X.append(text)
            y.append(intent)
    return X, y


class _SklearnIntent:
    """폴백 — TF-IDF(char n-gram, 한국어 무형태소) + 로지스틱 회귀."""

    def __init__(self):
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        self._p = Pipeline([
            ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=2)),
            ("clf", LogisticRegression(max_iter=1000)),
        ])

    def fit(self, X, y):
        self._p.fit(X, y)
        return self

    def predict(self, text: str) -> str:
        return str(self._p.predict([text])[0])


def can_train(messages: list[dict]) -> tuple[bool, str]:
    """학습 가능 여부 + 사유(데이터 부족이면 규칙 유지)."""
    X, y = _labeled(messages)
    if len(X) < MIN_SAMPLES:
        return False, f"샘플 {len(X)}<{MIN_SAMPLES}"
    if len(set(y)) < MIN_CLASSES:
        return False, f"클래스 {len(set(y))}<{MIN_CLASSES}"
    return True, "ok"


def train(messages: list[dict]):
    """의도 분류기 학습. FastText 있으면 정식, 없으면 sklearn 폴백."""
    X, y = _labeled(messages)
    try:
        import fasttext  # noqa: F401 — 설치 여부만
        return _train_fasttext(X, y)
    except ImportError:
        return _SklearnIntent().fit(X, y)


def _train_fasttext(X, y):
    """정식 FastText — __label__intent text 포맷으로 학습."""
    import tempfile

    import fasttext
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for xi, yi in zip(X, y):
            f.write(f"__label__{yi} {xi}\n")
        train_path = f.name
    model = fasttext.train_supervised(input=train_path, epoch=25, wordNgrams=2, verbose=0)
    os.unlink(train_path)

    class _FT:
        def __init__(self, m):
            self._m = m

        def predict(self, text: str) -> str:
            return self._m.predict(text.replace("\n", " "))[0][0].replace("__label__", "")
    return _FT(model)


def save(model, path: str) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "wb") as f:
        pickle.dump(model, f)
    os.replace(tmp, path)
