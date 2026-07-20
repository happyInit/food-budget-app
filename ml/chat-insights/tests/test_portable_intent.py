"""이식 포맷 저장/로드 왕복 — 교차모듈 pickle 문제 해소 증명.

핵심: save()가 남기는 pickle은 **순수 sklearn Pipeline**(커스텀 _SklearnIntent 아님)이라,
sklearn 만 있으면 어느 모듈(챗 서비스)에서든 언피클된다. 이 테스트가 그 불변식을 고정한다.
"""
import json
import os
import pickle

import intent_model
import synth


def _trained():
    msgs = synth.make_messages(n_users=120, sessions_per_user=4, seed=5)
    ok, why = intent_model.can_train(msgs)
    assert ok, f"학습조건 불충족: {why}"
    return intent_model.train(msgs)


def test_saved_pickle_is_native_not_custom_class(tmp_path):
    path = str(tmp_path / "intent.model")
    intent_model.save(_trained(), path)

    # meta.json 동반 + backend/labels
    assert os.path.exists(f"{path}.meta.json")
    meta = json.load(open(f"{path}.meta.json", encoding="utf-8"))
    assert meta["backend"] == "sklearn" and len(meta["labels"]) >= 3

    # ★ 불변식: 저장물은 순수 sklearn Pipeline — chat-insights 커스텀 클래스가 아니다.
    #   → sklearn 있는 챗 서비스가 intent_model 을 import 하지 않고도 언피클 가능.
    with open(path, "rb") as f:
        native = pickle.load(f)
    assert type(native).__module__.startswith("sklearn")
    assert type(native).__name__ == "Pipeline"


def test_portable_roundtrip_predict(tmp_path):
    path = str(tmp_path / "intent.model")
    m = _trained()
    intent_model.save(m, path)

    loaded = intent_model.load(path)                 # 커스텀 클래스 없이 로드
    assert loaded is not None
    pred = loaded.predict("이거 칼로리 얼마야")
    assert isinstance(pred, str) and pred in loaded.labels


def test_load_missing_returns_none(tmp_path):
    assert intent_model.load(str(tmp_path / "nope.model")) is None
    # 모델은 있는데 meta 없으면(반쪽) None
    p = tmp_path / "half.model"
    p.write_bytes(b"x")
    assert intent_model.load(str(p)) is None
