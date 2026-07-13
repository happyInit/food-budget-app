"""비파괴 마이그레이션: crawl_raw 스테이징 + retail_product/price + ner_status CRAWLER.
멱등(IF NOT EXISTS). apply_schema.py(DROP CASCADE)와 달리 기존 데이터 무손상.
정본: docs/prd/schema-public-data.sql (§E·§F). 재실행 안전."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect  # noqa: E402

DDL = """
CREATE TABLE IF NOT EXISTS crawl_raw (
  id           bigserial PRIMARY KEY,
  source       text NOT NULL,
  kind         text NOT NULL,
  src_key      text NOT NULL,
  payload      jsonb NOT NULL,
  crawled_at   timestamptz,
  landed_at    timestamptz NOT NULL DEFAULT now(),
  processed_at timestamptz,
  UNIQUE (source, kind, src_key, crawled_at)
);
CREATE INDEX IF NOT EXISTS crawl_raw_unprocessed_idx ON crawl_raw (source, kind) WHERE processed_at IS NULL;

CREATE TABLE IF NOT EXISTS retail_product (
  id          bigserial PRIMARY KEY,
  source      text NOT NULL,
  product_id  text NOT NULL,
  name        text NOT NULL,
  name_norm   text,
  item_id     bigint REFERENCES item_master(item_id),
  weight_g    numeric,
  volume_ml   numeric,
  category    text,
  url         text,
  image_url   text,
  storage     text,
  origin      text,
  expiry_text text,
  first_seen  timestamptz NOT NULL DEFAULT now(),
  last_seen   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source, product_id)
);
CREATE INDEX IF NOT EXISTS retail_product_item_idx ON retail_product (item_id);
CREATE INDEX IF NOT EXISTS retail_product_cat_idx ON retail_product (source, category);

CREATE TABLE IF NOT EXISTS retail_price (
  retail_product_id bigint NOT NULL REFERENCES retail_product(id) ON DELETE CASCADE,
  crawled_at        timestamptz NOT NULL,
  price             numeric NOT NULL,
  original_price    numeric,
  discount_rate     int,
  deal_type         text,
  timedeal_end      timestamptz,
  unit_price        numeric,
  is_sold_out       boolean,
  PRIMARY KEY (retail_product_id, crawled_at)
);
CREATE INDEX IF NOT EXISTS retail_price_deal_idx ON retail_price (deal_type) WHERE deal_type <> 'general';

ALTER TABLE recipe_ingredient DROP CONSTRAINT IF EXISTS recipe_ingredient_ner_chk;
ALTER TABLE recipe_ingredient DROP CONSTRAINT IF EXISTS recipe_ingredient_ner_status_check;
ALTER TABLE recipe_ingredient ADD CONSTRAINT recipe_ingredient_ner_chk
  CHECK (ner_status IN ('RAW','LABELED','NER_PARSED','CRAWLER'));
"""


def main():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(DDL)
        conn.commit()
        cur.execute("""select table_name from information_schema.tables
                       where table_name in ('crawl_raw','retail_product','retail_price')
                       order by table_name""")
        tabs = [r[0] for r in cur.fetchall()]
    print(f"마이그레이션 완료 · 테이블 존재: {tabs}")


if __name__ == "__main__":
    main()
