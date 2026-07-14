"""분량→그램 정규화 스키마 — item_master 밀도 컬럼 + item_unit_weight 테이블 (멱등).

레시피 재료 분량("1큰술"·"1대"·"1모")을 그램으로 환산해 영양·장보기에 연결하기 위한 참조 스키마.
- item_master.density_g_per_ml : 계량단위(큰술/작은술/컵) ml→g 변환용. NULL = 1.0(물류) 가정.
- item_unit_weight(item_id,unit,grams) : 낱개단위(개/대/모/장…) 환산. '장'이 치즈 20g·깻잎 2g처럼
  품목마다 달라 (품목,단위) 복합키 필수.
migrate_retail_crawl.py 처럼 standalone 멱등 마이그레이션 — apply_schema(drop/recreate) 경로와 분리.
사용:  python pipelines/ingest/migrate_quantity.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect  # noqa: E402

DDL = [
    # 계량단위 변환용 밀도 (NULL이면 코드가 1.0으로 간주)
    "ALTER TABLE item_master ADD COLUMN IF NOT EXISTS density_g_per_ml numeric",
    # 낱개단위 → 그램 (품목,단위 복합키)
    """CREATE TABLE IF NOT EXISTS item_unit_weight (
         item_id bigint  NOT NULL REFERENCES item_master(item_id) ON DELETE CASCADE,
         unit    text    NOT NULL,     -- '개','대','모','알','쪽','장','공기','줌','꼬집'
         grams   numeric NOT NULL,     -- 1단위 = grams
         src     text,                 -- 'MINED'|'CURATED'|'PUBLIC' (출처)
         PRIMARY KEY (item_id, unit)
       )""",
    "CREATE INDEX IF NOT EXISTS item_unit_weight_item_idx ON item_unit_weight (item_id)",
]


def main():
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SET lock_timeout = '15s'")   # 락 무한대기 방지(idle-in-tx 블로커 대비 → 걸리면 에러)
        for stmt in DDL:
            cur.execute(stmt)
        conn.commit()
        cur.execute("""select 1 from information_schema.columns
                       where table_name='item_master' and column_name='density_g_per_ml'""")
        has_col = cur.fetchone() is not None
        cur.execute("select count(*) from item_master")
        n_items = cur.fetchone()[0]
        cur.execute("select count(*) from item_unit_weight")
        n_uw = cur.fetchone()[0]
    print(f"migrate_quantity: density_g_per_ml={'OK' if has_col else 'MISSING'} "
          f"· item_master {n_items}행(보존) · item_unit_weight {n_uw}행")


if __name__ == "__main__":
    main()
