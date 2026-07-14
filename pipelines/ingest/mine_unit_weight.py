"""레시피 raw에서 낱개 단위무게 자동 도출 → item_unit_weight (src='MINED').

만개 레시피 ingredient_raw에 "대파 1대 125g"처럼 단위+그램이 병기된 걸 긁어 (품목,단위)→g 도출.
- 분수 파싱: "1/2개"=0.5, "반개"=0.5 (안 하면 양파 40g/개 처럼 오도출).
- 아웃라이어: 근거 n≥3 + MAD 트림 후 median.
- 계량단위(큰술/컵)는 제외 — 밀도(density) 경로 담당.
migrate_quantity.py 스키마 필요. 기본 DRY(도출 미리보기), 적재는 --commit.
사용:  python pipelines/ingest/mine_unit_weight.py [--commit]
"""
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect  # noqa: E402

UNITS = r"개|대|모|알|쪽|장|줌|톨|송이|봉|줄|마리|캔|팩|판|공기|포기|뿌리|족"
_FRAC = re.compile(rf"(\d+)\s*/\s*(\d+)\s*({UNITS})")
_HALF = re.compile(rf"반\s*({UNITS})")
_WHOLE = re.compile(rf"(\d+(?:\.\d+)?)\s*({UNITS})")
_GRAM = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|g)\b")
MIN_N = 3
BOUNDS = (0.5, 3000)   # g/단위 상식 범위 (분수 수정 후 median이 주 필터)


def parse_count(raw):
    m = _FRAC.search(raw)
    if m:
        return int(m.group(1)) / int(m.group(2)), m.group(3)
    m = _HALF.search(raw)
    if m:
        return 0.5, m.group(1)
    m = _WHOLE.search(raw)
    if m:
        return float(m.group(1)), m.group(2)
    return None, None


def parse_gram(raw):
    m = _GRAM.search(raw)
    if not m:
        return None
    return float(m.group(1)) * (1000 if m.group(2) == "kg" else 1)


def mad_median(vals):
    med = statistics.median(vals)
    mad = statistics.median([abs(v - med) for v in vals]) or 1
    kept = [v for v in vals if abs(v - med) <= 3.5 * mad] or vals
    return round(statistics.median(kept)), len(kept), len(vals)


def main():
    commit = "--commit" in sys.argv
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""select im.item_id, im.canonical_name, ri.ingredient_raw
            from recipe_ingredient ri join item_master im on im.item_id = ri.item_id
            join recipe r on r.id = ri.recipe_id
            where r.source = '10K' and ri.ingredient_raw ~ '[0-9]\\s*g'""")
        groups = defaultdict(list)   # (item_id, canonical, unit) → [g/단위]
        for item_id, canon, raw in cur.fetchall():
            g = parse_gram(raw)
            cnt, unit = parse_count(raw)
            if g and cnt and cnt > 0:
                gpu = g / cnt
                if BOUNDS[0] <= gpu <= BOUNDS[1]:
                    groups[(item_id, canon, unit)].append(gpu)

        seeds = {}
        for (item_id, canon, unit), vals in groups.items():
            if len(vals) >= MIN_N:
                grams, kept, total = mad_median(vals)
                seeds[(item_id, canon, unit)] = (grams, kept, total)

        print(f"도출 시드: {len(seeds)}개 (n≥{MIN_N}, 분수보정+MAD트림)\n")
        for (iid, canon, unit), (g, kept, tot) in sorted(seeds.items(), key=lambda x: -x[1][1])[:30]:
            print(f"  {canon:8} 1{unit:2} = {g:>4}g   (근거 {kept}/{tot})")

        if commit:
            for (item_id, _c, unit), (g, _k, _t) in seeds.items():
                cur.execute(
                    """insert into item_unit_weight (item_id, unit, grams, src)
                       values (%s,%s,%s,'MINED')
                       on conflict (item_id, unit) do update set
                         grams = excluded.grams, src = 'MINED'
                       where item_unit_weight.src = 'MINED'""",   # 수동(CURATED)은 안 덮음
                    (item_id, unit, g))
            conn.commit()
            print(f"\n[COMMIT] item_unit_weight {len(seeds)}행 upsert (MINED)")
        else:
            print("\n[DRY] 미적재. 적재는 --commit")


if __name__ == "__main__":
    main()
