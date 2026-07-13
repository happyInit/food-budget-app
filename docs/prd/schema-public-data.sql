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

-- ============ B. shelf_life_ref — 유통기한 추정 참조표 ============
-- 사용처: Pantry 유통기한 추정·임박 알림 (품목+보관위치 → 추정 소비기한 일수)
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
-- 소스: COOKRCP01(식약처) + 농교원 EPIS(정형)
CREATE TABLE recipe (
  id            bigserial PRIMARY KEY,
  source        text NOT NULL,     -- 'COOKRCP01'|'EPIS'
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
  ingredient_name text,            -- 정규화 재료명     [재고 매칭·장보기]  (EPIS=IRDNT_NM / COOKRCP01=NER후)
  quantity        text,            -- 용량             [장보기 수량]      (EPIS=IRDNT_CPCTY)
  ingredient_raw  text,            -- COOKRCP01 재료 원문 [NER 입력]; EPIS=null
  ner_status      text NOT NULL DEFAULT 'RAW'
                    CHECK (ner_status IN ('RAW','LABELED','NER_PARSED')),
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
