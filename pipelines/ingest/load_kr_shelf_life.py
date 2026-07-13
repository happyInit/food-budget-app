"""한식 원재료 소비기한 시드(CURATED) → shelf_life_ref 적재 (#4 보강).

값 = 식약처/USDA 소비자 보관 가이드 준거 참고값(정밀 DB 아님, 앱의 러프 추정·넛지용).
source='CURATED'로 FoodKeeper(FOODKEEPER)와 명확히 구분. 유니크키(source,item_name,storage).
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect  # noqa: E402

CSV = Path(__file__).parent / "data" / "kr_shelf_life_seed.csv"


def main():
    rows = []
    with CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append((
                r["food_category"] or None, r["item_name"], r["storage"],
                int(r["days_min"]) if r["days_min"] else None,
                int(r["days_max"]) if r["days_max"] else None,
                (r.get("note") or "").strip() or None,
            ))
    with connect() as conn, conn.cursor() as cur:
        cur.executemany(
            """insert into shelf_life_ref
                 (source, food_category, item_name, storage, days_min, days_max, note)
               values ('CURATED', %s, %s, %s, %s, %s, %s)
               on conflict (source, item_name, storage) do update set
                 food_category=excluded.food_category, days_min=excluded.days_min,
                 days_max=excluded.days_max, note=excluded.note, fetched_at=now()""",
            rows)
        conn.commit()
    print(f"CURATED 한식 시드: {len(rows)} shelf_life_ref rows upserted")


if __name__ == "__main__":
    main()
