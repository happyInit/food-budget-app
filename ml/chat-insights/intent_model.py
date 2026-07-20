"""의도 분류기 학습 — 대화 로그(text→intent)로 규칙 키워드 분류를 보강(ai-spec §5).

현행 챗 의도분류는 키워드 규칙(extract.py _INTENT_KEYWORDS). 대화가 쌓이면 실제 발화로
분류기를 학습해 규칙이 놓치는 표현을 잡는다. 정식은 FastText(빠른 텍스트 분류), 미설치
환경은 sklearn TF-IDF+LogisticRegression 폴백 — 둘 다 predict(text)로 의도를 낸다.

데이터 부족(라벨 다양성·건수 미달)이면 학습 skip(규칙 유지).

★ 산출물은 **이식 포맷**(프레임워크 네이티브 + meta.json)으로 저장한다 — 커스텀 래퍼 클래스를
pickle 하면 언피클 측(챗 서비스 등 다른 모듈)이 그 클래스를 import 해야 해서 교차모듈 로드가
불가능하기 때문. sklearn 은 순수 Pipeline 만, fasttext 는 네이티브 바이너리만 저장 → sklearn/
fasttext 라이브러리만 있으면 **어느 모듈에서든** load() 로 읽는다(services/chat/…/intent_ml.py 가 동일 계약으로 로드).
"""
from __future__ import annotations

import json
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

    backend = "sklearn"

    def __init__(self):
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        self._p = Pipeline([
            ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=2)),
            ("clf", LogisticRegression(max_iter=1000)),
        ])
        self.labels: list[str] = []

    def fit(self, X, y):
        self._p.fit(X, y)
        self.labels = [str(c) for c in self._p.classes_]
        return self

    def predict(self, text: str) -> str:
        return str(self._p.predict([text])[0])


def _backend_available() -> bool:
    """fasttext 또는 sklearn 중 하나라도 설치돼 있어야 학습 가능(둘 다 없으면 skip)."""
    import importlib.util
    return importlib.util.find_spec("fasttext") is not None or importlib.util.find_spec("sklearn") is not None


def can_train(messages: list[dict]) -> tuple[bool, str]:
    """학습 가능 여부 + 사유(데이터 부족·백엔드 부재면 규칙 유지)."""
    if not _backend_available():
        return False, "학습 백엔드(fasttext/sklearn) 미설치"
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
        backend = "fasttext"

        def __init__(self, m, labels):
            self._m = m
            self.labels = labels

        def predict(self, text: str) -> str:
            return self._m.predict(text.replace("\n", " "))[0][0].replace("__label__", "")
    return _FT(model, sorted(set(y)))


def _atomic_write(path: str, write_fn) -> None:
    tmp = f"{path}.tmp"
    write_fn(tmp)
    os.replace(tmp, path)


def save(model, path: str) -> None:
    """이식 포맷 저장 — 프레임워크 네이티브 모델 + `{path}.meta.json`(backend·labels).

    커스텀 래퍼 클래스는 저장하지 않는다(교차모듈 언피클 불가 회피):
      · sklearn → 순수 Pipeline(model._p)만 pickle. sklearn 있는 곳이면 어디서든 로드.
      · fasttext → 네이티브 바이너리(save_model). fasttext 있는 곳이면 어디서든 로드.
    로더(챗 서비스 포함)는 meta.json의 backend 로 분기해 네이티브 로드 → 클래스 import 불필요.
    """
    if model.backend == "sklearn":
        _atomic_write(path, lambda tmp: _pickle_to(model._p, tmp))   # 순수 sklearn Pipeline
    elif model.backend == "fasttext":
        model._m.save_model(path)                                    # fasttext 네이티브
    else:
        raise ValueError(f"알 수 없는 backend: {model.backend}")
    meta = {"backend": model.backend, "labels": list(getattr(model, "labels", []))}
    _atomic_write(f"{path}.meta.json",
                  lambda tmp: open(tmp, "w", encoding="utf-8").write(json.dumps(meta, ensure_ascii=False)))


def _pickle_to(obj, tmp: str) -> None:
    with open(tmp, "wb") as f:
        pickle.dump(obj, f)


class PortableIntent:
    """이식 포맷을 읽어 predict(text)->intent 를 제공. 커스텀 클래스 의존 없음(네이티브만).
    챗 서비스(services/chat/.../intent_ml.py)는 이 로직을 동일 계약으로 자체 구현한다(모듈 독립)."""

    def __init__(self, backend: str, native, labels: list[str]):
        self.backend, self._m, self.labels = backend, native, labels

    def predict(self, text: str) -> str:
        if self.backend == "sklearn":
            return str(self._m.predict([text])[0])
        return self._m.predict((text or "").replace("\n", " "))[0][0].replace("__label__", "")


def load(path: str):
    """이식 포맷 로드. 파일/메타/라이브러리 부재 → None(호출측이 규칙 폴백)."""
    meta_path = f"{path}.meta.json"
    if not (os.path.exists(path) and os.path.exists(meta_path)):
        return None
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        backend = meta.get("backend")
        if backend == "sklearn":
            with open(path, "rb") as f:
                native = pickle.load(f)          # 순수 Pipeline(sklearn 필요, 커스텀 클래스 불요)
        elif backend == "fasttext":
            import fasttext
            native = fasttext.load_model(path)
        else:
            return None
        return PortableIntent(backend, native, meta.get("labels", []))
    except Exception:                             # noqa: BLE001 — 라이브러리/포맷 문제 → 규칙 폴백
        return None
