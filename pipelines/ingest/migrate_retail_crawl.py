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
  unit_basis        text,
  is_sold_out       boolean,
  PRIMARY KEY (retail_product_id, crawled_at)
);
CREATE INDEX IF NOT EXISTS retail_price_deal_idx ON retail_price (deal_type) WHERE deal_type <> 'general';
ALTER TABLE retail_price ADD COLUMN IF NOT EXISTS unit_basis text;   -- 기존 테이블용(멱등)

ALTER TABLE recipe_ingredient DROP CONSTRAINT IF EXISTS recipe_ingredient_ner_chk;
ALTER TABLE recipe_ingredient DROP CONSTRAINT IF EXISTS recipe_ingredient_ner_status_check;
ALTER TABLE recipe_ingredient ADD CONSTRAINT recipe_ingredient_ner_chk
  CHECK (ner_status IN ('RAW','LABELED','NER_PARSED','CRAWLER'));

-- 단가(100g) 비교 뷰 (정본 docs/prd/schema-public-data.sql §F와 동일)
CREATE OR REPLACE VIEW retail_unit_price AS
WITH latest AS (
  SELECT retail_product_id, price, unit_price, unit_basis, deal_type, crawled_at,
         row_number() OVER (PARTITION BY retail_product_id ORDER BY crawled_at DESC) rn
  FROM retail_price WHERE price IS NOT NULL)
SELECT rp.id, rp.source, rp.item_id, rp.name, rp.weight_g,
       l.price, l.deal_type, l.crawled_at,
       COALESCE(
         CASE WHEN rp.weight_g > 0 THEN round(l.price / rp.weight_g * 100) END,
         CASE l.unit_basis
           WHEN '100g'  THEN round(l.unit_price)
           WHEN '10g'   THEN round(l.unit_price * 10)
           WHEN '1g'    THEN round(l.unit_price * 100)
           WHEN '1kg'   THEN round(l.unit_price / 10)
           WHEN '100kg' THEN round(l.unit_price / 1000)
         END
       ) AS won_per_100g,
       CASE WHEN pc.m[1] IS NOT NULL THEN round(l.price / pc.m[1]::numeric) END AS won_per_piece,
       CASE WHEN pc.m[2] IN ('구','개','알','입') THEN '알' ELSE pc.m[2] END AS piece_unit
FROM retail_product rp
JOIN latest l ON l.retail_product_id = rp.id AND l.rn = 1
LEFT JOIN LATERAL (SELECT regexp_match(rp.name, '(\\d+)\\s*(구|개|알|입|매|봉|장|모)') AS m) pc ON true
WHERE rp.item_id IS NOT NULL;

CREATE OR REPLACE VIEW retail_item_price_compare AS
SELECT im.item_id, im.canonical_name, im.category,
       min(u.won_per_100g) FILTER (WHERE u.source='kurly') AS kurly_100g,
       min(u.won_per_100g) FILTER (WHERE u.source='oasis') AS oasis_100g,
       count(u.won_per_100g) FILTER (WHERE u.source='kurly') AS kurly_n,
       count(u.won_per_100g) FILTER (WHERE u.source='oasis') AS oasis_n
FROM retail_unit_price u JOIN item_master im ON im.item_id = u.item_id
GROUP BY im.item_id, im.canonical_name, im.category;

CREATE OR REPLACE VIEW retail_item_piece_compare AS   -- 개수 상품 자연단위 단가(계란=알·김=봉/매)
SELECT im.canonical_name, im.category, u.piece_unit,
       min(u.won_per_piece) FILTER (WHERE u.source='kurly') AS kurly_per_piece,
       min(u.won_per_piece) FILTER (WHERE u.source='oasis') AS oasis_per_piece,
       count(u.won_per_piece) FILTER (WHERE u.source='kurly') AS kurly_n,
       count(u.won_per_piece) FILTER (WHERE u.source='oasis') AS oasis_n
FROM retail_unit_price u JOIN item_master im ON im.item_id = u.item_id
WHERE u.won_per_piece IS NOT NULL AND u.piece_unit IS NOT NULL
GROUP BY im.canonical_name, im.category, u.piece_unit;
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
