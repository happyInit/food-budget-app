"""만개의레시피 CSV → recipe / recipe_ingredient / recipe_step 적재 (COOKRCP01 교체).

소스(팀원 크롤 샘플, 4 CSV):
  공식_레시피.csv · 일반_검증완료_레시피.csv  → recipe(메타) + recipe_step(조리순서 분할)
  레시피_재료.csv                              → recipe_ingredient (재료명·수량 이미 분리)
  제외_레시피.csv                              → 제외 URL 필터

재료명은 크롤러가 분리해줌 → NER 불필요, gazetteer로 item_id만 해소. ner_status='CRAWLER'.
멱등: recipe upsert(source,src_recipe_id) · step/ingredient per-recipe delete+insert (COOKRCP01 교체 완료).
전처리 로직 process_recipe()는 배치·Kafka 컨슈머 공용(build_recipe_records=CSV, 컨슈머=메시지).
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


def build_recipe_records():
    """4 CSV → 레시피별 중첩 레코드 제너레이터 (재료·스텝 nested). 배치·Kafka 프로듀서 공용."""
    excluded = {r["레시피URL"] for r in _rows("제외_레시피.csv")}
    recs = {}       # 레시피ID → 레코드
    for fname in META_FILES:
        for r in _rows(fname):
            if r["레시피URL"] in excluded or not r.get("레시피ID"):
                continue
            recs[r["레시피ID"]] = {
                "src_recipe_id": r["레시피ID"], "name": r["제목"],
                "cooking_time": r.get("시간"), "level_nm": r.get("난이도"),
                "serving": r.get("인원"), "steps": parse_steps(r.get("조리순서")),
                "ingredients": [],
            }
    for r in _rows("레시피_재료.csv"):
        rec = recs.get(r.get("레시피ID"))
        if rec is not None:
            rec["ingredients"].append({
                "seq": _int(r.get("재료순번")), "name": (r.get("재료명") or "").strip(),
                "quantity": r.get("수량"), "raw": r.get("재료원문"),
            })
    yield from recs.values()


def process_recipe(cur, rec, match):
    """단일 레시피(재료·스텝 nested) → recipe/step/ingredient. 브로커 무관(배치·Kafka 컨슈머 공용).
    멱등: recipe upsert(source,src_recipe_id) · step/ingredient은 per-recipe delete+insert.
    반환 (n_step, n_ing, hit, tot)."""
    cur.execute(
        """insert into recipe (source, src_recipe_id, name, cooking_time, level_nm, serving)
           values ('10K',%s,%s,%s,%s,%s)
           on conflict (source, src_recipe_id) do update
             set name=excluded.name, cooking_time=excluded.cooking_time,
                 level_nm=excluded.level_nm, serving=excluded.serving
           returning id""",
        (rec["src_recipe_id"], rec["name"], rec.get("cooking_time"),
         rec.get("level_nm"), rec.get("serving")))
    rid = cur.fetchone()[0]
    cur.execute("delete from recipe_step where recipe_id=%s", (rid,))
    cur.execute("delete from recipe_ingredient where recipe_id=%s", (rid,))

    steps = [(rid, i, d) for i, d in enumerate(rec.get("steps") or [], 1)]
    cur.executemany(
        "insert into recipe_step (recipe_id, step_no, description) values (%s,%s,%s)", steps)

    ings, hit, tot = [], 0, 0
    for ing in rec.get("ingredients") or []:
        name = (ing.get("name") or "").strip()
        if not name:
            continue
        iid = None if (name in STOP or name.replace(" ", "") in STOP) else match(name)[0]
        if name not in STOP:
            tot += 1
            hit += iid is not None
        ings.append((rid, ing.get("seq"), name, ing.get("quantity"), ing.get("raw"), iid))
    cur.executemany(
        """insert into recipe_ingredient
             (recipe_id, seq, ingredient_name, quantity, ingredient_raw, ner_status, item_id)
           values (%s,%s,%s,%s,%s,'CRAWLER',%s)""", ings)
    return len(steps), len(ings), hit, tot


def load(cur):
    """배치: 전 레시피 레코드 → process_recipe 반복. (per-recipe 멱등 upsert)"""
    match = make_matcher(load_gazetteer(cur))
    nr = ns = ni = hit = tot = 0
    for rec in build_recipe_records():
        s, i, h, t = process_recipe(cur, rec, match)
        nr += 1; ns += s; ni += i; hit += h; tot += t
    return nr, ns, ni, hit, tot


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
