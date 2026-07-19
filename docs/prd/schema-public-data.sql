-- 공공데이터 적재 스키마 (서비스 확인용) — 2026-07-13
-- 원칙: **서비스가 실제 사용하는 컬럼만 적재.** 소스 원본 컬럼은 매핑만 하고, 미사용은 미적재.
-- 각 컬럼 옆 [사용처]. 대상: fb-data(.8) foodbudget. 멱등 upsert.

-- ============ 0. item_master / item_alias — 품목 정체성 스파인 (조인 키) ============
-- 4개 소스(재료명·소비기한·가격·영양)의 자유텍스트 품목을 하나의 표준 품목으로 봉합.
-- canonical = 한글 원재료 기준. 관측된 이름은 item_alias로 매핑(NER/수기 출력이 여기 쌓임).
CREATE TABLE item_master (
  item_id        bigserial PRIMARY KEY,
  canonical_name text NOT NULL UNIQUE,   -- 표준 품목명(예: 두부, 대파, 돼지고기)
  category       text,                   -- 채소/과일/육류/…
  note           text
);
CREATE TABLE item_alias (
  alias   text PRIMARY KEY,              -- 관측된 이름(재료명·영문 FoodKeeper·물가품목명)
  item_id bigint NOT NULL REFERENCES item_master(item_id) ON DELETE CASCADE,
  source  text                           -- alias 출처(provenance)
);
CREATE INDEX ON item_alias (item_id);

-- ============ A. food_nutrition — 식품/재료 영양 룩업 ============
-- 사용처: Recipe 영양성분 표시(DB 룩업) · 재고 재료 영양 · (P1)custom레시피 영양합산
-- 소스: 식약처 영양성분(표준데이터 15100064 CSV·무키 / 레거시 I0750)
CREATE TABLE food_nutrition (
  food_cd     text PRIMARY KEY,   -- FOOD_CD           [재료 매칭 키]
  food_name   text NOT NULL,      -- 식품명            [매칭·표시]
  serving_g   numeric,            -- 1회제공량(g)      [영양 기준량]
  kcal        numeric,            -- 열량              [영양성분 표시]
  carb_g      numeric,            -- 탄수화물
  protein_g   numeric,            -- 단백질
  fat_g       numeric,            -- 지방
  sugar_g     numeric,            -- 당류
  sodium_mg   numeric,            -- 나트륨
  item_id     bigint REFERENCES item_master(item_id),  -- 표준 품목(점진 매핑)
  fetched_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON food_nutrition (food_name);
CREATE INDEX ON food_nutrition (item_id);

-- ============ B. shelf_life_ref — 소비기한 추정 참조표 ============
-- 사용처: Pantry 소비기한 추정·임박 알림 (품목+보관위치 → 추정 소비기한 일수)
-- 소스: USDA FoodKeeper(CC0) + 식약처/KFIA 대표 샘플. **값은 일(day)로 정규화 적재**.
CREATE TABLE shelf_life_ref (
  id            bigserial PRIMARY KEY,
  source        text NOT NULL,     -- 'FOODKEEPER'|'KFIA'|'CURATED'
  food_category text,              -- 대분류            [매칭 fallback·필터]
  item_name     text NOT NULL,     -- 품목명            [재고 매칭]
  storage       text NOT NULL CHECK (storage IN ('ROOM','FRIDGE','FREEZER')),  -- 재고 보관위치
  days_min      int,               -- 정규화(주=7·월=30·년=365). 상태값이면 null
  days_max      int,               -- 〃
  note          text,              -- 특수값('WHEN_RIPE'|'INDEFINITE'|'NOT_RECOMMENDED') 등
  item_id       bigint REFERENCES item_master(item_id),  -- 표준 품목
  fetched_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON shelf_life_ref (item_name);
CREATE UNIQUE INDEX ON shelf_life_ref (source, item_name, storage);
CREATE INDEX ON shelf_life_ref (item_id);

-- ============ C. recipe / recipe_ingredient / recipe_step ============
-- 사용처: Recipe 검색·카테고리 필터·상세(재료·조리법·영양)·재고기반 추천·레시피북
-- 소스: 만개의레시피(10K, 크롤·주 소스) + COOKRCP01(placeholder, 교체예정) + EPIS(정형)
CREATE TABLE recipe (
  id            bigserial PRIMARY KEY,
  source        text NOT NULL,     -- '10K'|'COOKRCP01'|'EPIS'
  src_recipe_id text NOT NULL,     -- 원본 레시피 ID
  name          text NOT NULL,     -- 레시피명          [검색·표시]
  category      text,              -- 요리종류          [카테고리 필터]
  cook_method   text,              -- 조리방법          [필터] (EPIS 없음→null)
  cooking_time  text,              -- 조리시간          [15분 필터] (COOKRCP01 없음→null)
  level_nm      text,              -- 난이도            [표시] (EPIS)
  kcal          numeric,           -- 열량              [영양 표시]
  carb_g        numeric,
  protein_g     numeric,
  fat_g         numeric,
  sodium_mg     numeric,
  serving       text,              -- 인분/중량         [표시]
  image_url     text,              -- 대표 이미지       [상세]
  fetched_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source, src_recipe_id)
);

CREATE TABLE recipe_ingredient (
  id              bigserial PRIMARY KEY,
  recipe_id       bigint NOT NULL REFERENCES recipe(id) ON DELETE CASCADE,
  seq             int,
  ingredient_name text,            -- 정규화 재료명     [재고 매칭·장보기]  (10K=재료명 / EPIS=IRDNT_NM / COOKRCP01=NER후)
  quantity        text,            -- 용량             [장보기 수량]      (10K=수량 / EPIS=IRDNT_CPCTY)
  ingredient_raw  text,            -- 재료 원문         [10K=재료원문 / COOKRCP01=NER입력]; EPIS=null
  ner_status      text NOT NULL DEFAULT 'RAW'
                    -- CRAWLER=크롤러가 재료명/수량 분리(만개) · LABELED=정형gold(EPIS) · RAW→NER_PARSED=NER파이프라인
                    CHECK (ner_status IN ('RAW','LABELED','NER_PARSED','CRAWLER')),
  item_id         bigint REFERENCES item_master(item_id)   -- 표준 품목(NER/alias 해소)
);
CREATE INDEX ON recipe_ingredient (recipe_id);
CREATE INDEX ON recipe_ingredient (ingredient_name);
CREATE INDEX ON recipe_ingredient (item_id);

CREATE TABLE recipe_step (
  id          bigserial PRIMARY KEY,
  recipe_id   bigint NOT NULL REFERENCES recipe(id) ON DELETE CASCADE,
  step_no     int NOT NULL,        -- 순서
  description text,                -- 조리 설명         [상세]
  image_url   text                 -- 단계 이미지       [상세]
);
CREATE INDEX ON recipe_step (recipe_id);

-- ============ D. price_item / price_online_daily ============
-- 사용처: Price 예산 baseline·품목 시세 참고 (SKU 최저가 비교 아님)
-- 소스: 통계청/국가데이터처 온라인가격 15080757 (serviceKey)
CREATE TABLE price_item (
  item_cd   text PRIMARY KEY,      -- ic 품목코드
  item_name text NOT NULL,         -- in 품목명
  item_id   bigint REFERENCES item_master(item_id)  -- 표준 품목
);
CREATE INDEX ON price_item (item_id);

CREATE TABLE price_online_daily (  -- getPriceInfo(개별상품 sp) → 품목·일자별 집계
  item_cd    text NOT NULL REFERENCES price_item(item_cd),
  survey_date date NOT NULL,       -- sd 가격일자
  price_min  numeric,              -- 그날 최저 판매가(sp)
  price_med  numeric,              -- 대표 시세(중앙값)   [예산 baseline]
  price_max  numeric,              -- 최고
  obs_count  int,                  -- 관측 상품 수
  fetched_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (item_cd, survey_date)
);
-- 미적재: 개별상품(pi/pn)·할인가(dp)·혜택가(bp)·몰/단위 — baseline엔 판매가(sp) 집계만.
-- ⚠️ 원천이 단위 미정규(쌀 20kg vs 10kg 혼재) → 시세 '방향성' 지표지 정밀가 아님.

-- ============ E. crawl_raw — 크롤 원본 착지 (전처리 전 임시 스테이징) ============
-- 목적: 크롤러(팀원)가 뱉는 raw를 정제 전 잠깐 담아두는 랜딩 버퍼. **영구저장 아님.**
-- 정제 로더가 미처리분을 읽어 관계형(recipe/retail_*)으로 옮기고 processed_at 세팅 → 주기 프루닝.
-- 문서스토어(MongoDB) 불필요 — 임시 스테이징이라 PG jsonb로 충분(확정 스택). 크롤↔정제 분리·재정제용.
CREATE TABLE crawl_raw (
  id           bigserial PRIMARY KEY,
  source       text NOT NULL,        -- '10K'|'kurly'|'oasis'
  kind         text NOT NULL,        -- 'recipe'|'ingredient'|'product'
  src_key      text NOT NULL,        -- 소스 레시피/상품 id
  payload      jsonb NOT NULL,       -- 크롤 원본 그대로
  crawled_at   timestamptz,          -- 크롤 시각(payload 내)
  landed_at    timestamptz NOT NULL DEFAULT now(),
  processed_at timestamptz,          -- 정제완료(=프루닝 후보). null=미처리
  UNIQUE (source, kind, src_key, crawled_at)
);
CREATE INDEX ON crawl_raw (source, kind) WHERE processed_at IS NULL;  -- 미처리 스캔

-- ============ F. retail_product / retail_price — 소매 SKU + 할인/핫딜 ============
-- 사용처: 최저가 비교(컬리 vs 오아시스, item_id 축) · 핫딜 알림(deal_type) · 가격 이력
-- 소스: 마켓컬리·오아시스몰 크롤. price_item(통계 baseline)과 별개 — SKU 단위·할인·딜.
CREATE TABLE retail_product (
  id          bigserial PRIMARY KEY,
  source      text NOT NULL,         -- 'kurly'|'oasis'
  product_id  text NOT NULL,         -- 소스 SKU id
  name        text NOT NULL,         -- 원본 상품명       [표시]
  name_norm   text,                  -- 정규화명          [정규화기 출력·디버그]
  item_id     bigint REFERENCES item_master(item_id),  -- 표준 품목(정규화→gazetteer)
  weight_g    numeric,               -- 정규화 중량       [단위가격]
  volume_ml   numeric,
  category    text,                  -- 소스 카테고리명
  url         text,
  image_url   text,
  storage     text,                  -- 보관(오아시스)    [신선도]
  origin      text,                  -- 원산지(오아시스)
  expiry_text text,                  -- 소비기한 원문(오아시스)
  first_seen  timestamptz NOT NULL DEFAULT now(),
  last_seen   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source, product_id)
);
CREATE INDEX ON retail_product (item_id);
CREATE INDEX ON retail_product (source, category);

CREATE TABLE retail_price (           -- 크롤 스냅샷(시계열)
  retail_product_id bigint NOT NULL REFERENCES retail_product(id) ON DELETE CASCADE,
  crawled_at        timestamptz NOT NULL,
  price             numeric NOT NULL,   -- 현재/판매가       [최저가 비교]
  original_price    numeric,            -- 정가(컬리)        [할인율]
  discount_rate     int,                -- 할인율%
  deal_type         text,               -- 'general'|'마감세일'|'타임세일'  [핫딜]
  timedeal_end      timestamptz,        -- 타임딜 종료(오아시스)
  unit_price        numeric,            -- 단위가격(오아시스 표시가, unit_basis 기준)
  unit_basis        text,               -- 단위기준 '100g'|'10g'|'1개'|'100ml' (오아시스, 단가 정규화용)
  is_sold_out       boolean,
  PRIMARY KEY (retail_product_id, crawled_at)
);
CREATE INDEX ON retail_price (deal_type) WHERE deal_type <> 'general';  -- 핫딜 스캔

-- 파생 뷰: 팩크기 무관 단가(100g) 비교 — 크로스소스 최저가의 핵심(원시 price는 팩크기 아티팩트).
-- won_per_100g = price/weight_g*100 (소스무관·weight 기반). 계란·김 등 개수상품은 값은 나오나
-- 자연단위 아님 → weight 카테고리(정육·수산·곡물·채소·과일)에서 정확.
-- ★ MATERIALIZED: 일반 뷰였을 때 매 요청마다 retail_price 시계열 전체에 윈도우+정규식을 재계산해
--   Price(현재가)·MealPlan(compare 조인) 병목의 근원이었다(부하테스트, #186). 가격은 배치성
--   (크롤 일1~2회)이라 물질화가 궁합에 맞다 — 크롤 후 REFRESH CONCURRENTLY 로 갱신
--   (pipelines/ingest/refresh_price_matview.py). 조회는 저장된 결과를 읽어 즉시.
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
       CASE WHEN pc.m[1] IS NOT NULL THEN round(l.price / pc.m[1]::numeric) END AS won_per_piece,
       CASE WHEN pc.m[2] IN ('구','개','알','입') THEN '알' ELSE pc.m[2] END AS piece_unit,
       -- 부피 단가: 오아시스 표시단가(ml basis) 우선, 없으면 이름서 부피 파싱(× 팩배수). L→ml.
       COALESCE(
         CASE l.unit_basis WHEN '100ml' THEN round(l.unit_price) WHEN '10ml' THEN round(l.unit_price * 10)
           WHEN '1L' THEN round(l.unit_price / 10) END,
         CASE WHEN vp.v[1] IS NOT NULL THEN round(
           l.price / (vp.v[1]::numeric
             * CASE WHEN lower(vp.v[2]) IN ('l','리터','ℓ') THEN 1000 ELSE 1 END
             * COALESCE(mp.m[1]::numeric, 1)) * 100) END
       ) AS won_per_100ml
FROM retail_product rp
JOIN latest l ON l.retail_product_id = rp.id AND l.rn = 1
LEFT JOIN LATERAL (SELECT regexp_match(rp.name, '(\d+)\s*(구|개|알|입|매|봉|장|모)') AS m) pc ON true
LEFT JOIN LATERAL (SELECT regexp_match(rp.name, '(\d+(?:\.\d+)?)\s*(ml|mL|ML|L|리터|ℓ)') AS v) vp ON true
LEFT JOIN LATERAL (SELECT regexp_match(rp.name, '(?:ml|mL|ML|L|리터|ℓ)\s*[*xX×]\s*(\d+)') AS m) mp ON true
WHERE rp.item_id IS NOT NULL;
-- id는 상품당 1행(rn=1) → 유니크. REFRESH ... CONCURRENTLY 는 유니크 인덱스가 필수(락 없이 갱신).
CREATE UNIQUE INDEX retail_unit_price_id_idx ON retail_unit_price (id);
CREATE INDEX retail_unit_price_item_idx ON retail_unit_price (item_id);   -- 서비스 item_id 조회

CREATE OR REPLACE VIEW retail_item_price_compare AS   -- 품목별 컬리 vs 오아시스 최저 단가(100g)
SELECT im.item_id, im.canonical_name, im.category,
       min(u.won_per_100g) FILTER (WHERE u.source='kurly') AS kurly_100g,
       min(u.won_per_100g) FILTER (WHERE u.source='oasis') AS oasis_100g,
       count(u.won_per_100g) FILTER (WHERE u.source='kurly') AS kurly_n,
       count(u.won_per_100g) FILTER (WHERE u.source='oasis') AS oasis_n,
       min(u.won_per_100ml) FILTER (WHERE u.source='kurly') AS kurly_100ml,   -- 부피 단가(액체)
       min(u.won_per_100ml) FILTER (WHERE u.source='oasis') AS oasis_100ml,
       count(u.won_per_100ml) FILTER (WHERE u.source='kurly') AS kurly_ml_n,
       count(u.won_per_100ml) FILTER (WHERE u.source='oasis') AS oasis_ml_n
FROM retail_unit_price u JOIN item_master im ON im.item_id = u.item_id
GROUP BY im.item_id, im.canonical_name, im.category;

-- 개수 상품(계란=알·김=봉/매) 자연단위 단가 비교. piece_unit별 그룹 → 같은 단위끼리만 비교(봉≠매).
CREATE OR REPLACE VIEW retail_item_piece_compare AS
SELECT im.canonical_name, im.category, u.piece_unit,
       min(u.won_per_piece) FILTER (WHERE u.source='kurly') AS kurly_per_piece,
       min(u.won_per_piece) FILTER (WHERE u.source='oasis') AS oasis_per_piece,
       count(u.won_per_piece) FILTER (WHERE u.source='kurly') AS kurly_n,
       count(u.won_per_piece) FILTER (WHERE u.source='oasis') AS oasis_n
FROM retail_unit_price u JOIN item_master im ON im.item_id = u.item_id
WHERE u.won_per_piece IS NOT NULL AND u.piece_unit IS NOT NULL
GROUP BY im.canonical_name, im.category, u.piece_unit;
