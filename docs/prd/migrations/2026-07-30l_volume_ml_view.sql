-- 2026-07-30l — retail_unit_price: 부피 단가를 **컬럼**에서 계산 (#286)
--
-- ## 무엇을 바꾸나
--
-- 지금 뷰는 조회 때마다 **상품명을 SQL 정규식으로** 파싱해 부피를 구한다. 이 구조가
-- 2026-07-23 장애를 만들었다 — `"솔리몬 스퀴즈드 레몬즙 1,000ml"` 에서 정규식이 콤마를
-- 몰라 `000` 을 잡고 0 으로 나눠 **뷰 REFRESH 가 통째로 죽었다.** 4,634행 중 1행이
-- 가격 갱신 전체를 멈춰 세웠다. PR #285 가 콤마 인식과 NULLIF 0-가드로 급한 불은 껐지만,
-- **파싱 대상이 잘못됐다는 근본 문제는 그대로**였다.
--
-- 이제 `retail_product.volume_ml` 을 파이프라인이 쓰기 시점에 채운다
-- (`retail_norm.parse_volume_ml` + `load_retail.refine_record`, 백필은
--  `pipelines/ingest/backfill_volume_ml.py`). 뷰는 그 컬럼만 나눈다.
--
-- ## 이름 정규식 폴백을 **남기지 않는** 이유
--
-- 남겨두면 버그도 같이 남는다. 실측 거짓양성:
--
--     Ai선별 제주 하우스감귤 2kg(L-2L)   ← `2L` 을 2,000ml 로 읽는다
--
-- `L-2L` 은 농산물 **크기 등급**(S/M/L/2L/3L)이지 부피가 아니다. 2kg 짜리 감귤에
-- 부피 단가가 매겨지고 있었다. 파이썬 파서는 범위 표기를 배제해 이 부류를 거른다.
--
-- 커버리지 확인(운영 상품명 5,495건 실측): 이름에 부피 표기가 있는 106건 중 **101건 산출**.
-- 못 읽은 5건은 전부 **올바른 거부**다 — 감귤 `L-2L`, 계란 `2XL(왕란)`, `200g/L사이즈`,
-- `LA 갈비 500g`. 즉 진짜 부피 상품은 전부 잡았다.
--
-- ## 순서 주의
--
-- 🔴 **백필을 먼저 돌리고 이 마이그레이션을 적용한다.** 반대로 하면 `volume_ml` 이 비어 있는
--    동안 부피 단가가 오아시스 표시단가분만 남는다(80 → 63).
--
--     python pipelines/ingest/backfill_volume_ml.py --apply
--     psql -f docs/prd/migrations/2026-07-30l_volume_ml_view.sql
--     REFRESH MATERIALIZED VIEW CONCURRENTLY retail_unit_price;   -- 아래에서 수행
--
-- 물질화 뷰는 CREATE OR REPLACE 가 안 되므로 DROP ... CASCADE 로 내리고, 함께 떨어지는
-- 의존 뷰 2개(retail_item_piece_compare · retail_item_price_compare)를 **정본 그대로**
-- 되살린다. 정의는 운영 pg_get_viewdef 에서 받아 적었다.

BEGIN;

DROP MATERIALIZED VIEW IF EXISTS retail_unit_price CASCADE;

CREATE MATERIALIZED VIEW retail_unit_price AS         -- 상품별 최신 스냅샷 + 단가(물질화)
WITH latest AS (
  SELECT retail_product_id, price, unit_price, unit_basis, deal_type, crawled_at,
         row_number() OVER (PARTITION BY retail_product_id ORDER BY crawled_at DESC) rn
  FROM retail_price WHERE price IS NOT NULL)
SELECT rp.id, rp.source, rp.item_id, rp.name, rp.weight_g,
       l.price, l.deal_type, l.crawled_at,
       COALESCE(
         CASE WHEN rp.weight_g > 0 THEN round(l.price / rp.weight_g * 100) END,
         CASE l.unit_basis                        -- weight 없으면 오아시스 표시단가로 폴백(무게basis만)
           WHEN '100g'  THEN round(l.unit_price)
           WHEN '10g'   THEN round(l.unit_price * 10)
           WHEN '1g'    THEN round(l.unit_price * 100)
           WHEN '1kg'   THEN round(l.unit_price / 10)
           WHEN '100kg' THEN round(l.unit_price / 1000)
         END
       ) AS won_per_100g,
       -- 개수 상품 단가: 상품명서 개수 파싱(계란 구/개/알/입→'알', 김 봉/매). 무게 못 재는 상품용.
       -- ⚠️ 여기는 아직 이름 정규식이다. 부피와 달리 개수는 컬럼이 없다 — 별건(#286 후속).
       --    NULLIF 로 0을 NULL 로 바꿔 "이 상품만 단가 없음"으로 격리한다.
       CASE WHEN pc.m[1] IS NOT NULL
            THEN round(l.price / NULLIF(replace(pc.m[1], ',', '')::numeric, 0)) END AS won_per_piece,
       CASE WHEN pc.m[2] IN ('구','개','알','입') THEN '알' ELSE pc.m[2] END AS piece_unit,
       -- 부피 단가: 오아시스 표시단가(ml basis) 우선, 없으면 **volume_ml 컬럼**.
       -- 이름 정규식은 쓰지 않는다 — 크기 등급('2kg(L-2L)')을 부피로 오인한다.
       COALESCE(
         CASE l.unit_basis WHEN '100ml' THEN round(l.unit_price) WHEN '10ml' THEN round(l.unit_price * 10)
           WHEN '1L' THEN round(l.unit_price / 10) END,
         CASE WHEN rp.volume_ml > 0 THEN round(l.price / rp.volume_ml * 100) END
       ) AS won_per_100ml
FROM retail_product rp
JOIN latest l ON l.retail_product_id = rp.id AND l.rn = 1
LEFT JOIN LATERAL (SELECT regexp_match(rp.name, '([\d,]+)\s*(구|개|알|입|매|봉|장|모)') AS m) pc ON true
WHERE rp.item_id IS NOT NULL;

-- id는 상품당 1행(rn=1) → 유니크. REFRESH ... CONCURRENTLY 는 유니크 인덱스가 필수(락 없이 갱신).
CREATE UNIQUE INDEX retail_unit_price_id_idx ON retail_unit_price (id);
CREATE INDEX retail_unit_price_item_idx ON retail_unit_price (item_id);   -- 서비스 item_id 조회

-- ── CASCADE 로 함께 떨어진 의존 뷰 복원 (운영 pg_get_viewdef 정본) ──────────────
CREATE OR REPLACE VIEW retail_item_piece_compare AS
SELECT im.canonical_name,
    im.category,
    u.piece_unit,
    min(u.won_per_piece) FILTER (WHERE u.source = 'kurly'::text) AS kurly_per_piece,
    min(u.won_per_piece) FILTER (WHERE u.source = 'oasis'::text) AS oasis_per_piece,
    count(u.won_per_piece) FILTER (WHERE u.source = 'kurly'::text) AS kurly_n,
    count(u.won_per_piece) FILTER (WHERE u.source = 'oasis'::text) AS oasis_n
   FROM retail_unit_price u
     JOIN item_master im ON im.item_id = u.item_id
  WHERE u.won_per_piece IS NOT NULL AND u.piece_unit IS NOT NULL
  GROUP BY im.canonical_name, im.category, u.piece_unit;

CREATE OR REPLACE VIEW retail_item_price_compare AS
WITH item_med AS (
         SELECT retail_unit_price.item_id,
            percentile_cont(0.5::double precision) WITHIN GROUP (ORDER BY (retail_unit_price.won_per_100g::double precision)) AS med
           FROM retail_unit_price
          WHERE retail_unit_price.won_per_100g IS NOT NULL
          GROUP BY retail_unit_price.item_id
        )
 SELECT im.item_id,
    im.canonical_name,
    im.category,
    min(u.won_per_100g) FILTER (WHERE u.source = 'kurly'::text AND u.won_per_100g::double precision >= (0.25::double precision * m.med)) AS kurly_100g,
    min(u.won_per_100g) FILTER (WHERE u.source = 'oasis'::text AND u.won_per_100g::double precision >= (0.25::double precision * m.med)) AS oasis_100g,
    count(u.won_per_100g) FILTER (WHERE u.source = 'kurly'::text) AS kurly_n,
    count(u.won_per_100g) FILTER (WHERE u.source = 'oasis'::text) AS oasis_n,
    min(u.won_per_100ml) FILTER (WHERE u.source = 'kurly'::text) AS kurly_100ml,
    min(u.won_per_100ml) FILTER (WHERE u.source = 'oasis'::text) AS oasis_100ml,
    count(u.won_per_100ml) FILTER (WHERE u.source = 'kurly'::text) AS kurly_ml_n,
    count(u.won_per_100ml) FILTER (WHERE u.source = 'oasis'::text) AS oasis_ml_n
   FROM retail_unit_price u
     JOIN item_master im ON im.item_id = u.item_id
     LEFT JOIN item_med m ON m.item_id = u.item_id
  GROUP BY im.item_id, im.canonical_name, im.category;

COMMIT;

-- 물질화 뷰는 생성 직후 이미 채워져 있다(WITH DATA 기본). CONCURRENTLY 는 트랜잭션 밖에서만
-- 되므로, 이후 정기 갱신은 기존 스케줄 그대로 두면 된다.
