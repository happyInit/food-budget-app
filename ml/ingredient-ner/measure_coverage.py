"""약지도 라벨링 커버리지 before/after 실측 — 초안(EPIS만) vs 개선(사전증강+1자+섹션마스크).

before = 초안: EPIS 사전만, ≥2자, 1자·섹션마스크 없음
after  = 개선: EPIS + item_master 사전, 1자 화이트리스트(경계), 섹션 마스킹
"""
from __future__ import annotations

import json
from pathlib import Path

from weak_label import _DIR, build_dict, label_text


def _stats(rows, multi, single, mask):
    n = with_span = span = char = ing = 0
    surfaces = set()
    for r in rows:
        tags, spans = label_text(r["text"], multi, single, mask_sections=mask)
        n += 1
        span += len(spans)
        with_span += 1 if spans else 0
        char += len(r["text"])
        ing += sum(1 for t in tags if t != "O")
        surfaces.update(s["surface"] for s in spans)
    return {
        "span≥1 %": round(100 * with_span / n, 1),
        "0건 텍스트": n - with_span,
        "총 span": span,
        "평균 span/텍스트": round(span / n, 2),
        "재료 문자비율 %": round(100 * ing / char, 1),
        "고유 재료표현": len(surfaces),
    }


def main() -> None:
    rows = [json.loads(l) for l in (_DIR / "corpus.jsonl").read_text(encoding="utf-8").splitlines()]

    # before: EPIS 사전만 · 1자 없음 · 섹션마스크 off
    epis_multi, _ = build_dict(_DIR / "dict.txt")
    before = _stats(rows, epis_multi, set(), mask=False)

    # after: EPIS + item_master · 1자 화이트리스트 · 섹션마스크 on
    all_multi, single = build_dict(_DIR / "dict.txt", _DIR / "dict_item_master.txt")
    after = _stats(rows, all_multi, single, mask=True)

    print(f"타깃 텍스트: {len(rows)}")
    print(f"사전 크기: before(EPIS) 다자어 {len(epis_multi)} → after(+item_master) 다자어 {len(all_multi)} + 1자 {len(single)}\n")
    keys = list(before)
    w = max(len(k) for k in keys)
    print(f"{'지표':<{w}}  {'before':>10}  {'after':>10}  {'Δ':>8}")
    print("-" * (w + 34))
    for k in keys:
        b, a = before[k], after[k]
        d = round(a - b, 1)
        print(f"{k:<{w}}  {b:>10}  {a:>10}  {d:>+8}")


if __name__ == "__main__":
    main()
