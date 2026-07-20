"""ML 의도분류 로더(이식 포맷) — chat-insights가 저장한 **네이티브 모델 + meta.json** 을 읽는다.

교차모듈 계약: 커스텀 래퍼 클래스를 언피클하지 않는다(그 클래스는 chat-insights에만 있어 챗에서
import 불가). meta.json의 `backend` 로 분기해 프레임워크 네이티브만 로드한다:
  · sklearn  → 순수 Pipeline pickle (sklearn 필요)
  · fasttext → 네이티브 바이너리   (fasttext 필요)

라이브러리·모델파일·메타 중 하나라도 없으면 None → 호출측이 규칙 기반 의도(_classify_intent)를 유지.
이 배선은 **prep-ahead**: 데이터가 쌓여 chat-insights가 모델을 저장하고, 챗에 해당 라이브러리와
INTENT_ML_ENABLED=true·INTENT_ML_PATH 가 갖춰지면 자동 활성. 그 전엔 규칙만(무해).
"""
from __future__ import annotations

import json
import os
import pickle

from app.config import settings


class _MLIntent:
    """predict(text)->intent. 네이티브 모델만 감싼다(커스텀 클래스 의존 없음)."""

    def __init__(self, backend: str, native, labels: list[str]):
        self.backend, self._m, self.labels = backend, native, labels

    def predict(self, text: str) -> str:
        if self.backend == "sklearn":
            return str(self._m.predict([text])[0])
        return self._m.predict((text or "").replace("\n", " "))[0][0].replace("__label__", "")


def load_intent_model(path: str | None):
    """이식 포맷 로드. 부재/실패 → None(규칙 폴백). chat-insights.save()와 동일 on-disk 계약."""
    if not path:
        return None
    meta_path = f"{path}.meta.json"
    if not (os.path.exists(path) and os.path.exists(meta_path)):
        return None
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        backend = meta.get("backend")
        if backend == "sklearn":
            with open(path, "rb") as f:
                native = pickle.load(f)          # 순수 Pipeline — sklearn만 있으면 됨(커스텀 클래스 불요)
        elif backend == "fasttext":
            import fasttext
            native = fasttext.load_model(path)
        else:
            return None
        return _MLIntent(backend, native, meta.get("labels", []))
    except Exception:                            # noqa: BLE001 — 라이브러리/포맷 문제 → 규칙 폴백
        return None


_model = None
_loaded = False


def get_intent_model():
    """lazy 싱글턴 — flag off거나 로드 실패면 None(규칙 유지). 최초 1회만 로드 시도."""
    global _model, _loaded
    if _loaded:
        return _model
    _loaded = True
    if getattr(settings, "intent_ml_enabled", False):
        _model = load_intent_model(getattr(settings, "intent_ml_path", "") or None)
    return _model
