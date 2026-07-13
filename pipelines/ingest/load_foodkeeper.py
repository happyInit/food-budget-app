"""USDA FoodKeeper(CC0) → shelf_life_ref 적재 (Pantry 유통기한 추정, #4).

원칙: 서비스가 쓰는 것만. 8개 보관시나리오를 ROOM/FRIDGE/FREEZER 3종으로 접고,
소비기한을 '일(day)'로 정규화, 구매일 앵커 모델이라 DOP(구매일 기준) 값을 우선 채택.
라이브 서버는 Akamai 403 → Wayback 스냅샷(2018 이후 정적이라 안전).
"""
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect  # noqa: E402

URL = ("http://web.archive.org/web/20250702182320id_/"
       "https://www.fsis.usda.gov/shared/data/EN/foodkeeper.json")
FACTOR = {"Day": 1, "Days": 1, "Week": 7, "Weeks": 7,
          "Month": 30, "Months": 30, "Year": 365, "Years": 365}
STORAGES = {  # 서비스 보관위치 : 원본 접두어(DOP 우선)
    "ROOM":    ["DOP_Pantry", "Pantry"],
    "FRIDGE":  ["DOP_Refrigerate", "Refrigerate"],
    "FREEZER": ["DOP_Freeze", "Freeze"],
}


def rowdict(cells):
    d = {}
    for c in cells:
        d.update(c)
    return d


def pick(row, prefixes):
    for p in prefixes:
        mn, mx, me = row.get(f"{p}_Min"), row.get(f"{p}_Max"), row.get(f"{p}_Metric")
        if me is not None or mn is not None or mx is not None:
            return mn, mx, me
    return None, None, None


def norm(mn, mx, me):
    if me in FACTOR:
        f = FACTOR[me]
        return (int(mn * f) if mn is not None else None,
                int(mx * f) if mx is not None else None, None)
    return None, None, (me or None)  # 상태값(When Ripe/Indefinitely/…)은 note로


def build_rows(d):
    sheets = {s["name"]: s["data"] for s in d["sheets"]}
    cats = {}
    for cells in sheets["Category"]:
        c = rowdict(cells)
        cats[c.get("ID")] = c.get("Category_Name")
    rows = []
    for cells in sheets["Product"]:
        p = rowdict(cells)
        name = p.get("Name")
        if not name:
            continue
        sub = p.get("Name_subtitle")
        item = f"{name}, {sub}" if sub else name
        category = cats.get(p.get("Category_ID"))
        for storage, prefixes in STORAGES.items():
            mn, mx, me = pick(p, prefixes)
            dmin, dmax, note = norm(mn, mx, me)
            if dmin is None and dmax is None and note is None:
                continue
            rows.append((category, item, storage, dmin, dmax, note))
    return rows


def main():
    d = requests.get(URL, timeout=60, headers={"User-Agent": "Mozilla/5.0"}).json()
    rows = build_rows(d)
    with connect() as conn, conn.cursor() as cur:
        cur.executemany(
            """insert into shelf_life_ref
                 (source, food_category, item_name, storage, days_min, days_max, note)
               values ('FOODKEEPER', %s, %s, %s, %s, %s, %s)
               on conflict (source, item_name, storage) do update set
                 food_category = excluded.food_category, days_min = excluded.days_min,
                 days_max = excluded.days_max, note = excluded.note, fetched_at = now()""",
            rows,
        )
        conn.commit()
    print(f"FoodKeeper: {len(rows)} shelf_life_ref rows upserted")


if __name__ == "__main__":
    main()
