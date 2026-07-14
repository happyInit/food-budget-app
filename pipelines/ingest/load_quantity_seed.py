"""수동 curation 시드 → item_unit_weight(CURATED) + item_master.density_g_per_ml.

낱개무게(마이닝 미스 보강, data/unit_weight_seed.csv) + 계량 밀도(data/density_seed.csv).
canonical_name으로 item_master 매칭. CURATED는 MINED를 덮음(수동 우선).
사용:  python pipelines/ingest/load_quantity_seed.py
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect  # noqa: E402

DATA = Path(__file__).parent / "data"


def main():
    unmatched = []
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select canonical_name, item_id from item_master")
        idmap = dict(cur.fetchall())

        nw = 0
        with (DATA / "unit_weight_seed.csv").open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                iid = idmap.get(r["canonical_name"])
                if not iid:
                    unmatched.append(("낱개", r["canonical_name"]))
                    continue
                cur.execute(
                    """insert into item_unit_weight (item_id, unit, grams, src)
                       values (%s,%s,%s,'CURATED')
                       on conflict (item_id, unit) do update set
                         grams = excluded.grams, src = 'CURATED'""",
                    (iid, r["unit"], float(r["grams"])))
                nw += 1

        nd = 0
        with (DATA / "density_seed.csv").open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                iid = idmap.get(r["canonical_name"])
                if not iid:
                    unmatched.append(("밀도", r["canonical_name"]))
                    continue
                cur.execute("update item_master set density_g_per_ml=%s where item_id=%s",
                            (float(r["density"]), iid))
                nd += 1
        conn.commit()

    print(f"낱개무게 CURATED {nw}행 · 밀도 {nd}품목 적재")
    if unmatched:
        print("⚠️ item_master 미매칭(오타 의심):", unmatched)


if __name__ == "__main__":
    main()
