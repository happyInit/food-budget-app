"""④-a HITL gold 테스트셋 — 사람 검수용 리뷰 파일 생성.

진짜 성능(span F1)은 사람이 라벨링한 gold로 재야 한다(README §CRF 학습 결과의 caveat).
여기서는 사람이 **처음부터 라벨링하지 않고 '약지도 초안을 고치기만'** 하도록 사전채움한다(HITL 효율).

동작:
- test 분할에서 결정적 N개 샘플.
- 각 텍스트의 약지도 span을 `{{재료}}`로 감싼 편집용 라인 생성.
- data/gold_review.txt 출력 — 한 레코드 = 2줄:
    `#<idx>\t<원문>`        ← 불변(참고·채점 기준), 수정 금지
    `=<idx>\t{{...}} ...`   ← **편집 대상**: 잘못 잡힌 {{}} 제거, 놓친 재료에 {{}} 추가

사용:
1) python make_review_set.py
2) data/gold_review.txt 를 열어 `=` 줄의 {{}}만 사람이 교정 → ml/ingredient-ner/gold_test.txt 로 저장
3) python score_gold.py   (약지도·CRF 각각의 진짜 span F1)

마커는 `{{ }}` — 원문의 `[..]`(섹션)와 안 겹치게 선택.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

_DIR = Path(__file__).parent / "data"
_N = 50
_SEED = 20260715


def annotate(text: str, spans: list[dict]) -> str:
    """span(start,end)을 {{ }}로 감싼 문자열. 왼→오른쪽 삽입."""
    out, cur = [], 0
    for s in sorted(spans, key=lambda x: x["start"]):
        out.append(text[cur:s["start"]])
        out.append("{{" + text[s["start"]:s["end"]] + "}}")
        cur = s["end"]
    out.append(text[cur:])
    return "".join(out)


def main() -> None:
    rows = [json.loads(l) for l in (_DIR / "labeled.jsonl").read_text(encoding="utf-8").splitlines()]
    test = [r for r in rows if r.get("split") == "test" and r["text"].strip()]
    sample = random.Random(_SEED).sample(test, min(_N, len(test)))

    lines = [
        "# HITL gold 리뷰 — '=' 줄의 {{재료}}만 교정하세요(원문/# 줄은 수정 금지).",
        "#   잘못 잡힘 → {{}} 제거 · 놓침 → 해당 재료에 {{}} 추가.",
        "#   교정 후 이 파일을 ml/ingredient-ner/gold_test.txt 로 저장 → score_gold.py",
        "",
    ]
    for idx, r in enumerate(sample):
        lines.append(f"#{idx}\t{r['text']}")
        lines.append(f"={idx}\t{annotate(r['text'], r['spans'])}")
        lines.append("")

    (_DIR / "gold_review.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"리뷰셋 {len(sample)}건 → {_DIR/'gold_review.txt'}")
    print("→ '=' 줄의 {{}}를 사람이 교정 후 ml/ingredient-ner/gold_test.txt 로 저장하세요.")


if __name__ == "__main__":
    main()
