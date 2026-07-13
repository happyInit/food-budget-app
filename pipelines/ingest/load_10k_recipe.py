"""만개의레시피 CSV → recipe / recipe_ingredient / recipe_step 적재 (COOKRCP01 교체).

소스(팀원 크롤 샘플, 4 CSV):
  공식_레시피.csv · 일반_검증완료_레시피.csv  → recipe(메타) + recipe_step(조리순서 분할)
  레시피_재료.csv                              → recipe_ingredient (재료명·수량 이미 분리)
  제외_레시피.csv                              → 제외 URL 필터

재료명은 크롤러가 분리해줌 → NER 불필요, gazetteer로 item_id만 해소. ner_status='CRAWLER'.
멱등: source in ('10K','COOKRCP01') 삭제 후 재적재(만개가 COOKRCP01 placeholder 교체).
CSV 경로: env RECIPE_10K_DIR (기본 = 팀원 샘플 WSL 경로).
"""
import csv
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect            # noqa: E402
from gazetteer import load_gazetteer, make_matcher, STOP  # noqa: E402

CSV_DIR = Path(os.environ.get("RECIPE_10K_DIR",
                              "/mnt/c/Users/hi/Downloads/만개의레시피샘플"))
META_FILES = ["공식_레시피.csv", "일반_검증완료_레시피.csv"]
STEP_SPLIT = re.compile(r"^\s*\d+[.)]\s*")     # "1. " / "2) " 선두번호 제거


def _rows(fname):
    with open(CSV_DIR / fname, encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f)


def parse_steps(blob):
    out = []
    for line in (blob or "").split("\n"):
        line = STEP_SPLIT.sub("", line.strip())
        if line:
            out.append(line)
    return out


def load(cur):
    excluded = {r["레시피URL"] for r in _rows("제외_레시피.csv")}
    cur.execute("delete from recipe where source in ('10K','COOKRCP01')")  # 교체

    # --- recipe (공식+일반) ---
    metas = {}     # 레시피ID → (제목, 시간, 난이도, 인원, 조리순서)
    for fname in META_FILES:
        for r in _rows(fname):
            if r["레시피URL"] in excluded or not r.get("레시피ID"):
                continue
            metas[r["레시피ID"]] = (r["제목"], r.get("시간"), r.get("난이도"),
                                    r.get("인원"), r.get("조리순서"))
    cur.executemany(
        """insert into recipe (source, src_recipe_id, name, cooking_time, level_nm, serving)
           values ('10K',%s,%s,%s,%s,%s) on conflict (source, src_recipe_id) do nothing""",
        [(rid, m[0], m[1], m[2], m[3]) for rid, m in metas.items()])

    cur.execute("select src_recipe_id, id from recipe where source='10K'")
    idmap = dict(cur.fetchall())

    # --- recipe_step ---
    steps = [(idmap[rid], i, desc)
             for rid, m in metas.items() if rid in idmap
             for i, desc in enumerate(parse_steps(m[4]), 1)]
    cur.executemany(
        "insert into recipe_step (recipe_id, step_no, description) values (%s,%s,%s)", steps)

    # --- recipe_ingredient (gazetteer item_id) ---
    match = make_matcher(load_gazetteer(cur))
    ings, hit, tot = [], 0, 0
    for r in _rows("레시피_재료.csv"):
        rid = idmap.get(r.get("레시피ID"))
        name = (r.get("재료명") or "").strip()
        if not rid or not name:
            continue
        iid = None if (name in STOP or name.replace(" ", "") in STOP) else match(name)[0]
        if name not in STOP:
            tot += 1
            hit += iid is not None
        ings.append((rid, _int(r.get("재료순번")), name, r.get("수량"),
                     r.get("재료원문"), iid))
    cur.executemany(
        """insert into recipe_ingredient
             (recipe_id, seq, ingredient_name, quantity, ingredient_raw, ner_status, item_id)
           values (%s,%s,%s,%s,%s,'CRAWLER',%s)""", ings)
    return len(idmap), len(steps), len(ings), hit, tot


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def main():
    with connect() as conn, conn.cursor() as cur:
        nr, ns, ni, hit, tot = load(cur)
        conn.commit()
    print(f"10K 적재: recipe {nr} · step {ns} · ingredient {ni}")
    print(f"  재료 item_id 매칭: {hit}/{tot} = {round(100*hit/tot,1)}%")


if __name__ == "__main__":
    main()
