"""식약처 전국통합식품영양성분 표준데이터(CSV) → food_nutrition 적재 (#5 영양성분).

원재료성식품(R)·가공식품(P) 표준데이터 파일 공용. 47~58컬럼 중 서비스가 쓰는 9필드만 매핑.
컬럼 구성이 파일마다 달라(부가컬럼·공백) 헤더를 '공백 제거 정규화'로 찾는다.
영양치는 per-100g/100ml 기준(영양성분함량기준량) — serving_g엔 기준량 숫자(=100)만. 빈칸은 NULL.
food_cd PK 멱등 upsert. item_id(표준품목 앵커)는 여기서 채우지 않음 — 별도 앵커링 단계.

사용:  python pipelines/ingest/load_nutrition.py [csv경로 ...]   # 기본: 원재료성식품 파일
"""
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect, repo_path  # noqa: E402

DEFAULT = ["전국통합식품영양성분정보_원재료성식품_표준데이터.csv"]

# 우리 9필드 ← 표준데이터 컬럼명(공백 제거 기준으로 매칭)
COLS = {
    "food_cd": "식품코드", "food_name": "식품명", "serving_g": "영양성분함량기준량",
    "kcal": "에너지(kcal)", "carb_g": "탄수화물(g)", "protein_g": "단백질(g)",
    "fat_g": "지방(g)", "sugar_g": "당류(g)", "sodium_mg": "나트륨(mg)",
}


def _num(v):
    """숫자만 추출. 빈칸/'-'/'Tr'(미량) 등 → None."""
    if not v:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", v.replace(",", ""))
    return float(m.group()) if m else None


def read_rows(path):
    with open(path, encoding="cp949") as f:
        r = csv.DictReader(f)
        norm = {h.replace(" ", ""): h for h in r.fieldnames}     # 정규화헤더 → 실제헤더
        col = {k: norm[v.replace(" ", "")] for k, v in COLS.items()}
        for row in r:
            yield (
                row[col["food_cd"]], row[col["food_name"]], _num(row[col["serving_g"]]),
                _num(row[col["kcal"]]), _num(row[col["carb_g"]]), _num(row[col["protein_g"]]),
                _num(row[col["fat_g"]]), _num(row[col["sugar_g"]]), _num(row[col["sodium_mg"]]),
            )


def main():
    files = sys.argv[1:] or DEFAULT
    total = 0
    with connect() as conn, conn.cursor() as cur:
        for f in files:
            path = Path(f) if Path(f).exists() else repo_path(f)
            rows = list(read_rows(path))
            cur.executemany(
                """insert into food_nutrition
                     (food_cd, food_name, serving_g, kcal, carb_g,
                      protein_g, fat_g, sugar_g, sodium_mg)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   on conflict (food_cd) do update set
                     food_name=excluded.food_name, serving_g=excluded.serving_g,
                     kcal=excluded.kcal, carb_g=excluded.carb_g, protein_g=excluded.protein_g,
                     fat_g=excluded.fat_g, sugar_g=excluded.sugar_g,
                     sodium_mg=excluded.sodium_mg, fetched_at=now()""",
                rows)
            total += len(rows)
            print(f"  {Path(path).name}: {len(rows)} rows")
        conn.commit()
    print(f"food_nutrition: {total} rows upserted")


if __name__ == "__main__":
    main()
