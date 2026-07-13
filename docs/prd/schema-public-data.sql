-- 공공데이터 적재 스키마 (서비스 확인용) — 실제 검증된 컬럼 기반, 2026-07-13
-- 대상 DB: fb-data(.8) foodbudget. 소량 적재(멱등 upsert). SSOT 아님, 초안.

-- ============ A. 영양성분 (식약처) → Recipe 영양성분 / 품목마스터 ============
-- 소스: 서비스확인용=표준데이터 15100064 CSV(키 불필요) 또는 레거시 I0750 API(9영양소)
CREATE TABLE food_nutrition (
  food_cd        text PRIMARY KEY,          -- FOOD_CD / 식품코드
  food_name      text NOT NULL,             -- DESC_KOR / 식품명
  food_group     text,                      -- FDGRP_NM / 식품군(대분류)
  serving_wt_g   numeric,                   -- SERVING_WT (1회제공량 g)
  energy_kcal    numeric,                   -- NUTR_CONT1
  carb_g         numeric,                   -- NUTR_CONT2
  protein_g      numeric,                   -- NUTR_CONT3
  fat_g          numeric,                   -- NUTR_CONT4
  sugar_g        numeric,                   -- NUTR_CONT5
  sodium_mg      numeric,                   -- NUTR_CONT6
  cholesterol_mg numeric,                   -- NUTR_CONT7
  sat_fat_g      numeric,                   -- NUTR_CONT8
  trans_fat_g    numeric,                   -- NUTR_CONT9
  maker          text,                      -- ANIMAL_PLANT (가공업체)
  base_year      int,                       -- BGN_YEAR
  source         text NOT NULL DEFAULT 'MFDS_I0750',
  fetched_at     timestamptz NOT NULL DEFAULT now()
);
-- 표준데이터(15100064) 채택 시: 비타민/미네랄 컬럼 + 대·중·소·세분류 코드 확장

-- ============ B. 소비기한 참조표 (KFIA + FoodKeeper 통합) → Pantry 유통기한 추정 ============
-- KFIA=식품유형 category-level(PDF, 소량 수기), FoodKeeper=generic product(CC0, 8시나리오 melt)
CREATE TABLE shelf_life_ref (
  id            bigserial PRIMARY KEY,
  source        text NOT NULL,             -- 'KFIA' | 'FOODKEEPER'
  food_category text,                      -- 식품유형(KFIA) / Category_Name(FoodKeeper)
  item_name     text NOT NULL,             -- 세부품목 / Product.Name
  storage       text NOT NULL,             -- 'ROOM'|'FRIDGE'|'FRIDGE_OPENED'|'FREEZER'|'FREEZER_DOP' ...
  life_min      int,                       -- 상태값일 때 null
  life_max      int,
  unit          text,                      -- 'DAYS'|'WEEKS'|'MONTHS'|'YEARS' | 'WHEN_RIPE'|'INDEFINITE'|'NOT_RECOMMENDED'|'PKG_USE_BY'
  ref_note      text,                      -- 포장/살균조건(KFIA) / tips(FoodKeeper)
  raw_meta      jsonb,                     -- 원본 부가필드 보존(KFIA 포장·보존료·유탕·살균 / FoodKeeper DOP변형)
  source_url    text,
  fetched_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON shelf_life_ref (item_name);
CREATE INDEX ON shelf_life_ref (food_category);
-- ⚠️ 냉장고 재고(자유텍스트/SKU) → 이 참조표 매칭 = load-bearing(우리 NER·품목마스터가 붙는 지점)

-- ============ C. 공공 레시피 (COOKRCP01 + 농교원 EPIS) → Recipe ============
CREATE TABLE recipe (
  id            bigserial PRIMARY KEY,
  source        text NOT NULL,             -- 'COOKRCP01' | 'EPIS'
  src_recipe_id text NOT NULL,             -- RCP_SEQ / RECIPE_ID
  name          text NOT NULL,             -- RCP_NM / RECIPE_NM_KO
  category      text,                      -- RCP_PAT2 / TY_NM
  cook_method   text,                      -- RCP_WAY2 (COOKRCP01)
  calorie_kcal  numeric,                   -- INFO_ENG / CALORIE
  carb_g        numeric,                   -- INFO_CAR
  protein_g     numeric,                   -- INFO_PRO
  fat_g         numeric,                   -- INFO_FAT
  sodium_mg     numeric,                   -- INFO_NA
  serving       text,                      -- INFO_WGT / QNT
  level_nm      text,                      -- LEVEL_NM (EPIS)
  cooking_time  text,                      -- COOKING_TIME (EPIS)
  hash_tag      text,                      -- HASH_TAG (COOKRCP01)
  image_url     text,                      -- ATT_FILE_NO_MK
  na_tip        text,                      -- RCP_NA_TIP (COOKRCP01)
  raw_meta      jsonb,
  fetched_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source, src_recipe_id)
);

CREATE TABLE recipe_ingredient (
  id              bigserial PRIMARY KEY,
  recipe_id       bigint NOT NULL REFERENCES recipe(id) ON DELETE CASCADE,
  seq             int,                     -- IRDNT_SN(EPIS) / 파싱순번
  ingredient_raw  text,                    -- COOKRCP01 RCP_PARTS_DTLS 원문(덩어리) / EPIS 원본
  ingredient_name text,                    -- 정규화 재료명: EPIS=IRDNT_NM 직접 / COOKRCP01=NER 후
  quantity        text,                    -- IRDNT_CPCTY(EPIS) / NER 후
  ner_status      text NOT NULL DEFAULT 'RAW'  -- 'RAW'|'LABELED'(EPIS=정답)|'NER_PARSED'(COOKRCP01)
);
CREATE INDEX ON recipe_ingredient (recipe_id);
CREATE INDEX ON recipe_ingredient (ingredient_name);
-- EPIS는 ingredient_name/quantity 즉시 채워짐(NER 학습 라벨), COOKRCP01은 raw만→NER 대상

CREATE TABLE recipe_step (
  id          bigserial PRIMARY KEY,
  recipe_id   bigint NOT NULL REFERENCES recipe(id) ON DELETE CASCADE,
  step_no     int NOT NULL,                -- MANUAL 순번 / COOKING_NO
  description text,                        -- MANUALxx / COOKING_DC
  image_url   text                         -- MANUAL_IMGxx / STRE_STEP_IMAGE_URL
);
CREATE INDEX ON recipe_step (recipe_id);

-- ============ D. 온라인 가격 baseline (15080757) → Price [조건부: serviceKey 후 필드 확정] ============
CREATE TABLE price_item (
  item_cd   text PRIMARY KEY,              -- ic / 품목코드
  item_name text NOT NULL                  -- in / 품목명
);
CREATE TABLE price_online_daily (
  id         bigserial PRIMARY KEY,
  item_cd    text NOT NULL REFERENCES price_item(item_cd),
  survey_date date NOT NULL,               -- 조사일자 (필드명 serviceKey 후 확정)
  price      numeric,                      -- 가격
  unit       text,                         -- 단위/규격 (존재여부 미확정)
  source     text NOT NULL DEFAULT 'NDATA_15080757',
  fetched_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (item_cd, survey_date)
);
