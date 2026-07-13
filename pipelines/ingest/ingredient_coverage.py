"""재료 매핑 커버리지 리포트 (품질 지표).

COOKRCP01 재료 원문(RAW)에서 head-noun을 뽑아 빈도·누적 커버리지를 계산하고,
현재 item_master가 재료 등장의 몇 %를 덮는지(=매핑률) 보고한다. 재실행으로 성숙도 추적.
부수 산출: data/ingredient_candidates.csv (item_master 확장 후보, 사람이 리뷰).
"""
import csv
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect  # noqa: E402

DIGIT = re.compile(r"[0-9¼-¾⅐-⅞]")
STOP = {"고명", "양념", "양념장", "소스", "곁들이", "재료", "기타", "약간", "적당량", "토핑", "육수",
        "물", "각"}  # 비재료/파싱노이즈 — 추적 대상 아님
OUT = Path(__file__).parent / "data" / "ingredient_candidates.csv"


def head_nouns():
    with connect() as c, c.cursor() as cur:
        cur.execute("select ingredient_raw from recipe_ingredient "
                    "where ner_status='RAW' and ingredient_raw is not null")
        blobs = [r[0] for r in cur.fetchall()]
    heads = Counter()
    for b in blobs:
        for piece in re.split(r"[,\n]", b):
            p = piece.strip()
            m = DIGIT.search(p)
            if not p or not m:
                continue
            name = re.sub(r"[·:()\[\]●▶]", " ", p[:m.start()]).strip()
            name = re.sub(r"^\d+인분", "", name).strip()
            if not name or not re.search(r"[가-힣]", name):
                continue
            head = name.split()[-1] if " " in name else name
            if head in STOP:
                continue
            heads[head] += 1
    return heads


def main():
    heads = head_nouns()
    total = sum(heads.values())
    with connect() as c, c.cursor() as cur:
        cur.execute("select alias from item_alias")     # 매핑률은 alias 경유(변형 흡수)
        aliases = {r[0] for r in cur.fetchall()}
        cur.execute("select count(*) from item_master")
        n_master = cur.fetchone()[0]

    # 후보 CSV
    OUT.parent.mkdir(exist_ok=True)
    acc = 0
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "head_noun", "freq", "cum_coverage_pct", "in_item_master"])
        for i, (h, n) in enumerate(heads.most_common(), 1):
            acc += n
            w.writerow([i, h, n, round(100 * acc / total, 1), "Y" if h in aliases else ""])

    covered = sum(n for h, n in heads.items() if h in aliases)
    print(f"재료 토큰(수량有): {total} · distinct head-noun: {len(heads)}")
    print(f"item_master {n_master} · alias {len(aliases)} → 매핑률: {round(100*covered/total,1)}%")
    print("상위 N 후보 누적 커버리지:", end=" ")
    a = 0
    for i, (_, n) in enumerate(heads.most_common(), 1):
        a += n
        if i in (100, 200, 300, 500):
            print(f"top{i}={round(100*a/total,1)}%", end=" ")
    print(f"\n후보 CSV: {OUT}")


if __name__ == "__main__":
    main()
