"""정규화 인덱스 오프라인 빌더 — item_master 스냅샷에서 '변형→표준철자' 후보를 1회 생성.

혼자 진행 가능(솔로): item_master를 **읽기전용**으로 채굴해 변형표기 후보를 만들 뿐,
카탈로그(item_id)는 안 바꾼다. 산출 = 검토시트(alias_review.tsv). 사람이 빈도 head만
검토해 골라 app/data/aliases.json 에 확정 → 런타임 normalize.py가 로드.

⚠️ 오프라인 1회성. 런타임(챗봇) 호출 없음 — 사용자 응답속도 무영향. item_master가 크게
   늘 때만 재실행(dict_gemini 재실행 룰과 동일 정신).

후보 소스 2종(테스트로 확인된 유효 소스):
  rule   : 생산적 철자규칙 역생성(요거트 포함 표준명 → 요구르트 변형). 고신뢰, 거의 그대로 채택.
  gemini : (옵션 --gemini) 오프라인 1회 LLM 의미제안 — gemini_dict.py 패턴. 비생산적 변형의
           유일한 recall 레버(외래어 변형은 문자유사도=0이라 규칙/의미제안으로만 잡힘).
  ✗ 문자유사도 클러스터링은 제외 — 표준명끼리의 morphology(홍파프리카~파프리카)만 나오는데
    그건 (a) matcher가 이미 suffix/prefix로 처리, (b) granularity=Taylor 소관, (c) 외래어
    변형은 애초에 못 잡음. 이 문제엔 무용해서 뺌.

사용: python -m tools.build_alias [--snapshot PATH] [--corpus PATH] [--gemini]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_CHAT = _HERE.parent
_REPO = _CHAT.parent.parent
# 기본 스냅샷 = NER 파이프라인이 export한 item_master 표준명 목록(읽기전용)
_DEFAULT_SNAPSHOT = _REPO / "ml" / "ingredient-ner" / "data" / "dict_item_master.txt"
_DEFAULT_CORPUS = _REPO / "ml" / "ingredient-ner" / "data" / "corpus.jsonl"
_OUT = _HERE / "alias_review.tsv"

# 생산적 철자·외래어 규칙 (표준철자, 변형철자) — normalize._RULES 와 방향 일치.
# 표준명에 표준철자가 있으면 변형철자 버전을 후보로 역생성한다. 빌더 검토로 확장.
_PRODUCTIVE = [("요거트", "요구르트")]


def _load_canonicals(path: Path) -> list[str]:
    if not path.exists():
        raise SystemExit(f"스냅샷 없음: {path} — export_corpus.py로 dict_item_master.txt 생성 후 지정.")
    seen, out = set(), []
    for line in path.read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _freq(corpus: Path, terms: list[str]) -> Counter:
    """표준명별 코퍼스 등장 텍스트 수 — head 우선순위용(없으면 0)."""
    cnt: Counter = Counter()
    if not corpus.exists():
        return cnt
    texts = [json.loads(l)["text"] for l in corpus.read_text(encoding="utf-8").splitlines() if l.strip()]
    for t in terms:
        key = t.replace(" ", "")
        cnt[t] = sum(1 for x in texts if key in x.replace(" ", ""))
    return cnt


def _gemini_candidates(canonicals: list[str]) -> list[tuple[str, str]]:
    raise NotImplementedError(
        "gemini 후보생성 미구현 훅 — ml/ingredient-ner/gemini_dict.py 의 오프라인 배치 패턴을 이식하세요"
        "(system: 표준명별 흔한 철자/외래어 변형만 제안, 정규화·번역 금지). 오프라인 1회, 수십원."
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", type=Path, default=_DEFAULT_SNAPSHOT)
    ap.add_argument("--corpus", type=Path, default=_DEFAULT_CORPUS)
    ap.add_argument("--gemini", action="store_true", help="오프라인 LLM 의미제안 후보 추가(기본 off)")
    args = ap.parse_args()

    canon = _load_canonicals(args.snapshot)
    canon_set = {c.replace(" ", "") for c in canon}
    freq = _freq(args.corpus, canon)

    rows: list[tuple[int, str, str, str]] = []
    seen: set[str] = set()

    def add(variant: str, canonical: str, source: str) -> None:
        vk = variant.replace(" ", "")
        # 이미 표준명이면(matcher가 잡음) 불필요 · 중복 · 자기자신 제외
        if not vk or vk in canon_set or vk in seen or vk == canonical.replace(" ", ""):
            return
        seen.add(vk)
        rows.append((freq.get(canonical, 0), source, variant, canonical))

    for c in canon:                              # rule: 생산적 규칙 역생성
        for std, var in _PRODUCTIVE:
            if std in c:
                add(c.replace(std, var), c, "rule")

    if args.gemini:                              # gemini: 오프라인 의미제안(옵션)
        for variant, canonical in _gemini_candidates(canon):
            add(variant, canonical, "gemini")

    rows.sort(key=lambda r: (-r[0], r[1]))       # 빈도 head 우선
    with _OUT.open("w", encoding="utf-8") as fh:
        fh.write("# freq\tsource\tvariant\tproposed_canonical  (검토 후 채택행을 aliases.json으로)\n")
        for f, src, var, can in rows:
            fh.write(f"{f}\t{src}\t{var}\t{can}\n")

    print(f"표준명 {len(canon)}개 · 후보 {len(rows)}행 → {_OUT}")
    print("  소스별: " + ", ".join(f"{s}={sum(1 for r in rows if r[1] == s)}"
                                   for s in ("rule", "gemini")))
    print("  다음: 빈도 head만 검토 → app/data/aliases.json 에 {변형:표준명} 확정")
    if not args.gemini:
        print("  (recall 더 원하면 --gemini: 외래어·비생산적 변형까지 오프라인 1회 제안)")


if __name__ == "__main__":
    main()
