"""④-b HITL gold 채점 — 사람이 교정한 gold_test.txt로 CRF·약지도의 **진짜** span F1 측정.

입력: ml/ingredient-ner/gold_test.txt (make_review_set.py 산출 gold_review.txt를 사람이 교정한 것)
      각 레코드 = `#<idx>\t<원문>`(불변) + `=<idx>\t{{..}} 주석`(사람 gold)
비교: gold(사람) vs CRF 예측 · gold vs 약지도(사전) — 각각 span P/R/F1
      + CRF 오류(놓침/오탐) 목록.
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

from train_crf import bio_to_spans, char_features, span_prf
from weak_label import _DIR, build_dict, label_text

_ROOT = Path(__file__).parent
_GOLD = _ROOT / "gold_test.txt"
_MODEL = _DIR / "model" / "crf_ingredient.pkl"


def parse_annot(s: str):
    """`{{재료}}` 주석 문자열 → (원문복원, span[(start,end)])."""
    clean, spans, i, st = [], [], 0, None
    while i < len(s):
        if s[i:i + 2] == "{{":
            st = len(clean); i += 2
        elif s[i:i + 2] == "}}":
            if st is not None:
                spans.append((st, len(clean))); st = None
            i += 2
        else:
            clean.append(s[i]); i += 1
    return "".join(clean), spans


def load_gold(path: Path):
    orig: dict[str, str] = {}
    annot: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "\t" not in line:
            continue
        head, rest = line.split("\t", 1)
        if head[:1] == "#" and head[1:].isdigit():
            orig[head[1:]] = rest
        elif head[:1] == "=" and head[1:].isdigit():
            annot[head[1:]] = rest
    recs = []
    for idx, text in orig.items():
        if idx not in annot:
            continue
        clean, spans = parse_annot(annot[idx])
        if clean != text:
            print(f"  ⚠️ idx={idx}: 주석줄 원문이 바뀜(브래킷 외 편집?) — 채점 제외")
            continue
        recs.append({"text": text, "gold": set(spans)})
    return recs


def crf_spans(crf, text: str) -> set:
    labels = crf.predict([[char_features(text, i) for i in range(len(text))]])[0]
    return bio_to_spans(labels)


def weak_spans(text: str, multi, single) -> set:
    _, spans = label_text(text, multi, single)
    return {(s["start"], s["end"]) for s in spans}


def _prf(golds, preds):
    # span_prf는 BIO seq를 받으므로 여기선 set 기반 직접 계산
    tp = fp = fn = 0
    for g, p in zip(golds, preds):
        tp += len(g & p); fp += len(p - g); fn += len(g - p)
    pr = tp / (tp + fp) if tp + fp else 0.0
    rc = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * pr * rc / (pr + rc) if pr + rc else 0.0
    return pr, rc, f1


def main() -> None:
    if not _GOLD.exists():
        sys.exit(f"gold_test.txt 없음 — make_review_set.py로 리뷰파일 만들어 교정 후 {_GOLD}로 저장하세요.")
    recs = load_gold(_GOLD)
    if not recs:
        sys.exit("채점 가능한 레코드 0 — gold_test.txt 형식 확인.")

    with _MODEL.open("rb") as fh:
        crf = pickle.load(fh)
    multi, single = build_dict(_DIR / "dict.txt", _DIR / "dict_item_master.txt")

    golds = [r["gold"] for r in recs]
    crf_p = [crf_spans(crf, r["text"]) for r in recs]
    weak_p = [weak_spans(r["text"], multi, single) for r in recs]

    print(f"gold 레코드: {len(recs)}건 (사람 검수)")
    for name, preds in [("약지도(사전)", weak_p), ("CRF", crf_p)]:
        pr, rc, f1 = _prf(golds, preds)
        print(f"  {name:12} vs gold — P {pr:.3f} · R {rc:.3f} · F1 {f1:.3f}")

    # CRF 오류 표본
    print("\n--- CRF 오류 표본(최대 5건) ---")
    shown = 0
    for r, p in zip(recs, crf_p):
        miss = r["gold"] - p          # 놓침
        extra = p - r["gold"]         # 오탐
        if (miss or extra) and shown < 5:
            t = r["text"]
            print(f"  {t[:45]}")
            if miss:
                print(f"    놓침: {[t[s:e] for s,e in sorted(miss)]}")
            if extra:
                print(f"    오탐: {[t[s:e] for s,e in sorted(extra)]}")
            shown += 1


if __name__ == "__main__":
    main()
