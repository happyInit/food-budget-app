"""② 약지도(weak supervision) 라벨링 — 사전으로 COOKRCP01 자유텍스트에 BIO 자동 라벨.

개선(초안 한계 대응, README §해결):
  #2 recall: EPIS + **item_master(canonical+alias)** 사전 증강 (공공데이터만, span 탐지용이라
             육류 코드 뭉갬 PR #54와 무관)
  #1 1자 재료: `_MIN_LEN=2`로 거른 뒤, **화이트리스트 1자어**를 **토큰경계**(앞뒤 비한글)에서만 매칭
             → "팥 15g"는 잡고 "팥소"는 안 잡음
  #4 섹션어 오탐: `[...]`·`●…:`·`·…:` 섹션 마커 영역을 **마스킹**(라벨 금지)해 "[시럽]" 등 제외
             (원문·문자오프셋은 보존 — 삭제 아님, ner-training-data-spec §1)

산출: data/labeled.jsonl (문자단위 BIO + span + 결정적 train/test 분할).
⚠️ 여전히 '약'지도 — CRF 학습 전 육안 검수 + HITL 보정 전제.
"""
from __future__ import annotations

import json
import re
import zlib
from pathlib import Path

_DIR = Path(__file__).parent / "data"
_BRACKET = re.compile(r"^\s*\[[^\]]*\]\s*")             # 사전어 정제용: "[불고기양념] 간장" → "간장"
_SECTION = re.compile(r"\[[^\]]*\]|[●·][^:\n]*[:：]")   # 타깃 섹션 마커: [..] / ●..: / ·..:
_HANGUL = re.compile(r"[가-힣]")
_TEST_MOD = 8

# #1 정당한 1자 재료(사전에 존재 + 안전) — 토큰경계에서만 매칭
_SINGLE_WHITELIST = {"물", "파", "무", "김", "쌀", "팥", "잣", "밤", "굴", "알", "술", "꿀", "잎", "쑥", "깨"}


def _clean(term: str) -> str:
    return _BRACKET.sub("", term).strip()


def build_dict(*paths: Path) -> tuple[list[str], set[str]]:
    """여러 사전 파일 → (다자어[≥2, 최장우선], 화이트리스트 1자어 집합)."""
    multi: set[str] = set()
    single: set[str] = set()
    for p in paths:
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            t = _clean(line)
            if len(t) >= 2:
                multi.add(t)
            elif len(t) == 1 and t in _SINGLE_WHITELIST:
                single.add(t)
    return sorted(multi, key=len, reverse=True), single


def _section_mask(text: str) -> list[bool]:
    """섹션 마커 영역 = True(라벨 금지). 원문 길이 보존."""
    mask = [False] * len(text)
    for m in _SECTION.finditer(text):
        for k in range(m.start(), m.end()):
            mask[k] = True
    return mask


def _is_left_boundary(text: str, i: int) -> bool:
    return i == 0 or not _HANGUL.match(text[i - 1])


def label_text(text: str, multi: list[str], single: set[str], mask_sections: bool = True):
    n = len(text)
    tags = ["O"] * n
    used = [False] * n
    masked = _section_mask(text) if mask_sections else [False] * n
    spans: list[dict] = []

    def _try(term: str, idx: int, boundary: bool) -> None:
        end = idx + len(term)
        if any(used[idx:end]) or any(masked[idx:end]):
            return
        if boundary and not (_is_left_boundary(text, idx) and (end >= n or not _HANGUL.match(text[end]))):
            return
        for k in range(idx, end):
            used[k] = True
        tags[idx] = "B-ING"
        for k in range(idx + 1, end):
            tags[k] = "I-ING"
        spans.append({"start": idx, "end": end, "surface": term})

    for term in multi:              # 다자어: 최장 우선, 비겹침
        start = 0
        while (idx := text.find(term, start)) != -1:
            _try(term, idx, boundary=False)
            start = idx + 1
    for term in single:             # 1자어: 토큰경계에서만
        start = 0
        while (idx := text.find(term, start)) != -1:
            _try(term, idx, boundary=True)
            start = idx + 1

    spans.sort(key=lambda s: s["start"])
    return tags, spans


def _split(src_recipe_id: str) -> str:
    return "test" if zlib.crc32(src_recipe_id.encode("utf-8")) % 10 >= _TEST_MOD else "train"


def main() -> None:
    multi, single = build_dict(_DIR / "dict.txt", _DIR / "dict_item_master.txt")
    rows = [json.loads(l) for l in (_DIR / "corpus.jsonl").read_text(encoding="utf-8").splitlines()]

    out = (_DIR / "labeled.jsonl").open("w", encoding="utf-8")
    n_text = n_with = n_span = n_char = n_ing = 0
    sc = {"train": 0, "test": 0}
    for r in rows:
        tags, spans = label_text(r["text"], multi, single)
        split = _split(r["src_recipe_id"])
        out.write(json.dumps({
            "src_recipe_id": r["src_recipe_id"], "seq": r.get("seq"),
            "text": r["text"], "labels": tags, "spans": spans, "split": split,
        }, ensure_ascii=False) + "\n")
        n_text += 1; n_span += len(spans); n_with += 1 if spans else 0
        n_char += len(r["text"]); n_ing += sum(1 for t in tags if t != "O"); sc[split] += 1
    out.close()

    print(f"사전: 다자어 {len(multi)} + 1자 화이트리스트 {len(single)}")
    print(f"라벨링: {n_text} 텍스트, span {n_span}")
    print(f"  span≥1: {n_with}/{n_text} = {round(100*n_with/n_text,1)}%")
    print(f"  평균 span/텍스트: {round(n_span/n_text,2)} · 재료 문자비율: {round(100*n_ing/n_char,1)}%")
    print(f"  분할: train {sc['train']} / test {sc['test']} → {_DIR/'labeled.jsonl'}")


if __name__ == "__main__":
    main()
