"""④-c 자기학습(부트스트래핑) — CRF가 코퍼스에서 예측한 '사전 밖 재료'를 사전에 추가(recall↑).

**gold를 보지 않고 코퍼스(COOKRCP01)만 사용** → 테스트셋 과적합 아님(원칙적 recall 확장).
CRF가 문자·문맥 패턴으로 사전에 없는 재료도 일부 예측 → 그중 자주 나오는 것을 새 사전어로 채택 →
다음 재라벨·재학습에서 약지도가 그 재료도 잡게 됨.

산출: data/dict_selftrain.txt (weak_label.dict_paths() 가 자동 병합).
보수적 필터: 한글 2~6자 · 빈도 ≥ _MIN_FREQ · 기존 사전에 없음.
"""
from __future__ import annotations

import json
import pickle
import re
from collections import Counter
from pathlib import Path

from train_crf import bio_to_spans, char_features
from weak_label import _DIR, build_dict, dict_paths

_MODEL = _DIR / "model" / "crf_ingredient.pkl"
_HANGUL_ONLY = re.compile(r"^[가-힣]{2,6}$")
_MIN_FREQ = 3


def main() -> None:
    with _MODEL.open("rb") as fh:
        crf = pickle.load(fh)
    multi, single = build_dict(*dict_paths())
    known = {m.replace(" ", "") for m in multi} | single

    rows = [json.loads(l) for l in (_DIR / "corpus.jsonl").read_text(encoding="utf-8").splitlines()]
    cnt: Counter = Counter()
    for r in rows:
        t = r["text"]
        if not t:
            continue
        labels = crf.predict([[char_features(t, i) for i in range(len(t))]])[0]
        for s, e in bio_to_spans(labels):
            surf = t[s:e]
            if surf.replace(" ", "") not in known and _HANGUL_ONLY.match(surf):
                cnt[surf] += 1

    cands = sorted(w for w, c in cnt.items() if c >= _MIN_FREQ)
    (_DIR / "dict_selftrain.txt").write_text("\n".join(cands), encoding="utf-8")
    print(f"자기학습 후보 {len(cands)}개 (freq≥{_MIN_FREQ}) → dict_selftrain.txt")
    print("  예:", cands[:25])


if __name__ == "__main__":
    main()
