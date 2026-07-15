"""② 약지도(weak supervision) 라벨링 — EPIS gold 재료명 사전으로 COOKRCP01 자유텍스트에
자동 BIO 라벨을 붙인다. 사람 검수(HITL) 전 1차 자동 라벨.

방법:
1. 사전 정제: EPIS 재료명의 `[불고기양념]` 같은 섹션 접두 제거, 공백정리, 최소길이 필터.
2. 최장·비겹침 문자 매칭: 각 자유텍스트에서 사전 표현을 긴 것부터 겹치지 않게 찾아 span.
3. 문자 단위 BIO 부여: 매칭 span의 첫 글자 B-ING, 이후 I-ING, 나머지 O.
   (문자 오프셋 보존 = ner-training-data-spec §1. 형태소 단위는 후속 개선 여지 — README 참고.)

산출: data/labeled.jsonl (텍스트별 문자열·문자·BIO·span + train/test 분할 플래그)
      + 커버리지 통계 stdout.

⚠️ 이건 '약'지도라 라벨에 노이즈가 있다(사전 미등재 재료 누락, 부분매칭 등). CRF 학습 전
샘플 수십 건 육안 검수 + HITL 보정이 전제(README §다음 단계).
"""
from __future__ import annotations

import json
import re
import zlib
from pathlib import Path

_DIR = Path(__file__).parent / "data"
_BRACKET = re.compile(r"^\s*\[[^\]]*\]\s*")   # "[불고기양념] 간장" → "간장"
_MIN_LEN = 2                                    # 1자 사전어(물·파…)는 오탐↑ → 기본 제외(설정)
_TEST_MOD = 8                                   # hash % 10 >= 8 → test (결정적 20% 분할)


def clean_dict(path: Path) -> list[str]:
    terms: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        t = _BRACKET.sub("", line).strip()
        if len(t) >= _MIN_LEN:
            terms.add(t)
    # 최장 우선(부분어보다 긴 재료명을 먼저 잡아 겹침 방지: "칵테일새우"가 "새우"보다 먼저)
    return sorted(terms, key=len, reverse=True)


def label_text(text: str, terms: list[str]) -> tuple[list[str], list[dict]]:
    n = len(text)
    tags = ["O"] * n
    used = [False] * n
    spans: list[dict] = []
    for term in terms:
        start = 0
        while (idx := text.find(term, start)) != -1:
            end = idx + len(term)
            if not any(used[idx:end]):
                for k in range(idx, end):
                    used[k] = True
                tags[idx] = "B-ING"
                for k in range(idx + 1, end):
                    tags[k] = "I-ING"
                spans.append({"start": idx, "end": end, "surface": term})
            start = idx + 1
    spans.sort(key=lambda s: s["start"])
    return tags, spans


def _split(src_recipe_id: str) -> str:
    # 결정적 분할 — 같은 레시피는 항상 같은 쪽(ner-training-data-spec §4 원칙1)
    h = zlib.crc32(src_recipe_id.encode("utf-8")) % 10
    return "test" if h >= _TEST_MOD else "train"


def main() -> None:
    terms = clean_dict(_DIR / "dict.txt")
    rows = [json.loads(l) for l in (_DIR / "corpus.jsonl").read_text(encoding="utf-8").splitlines()]

    out = (_DIR / "labeled.jsonl").open("w", encoding="utf-8")
    n_text = n_with_span = n_span = n_char = n_char_ing = 0
    split_count = {"train": 0, "test": 0}
    for r in rows:
        text = r["text"]
        tags, spans = label_text(text, terms)
        split = _split(r["src_recipe_id"])
        out.write(json.dumps({
            "src_recipe_id": r["src_recipe_id"], "seq": r.get("seq"),
            "text": text, "chars": list(text), "labels": tags,
            "spans": spans, "split": split,
        }, ensure_ascii=False) + "\n")
        n_text += 1
        n_span += len(spans)
        n_with_span += 1 if spans else 0
        n_char += len(text)
        n_char_ing += sum(1 for t in tags if t != "O")
        split_count[split] += 1
    out.close()

    print(f"사전(정제 후): {len(terms)}개")
    print(f"라벨링: {n_text}개 텍스트, span {n_span}개")
    print(f"  span≥1 텍스트: {n_with_span}/{n_text} = {round(100*n_with_span/n_text,1)}%")
    print(f"  평균 span/텍스트: {round(n_span/n_text,2)}")
    print(f"  재료로 라벨된 문자 비율: {round(100*n_char_ing/n_char,1)}%")
    print(f"  분할: train {split_count['train']} / test {split_count['test']}")
    print(f"→ {_DIR/'labeled.jsonl'}")


if __name__ == "__main__":
    main()
