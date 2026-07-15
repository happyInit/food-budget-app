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
import sys
import zlib
from pathlib import Path

# gazetteer STOP(물·기름·구매·고명·곁들이…) — 사전에서 제외해 재료로 라벨 안 되게 (precision↑)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipelines" / "ingest"))
try:
    from gazetteer import STOP as _GAZ_STOP  # noqa: E402
except Exception:  # noqa: BLE001
    _GAZ_STOP = set()
# STOP엔 없지만 콜론 앞 섹션 헤더로 자주 쓰이는 범용어(복합어 굴소스·닭육수는 별도 유지됨)
_HEADER_BLOCK = {"소스", "양념", "육수", "드레싱", "양념장", "재료", "주재료", "부재료", "찌개", "국물"}
_DICT_STOP = {s.replace(" ", "") for s in _GAZ_STOP} | _HEADER_BLOCK

_DIR = Path(__file__).parent / "data"
_BRACKET = re.compile(r"^\s*\[[^\]]*\]\s*")             # 사전어 정제용: "[불고기양념] 간장" → "간장"
_SECTION = re.compile(r"\[[^\]]*\]|[●·][^:\n]*[:：]")   # 타깃 섹션 마커: [..] / ●..: / ·..:
_HANGUL = re.compile(r"[가-힣]")
_TEST_MOD = 8
# 형태·가공 수식어 — 재료 앞 공백으로 붙으면 span에 포함(gold 관례: "마른 미역"=통째). 일반 규칙.
_SPAN_MODIFIERS = ("마른", "다진", "냉동", "건", "저염", "생", "삶은", "구운", "볶은", "데친", "말린", "플레인")
# 접미 — 재료 뒤 바로 붙으면 별개 재료 형태(오렌지주스≠오렌지). span 우측 확장.
_SPAN_SUFFIXES = ("주스", "즙", "퓨레")

# #1 정당한 1자 재료(사전에 존재 + 안전) — 토큰경계에서만 매칭. "물"은 STOP이라 제외(precision↑).
_SINGLE_WHITELIST = {"파", "무", "김", "쌀", "팥", "잣", "밤", "굴", "알", "술", "꿀", "잎", "쑥", "깨"}


def dict_paths() -> list[Path]:
    """data/dict*.txt 전부 — EPIS·item_master·자기학습(dict_selftrain) 자동 병합."""
    return sorted(_DIR.glob("dict*.txt"))


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
            if t.replace(" ", "") in _DICT_STOP:   # STOP·헤더성 단어는 사전에서 제외
                continue
            if len(t) >= 2:
                multi.add(t)
            elif len(t) == 1 and t in _SINGLE_WHITELIST:
                single.add(t)
    return sorted(multi, key=len, reverse=True), single


def _section_mask(text: str) -> list[bool]:
    """섹션 마커 영역 + 레시피 제목 줄 = True(라벨 금지). 원문 길이 보존."""
    mask = [False] * len(text)
    for m in _SECTION.finditer(text):
        for k in range(m.start(), m.end()):
            mask[k] = True
    # 제목 줄: COOKRCP01은 첫 줄이 요리명인 경우가 많다(새우두부계란찜). 재료 줄은 수량(숫자)이
    # 붙지만 제목은 숫자·쉼표가 없다 → 뒤에 재료 줄이 이어질 때만(=멀티라인) 첫 줄을 마스킹.
    nl = text.find("\n")
    if nl != -1:
        first = text[:nl]
        if first.strip() and not any(c.isdigit() for c in first) and "," not in first:
            for k in range(nl):
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
        # 수식어 확장: "마른 미역"이면 앞의 "마른 "까지 span에 포함(gold 관례 정렬)
        for mod in _SPAN_MODIFIERS:
            pref = mod + " "
            s2 = idx - len(pref)
            if s2 >= 0 and text[s2:idx] == pref and not any(used[s2:idx]) and not any(masked[s2:idx]):
                idx = s2
                break
        # 접미 확장: "오렌지주스"면 뒤의 "주스"까지 포함(오렌지≠오렌지주스, 별개 재료 형태)
        for suf in _SPAN_SUFFIXES:
            e2 = end + len(suf)
            if text[end:e2] == suf and not any(used[end:e2]) and not any(masked[end:e2]) \
                    and (e2 >= n or not _HANGUL.match(text[e2])):
                end = e2
                break
        for k in range(idx, end):
            used[k] = True
        tags[idx] = "B-ING"
        for k in range(idx + 1, end):
            tags[k] = "I-ING"
        spans.append({"start": idx, "end": end, "surface": text[idx:end]})

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
    multi, single = build_dict(*dict_paths())
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
