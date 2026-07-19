"""학습 — LightGBM LambdaMART(정식) / sklearn 폴백(미설치 환경).

정식은 LightGBM `LGBMRanker(objective='lambdarank')` — 그룹(노출요청) 단위 리스트와이즈 학습.
lightgbm 미설치 환경에선 sklearn `GradientBoostingRegressor`(pointwise)로 폴백해 스캐폴드
end-to-end가 돌아가게 한다(관련도를 회귀 타깃으로). 둘 다 `.predict(X)`로 점수를 낸다.

랭커 래퍼는 **모듈 최상위 클래스**여야 pickle 가능(재학습 배치가 저장→서빙이 로드).
중첩 클래스는 pickle이 경로를 못 찾으므로 _LgbRanker도 모듈 레벨에 둔다.
"""
from __future__ import annotations

import pickle

import numpy as np

from features import group_sizes


class _SklearnRanker:
    """폴백 — 관련도(0/1/2)를 회귀로 학습한 pointwise 랭커. 그룹 무시(근사)."""

    def __init__(self, **kw):
        from sklearn.ensemble import GradientBoostingRegressor
        self._m = GradientBoostingRegressor(**kw)

    def fit(self, X, y, groups=None):
        self._m.fit(X, y)
        return self

    def predict(self, X):
        return self._m.predict(X)


class _LgbRanker:
    """정식 — LightGBM LambdaMART(리스트와이즈). 내부 LGBMRanker는 pickle 가능."""

    def __init__(self):
        import lightgbm as lgb
        self._m = lgb.LGBMRanker(objective="lambdarank", n_estimators=200,
                                 learning_rate=0.05, num_leaves=31, verbose=-1)

    def fit(self, X, y, groups):
        self._m.fit(X, y, group=group_sizes(groups))
        return self

    def predict(self, X):
        return self._m.predict(X)


def build_ranker(**kw):
    """정식 LightGBM 랭커, 없으면 sklearn 폴백. 반환 객체는 fit/predict(둘 다 pickle 가능)."""
    try:
        import lightgbm  # noqa: F401 — 설치 여부만 확인
    except ImportError:
        return _SklearnRanker(random_state=kw.get("random_state", 0))
    return _LgbRanker()


def train(X: np.ndarray, y: np.ndarray, groups: np.ndarray, **kw):
    """피처행렬·관련도·그룹으로 랭커 학습(그룹은 to_matrix가 정렬해 넘긴 것)."""
    model = build_ranker(**kw)
    try:
        model.fit(X, y, groups)          # LightGBM 경로(그룹 사용)
    except TypeError:
        model.fit(X, y)                  # 폴백 경로(그룹 무시)
    return model


def save_model(model, path: str) -> None:
    """모델 원자적 저장 — tmp에 쓰고 rename(서빙이 반쯤 쓰인 파일을 읽지 않도록)."""
    import os
    tmp = f"{path}.tmp"
    with open(tmp, "wb") as f:
        pickle.dump(model, f)
    os.replace(tmp, path)


def load_model(path: str):
    """저장된 랭커 로드(pickle). 서빙 _init_from_env와 동일 포맷."""
    with open(path, "rb") as f:
        return pickle.load(f)
