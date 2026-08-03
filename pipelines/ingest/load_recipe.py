"""공공 레시피 → recipe / recipe_ingredient / recipe_step 적재 (#5).

- COOKRCP01(식약처): 재료가 자유텍스트(RCP_PARTS_DTLS) → ner_status=RAW (NER 대상)
- 농교원 EPIS(3 grid, RECIPE_ID 조인): 재료 정형(IRDNT_NM/CPCTY) → ner_status=LABELED (NER 학습 라벨)

무키 'sample' 키는 각 소스 5행 상한. 전량은 data.go.kr 활용신청 후 실키로 교체(아래 KEY 변수).
"""
import os
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect  # noqa: E402
from gazetteer import load_gazetteer, make_matcher, load_meat_canons  # noqa: E402

FS_KEY = os.environ.get("RECIPE_DB_KEY") or os.environ.get("FOODSAFETY_API_KEY") or "sample"  # 식품안전나라 keyId
EPIS_KEY = os.environ.get("EPIS_KEY") or os.environ.get("EPIS_API_KEY") or "sample"  # 농교원 키(활용신청 후)
FS = "http://openapi.foodsafetykorea.go.kr/api/{key}/COOKRCP01/json/{s}/{e}"
# NOSONAR(S1313): 농교원 EPIS 가 IP 로 공개한 엔드포인트 — 우리 인프라가 아니라 살아 있는 외부 주소다.
EPIS = "http://211.237.50.150:7080/openapi/{key}/json/{grid}/{s}/{e}"  # NOSONAR
G_BASE, G_IRDNT, G_STEP = (
    "Grid_20150827000000000226_1",
    "Grid_20150827000000000227_1",
    "Grid_20150827000000000228_1",
)


def _num(v):
    if not v:
        return None
    m = re.search(r"[\d.]+", str(v).replace(",", ""))
    return float(m.group()) if m else None


def load_cookrcp01(cur, chunk=1000):
    total = 0
    start = 1
    while True:  # 식품안전나라 1회 최대 1000건 → 페이징. sample키는 5건서 break.
        data = requests.get(FS.format(key=FS_KEY, s=start, e=start + chunk - 1),
                            timeout=60).json()["COOKRCP01"]
        rows = data.get("row", [])
        if not rows:
            break
        _cookrcp01_rows(cur, rows)
        total += len(rows)
        if len(rows) < chunk:
            break
        start += chunk
    return total


def _cookrcp01_rows(cur, rows):
    for r in rows:
        cur.execute(
            """insert into recipe (source, src_recipe_id, name, category, cook_method,
                 kcal, carb_g, protein_g, fat_g, sodium_mg, serving, image_url)
               values ('COOKRCP01',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               on conflict (source, src_recipe_id) do update set name=excluded.name
               returning id""",
            (r["RCP_SEQ"], r["RCP_NM"], r.get("RCP_PAT2"), r.get("RCP_WAY2"),
             _num(r.get("INFO_ENG")), _num(r.get("INFO_CAR")), _num(r.get("INFO_PRO")),
             _num(r.get("INFO_FAT")), _num(r.get("INFO_NA")), r.get("INFO_WGT") or None,
             r.get("ATT_FILE_NO_MK") or None),
        )
        rid = cur.fetchone()[0]
        cur.execute("delete from recipe_ingredient where recipe_id=%s", (rid,))
        cur.execute("delete from recipe_step where recipe_id=%s", (rid,))
        # 재료 = 자유텍스트 원문 1행 (NER 대상)
        parts = (r.get("RCP_PARTS_DTLS") or "").strip()
        if parts:
            cur.execute(
                """insert into recipe_ingredient (recipe_id, seq, ingredient_raw, ner_status)
                   values (%s,1,%s,'RAW')""", (rid, parts))
        # 조리순서 MANUAL01..20
        for i in range(1, 21):
            desc = (r.get(f"MANUAL{i:02d}") or "").strip()
            if not desc:
                continue
            img = (r.get(f"MANUAL_IMG{i:02d}") or "").strip() or None
            cur.execute(
                """insert into recipe_step (recipe_id, step_no, description, image_url)
                   values (%s,%s,%s,%s)""", (rid, i, desc, img))
    return len(rows)


def _epis(grid, chunk=1000):  # 전량 페이징 — grid마다 행수 상이(base 537 < irdnt 6천), 요청상한 1000
    out, start = [], 1
    while True:
        rows = requests.get(EPIS.format(key=EPIS_KEY, grid=grid, s=start, e=start + chunk - 1),
                            timeout=40).json().get(grid, {}).get("row", [])  # 미승인 grid → 빈 리스트
        out += rows
        if len(rows) < chunk:
            return out
        start += chunk


def load_epis(cur):
    match = make_matcher(load_gazetteer(cur), load_meat_canons(cur))  # 재료명 → 표준품목 item_id (종세분화 가드)
    base = _epis(G_BASE)
    irdnt = _epis(G_IRDNT)
    steps = _epis(G_STEP)
    ids = {}
    for r in base:
        cur.execute(
            """insert into recipe (source, src_recipe_id, name, category, cooking_time,
                 level_nm, kcal, serving)
               values ('EPIS',%s,%s,%s,%s,%s,%s,%s)
               on conflict (source, src_recipe_id) do update set name=excluded.name
               returning id""",
            (str(r["RECIPE_ID"]), r["RECIPE_NM_KO"], r.get("TY_NM"), r.get("COOKING_TIME"),
             r.get("LEVEL_NM"), _num(r.get("CALORIE")), r.get("QNT")),
        )
        rid = cur.fetchone()[0]
        ids[r["RECIPE_ID"]] = rid
        cur.execute("delete from recipe_ingredient where recipe_id=%s", (rid,))
        cur.execute("delete from recipe_step where recipe_id=%s", (rid,))
    for r in irdnt:  # 정형 재료 = LABELED (+ gazetteer로 item_id 매칭 → 영양·분량 조인 활성화)
        rid = ids.get(r["RECIPE_ID"])
        if rid:
            item_id = match(r.get("IRDNT_NM"))[0]
            cur.execute(
                """insert into recipe_ingredient (recipe_id, seq, ingredient_name, quantity, ner_status, item_id)
                   values (%s,%s,%s,%s,'LABELED',%s)""",
                (rid, r.get("IRDNT_SN"), r.get("IRDNT_NM"), r.get("IRDNT_CPCTY"), item_id))
    for r in steps:
        rid = ids.get(r["RECIPE_ID"])
        if rid:
            cur.execute(
                """insert into recipe_step (recipe_id, step_no, description, image_url)
                   values (%s,%s,%s,%s)""",
                (rid, r.get("COOKING_NO"), r.get("COOKING_DC"), r.get("STRE_STEP_IMAGE_URL")))
    return len(base)


def main():
    with connect() as conn, conn.cursor() as cur:
        n1 = load_cookrcp01(cur)
        conn.commit()                    # 소스별 독립 커밋 — EPIS 실패가 COOKRCP01 롤백 안 하게
        n2 = load_epis(cur)
        conn.commit()
    mask = lambda k: "real" if k != "sample" else "sample"   # 키 값 로그 노출 금지
    print(f"recipe: COOKRCP01 {n1} + EPIS {n2} recipes loaded "
          f"(keys: FS={mask(FS_KEY)}, EPIS={mask(EPIS_KEY)})")


if __name__ == "__main__":
    main()
