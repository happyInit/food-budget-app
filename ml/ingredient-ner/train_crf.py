"""③ CRF 학습 — 약지도 라벨(labeled.jsonl)로 문자 단위 CRF 재료 NER 학습·평가.

- 입력: weak_label.py 산출 labeled.jsonl (문자 BIO + train/test 결정적 분할)
- 피처: 문자 자체 + 문자유형(한글/숫자/공백/기호) + 전후 문자·바이그램 + BOS/EOS
        ⚠️ 사전멤버십(in_dict) 피처는 **일부러 제외** — 약지도 라벨이 사전매칭에서 나왔으므로
        그 피처를 넣으면 CRF가 사전을 그대로 외워 **사전 밖 재료로 일반화가 안 됨**. 문자·문맥
        패턴("명사 + 수량단위" 등)만 학습해 미등재 재료도 잡게 한다(순수 사전 대비 CRF의 존재이유).
- 평가: 엔티티(span) 단위 P/R/F1 (목표 F1 ≥ 0.85, ai-spec.md §1)
- 저장: data/model/crf_ingredient.pkl (초안은 gitignore, 확정 모델은 추후 git 아티팩트=모델 X)
"""
from __future__ import annotations

import json
import pickle
import shutil
import re
from pathlib import Path

import sklearn_crfsuite

_DIR = Path(__file__).parent / "data"
_MODEL = _DIR / "model"
_HANGUL = re.compile(r"[가-힣]")
_PUNCT = set("(),[]{}·●:：/.-·⅓½¾")


def _ctype(c: str) -> str:
    if c.isdigit():
        return "d"
    if _HANGUL.match(c):
        return "h"
    if c.isspace():
        return "s"
    if c in _PUNCT:
        return "p"
    return "o"


def char_features(text: str, i: int) -> dict:
    c = text[i]
    f = {"bias": 1.0, "c": c, "ct": _ctype(c)}
    if i > 0:
        f["-1c"], f["-1ct"] = text[i - 1], _ctype(text[i - 1])
        f["-1:0"] = text[i - 1] + c
    else:
        f["BOS"] = True
    if i < len(text) - 1:
        f["+1c"], f["+1ct"] = text[i + 1], _ctype(text[i + 1])
        f["0:+1"] = c + text[i + 1]
    else:
        f["EOS"] = True
    if i > 1:
        f["-2c"] = text[i - 2]
    if i < len(text) - 2:
        f["+2c"] = text[i + 2]
    return f


def to_xy(rows: list[dict]):
    X, Y = [], []
    for r in rows:
        text, labels = r["text"], r["labels"]
        if not text:
            continue
        X.append([char_features(text, i) for i in range(len(text))])
        Y.append(labels)
    return X, Y


def bio_to_spans(labels: list[str]) -> set[tuple[int, int]]:
    spans, start = set(), None
    for i, l in enumerate(labels):
        if l == "B-ING":
            if start is not None:
                spans.add((start, i))
            start = i
        elif l == "I-ING":
            if start is None:
                start = i
        else:
            if start is not None:
                spans.add((start, i))
                start = None
    if start is not None:
        spans.add((start, len(labels)))
    return spans


def span_prf(gold_seqs, pred_seqs) -> tuple[float, float, float]:
    tp = fp = fn = 0
    for g, p in zip(gold_seqs, pred_seqs):
        gs, ps = bio_to_spans(g), bio_to_spans(p)
        tp += len(gs & ps)
        fp += len(ps - gs)
        fn += len(gs - ps)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return prec, rec, f1


def main() -> None:
    rows = [json.loads(l) for l in (_DIR / "labeled.jsonl").read_text(encoding="utf-8").splitlines()]
    train = [r for r in rows if r.get("split") == "train"]
    test = [r for r in rows if r.get("split") == "test"]
    Xtr, Ytr = to_xy(train)
    Xte, Yte = to_xy(test)

    crf = sklearn_crfsuite.CRF(
        algorithm="lbfgs", c1=0.1, c2=0.1, max_iterations=100,
        all_possible_transitions=True,
    )
    crf.fit(Xtr, Ytr)
    Ypred = crf.predict(Xte)

    p, r, f1 = span_prf(Yte, Ypred)
    print(f"학습: train {len(Xtr)} · test {len(Xte)} 텍스트")
    print(f"엔티티(span) 단위 — Precision {p:.3f} · Recall {r:.3f} · F1 {f1:.3f}  (목표 ≥ 0.85)")

    _MODEL.mkdir(exist_ok=True)
    with (_MODEL / "crf_ingredient.pkl").open("wb") as fh:
        pickle.dump(crf, fh)
    print(f"→ 모델 저장 {_MODEL/'crf_ingredient.pkl'}")

    # ── 서빙용 아티팩트 추출 ──────────────────────────────────────────────────
    # 🔴 **이 단계를 빼면 다음 재학습이 원점으로 돌아간다.**
    # 피클은 `sklearn_crfsuite.CRF` **객체**라, 열려면 scikit-learn·scipy·numpy 195MB 가
    # 따라온다(추론에는 한 줄도 안 쓰인다 — `predict()` 는 `tagger_.tag()` 로 그대로 넘긴다).
    # `.crfsuite` 는 CRFsuite 네이티브 포맷이라 `python-crfsuite`(5MB) 만으로 열린다.
    #
    # 실측(2026-08-14) — gold 50건에서 **P·R·F1 소수점 넷째 자리까지 동일**(F1 0.9238),
    # 예측 스팬 **50/50 완전 일치**. Lambda 번들 224MB→19MB · import 18,986ms→243ms.
    # 🔴 그리고 `pickle.load()` 는 파일대로 코드를 실행한다 — 모델을 S3 에서 받는 구조에서는
    #    그 자체가 실행 경로다. `.crfsuite` 는 순수 데이터라 그 경로가 없다.
    lean = _MODEL / "crf_ingredient.crfsuite"
    shutil.copy(crf.modelfile.name, lean)   # 언피클/학습이 풀어둔 원본 모델 파일
    print(f"→ 서빙 아티팩트 {lean}  ({lean.stat().st_size:,} bytes)")

    # 메타데이터는 `.crfsuite` 에 안 담긴다(학습 이력·라벨 집합). 따로 남긴다 — 모델 카드용.
    meta = {"labels": sorted(crf.classes_), "algorithm": crf.algorithm,
            "c1": crf.c1, "c2": crf.c2, "max_iterations": crf.max_iterations,
            "span_f1_holdout": round(f1, 4), "precision": round(p, 4), "recall": round(r, 4),
            "artifact_bytes": lean.stat().st_size}
    (_MODEL / "crf_ingredient.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"→ 메타데이터 {_MODEL/'crf_ingredient.meta.json'}")

    # 미등재 일반화 스팟체크 — 학습에 없던 표현도 잡는지
    for t in ["방울토마토 150g, 양파 10g, 부추 10g", "돼지고기살코기 40g, 완두콩 30g"]:
        pred = crf.predict([[char_features(t, i) for i in range(len(t))]])[0]
        surf = ["".join(t[s:e]) for s, e in sorted(bio_to_spans(pred))]
        print(f"  예측 {t[:30]!r} → {surf}")


if __name__ == "__main__":
    main()
